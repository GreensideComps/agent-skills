"""The always-on loop: poll, validate, evaluate, act behind the risk gate, persist, report health.

Each duty runs on its own interval and fails independently: one failing feed is recorded, backed off and retried
without stopping the rest. Nothing here sends an order except `Executor.submit`, and only after `risk_check`.
"""
from __future__ import annotations

import json
import math
import time
import traceback
import uuid
from pathlib import Path

from . import active, execution, feeds

HERE = Path(__file__).resolve().parent


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or HERE / "config.json").read_text())


class Agent:
    def __init__(self, store, client, cfg: dict, *, ambiguous_exc, api_exc, get=feeds.http_get,
                 clock=time.time, sleep=time.sleep):
        self.s, self.c, self.cfg, self.get, self.clock, self.sleep = store, client, cfg, get, clock, sleep
        self.ex = execution.Executor(store, client, ambiguous_exc, api_exc)
        self.wiki_get = feeds.wiki_get if get is feeds.http_get else get
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
        if ((self.cfg.get("active") or {}).get("attention") or {}).get("enabled"):
            self._run("attention", self.refresh_attention)
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
        want = set(self.positions) | {self.cfg["benchmark"]["t212"]} | set(self.cfg["exits"]["tickers"]) | set(self._watch())
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
        self._sync_stops()
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
        syms |= set(self.cfg["extra_symbols"]) | {feeds.yahoo_symbol(t, ov) for t in self._watch()}
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

    def refresh_attention(self) -> None:
        """attention_spike, logged forward only: each watched name's Wikipedia views against its own 28-day norm,
        with the day's price move, so the signal builds a record before it may trade."""
        a = self.cfg["active"]["attention"]
        now = self.clock()
        end = time.strftime("%Y%m%d", time.gmtime(now - 86400))
        start = time.strftime("%Y%m%d", time.gmtime(now - 86400 * (a["lookback_days"] + 12)))
        rows = []
        for t, art in sorted(a["articles"].items()):
            z, err = None, None
            for wait in (0, 15):  # one retry after a pause if Wikimedia rate-limits us (HTTP 429)
                self.sleep(wait or 2.0)  # polite pacing for the Wikimedia API
                try:
                    z, err = feeds.attention_z(feeds.pageviews(art, start, end, get=self.wiki_get),
                                               a["lookback_days"]), None
                    break
                except Exception as e:  # noqa: BLE001 - one missing article never stops the rest
                    err = str(e)[:120]
            if err:
                rows.append({"ticker": t, "error": err})
                continue
            q = self.quotes.get(feeds.yahoo_symbol(t, self.cfg["yahoo_overrides"]) or "")
            rows.append({"ticker": t, **(z or {}), "px": q and q["price"],
                         "move": q and q.get("prev_close") and round(q["price"] / q["prev_close"] - 1, 4)})
        self.s.event("attention", rows=rows)
        for r in rows:
            if (r.get("z") or 0) >= a["z_threshold"]:
                self.s.event("attention_signal", strategy="attention_spike", traded=False, **r)

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
            if r["weight"] and r["weight"] * 100 > lim["concentration_pct"] and r["ticker"] != self.cfg["benchmark"]["t212"]:
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
        """agent-1.1 takes three kinds of action, at most one order per pass (each waits for the last to resolve):
        the authorised full exits, the satellite rebalance (pro rata trims to the target weight and the single-name
        cap, from a plan fixed when the rebalance starts), and investing idle cash in the VWRP core once no sell is
        outstanding. Everything else is a recorded no-trade."""
        day = feeds_ts(self.clock())[:10]
        notes: list[str] = []
        if execution.unresolved(self.s.intents()):
            notes.append("waits: an earlier order is unresolved")
            self.s.event("decision", orders=[], no_trade=True, notes=notes)
            return
        vw = self.quotes.get(self.cfg["benchmark"]["yahoo"])
        vwrp_px = vw["price"] if vw else None
        recs = self.s.intents()
        self._place_stops(recs, notes)
        sells = self._exit_orders(notes) + self._active_exits(recs, vwrp_px) + self._rebalance_orders(notes)
        order = None
        if sells:
            order = next((o for o in sells if self.market_open(o[0])), None)
            if order is None:
                notes.append(f"{len(sells)} sell(s) wait for their market to open")
        else:
            order = self._core_order(day, notes)
            if order is None:
                order = self._active_entry(recs, day, vwrp_px, notes)
        acted = [self._order(*order, day)] if order else []
        self.s.event("decision", orders=[a for a in acted if a],
                     no_trade=not any(a and a.get("status") == "placed" for a in acted), notes=notes)

    def _quote(self, t212: str) -> dict | None:
        sym = feeds.yahoo_symbol(t212, self.cfg["yahoo_overrides"])
        return self.quotes.get(sym) if self.quote_state.get(sym) == "ok" else None

    def _value(self, p: dict) -> float:
        return float((p.get("walletImpact") or {}).get("currentValue") or 0)

    def _exit_orders(self, notes: list[str]) -> list[tuple]:
        out = []
        for t in self.cfg["exits"]["tickers"]:
            p = self.positions.get(t)
            if not p:
                continue
            avail = float(p.get("quantityAvailableForTrading") or 0)
            if avail <= 0:
                notes.append(f"{t}: {p.get('quantityInPies')} held in a pie, 0 tradeable via the API")
                self.alert("warn", f"exit_blocked_pie:{t}",
                           f"exit of {t} waits: its shares are inside a pie (the API cannot sell pie shares)")
                continue
            q = self._quote(t)
            val = self._value(p) * avail / float(p.get("quantity") or avail)
            out.append((t, -avail, val, float(p.get("currentPrice") or 0), q is not None,
                        f"exit: {self.cfg['exits']['rationale']}", {"type": "authorised_exit", "quote": q}))
        return out

    # ------------------------------------------------------------ active sleeve (C6)
    def _watch(self) -> list[str]:
        a = self.cfg.get("active") or {}
        return list(a.get("watchlist", [])) if a.get("enabled") else []

    def _active_exits(self, recs, vwrp_px) -> list[tuple]:
        if not self._watch():
            return []
        stops = self.s.read("stops.json") or {}
        resting = {v["ticker"]: (k, v) for k, v in stops.items() if v.get("order_id")}
        # a resting sell stop holds the shares, so the trade's whole quantity counts as available to exit
        pos = {t: ({**p, "quantityAvailableForTrading": p.get("quantity")} if t in resting else p)
               for t, p in self.positions.items()}
        out = []
        for o in active.exit_orders(recs, pos, self._quote, self.clock(), vwrp_px):
            if o[0] not in resting:
                out.append(o)
                continue
            k, v = resting[o[0]]
            if not self.market_open(o[0]) or self.s.control().get("trading_enabled") is not True:
                continue  # keep the protection until the exit could actually be sent
            try:  # cancel the broker stop first; the exit goes out on a later pass once the broker shows it gone
                self.c.cancel_order(v["order_id"])
                self.s._replace("stops.json", {**stops, k: {**v, "order_id": None, "cancelled": feeds_ts(self.clock()),
                                                             "why": o[6]["why"]}})
                self.s.event("stop_cancelled", entry=k, ticker=o[0], order_id=v["order_id"], for_exit=o[6]["why"])
            except Exception as e:  # noqa: BLE001 - it may have just filled; the next sync reads the broker's record
                self.s.event("stop_cancel_failed", entry=k, ticker=o[0], error=str(e)[:300])
            self.due["broker"] = 0
        return out

    def _place_stops(self, recs, notes) -> None:
        """Give every open active trade a resting broker stop at its own stop-loss level (kill switch respected)."""
        if not self._watch() or self.s.control().get("trading_enabled") is not True:
            return
        stops = self.s.read("stops.json") or {}
        for n in active.stops_needed(recs, self.positions, stops):
            if not self.market_open(n["ticker"]):
                continue  # placed during the market's own hours, when the broker accepts and works it
            try:
                ack = self.c.place_stop_order(n["ticker"], -n["qty"], n["stop_px"])
                stops[n["entry_id"]] = {"order_id": (ack or {}).get("id"), "ticker": n["ticker"], "qty": n["qty"],
                                        "stop_px": n["stop_px"], "ts": feeds_ts(self.clock()), "ack": ack}
                self.s.event("stop_placed", entry=n["entry_id"], **{k: n[k] for k in ("ticker", "qty", "stop_px")},
                             order_id=stops[n["entry_id"]]["order_id"])
                notes.append(f"broker stop placed: {n['ticker']} {n['qty']} at {n['stop_px']}")
            except Exception as e:  # noqa: BLE001 - recorded once; the agent's own stop still watches while it runs
                stops[n["entry_id"]] = {"order_id": None, "ticker": n["ticker"], "failed": str(e)[:300],
                                        "ts": feeds_ts(self.clock())}
                self.s.event("stop_failed", entry=n["entry_id"], ticker=n["ticker"], error=str(e)[:300])
                self.alert("warn", f"stop_failed:{n['ticker']}", f"broker stop for {n['ticker']} refused: {str(e)[:150]}")
            self.s._replace("stops.json", stops)

    def _sync_stops(self) -> None:
        """Record a broker stop that filled as the trade's exit; forget one the broker cancelled or rejected."""
        stops = self.s.read("stops.json") or {}
        live = {execution._hid(p) for p in self.pending}
        entries = {e["id"]: e for e in active.open_trades(self.s.intents())}
        changed = False
        for k, v in list(stops.items()):
            oid = v.get("order_id")
            if not oid or oid in live:
                continue
            h = next((x for x in self.c.history_orders(ticker=v["ticker"], limit=20, max_pages=1)
                      if execution._hid(x) == oid), None)
            st = execution._hist_status(h) if h else None
            if st == "filled" and k in entries:
                vw = self.quotes.get(self.cfg["benchmark"]["yahoo"])
                rec = self.s.intent(id=uuid.uuid4().hex, **active.stop_exit_record(entries[k], v, h,
                                                                                    vw["price"] if vw else None))
                self.s.event("order_outcome", intent=rec["id"], status="filled", broker=h, via="broker_stop")
                self.alert("info", f"stop_filled:{v['ticker']}", f"broker stop filled: {v['ticker']} at {v['stop_px']}")
                stops[k] = {**v, "order_id": None, "filled": feeds_ts(self.clock())}
                changed = True
            elif st in ("cancelled", "rejected"):
                stops[k] = {**v, "order_id": None, st: feeds_ts(self.clock())}
                self.s.event(f"stop_{st}", entry=k, ticker=v["ticker"], order_id=oid)
                changed = True
        if changed:
            self.s._replace("stops.json", stops)

    def _active_entry(self, recs, day, vwrp_px, notes) -> tuple | None:
        if not self._watch():
            return None
        disabled = self.s.read("strategies.json") or {}
        new = active.kill_check(active.strategy_scores(recs), self.cfg, disabled, feeds_ts(self.clock()))
        if new:
            disabled = {**disabled, **new}
            self.s._replace("strategies.json", disabled)
            for k, v in new.items():
                self.s.event("strategy_disabled", strategy=k, **v)
                self.alert("warn", f"strategy_disabled:{k}", f"strategy {k} switched off: {v['why']}")
        total = float((self.summary or {}).get("totalValue") or 0)
        cash = float(((self.summary or {}).get("cash") or {}).get("availableToTrade") or 0)
        fxq = self.quotes.get(self.cfg["benchmark"]["fx"])
        orders, n = active.entry_orders(self.cfg, recs, self.positions, self._quote, fxq["price"] if fxq else None,
                                        total, cash, day, self.clock(), vwrp_px, disabled)
        notes += n
        if any("FROZEN" in x for x in n):
            self.alert("critical", "active_frozen", n[0])
        return next((o for o in orders if self.market_open(o[0])), None)

    def _satellite(self) -> dict[str, dict]:
        skip = {self.cfg["benchmark"]["t212"], *self.cfg["exits"]["tickers"], *self._watch()}
        return {t: p for t, p in self.positions.items() if t not in skip}

    def _rebalance_orders(self, notes: list[str]) -> list[tuple]:
        sat = self.cfg.get("satellite") or {}
        if not sat.get("enabled"):
            return []
        total = float((self.summary or {}).get("totalValue") or 0)
        if total <= 0:
            return []
        held = self._satellite()
        plan = self.s.read("rebalance_plan.json")
        if plan and plan.get("status") == "active":
            pass
        else:
            value = sum(self._value(p) for p in held.values())
            cap = sat["single_name_cap"] * total
            if value / total <= sat["rebalance_above"] and all(self._value(p) <= cap * 1.1 for p in held.values()):
                return []
            # Fix the targets once, so the trims converge however prices and the order of fills move.
            f = min(1.0, sat["target_weight"] * total / value) if value else 1.0
            targets = {}
            for t, p in held.items():
                v = self._value(p)
                tv = min(v * f, cap)
                qty = float(p.get("quantity") or 0)
                targets[t] = {"value_now": round(v, 2), "target_value": round(tv, 2) if tv >= sat["min_position_gbp"] else 0.0,
                              "target_qty": round(qty * tv / v, 8) if v and tv >= sat["min_position_gbp"] else 0.0}
            plan = {"status": "active", "ts": feeds_ts(self.clock()), "total_gbp": total, "satellite_gbp": round(value, 2),
                    "factor": round(f, 6), "rationale": sat["rationale"], "targets": targets}
            self.s._replace("rebalance_plan.json", plan)
            self.s.event("rebalance_plan", **plan)
        out = []
        for t, tg in plan["targets"].items():
            p = held.get(t)
            if not p:
                continue
            qty, avail = float(p.get("quantity") or 0), float(p.get("quantityAvailableForTrading") or 0)
            v = self._value(p)
            px = v / qty if qty else 0
            sell = qty if tg["target_qty"] <= 0 else qty - tg["target_qty"]
            if tg["target_qty"] > 0:
                d = 10 ** sat["qty_decimals"]
                sell = math.floor(sell * d) / d
            sell = min(sell, avail)
            if sell <= 0 or (tg["target_qty"] > 0 and sell * px < sat["min_trade_gbp"]):
                continue
            q = self._quote(t)
            out.append((t, -sell, sell * px, float(p.get("currentPrice") or 0), q is not None,
                        f"rebalance: {sat['rationale']} Target {tg['target_value']:.2f} GBP from {tg['value_now']:.2f}.",
                        {"type": "satellite_trim", "plan_ts": plan["ts"], "target": tg, "quote": q}))
        if not out:
            plan = {**plan, "status": "done", "done_ts": feeds_ts(self.clock())}
            self.s._replace("rebalance_plan.json", plan)
            self.s.event("rebalance_done", plan_ts=plan["ts"])
        return out

    def _core_order(self, day: str, notes: list[str]) -> tuple | None:
        cash = float(((self.summary or {}).get("cash") or {}).get("availableToTrade") or 0)
        core, lim = self.cfg["core"], self.cfg["limits"]
        bt = self.cfg["benchmark"]["t212"]
        if cash <= core["invest_cash_above_gbp"]:
            notes.append(f"cash £{cash:.2f}: below the £{core['invest_cash_above_gbp']:.0f} investing threshold")
            return None
        last = [r for r in execution.today_orders(self.s.intents(), day)
                if (r.get("signal") or {}).get("type") == "core_invest"]
        if last and self.clock() - max(float(r.get("t", 0)) for r in last) < core["cooldown_s"]:
            notes.append("core buy cooling down: cash figures may lag the last fill")
            return None
        q = self._quote(bt)
        if not q:
            notes.append(f"core buy waits: no validated {self.cfg['benchmark']['yahoo']} price "
                         f"({self.quote_state.get(self.cfg['benchmark']['yahoo'])})")
            return None
        total = float((self.summary or {}).get("totalValue") or 0)
        keep = (self.cfg.get("active") or {}).get("cash_reserve_weight", 0) * total if self._watch() else 0.0
        if cash - keep <= core["invest_cash_above_gbp"]:
            notes.append(f"cash £{cash:.2f}: £{keep:.2f} is kept for the active sleeve")
            return None
        spend = min((cash - keep - core["cash_buffer_gbp"]) / (1 + core.get("buy_reserve", 0)), lim["max_order_gbp"])
        qty = math.floor(spend / q["price"] * 100) / 100
        if qty <= 0:
            return None
        return (bt, qty, qty * q["price"], q["price"], True, f"core: {core['rationale']} Cash £{cash:.2f} is idle.",
                {"type": "core_invest", "quote": q, "cash": cash})

    def _order(self, ticker, qty, value, price, quote_ok, reason, signal, day):
        order = {"ticker": ticker, "quantity": qty, "value_gbp": abs(value), "price": price, "reason": reason,
                 "signal": signal}
        total = float((self.summary or {}).get("totalValue") or 0)
        if qty > 0 and total:
            order["post_weight"] = (self._value(self.positions.get(ticker) or {}) + abs(value)) / total
        refusals = execution.risk_check(order, control=self.s.control(), records=self.s.intents(),
                                        pending=self.pending, positions=self.positions, limits=self.cfg["limits"],
                                        day=day, consecutive_errors=self.ex.consecutive_errors, quote_ok=quote_ok,
                                        market_open=self.market_open(ticker))
        key = f"{ticker}:{qty}:{';'.join(refusals)}"
        if refusals and key in self.alerted:
            return None  # the same refusal is recorded once, not every five minutes
        self.alerted.add(key)
        rec = self.ex.submit(order, refusals)
        if rec["status"] == "placed":
            self.due["broker"] = min(self.due.get("broker", 0), self.clock() + 20)  # confirm the fill quickly
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
        for t in list(self.positions) + [self.cfg["benchmark"]["t212"]] + self._watch():
            if feeds.yahoo_symbol(t, ov) == sym:
                return t
        return None


def feeds_ts(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
