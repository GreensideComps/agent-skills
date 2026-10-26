"""The always-on loop: poll, validate, evaluate, act behind the risk gate, persist, report health.

Each duty runs on its own interval and fails independently: one failing feed is recorded, backed off and retried
without stopping the rest. Nothing here sends an order except `Executor.submit`, and only after `risk_check`.
"""
from __future__ import annotations

import json
import math
import time
import traceback
from pathlib import Path

from . import execution, feeds

HERE = Path(__file__).resolve().parent


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or HERE / "config.json").read_text())


class Agent:
    def __init__(self, store, client, cfg: dict, *, ambiguous_exc, api_exc, get=feeds.http_get,
                 clock=time.time, sleep=time.sleep):
        self.s, self.c, self.cfg, self.get, self.clock, self.sleep = store, client, cfg, get, clock, sleep
        self.ex = execution.Executor(store, client, ambiguous_exc, api_exc)
        self.due: dict[str, float] = {}
        self.fail: dict[str, int] = {}
        self.quotes: dict[str, dict] = {}      # last validated quote per Yahoo symbol
        self.quote_state: dict[str, str] = {}  # last validation result per symbol
        self.positions: dict[str, dict] = {}
        self.summary: dict | None = None
        self.pending: list[dict] = []
        self.sessions: dict[int, list[dict]] = {}
        self.schedule_of: dict[str, int] = {}
        self.seen_news: set[str] = set()
        self.alerted: set[str] = set()
        self.loops = 0
        self.started = clock()
        self.last_ok: dict[str, float] = {}
        self.need_decide = False

    # ------------------------------------------------------------ scheduling
    def _run(self, name: str, fn) -> None:
        now = self.clock()
        if now < self.due.get(name, 0):
            return
        base = self.cfg["intervals_s"][name]
        try:
            fn()
            self.fail[name] = 0
            self.last_ok[name] = self.clock()
            self.due[name] = now + base
        except Exception as e:  # noqa: BLE001 - every duty is isolated; the failure is recorded and retried
            n = self.fail.get(name, 0) + 1
            self.fail[name] = n
            back = min(base * 2 ** (n - 1), 1800) if n > 1 else min(base, 60)
            self.due[name] = now + back
            self.s.event("duty_failed", duty=name, attempt=n, retry_in_s=back,
                         error=f"{type(e).__name__}: {str(e)[:300]}", trace=traceback.format_exc()[-800:])
            if n == 3:
                self.alert("warn", f"{name}_failing", f"{name} has failed {n} times in a row: {type(e).__name__}")

    def _run_once(self, name: str, fn) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            self.s.event("duty_failed", duty=name, error=f"{type(e).__name__}: {str(e)[:300]}",
                         trace=traceback.format_exc()[-800:])
            self.alert("critical", f"{name}_failed", f"{name} raised {type(e).__name__}: {str(e)[:200]}")

    def step(self) -> None:
        self.loops += 1
        self.s.renew_lease()
        self._run("calendar", self.refresh_calendar)
        self._run("broker", self.refresh_broker)
        self._run("prices", self.refresh_prices)
        if self.need_decide:  # decisions use this pass's positions and the prices fetched after them
            self.need_decide = False
            self._run_once("decide", self.decide)
        self._run("news", self.refresh_news)
        self._run("heartbeat", self.write_heartbeat)

    def run_forever(self) -> None:
        import signal

        def _term(signum, frame):  # noqa: ARG001 - turn SIGTERM into a clean, recorded stop
            raise SystemExit(f"signal {signum}")
        signal.signal(signal.SIGTERM, _term)
        self.s.acquire_lease()
        self.s.event("agent_started", version=self.cfg["version"], control=self.s.control())
        try:
            while True:
                t0 = self.clock()
                self.step()
                self.sleep(max(1.0, self.cfg["intervals_s"]["loop"] - (self.clock() - t0)))
        except BaseException as e:
            self.s.event("agent_stopping", loops=self.loops, why=f"{type(e).__name__}: {e}")
            raise
        finally:
            self.s.release_lease()

    # ------------------------------------------------------------ duties
    def refresh_calendar(self) -> None:
        sched = {}
        for e in self.c.exchanges():
            for w in e.get("workingSchedules", []):
                sched[w["id"]] = w.get("timeEvents", [])
        self.sessions = sched
        self.learn_schedules()
        self.s.event("calendar", schedules=len(sched),
                     tracked={t: self.schedule_of.get(t) for t in sorted(set(self.positions) | set(self.cfg["exits"]["tickers"])
                                                                     | {self.cfg["benchmark"]["t212"]})})

    def learn_schedules(self) -> None:
        """Map each instrument to its market calendar. The full instrument list is cached; it is fetched again only
        for a ticker it does not know (the endpoint allows one call a minute)."""
        want = set(self.positions) | {self.cfg["benchmark"]["t212"]} | set(self.cfg["exits"]["tickers"])
        if want - set(self.schedule_of):
            self.schedule_of = {i["ticker"]: i["workingScheduleId"] for i in self.c.instruments()
                                if i.get("ticker") and i.get("workingScheduleId") is not None}

    def market_open(self, t212: str) -> bool:
        sid = self.schedule_of.get(t212)
        if sid is None or sid not in self.sessions:
            return False  # unknown calendar: treated as closed, so nothing trades on it
        return feeds.session_state(self.sessions[sid], self.clock())["open"]

    def refresh_broker(self) -> None:
        self.summary = self.c.account_summary()
        pos = self.c.positions()
        self.positions = {(p.get("instrument") or {}).get("ticker") or p.get("ticker"): p for p in pos}
        self.pending = self.c.pending_orders()
        if set(self.positions) - set(self.schedule_of):
            self.learn_schedules()  # a new holding: learn which market calendar it trades on
        rec = self.ex.reconcile(self.clock(), self.cfg["limits"]["fill_check_timeout_s"])
        for r in rec:
            self.s.event("order_outcome", intent=r["id"], status=r["status"], broker=r.get("broker"))
        if rec and any(r["status"] == "filled" for r in rec):
            self.summary = self.c.account_summary()
            self.positions = {(p.get("instrument") or {}).get("ticker"): p for p in self.c.positions()}
        self.snapshot()
        self.need_decide = True
        self.due["prices"] = 0  # price the current holdings before deciding

    def refresh_prices(self) -> None:
        ov = self.cfg["yahoo_overrides"]
        syms = {feeds.yahoo_symbol(t, ov) for t in self.positions} | {self.cfg["benchmark"]["yahoo"],
                                                                        self.cfg["benchmark"]["fx"]}
        syms |= set(self.cfg["extra_symbols"])
        syms.discard(None)
        raw = feeds.fetch_quotes(sorted(syms), get=self.get)
        now = self.clock()
        bad = []
        for sym in sorted(syms):
            t212 = self._t212_of(sym)
            ok, why = feeds.validate(sym, raw.get(sym), now, self.market_open(t212) if t212 else False,
                                     self.cfg["freshness_s"], self.cfg["abnormal_move"], self.quotes.get(sym))
            if ok:
                self.quotes[sym] = raw[sym]
            if (self.quote_state.get(sym) or "").split(":")[0] != why.split(":")[0]:
                self.s.event("quote_state", symbol=sym, ok=ok, why=why, quote=raw.get(sym))  # on change only
            self.quote_state[sym] = why
            if not ok:
                bad.append(sym)
        self.s.event("prices", n=len(raw), symbols=len(syms), invalid=bad,
                     vwrp=self.quotes.get(self.cfg["benchmark"]["yahoo"]),
                     fx=self.quotes.get(self.cfg["benchmark"]["fx"]))
        self.check_moves()

    def refresh_news(self) -> None:
        tickers = sorted({feeds.yahoo_symbol(t, self.cfg["yahoo_overrides"]) for t in self.positions} - {None})
        fresh = []
        for sym in tickers:
            for n in feeds.fetch_news(sym, get=self.get):
                if n["id"] in self.seen_news:
                    continue
                self.seen_news.add(n["id"])
                if n.get("published") and self.clock() - n["published"] < 86400 and sym in (n.get("tickers") or [sym]):
                    fresh.append({**n, "query": sym})
            self.sleep(0.5)
        if fresh:
            self.s.event("news", items=fresh)

    # ------------------------------------------------------------ evaluation
    def snapshot(self) -> None:
        s = self.summary or {}
        total = float(s.get("totalValue") or 0)
        rows = []
        for t, p in self.positions.items():
            w = p.get("walletImpact") or {}
            v = float(w.get("currentValue") or 0)
            rows.append({"ticker": t, "qty": p.get("quantity"), "avail": p.get("quantityAvailableForTrading"),
                         "in_pies": p.get("quantityInPies"), "value_gbp": v, "cost_gbp": w.get("totalCost"),
                         "weight": round(v / total, 4) if total else None,
                         "ccy": (p.get("instrument") or {}).get("currency")})
        ccy: dict[str, float] = {}
        for r in rows:
            ccy[r["ccy"]] = ccy.get(r["ccy"], 0) + r["value_gbp"]
        vw = self.quotes.get(self.cfg["benchmark"]["yahoo"])
        base = self.s.read("baseline.json")
        if base is None and vw and total:
            base = {"ts": feeds_ts(self.clock()), "total_gbp": total, "vwrp_gbp": vw["price"], "vwrp_t": vw["t"],
                    "note": "Written once at the agent's first priced snapshot; never rewritten."}
            self.s._replace("baseline.json", base)
            self.s.event("baseline", **base)
        rel = None
        if base and vw and total:
            rel = {"portfolio_return": total / base["total_gbp"] - 1, "vwrp_return": vw["price"] / base["vwrp_gbp"] - 1}
            rel["excess"] = rel["portfolio_return"] - rel["vwrp_return"]
        self.s.event("snapshot", total_gbp=total, cash=s.get("cash"), invested=s.get("investments"),
                     positions=len(rows), pending=len(self.pending), currency_gbp=ccy,
                     max_weight=max((r["weight"] or 0 for r in rows), default=0), vs_vwrp=rel, rows=rows)
        lim = self.cfg["alerts"]
        for r in rows:
            if r["weight"] and r["weight"] * 100 > lim["concentration_pct"]:
                self.alert("warn", f"concentration:{r['ticker']}", f"{r['ticker']} is {r['weight']:.1%} of the portfolio")
            if r["cost_gbp"] and r["value_gbp"] / float(r["cost_gbp"]) - 1 < -lim["drawdown_from_cost_pct"] / 100:
                self.alert("info", f"drawdown:{r['ticker']}",
                           f"{r['ticker']} is {r['value_gbp'] / float(r['cost_gbp']) - 1:.1%} on cost")

    def check_moves(self) -> None:
        lim = self.cfg["alerts"]
        for sym, q in self.quotes.items():
            pc = q.get("prev_close")
            if not pc:
                continue
            mv = q["price"] / pc - 1
            thr = lim["fx_move_pct"] if sym.endswith("=X") else lim["daily_move_pct"]
            if abs(mv) * 100 >= thr:
                self.alert("info", f"move:{sym}", f"{sym} {mv:+.1%} on the day ({pc} -> {q['price']})")

    def decide(self) -> None:
        """The only two actions agent-1.0 takes: the owner-authorised exits, and investing idle cash in the VWRP
        core. Everything else is a recorded no-trade."""
        day = feeds_ts(self.clock())[:10]
        acted, notes = [], []
        for t in self.cfg["exits"]["tickers"]:
            p = self.positions.get(t)
            if not p:
                notes.append(f"{t}: not held")
                continue
            avail = float(p.get("quantityAvailableForTrading") or 0)
            if avail <= 0:
                notes.append(f"{t}: {p.get('quantityInPies')} held in a pie, 0 tradeable via the API")
                self.alert("warn", f"exit_blocked_pie:{t}",
                           f"exit of {t} waits: its shares are inside a pie (the API cannot sell pie shares)")
                continue
            sym = feeds.yahoo_symbol(t, self.cfg["yahoo_overrides"])
            q = self.quotes.get(sym) if self.quote_state.get(sym) == "ok" else None
            px = float(p.get("currentPrice") or 0)
            val = float((p.get("walletImpact") or {}).get("currentValue") or 0) * avail / float(p.get("quantity") or avail)
            acted.append(self._order(t, -avail, val, px, q is not None, f"exit: {self.cfg['exits']['rationale']}",
                                     {"type": "authorised_exit", "quote": q}, day))
        cash = float(((self.summary or {}).get("cash") or {}).get("availableToTrade") or 0)
        core = self.cfg["core"]
        bt = self.cfg["benchmark"]["t212"]
        core_today = [r for r in execution.today_orders(self.s.intents(), day)
                      if (r.get("signal") or {}).get("type") == "core_invest"]
        if core_today:
            notes.append("core buy already made today; cash figures may lag the fill, so no second buy")
        elif cash > core["invest_cash_above_gbp"] and not execution.unresolved(self.s.intents()):
            sym = self.cfg["benchmark"]["yahoo"]
            q = self.quotes.get(sym) if self.quote_state.get(sym) == "ok" else None
            if q:
                qty = math.floor((cash - core["cash_buffer_gbp"]) / q["price"] * 100) / 100
                if qty > 0:
                    acted.append(self._order(bt, qty, qty * q["price"], q["price"], True,
                                             f"core: {core['rationale']} Cash £{cash:.2f} is idle.",
                                             {"type": "core_invest", "quote": q, "cash": cash}, day))
            else:
                notes.append(f"core buy waits: no validated {sym} price ({self.quote_state.get(sym)})")
        else:
            notes.append(f"cash £{cash:.2f}: below the £{core['invest_cash_above_gbp']:.0f} investing threshold"
                         if cash <= core["invest_cash_above_gbp"] else "core buy waits for an unresolved order")
        self.s.event("decision", orders=[a for a in acted if a], no_trade=not any(a and a.get("status") == "placed"
                                                                                  for a in acted), notes=notes)

    def _order(self, ticker, qty, value, price, quote_ok, reason, signal, day):
        order = {"ticker": ticker, "quantity": qty, "value_gbp": abs(value), "price": price, "reason": reason,
                 "signal": signal}
        refusals = execution.risk_check(order, control=self.s.control(), records=self.s.intents(),
                                        pending=self.pending, positions=self.positions, limits=self.cfg["limits"],
                                        day=day, consecutive_errors=self.ex.consecutive_errors, quote_ok=quote_ok,
                                        market_open=self.market_open(ticker))
        key = f"{ticker}:{qty}:{';'.join(refusals)}"
        if refusals and key in self.alerted:
            return None  # the same refusal is recorded once, not every five minutes
        self.alerted.add(key)
        rec = self.ex.submit(order, refusals)
        if rec["status"] in ("rejected", "ambiguous"):
            self.alert("critical", f"order_{rec['status']}:{rec['id']}", f"order {ticker} {qty}: {rec['status']}: "
                                                                          f"{rec.get('error', '')[:200]}")
        return rec

    # ------------------------------------------------------------ health and alerts
    def alert(self, level: str, code: str, text: str) -> None:
        key = f"{feeds_ts(self.clock())[:10]}:{code}"
        if key in self.alerted:
            return
        self.alerted.add(key)
        self.s.event("alert", level=level, code=code, text=text)

    def write_heartbeat(self) -> None:
        now = self.clock()
        ages = {k: round(now - v) for k, v in self.last_ok.items()}
        bad = sorted(k for k, v in self.quote_state.items() if v != "ok")
        self.s.heartbeat({"version": self.cfg["version"], "loops": self.loops, "up_s": round(now - self.started),
                          "duty_age_s": ages, "duty_failures": {k: v for k, v in self.fail.items() if v},
                          "invalid_quotes": bad, "positions": len(self.positions),
                          "total_gbp": (self.summary or {}).get("totalValue"), "control": self.s.control(),
                          "unresolved_orders": len(execution.unresolved(self.s.intents())),
                          "consecutive_order_errors": self.ex.consecutive_errors})
        self.s.event("heartbeat", loops=self.loops, up_s=round(now - self.started), duty_age_s=ages)

    def _t212_of(self, sym: str) -> str | None:
        ov = self.cfg["yahoo_overrides"]
        for t in list(self.positions) + [self.cfg["benchmark"]["t212"]]:
            if feeds.yahoo_symbol(t, ov) == sym:
                return t
        return None


def feeds_ts(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
