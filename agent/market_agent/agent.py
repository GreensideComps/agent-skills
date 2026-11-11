"""The always-on loop: poll, validate, evaluate, act behind the risk gate, persist, report health.

Each duty runs on its own interval and fails independently: one failing feed is recorded, backed off and retried
without stopping the rest. Nothing here sends an order except `Executor.submit`, and only after `risk_check`.
"""
from __future__ import annotations

import calendar
import json
import math
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import quote

from . import (
    active,
    buyback_value,
    datasrc,
    exits,
    execution,
    feeds,
    gap_rebound,
    merger,
    news_shock,
    slippage,
    review,
    social,
    stock_screen,
    swing,
    value_timing,
)

HERE = Path(__file__).resolve().parent


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or HERE / "config.json").read_text())


FRAMES = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/{p}.json"


class Agent:
    def __init__(self, store, client, cfg: dict, *, ambiguous_exc, api_exc, get=feeds.http_get,
                 clock=time.time, sleep=time.sleep, sec_get=None):
        self.sec_get = sec_get  # SEC EDGAR getter; built from the contact User-Agent on first use when not injected
        self.s, self.c, self.cfg, self.get, self.clock, self.sleep = store, client, cfg, get, clock, sleep
        self.ex = execution.Executor(store, client, ambiguous_exc, api_exc)
        self.wiki_get = feeds.wiki_get if get is feeds.http_get else get
        self.due: dict[str, float] = {}
        self.fail: dict[str, int] = {}
        self.skipped: dict[str, float] = {}
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
        self.reviews: dict[str, dict] = {}   # agent-1.5 multi-horizon review per T212 ticker
        self.attn: dict[str, float] = {}     # last Wikipedia attention z per T212 ticker
        self.earn: dict[str, str] = {}
        self.earn_t = 0.0
        self.earn_day: dict[str, str] = {}   # agent-1.21: day each name's SEC results check last ran
        self.broker_t = 0.0                  # when positions (and their broker prices) were last read
        self.data = None                     # datasrc.Honest when the agent runs on the honest data sources
        self.mstate: dict = store.read("merger.json") or {}
        self.bars: dict[str, dict] = {}      # daily bars per T212 ticker, from the review pass
        self.squeezes: dict[str, dict] = {}  # vol_squeeze readings on the last finished session
        self.gaps: dict[str, dict] = {}      # gap_go candidates found at today's check
        self.gap_done: dict[str, str] = {}   # ticker -> day its gap check ran  # merger_arb deals, terminations, watch list

    # ------------------------------------------------------------ scheduling
    def _run(self, name: str, fn) -> None:
        now = self.clock()
        if now < self.due.get(name, 0):
            return
        base = self.cfg["intervals_s"][name]
        try:
            nxt = fn()  # a duty may ask to run again sooner than its interval, in seconds
            self.fail[name] = 0
            self.last_ok[name] = self.clock()
            self.due[name] = now + (nxt if isinstance(nxt, (int, float)) and not isinstance(nxt, bool) else base)
        except Exception as e:  # noqa: BLE001 - every duty is isolated; the failure is recorded and retried
            until = getattr(e, "tiingo_down_until", None)
            if until:  # agent-1.22.6: a known Tiingo outage is a skip, logged once per outage, not a failure
                self.due[name] = now + base
                if self.skipped.get(name) != until:
                    self.skipped[name] = until
                    self.s.event("duty_skipped", duty=name, why=str(e)[:200])
                return
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
        if ((self.cfg.get("active") or {}).get("attention") or {}).get("enabled"):
            self._run("attention", self.refresh_attention)
        if self._watch() and ((self.cfg.get("active") or {}).get("review") or {}).get("enabled"):
            self._run("review", self.refresh_review)
        if self._social():
            self._run("social", self.refresh_social)
        if self._merger():
            self._run("merger", self.refresh_merger)
        if self._screen():
            self._run("screen_watch", self.refresh_screen_watch)
        if self._gap_rebound():
            self._run("gap_rebound", self.refresh_gap_rebound)
        if self._exit_cfg():
            self._run("exit_review", self.refresh_exit_review)
        if self._news_shock():
            self._run("news_shock", self.refresh_news_shock)
        if (self.cfg.get("slippage") or {}).get("enabled"):
            self._run("slippage", self.refresh_slippage)
        if self._swing("gap"):
            self._run("gaps", self.refresh_gaps)
        if self._vt():
            self._run("timing", self.refresh_value_timing)
        if (self.cfg.get("scoreboard") or {}).get("enabled"):
            self._run("scoreboard", self.refresh_scoreboard)
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
        self.broker_t = self.clock()
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

    def broker_quotes(self) -> dict[str, dict]:
        """agent-1.21: London lines are priced from the broker's own position price ({yahoo symbol: {price, t}}), as
        no free source serves LSE quotes to an honest client. agent-1.22.2: every held line has one (US lines use it
        only when Tiingo fails), plus GBPUSD=X implied by the broker's USD positions (median of quantity x price /
        GBP value). Lines not held stay UNVERIFIED."""
        ov = self.cfg["yahoo_overrides"]
        out, fx = {}, []
        for t, p in self.positions.items():
            sym = feeds.yahoo_symbol(t, ov)
            px = p.get("currentPrice")
            if sym and px:
                out[sym] = {"price": float(px), "t": self.broker_t}
            v, q = float((p.get("walletImpact") or {}).get("currentValue") or 0), float(p.get("quantity") or 0)
            if px and v > 1 and q > 0 and (p.get("instrument") or {}).get("currency") == "USD":
                fx.append(q * float(px) / v)
        if fx:
            fx.sort()
            out[self.cfg["benchmark"]["fx"]] = {"price": fx[len(fx) // 2], "t": self.broker_t}
        return out

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
        self.attn = {r["ticker"]: r["z"] for r in rows if r.get("z") is not None}
        self.s.event("attention", rows=rows)
        for r in rows:
            if (r.get("z") or 0) >= a["z_threshold"]:
                self.s.event("attention_signal", strategy="attention_spike", traded=False, **r)

    def refresh_review(self) -> None:
        """Score every watched name and open trade on short, medium and long horizons (review.py) and log it."""
        rc = self.cfg["active"]["review"]
        now = self.clock()
        held = sorted({e["ticker"] for e in active.open_trades(self.s.intents())})
        names = held + sorted(set(self._watch()) - set(held))  # agent-1.22.4: held lines first, so a data cap
        # (Tiingo 45/h) starves watchlist names, never the review of what we own
        self._earnings_sec(names, rc["earnings_block_days"], now)
        rows = []
        for t in names:
            sym = feeds.yahoo_symbol(t, self.cfg["yahoo_overrides"])
            try:
                bars = swing.ohlcv(sym, self.get)
                closes, vols = bars["c"], bars["v"]
                if not closes:
                    raise ValueError(f"no daily bars for {sym}")
            except Exception as e:  # noqa: BLE001 - a name without history gets no review, so no entry
                rows.append({"ticker": t, "error": str(e)[:120]})
                self.reviews.pop(t, None)
                self.bars.pop(t, None)
                self.squeezes.pop(t, None)
                continue
            finally:
                self.sleep(0.5)
            self.bars[t] = {**bars, "fetched": now}
            sq = self._swing("squeeze")
            if sq and t in self.cfg["active"]["watchlist"]:
                self.squeezes[t] = {**swing.squeeze(swing.completed(bars, now), sq), "t": now}
            q = self._quote(t)
            f = review.factors(closes, vols, q["price"] if q else None)
            rev = {"t": now, "ticker": t, "factors": f, "scores": review.score(f, self.attn.get(t)),
                   "earnings": self.earn.get(sym, "UNVERIFIED (results check not run)") if t.endswith("_US_EQ")
                   else None}
            self.reviews[t] = rev
            rows.append({k: v for k, v in rev.items() if k != "t"})
        self.s.event("review", rows=rows)
        if self.squeezes:
            self.s.event("squeeze_scan", strategy=swing.SQUEEZE,
                         rows=[{"ticker": t, **{k: v for k, v in r.items() if k != "t"}} for t, r in sorted(self.squeezes.items())])

    def refresh_social(self) -> float | None:
        """social_trend (C8): once per Friday close, score every brand's Wikipedia attention and 20-day run-up and
        keep the candidates in state/social.json. A partial scan is finished on the next run, never re-scored."""
        sc = self._social()
        now = self.clock()
        fri = social.signal_friday(now)
        scan = self.s.read("social.json") or {}
        if scan.get("friday") != fri:
            scan = {"friday": fri, "started": feeds_ts(now), "valid_until": social.valid_until(fri, sc["valid_days"]),
                    "confirmation": social.CONFIRMATION, "rows": {}}
        if sc.get("vix_min") is not None and scan.get("vix") is None:  # the bench gate reads the Friday's VIX close
            try:
                vb = [(d, c) for d, c, _ in gap_rebound.bars("^VIX", self.get) if d <= fri]
                if vb and vb[-1][0] == fri:
                    scan["vix"] = round(vb[-1][1], 2)
                    self.s._replace("social.json", scan)
            except Exception as e:  # noqa: BLE001 - unread VIX: UNVERIFIED, so no social entry
                self.s.event("social_vix_unread", strategy=social.NAME, friday=fri, error=str(e)[:200])
        todo = [t for t in sorted(sc["universe"])
                if t not in scan["rows"] or (scan["rows"][t].get("error") and scan["rows"][t].get("tries", 1) < 3)]
        if not todo:
            return None
        fri_t = calendar.timegm(time.strptime(fri, "%Y-%m-%d"))
        end = time.strftime("%Y%m%d", time.gmtime(min(fri_t, now - 86400)))  # whole days only, up to the Friday
        start = time.strftime("%Y%m%d", time.gmtime(fri_t - 86400 * (28 + 7 * 52 + 14)))
        done: list[str] = []
        wait = None
        for t in todo[:sc["brands_per_run"]]:  # a few brands per run, so the loop never stalls for long
            self.s.renew_lease()
            art = sc["universe"][t]
            row = {"ticker": t, "article": art, "tries": (scan["rows"].get(t) or {}).get("tries", 0) + 1}
            self.sleep(sc["pacing_s"])  # Wikimedia limits unidentified callers to 10 requests a minute
            try:
                row.update(social.attention(feeds.pageviews(quote(art, safe=""), start, end, get=self.wiki_get)) or {})
            except Exception as e:  # noqa: BLE001 - one missing brand never stops the rest
                if getattr(e, "retry_after", 0):  # rate-limited: stop here and come back when Wikimedia says
                    wait = max(60.0, e.retry_after)
                    break
                row["error"] = str(e)[:120]
            if "error" not in row:
                try:
                    closes, _ = review.history(feeds.yahoo_symbol(t, self.cfg["yahoo_overrides"]), self.get)
                    r = social.run_up(closes)
                    row["ret20"] = r if r is None else round(r, 4)
                except Exception as e:  # noqa: BLE001
                    row["price_error"] = str(e)[:120]
            scan["rows"][t] = social.judge(row, sc)
            done.append(t)
        if not done:
            return wait or sc["resume_s"]
        scan["ts"] = feeds_ts(self.clock())
        self.s._replace("social.json", scan)
        errs = sorted(t for t, r in scan["rows"].items() if r.get("error"))
        cands = sorted(t for t, r in scan["rows"].items() if r.get("candidate"))
        self.s.event("social_scan", strategy=social.NAME, friday=fri, candidates=cands, errors=errs,
                     confirmation=social.CONFIRMATION, rows=[scan["rows"][t] for t in done])
        for t in cands:
            if t in done:
                self.s.event("social_signal", strategy=social.NAME, friday=fri, **scan["rows"][t])
        if wait or len(done) < len(todo) or any(r.get("error") and r["tries"] < 3 for r in scan["rows"].values()):
            return wait or sc["resume_s"]  # finish the scan sooner than the hourly cadence
        return None

    def refresh_merger(self) -> float | None:
        """merger_arb (C8): find agreed all-cash takeovers in SEC EDGAR, read their filings (cached, a few per run),
        and keep the deal list in state/merger.json; flag terminations and record deals that closed."""
        mc = self._merger()
        if self.sec_get is None:
            ua = feeds.sec_user_agent(self.s.root)
            if not ua:
                if "merger_no_ua" not in self.alerted:
                    self.alerted.add("merger_no_ua")
                    self.s.event("merger_scan", strategy=merger.NAME, skipped="no SEC contact User-Agent configured")
                return None
            self.sec_get = feeds.sec_get(ua)
        get, now = self.sec_get, self.clock()
        day = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t))  # noqa: E731
        hits = merger.search(get, day(now - mc["lookback_days"] * 86400), day(now))
        st = {"docs": {}, "terminated": {}, "gone": {}, **(self.s.read("merger.json") or {})}
        docs = {k: v for k, v in st["docs"].items() if k in {h["id"] for h in hits}}
        tciks = {h["target"]["cik"] for h in hits if merger.is_target_form(h["form"])}
        todo = [h for h in sorted(hits, key=lambda h: h["date"], reverse=True)
                if h["target"]["cik"] in tciks and h["id"] not in docs]
        for h in todo[:mc["docs_per_run"]]:
            self.s.renew_lease()
            self.sleep(mc["pacing_s"])  # well under the SEC's 10 requests a second
            try:
                docs[h["id"]] = merger.parse(merger.text_of(get(h["url"], {})), h["form"])
            except Exception as e:  # noqa: BLE001 - an unreadable filing confirms nothing
                docs[h["id"]] = {"error": str(e)[:120], "price": None, "mixed": False, "hostile": False,
                                 "agreement": False, "close": None}
        known = self.schedule_of

        def tradeable(tk):
            t = f"{tk}_US_EQ"
            return t if t in known else None
        deals = merger.build_deals(hits, docs, tradeable)
        recs = self.s.intents()
        vw = self.quotes.get(self.cfg["benchmark"]["yahoo"])
        fxq = self.quotes.get(self.cfg["benchmark"]["fx"])
        for e in merger.open_deals(recs):
            tk, tgt, since = e["ticker"], e["signal"]["target"], e.get("ts", "")[:10]
            if tk not in st["terminated"]:
                self.sleep(mc["pacing_s"])
                th = merger.search(get, since, day(now), pages=1, q='"merger agreement"', forms="8-K",
                                   ciks=tgt["cik"].zfill(10))
                t = merger.terminated(th, tgt["cik"], since)
                if t:
                    st["terminated"][tk] = {"ts": feeds_ts(now), "filing": t["id"], "date": t["date"]}
                    self.s.event("merger_terminated", strategy=merger.NAME, ticker=tk, filing=t["id"])
                    self.alert("warn", f"merger_terminated:{tk}", f"{tk}: target filed a termination 8-K; exiting")
            if tk in self.positions:
                st["gone"].pop(e["id"], None)
                continue
            first = st["gone"].setdefault(e["id"], now)
            if now - first >= mc["closed_after_s"]:  # shares gone for a day with no sell of ours: cashed out
                rec = self.s.intent(id=uuid.uuid4().hex, **merger.closed_exit_record(
                    e, fxq["price"] if fxq else None, vw["price"] if vw else None))
                self.s.event("order_outcome", intent=rec["id"], status="filled", via="deal_closed", estimated=True)
                self.alert("info", f"merger_closed:{tk}", f"{tk}: deal closed, cash-out recorded at the offer")
                st["gone"].pop(e["id"], None)
        open_tk = {e["ticker"] for e in merger.open_deals(self.s.intents())}
        st.update(ts=feeds_ts(now), docs=docs, deals=deals,
                  watch=sorted({t for t, d in deals.items() if d["eligible"]} | open_tk))
        self.s._replace("merger.json", st)
        if st["watch"] != self.mstate.get("watch"):
            self.due["prices"] = 0  # price newly found deals before the next decision
        self.mstate = st
        self.s.event("merger_scan", strategy=merger.NAME, hits=len(hits), read=len(docs), deals=len(deals),
                     eligible={t: {k: d[k] for k in ("offer", "close")} for t, d in deals.items() if d["eligible"]},
                     skipped={t: d["why"] for t, d in deals.items() if not d["eligible"]})
        return mc["resume_s"] if len(todo) > mc["docs_per_run"] else None

    def refresh_gaps(self) -> None:
        """gap_go: once per name per day, 30-60 minutes after its US open, read today's 1-minute bars for a name that
        opened up; a check the agent slept through is logged as missed."""
        gc = self._swing("gap")
        now = self.clock()
        day = feeds_ts(now)[:10]
        self.gaps = {t: g for t, g in self.gaps.items() if g["day"] == day}
        rows = []  # one gap_scan event per run that checked anything: [{ticker, gap, held, signal, why}]
        for t in self.cfg["active"]["watchlist"]:
            if self.gap_done.get(t) == day:
                continue
            open_t = self._session_open(t)
            if open_t is None or now < open_t + gc["check_from_s"]:
                continue
            self.gap_done[t] = day
            if now > open_t + gc["check_to_s"]:
                self.s.event("gap_go_missed", strategy=swing.GAP, ticker=t, why="the agent was not running in the check window")
                rows.append({"ticker": t, "gap": None, "held": None, "signal": False, "why": "missed: agent not running"})
                continue
            q = self._quote(t)
            if not q or not q.get("prev_close"):
                rows.append({"ticker": t, "gap": None, "held": None, "signal": False, "why": "no validated quote"})
                continue
            if q["price"] / q["prev_close"] - 1 < gc["min_gap"] * gc["min_held"]:
                rows.append({"ticker": t, "gap": None, "held": None, "signal": False,
                             "why": f"up {q['price'] / q['prev_close'] - 1:+.1%}: cannot be a held gap"})
                continue  # no intraday fetch
            try:
                bars = swing.ohlcv(feeds.yahoo_symbol(t, self.cfg["yahoo_overrides"]), self.get, "1d", "1m")
            except Exception as e:  # noqa: BLE001 - no bars, no signal
                self.s.event("gap_check", strategy=swing.GAP, ticker=t, signal=False, why=f"no data: {str(e)[:100]}")
                rows.append({"ticker": t, "gap": None, "held": None, "signal": False, "why": f"no data: {str(e)[:100]}"})
                continue
            finally:
                self.sleep(0.5)
            g = swing.gap_check(bars, q["prev_close"], open_t, now, gc)
            self.s.event("gap_check", strategy=swing.GAP, ticker=t, **g)
            rows.append({"ticker": t, "gap": g.get("gap"), "held": g.get("held"), "signal": g["signal"], "why": g["why"]})
            if g["signal"]:
                self.gaps[t] = {**g, "day": day}
        if rows:
            self.s.event("gap_scan", strategy=swing.GAP, rows=rows)

    def refresh_scoreboard(self) -> None:
        """Run the research scoreboard (a separate script) once a day after the US close and after each new active
        exit fill. It runs in its own process with no credentials in its environment; a failure is only logged."""
        import subprocess
        sb = self.cfg["scoreboard"]
        now = self.clock()
        day = feeds_ts(now)[:10]
        exits = sum(1 for r in execution.latest_intents(self.s.intents()).values()
                    if (r.get("signal") or {}).get("type") == "active_exit" and r["status"] == "filled")
        last = getattr(self, "_sb", {"day": None, "exits": None})
        after_close = time.gmtime(now).tm_hour >= sb["after_hour_utc"] and last["day"] != day
        if not (after_close or (last["exits"] is not None and exits > last["exits"])):
            if last["exits"] is None:
                self._sb = {"day": last["day"], "exits": exits}
            return
        self._sb = {"day": day if after_close else last["day"], "exits": exits}
        if not Path(sb["path"]).exists():
            self.s.event("scoreboard", ok=False, why="script not found")
            return
        try:
            r = subprocess.run(["python3", "-I", sb["path"], "--state", str(self.s.root)], capture_output=True,
                               text=True, timeout=sb["timeout_s"], env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
            self.s.event("scoreboard", ok=r.returncode == 0, out=(r.stdout or r.stderr)[-300:])
        except Exception as e:  # noqa: BLE001 - the scoreboard never affects trading
            self.s.event("scoreboard", ok=False, why=str(e)[:200])

    def _session_open(self, t212: str) -> float | None:
        """When today's regular session opened for this instrument, while it is open; None otherwise."""
        sid = self.schedule_of.get(t212)
        if sid is None or sid not in self.sessions:
            return None
        st = feeds.session_state(self.sessions[sid], self.clock())
        return st["last_event"][0] if st["open"] and st["last_event"] else None

    def _session_close(self, t212: str) -> float | None:
        sid = self.schedule_of.get(t212)
        if sid is None or sid not in self.sessions:
            return None
        return feeds.session_state(self.sessions[sid], self.clock())["next_close"]

    def _swing(self, which: str) -> dict | None:
        a = self.cfg.get("active") or {}
        c = (a.get("swing") or {}).get(which) or {}
        return c if a.get("enabled") and c.get("enabled") else None

    def _swing_why(self, ticker: str, strategy: str) -> str | None:
        e = next((x for x in active.open_trades(self.s.intents()) if x["ticker"] == ticker), None)
        q = self._quote(ticker)
        if not e:
            return None
        if strategy == swing.GAP:
            close = self._session_close(ticker)
            late = close is not None and self.clock() >= close - self.cfg["active"]["swing"]["gap"]["flat_before_close_s"]
            overnight = feeds_ts(e.get("t", 0))[:10] != feeds_ts(self.clock())[:10]
            return "flat_by_close" if late or overnight else None
        sc = self.cfg["active"]["swing"]["squeeze"]
        b = self.bars.get(ticker)
        if not b or not q:
            return None
        done = swing.completed(b, self.clock())
        return "trailing" if done["l"] and swing.squeeze_trailing(done, e.get("t", 0), e["signal"]["entry_px"],
                                                                  q["price"], sc) else None

    def _swing_entries(self, recs, day, total, cash, fx, vwrp_px, disabled, notes) -> list[tuple]:
        """vol_squeeze and gap_go entries, sized like every C6 entry; no name held by any strategy is doubled."""
        a = self.cfg["active"]
        now = self.clock()
        li = execution.latest_intents(recs).values()
        busy = {e["ticker"] for e in active.open_trades(recs)} | set(self.positions) | {
            r["ticker"] for r in li if (r.get("signal") or {}).get("type") == "active_entry" and r.get("ts", "").startswith(day)}
        size = a["entry_weight"] * total
        reserve = 1 + self.cfg["core"].get("buy_reserve", 0)
        out = []

        def order(tk, q, name, rule, stop_px, extra, tp, days):
            qty = merger.math_floor(size / (q["price"] / fx), a["qty_decimals"])
            if qty <= 0:
                return
            out.append((tk, qty, qty * q["price"] / fx, q["price"], True, f"active entry: {name} ({rule})",
                        {"type": "active_entry", "strategy": name, "rule": rule, "entry_px": q["price"],
                         "stop": round(1 - stop_px / q["price"], 4), "take_profit": tp,
                         "time_stop_s": days * 86400, "quote": q, "vwrp_px": vwrp_px, **extra}))
        sq = self._swing("squeeze")
        if sq and swing.SQUEEZE not in disabled and fx:
            for tk, r in sorted(self.squeezes.items(), key=lambda kv: kv[1].get("pct", 1)):
                q = self._quote(tk)
                if not r.get("signal") or tk in busy or not q or now - r["t"] > self.cfg["active"]["review"]["max_age_s"]:
                    continue
                if not self.market_open(tk) or r["day"] >= day:
                    continue  # bought in the session after the trigger close
                if q["price"] > r["close"] * (1 + sq["max_chase"]):
                    notes.append(f"{swing.SQUEEZE}: {tk} already {q['price'] / r['close'] - 1:+.1%} above the trigger close")
                    continue
                if cash < size * reserve:
                    notes.append(f"{swing.SQUEEZE}: {tk} qualifies but cash £{cash:.2f} < £{size * reserve:.2f}")
                    break
                stop_px = max(r["low20"], q["price"] * (1 - sq["stop_loss"]))
                order(tk, q, swing.SQUEEZE, sq["rule"], stop_px, {"squeeze": {k: r[k] for k in ("day", "pct", "close", "low20", "vol_x")}},
                      sq["take_profit"], sq["time_stop_days"])
                busy.add(tk)
        gc = self._swing("gap")
        if gc and swing.GAP not in disabled and fx:
            n = sum(1 for r in li if (r.get("signal") or {}).get("strategy") == swing.GAP and r.get("ts", "").startswith(day))
            for tk, g in sorted(self.gaps.items(), key=lambda kv: -kv[1]["held"]):
                q = self._quote(tk)
                if n >= gc["max_per_day"] or tk in busy or not q:
                    continue
                if q["price"] <= g["low30"]:
                    continue
                if cash < size * reserve:
                    notes.append(f"{swing.GAP}: {tk} qualifies but cash £{cash:.2f} < £{size * reserve:.2f}")
                    break
                order(tk, q, swing.GAP, gc["rule"], g["low30"], {"gap": {k: g[k] for k in ("gap", "held", "open", "vwap30", "low30")}},
                      gc["take_profit"], 1)
                busy.add(tk)
                n += 1
        return out

    def refresh_value_timing(self) -> None:
        """Month-end timing (value_timing Q48a, momentum_timing Q50a): after each US month end, record next month's
        target ETF in state/<name>.json. The last target stands until a new month end is read."""
        now = self.clock()
        for vc in self._vt():
            state = self.s.read(f"{vc['name']}.json") or {}
            if vc.get("months"):  # a calendar entry (january_small): no prices needed
                sig = value_timing.calendar_signal(now, vc)
                if sig["month"] == state.get("month"):
                    continue
            else:
                if "factor_12m" in state and state.get("month", "") >= value_timing.last_done_month(now):
                    continue  # this month's signal is already read: no price calls until the next month end
                f = value_timing.month_ends(value_timing.adjusted(vc["factor_symbol"], self.get), now)
                b = value_timing.month_ends(value_timing.adjusted(vc["versus_symbol"], self.get), now)
                sig = value_timing.signal(f, b, vc)
                if not sig or (sig["month"] == state.get("month") and "factor_12m" in state):
                    continue
            self.s._replace(f"{vc['name']}.json", {**sig, "ts": feeds_ts(now), "previous": state.get("target")})
            self.s.event("timing_signal", strategy=vc["name"], **sig, previous=state.get("target"))
            self.need_decide = True

    def _vt(self) -> list[dict]:
        """The enabled month-end timing strategies, each with its name."""
        a = self.cfg.get("active") or {}
        if not a.get("enabled"):
            return []
        return [{**v, "name": k} for k, v in (a.get("timing") or {}).items() if v.get("enabled")]

    def _screen(self) -> dict | None:
        a = self.cfg.get("active") or {}
        sc = a.get("stock_screen") or {}
        return ({**sc, "name": stock_screen.NAME, "_state": self.s.read("stock_screen.json") or {}}
                if a.get("enabled") and sc.get("enabled") else None)

    def _buyback(self) -> dict | None:
        a = self.cfg.get("active") or {}
        bc = a.get("buyback_value") or {}
        return ({**bc, "name": buyback_value.NAME, "fund_type": "buyback_fund"}
                if a.get("enabled") and bc.get("enabled") else None)

    def _buyback_picks(self) -> dict | None:
        bc = self._buyback()
        return buyback_value.load_picks(bc["picks_dir"], self.clock(), bc["max_picks_age_days"]) if bc else None

    def _us_tradeable(self, sym: str) -> str | None:
        t = f"{sym}_US_EQ"
        return t if t in self.schedule_of else None

    def _gap_rebound(self) -> dict | None:
        a = self.cfg.get("active") or {}
        gc = a.get("gap_rebound") or {}
        return {**gc, "name": gap_rebound.NAME} if a.get("enabled") and gc.get("enabled") else None

    def refresh_gap_rebound(self) -> float | None:
        """gap_rebound (Q205): for each recent earnings day whose day +1 close is in, measure every listed US stock's
        move vs SPY over days -1..+1; for a liquid >= 10% drop, read its SEC filings (made before day 0) for the health
        gate. Signals go to state/gap_rebound.json and the research thread's forward log; buys happen in decide()."""
        gc = self._gap_rebound()
        now = self.clock()
        nyd = gap_rebound.ny_now(now)
        # agent-1.21: scans run at weekends too; the bars are final and Tiingo's request budget is idle then
        st = {"done": {}, "signals": {}, "queue": {}, **(self.s.read("gap_rebound.json") or {})}
        spy = gap_rebound.bars("SPY", self.get)
        days = [d for d, _, _ in spy]
        today = nyd.date().isoformat()
        complete = [d for d in days if d < today or (d == today and nyd.hour >= 17)]
        for i in range(max(0, len(complete) - 4), len(complete) - 1):
            d0, dp1 = complete[i], complete[i + 1]
            buy = gap_rebound.exit_day(dp1, 1)
            if buy < today or d0 in st["done"]:
                continue
            if d0 not in st["queue"]:  # agent-1.21: results 8-Ks from SEC (Nasdaq's calendar refuses honest clients)
                rows = self._efts_8k(complete, d0, earnings=True)
                st["queue"][d0] = self._liquid_enough(sorted({r["symbol"] for r in rows if r["symbol"].isalpha()
                                                              and f"{r['symbol']}_US_EQ" in self.schedule_of}),
                                                      gc["min_dollar_vol"])
        n = 0
        self._vix_bars = None
        for d0 in sorted(st["queue"]):
            todo = st["queue"][d0]
            while todo and n < gc["per_run"]:
                sym = todo.pop(0)
                n += 1
                self.s.renew_lease()
                self.sleep(gc["pacing_s"])
                try:
                    if gc.get("min_mcap") and not self._liquid_enough([sym], 0, gc["min_mcap"], gap_rebound.NAME):
                        continue  # below the tested cap floor, or cap UNVERIFIED (agent-1.21.2)
                    m = gap_rebound.event_move(gap_rebound.bars(sym, self.get), spy, d0)
                except (datasrc.BudgetError, feeds.FeedError) as e:
                    if not isinstance(e, datasrc.BudgetError) and "retried" not in str(e):
                        self.s.event("gap_rebound_skip", strategy=gap_rebound.NAME, symbol=sym, error=str(e)[:200])
                        continue
                    todo.insert(0, sym)  # Tiingo's hourly budget: the name waits for the next run
                    n = gc["per_run"]
                    break
                except Exception as e:  # noqa: BLE001 - no bars confirm nothing; the name is skipped and logged
                    self.s.event("gap_rebound_skip", strategy=gap_rebound.NAME, symbol=sym, error=str(e)[:200])
                    continue
                if not m or m["ear"] > gc["ear_max"] or m["median_dollar_vol"] < gc["min_dollar_vol"]:
                    continue
                self._gap_rebound_signal(sym, m, gc, st)
            if not todo:
                st["queue"].pop(d0)
                st["done"][d0] = feeds_ts(self.clock())
        untagged = [v for v in st["signals"].values() if "variant" not in v]
        if untagged:  # signals recorded before agent-1.17 get their Q218b VIX tag too
            if getattr(self, "_vix_bars", None) is None:
                try:
                    self._vix_bars = gap_rebound.bars("^VIX", self.get)
                except Exception:  # noqa: BLE001 - tagged vix_unknown
                    self._vix_bars = []
            for v in untagged:
                v["vix"], v["variant"] = gap_rebound.vix_tag(self._vix_bars, v["day0"], gc.get("vix_hi", 25.0))
        st["done"] = dict(sorted(st["done"].items())[-30:])
        keep_from = complete[max(0, len(complete) - 40)] if complete else today
        st["signals"] = {k: v for k, v in st["signals"].items() if v["day0"] >= keep_from}  # the last ~40 sessions
        st["checked"] = feeds_ts(self.clock())
        self.s._replace("gap_rebound.json", st)
        if any(s.get("eligible") and s["buy_day"] == today for s in st["signals"].values()):
            self.need_decide = True
        return gc["resume_s"] if st["queue"] else None

    def refresh_slippage(self) -> None:
        """Q224: fill vs the backtest's reference price (open or close of the fill session) for every filled strategy
        order whose session bar is final; at most `per_run` names per run."""
        sc = self.cfg["slippage"]
        now = self.clock()
        nyd = gap_rebound.ny_now(now)
        today = nyd.date().isoformat()
        st = {"rows": {}, "skip": {}, **(self.s.read("slippage.json") or {})}
        cache: dict[str, dict] = {}
        n = 0
        for rec in execution.latest_intents(self.s.intents()).values():
            sig = rec.get("signal") or {}
            if rec.get("status") != "filled" or not sig.get("strategy") or rec["id"] in st["rows"]:
                continue
            t = rec.get("t") or 0
            day = gap_rebound.ny_now(t).date().isoformat()
            if day > today or (day == today and nyd.hour < 17) or st["skip"].get(rec["id"], 0) >= 3:
                continue
            kind = (sc.get("ref_kind") or {}).get(sig["strategy"], sc.get("default_kind", "close"))
            sym = feeds.yahoo_symbol(rec["ticker"], self.cfg.get("yahoo_overrides") or {})
            if not sym:
                continue
            if sym not in cache:
                if n >= sc["per_run"]:
                    break
                n += 1
                self.s.renew_lease()
                self.sleep(0.25)
                try:
                    cache[sym] = slippage.day_bars(sym, self.get, "3mo")
                except Exception:  # noqa: BLE001 - retried next run, at most three times
                    cache[sym] = {}
            r = slippage.row(rec, kind, cache[sym], day)
            if r:
                st["rows"][rec["id"]] = r
            else:
                st["skip"][rec["id"]] = st["skip"].get(rec["id"], 0) + 1
        st["checked"] = feeds_ts(now)
        self.s._replace("slippage.json", st)

    def _news_shock(self) -> dict | None:
        a = self.cfg.get("active") or {}
        nc = a.get("news_shock") or {}
        return {**nc, "name": news_shock.NAME} if a.get("enabled") and nc.get("enabled") else None

    def refresh_news_shock(self) -> float | None:
        """news_shock_vix_hi (Q222): for each session d0 whose VIX close was >= vix_min and whose d0+1 close is in, list
        the non-earnings 8-Ks (SEC full-text search) filed for d0 and measure each T212-listed name's 2-day move vs
        SPY. A liquid -8% shock is a signal bought near the close of d0+2. State: state/news_shock.json."""
        nc = self._news_shock()
        now = self.clock()
        nyd = gap_rebound.ny_now(now)
        # agent-1.21: scans run at weekends too; the bars are final and Tiingo's request budget is idle then
        st = {"done": {}, "signals": {}, "queue": {}, **(self.s.read("news_shock.json") or {})}
        for tk, sig in st["signals"].items():  # agent-1.21.2: signals logged before the cap floor get checked once
            if "cap_ok" not in sig and nc.get("min_mcap"):
                try:
                    sig["cap_ok"] = bool(self._liquid_enough([tk[:-len("_US_EQ")]], 0, nc["min_mcap"], news_shock.NAME))
                except feeds.FeedError:
                    continue  # no price or share data yet: checked again next run
                if not sig["cap_ok"] and sig.get("eligible"):
                    sig["eligible"], sig["why"] = False, "below the tested market-cap floor or cap UNVERIFIED"
        spy = gap_rebound.bars("SPY", self.get)
        vix = {d: c for d, c, _ in gap_rebound.bars("^VIX", self.get)}
        days = [d for d, _, _ in spy]
        today = nyd.date().isoformat()
        complete = [d for d in days if d < today or (d == today and nyd.hour >= 17)]
        if self.sec_get is None:
            ua = feeds.sec_user_agent(self.s.root)
            if ua:
                self.sec_get = feeds.sec_get(ua, max_bytes=5_000_000)
        for i in range(max(1, len(complete) - 3), len(complete) - 1):
            d0, dp1 = complete[i], complete[i + 1]
            if gap_rebound.exit_day(dp1, 1) < today or d0 in st["done"] or d0 in st["queue"]:
                continue
            if d0 not in vix:
                continue  # UNVERIFIED: no VIX close for d0 yet; retried next run
            if vix[d0] < nc["vix_min"]:
                st["done"][d0] = f"VIX {vix[d0]:.2f} < {nc['vix_min']}: no scan"
                continue
            try:
                rows = self._efts_8k(complete, d0, earnings=False)
            except feeds.FeedError:
                continue
            items: dict[str, list] = {}
            for x in rows:
                if f"{x['symbol']}_US_EQ" in self.schedule_of:
                    items[x["symbol"]] = sorted(set(items.get(x["symbol"], [])) | set(x["items"]))
            st["queue"][d0] = {"vix": round(vix[d0], 2), "items": items,
                               "todo": self._liquid_enough(sorted(items), nc["min_dollar_vol"])}
        n = 0
        for d0 in sorted(st["queue"]):
            q = st["queue"][d0]
            buy = gap_rebound.exit_day(complete[complete.index(d0) + 1], 1) if d0 in complete[:-1] else None
            while q["todo"] and n < nc["per_run"]:
                sym = q["todo"].pop(0)
                n += 1
                self.s.renew_lease()
                self.sleep(nc["pacing_s"])
                try:
                    if nc.get("min_mcap") and not self._liquid_enough([sym], 0, nc["min_mcap"], news_shock.NAME):
                        continue  # below the tested cap floor, or cap UNVERIFIED (agent-1.21.2)
                    m = news_shock.move(gap_rebound.bars(sym, self.get), spy, d0)
                except (datasrc.BudgetError, feeds.FeedError) as e:
                    if not isinstance(e, datasrc.BudgetError) and "retried" not in str(e):
                        self.s.event("news_shock_skip", strategy=news_shock.NAME, symbol=sym, error=str(e)[:200])
                        continue
                    q["todo"].insert(0, sym)  # Tiingo's hourly budget: the name waits for the next run
                    n = nc["per_run"]
                    break
                except Exception as e:  # noqa: BLE001 - no bars confirm nothing; the name is skipped and logged
                    self.s.event("news_shock_skip", strategy=news_shock.NAME, symbol=sym, error=str(e)[:200])
                    continue
                if not m or m["ear"] > nc["ear_max"] or m["median_dollar_vol"] < nc["min_dollar_vol"]:
                    continue
                tk = f"{sym}_US_EQ"
                rep = news_shock.recent(st["signals"], sym, d0, days, nc["no_repeat_days"])
                sig = {**m, "symbol": sym, "items": q["items"].get(sym, []), "vix": q["vix"], "buy_day": buy, "cap_ok": True,
                       "eligible": bool(buy) and not rep, "why": "repeat within 10 sessions" if rep else "signal"}
                if not rep:  # a repeat is logged only; the earlier signal for the name stays
                    st["signals"][tk] = sig
                self.s.event("news_shock_signal", strategy=news_shock.NAME, ticker=tk, **sig)
            if not q["todo"]:
                st["queue"].pop(d0)
                st["done"][d0] = feeds_ts(self.clock())
        st["done"] = dict(sorted(st["done"].items())[-30:])
        keep_from = complete[max(0, len(complete) - 30)] if complete else today
        st["signals"] = {k: v for k, v in st["signals"].items() if v["day0"] >= keep_from}
        st["checked"] = feeds_ts(self.clock())
        self.s._replace("news_shock.json", st)
        if any(s.get("eligible") and s["buy_day"] == today for s in st["signals"].values()):
            self.need_decide = True
        return nc["resume_s"] if st["queue"] else None

    def _gap_rebound_signal(self, sym: str, m: dict, gc: dict, st: dict) -> None:
        """Health gate (SEC companyfacts, filed before day 0) for one liquid >= 10% earnings drop, then record it."""
        if self.sec_get is None:
            ua = feeds.sec_user_agent(self.s.root)
            if ua:
                self.sec_get = feeds.sec_get(ua, max_bytes=5_000_000)
        h = {"weak": None, "why": "UNVERIFIED: no SEC contact User-Agent configured"}
        if self.sec_get is not None:
            try:
                if not getattr(self, "sec_ciks", None):
                    raw = self.sec_get(gap_rebound.TICKERS, {})
                    raw = json.loads(raw) if isinstance(raw, str) else raw
                    self.sec_ciks = {v["ticker"]: int(v["cik_str"]) for v in raw.values()}
                cik = self.sec_ciks.get(sym)
                if cik is None:
                    h = {"weak": None, "why": "UNVERIFIED: ticker not in SEC company_tickers"}
                else:
                    self.sleep(0.3)
                    h = gap_rebound.health(self.sec_get(gap_rebound.FACTS.format(cik=cik), {}), m["day0"])
            except Exception as e:  # noqa: BLE001 - an unreadable filing confirms nothing: no trade
                h = {"weak": None, "why": f"UNVERIFIED: SEC read failed ({str(e)[:120]})"}
        if getattr(self, "_vix_bars", None) is None:
            try:  # Q218b: tag each signal with the VIX close; the trade itself does not depend on it
                self._vix_bars = gap_rebound.bars("^VIX", self.get)
            except Exception as e:  # noqa: BLE001 - no VIX: the signal is tagged vix_unknown and trades as before
                self._vix_bars = []
                self.s.event("gap_rebound_skip", strategy=gap_rebound.NAME, symbol="^VIX", error=str(e)[:200])
        vix, variant = gap_rebound.vix_tag(self._vix_bars, m["day0"], gc.get("vix_hi", 25.0))
        tk = f"{sym}_US_EQ"
        sig = {**m, "symbol": sym, "ticker": tk, "health": h, "eligible": h.get("weak") is True,
               "vix": vix, "variant": variant,
               "buy_day": gap_rebound.exit_day(m["day_p1"], 1), "ts": feeds_ts(self.clock())}
        st["signals"][tk] = sig
        self.s.event("gap_rebound_signal", strategy=gap_rebound.NAME, **sig)
        path = Path(gc["forward_csv"])
        try:
            new = not path.exists()
            with path.open("a") as f:
                if new:
                    f.write("logged_utc,symbol,day0,ear,ret,spy_ret,median_dollar_vol,fcf_ttm,rev_ttm,rev_ttm_prev,"
                            "weak,eligible,buy_day,note\n")
                f.write(",".join(str(x) for x in (
                    sig["ts"], sym, m["day0"], m["ear"], m["ret"], m["spy_ret"], m["median_dollar_vol"], h.get("fcf"),
                    h.get("rev"), h.get("rev_prev"), h.get("weak"), sig["eligible"], sig["buy_day"],
                    '"' + h.get("why", "").replace('"', "'") + '"')) + "\n")
        except OSError as e:
            self.s.event("duty_failed", duty="gap_rebound", error=f"forward log: {e}"[:200])

    def refresh_screen_watch(self) -> None:
        """stock_screen continuous watch: each held name's SEC filings (8-K items, delisting, merger and tender
        forms, new 10-Q/10-K), a 25% fall from entry, and a missing quote while its market is open (a possible halt).
        A hard SEC event marks the name for exit (replaced at the next monthly refresh); the rest are stock_screen_alert
        events for the daily brief."""
        sc = self._screen()
        xc = self._exit_cfg() or {}
        watch = {stock_screen.NAME, *xc.get("hard_events_for", [])}  # agent-1.19: buyback and gap names too
        held = {e["ticker"]: {"cik": (sc.get("ciks") or {}).get(e["ticker"]), "since": feeds_ts(e.get("t", 0))[:10],
                              "entry_px": e["signal"].get("entry_px"), "strategy": e["signal"].get("strategy")}
                for e in active.open_trades(self.s.intents()) if e["signal"].get("strategy") in watch}
        for tk, h in held.items():
            if not h["cik"] and h["strategy"] != stock_screen.NAME:
                try:
                    h["cik"] = self._sec_cik(tk)
                except Exception as e:  # noqa: BLE001 - no CIK means no filing check this pass, logged below
                    self.s.event("duty_failed", duty="screen_watch", ticker=tk, error=f"cik: {e}"[:200])
        if not held:
            return
        state = sc["_state"]
        if self.sec_get is None:
            ua = feeds.sec_user_agent(self.s.root)
            if ua:
                self.sec_get = feeds.sec_get(ua)
        subs = {}
        for tk, h in held.items():
            if not h["cik"] or self.sec_get is None:
                continue
            self.s.renew_lease()
            self.sleep(0.3)  # well under the SEC's 10 requests a second
            try:
                subs[tk] = self.sec_get(stock_screen.SUBMISSIONS.format(cik=int(h["cik"])), {})
            except Exception as e:  # noqa: BLE001 - an unreadable reply confirms nothing; the next run retries
                self.s.event("duty_failed", duty="screen_watch", ticker=tk, error=str(e)[:200])
        state, found = stock_screen.watch_filings({k: v for k, v in held.items() if k in subs}, subs, state)
        state, drops = stock_screen.price_alerts(held, self._quote, state, sc.get("alert_drop", 0.25))
        day = feeds_ts(self.clock())[:10]
        halts = dict(state.get("halt_alerted") or {})
        for tk in held:
            if self.market_open(tk) and not self._quote(tk) and halts.get(tk) != day:
                halts[tk] = day
                drops.append({"ticker": tk, "kind": "alert",
                              "why": f"no valid quote while its market is open ({self.quote_state.get(feeds.yahoo_symbol(tk, self.cfg['yahoo_overrides']))}): possible halt"})
        state = {**state, "halt_alerted": halts, "checked": feeds_ts(self.clock()),
                 "missing_cik": sorted(k for k, v in held.items() if not v["cik"])}
        self.s._replace("stock_screen.json", state)
        for r in found + drops:
            strat = held.get(r["ticker"], {}).get("strategy") or stock_screen.NAME
            self.s.event("stock_screen_alert", strategy=strat, check=r["kind"],
                         **{k: v for k, v in r.items() if k != "kind"})
            if r["kind"] != "exit":
                continue  # alert-only checks stay in the event log; nothing is pushed to the owner (4 Nov 2026)
            self.alert("critical", f"stock_screen:{r['ticker']}:{r.get('adsh') or r['why'][:20]}",
                       f"{strat} {r['ticker']}: {'EXIT ' if r['kind'] == 'exit' else ''}{r['why']}"
                       + (f" ({r['form']} {r['date']})" if r.get("form") else ""))
        if any(r["kind"] == "exit" for r in found):
            self.need_decide = True

    def _merger(self) -> dict | None:
        a = self.cfg.get("active") or {}
        mc = a.get("merger") or {}
        return mc if a.get("enabled") and mc.get("enabled") else None

    def _social(self) -> dict | None:
        a = self.cfg.get("active") or {}
        sc = a.get("social") or {}
        return sc if a.get("enabled") and sc.get("enabled") else None

    def _gate(self, strategy: str, ticker: str):
        rev = self.reviews.get(ticker)
        ok, why = review.entry_ok(strategy, rev, self.cfg["active"]["review"], self.clock())
        return ok, why, rev

    def _review_why(self, ticker: str, strategy: str | None = None) -> str | None:
        why = self._exit_rules_why(ticker, strategy)
        if why:
            return why
        return self._strategy_why(ticker, strategy)

    def _strategy_why(self, ticker: str, strategy: str | None = None) -> str | None:
        if strategy in (swing.SQUEEZE, swing.GAP):  # C9 trades follow their own exits, not the price review
            return self._swing_why(ticker, strategy)
        if strategy in value_timing.NAMES:  # held until the month-end signal names the other ETF, or the kill rule
            if strategy in (self.s.read("strategies.json") or {}):
                return "killed"
            return value_timing.exit_why(self.s.read(f"{strategy}.json"), ticker)
        if strategy == stock_screen.NAME:  # held until a monthly refresh drops the name, or the kill rule
            if strategy in (self.s.read("strategies.json") or {}):
                return "killed"
            return stock_screen.exit_why(self._screen() or self.cfg["active"].get("stock_screen"), ticker,
                                         self.s.read("stock_screen.json"))
        if strategy == buyback_value.NAME:  # held 6 months (its time stop), or until the kill rule
            return "killed" if strategy in (self.s.read("strategies.json") or {}) else None
        if strategy == news_shock.NAME:  # held 5 trading days (its time stop), or until the kill rule
            return "killed" if strategy in (self.s.read("strategies.json") or {}) else None
        if strategy == gap_rebound.NAME:  # held 60 trading days (its time stop), or until the kill rule
            return "killed" if strategy in (self.s.read("strategies.json") or {}) else None
        if strategy == merger.NAME:  # a deal trade exits on a termination, its stop or the cash-out, not on price
            return "deal_terminated" if ticker in self.mstate.get("terminated", {}) else None
        if strategy == social.NAME:  # C8 trades exit on their own attention rule, not the price review
            sc = self._social() or self.cfg["active"].get("social")
            return social.exit_why(self.s.read("social.json"), ticker, sc) if sc else None
        rc = self.cfg["active"]["review"]
        rev = self.reviews.get(ticker)
        if not rev or self.clock() - rev["t"] > rc["max_age_s"] or rev["scores"]["composite"] is None:
            return None
        return "review" if rev["scores"]["composite"] <= rc["exit_max"] else None

    # ------------------------------------------------------------ exit review (agent-1.19)
    def _exit_cfg(self) -> dict | None:
        a = self.cfg.get("active") or {}
        c = a.get("exit_review") or {}
        return c if a.get("enabled") and c.get("enabled") else None

    def _earnings_sec(self, names: list[str], block_days: int, now: float) -> None:
        """agent-1.21: next results dates from each US name's SEC filings (review.earnings_due), once a New York day per
        name. A failed check marks the name UNVERIFIED, which blocks its entries."""
        today = gap_rebound.ny_now(now).date().isoformat()
        for t in names:
            sym = feeds.yahoo_symbol(t, self.cfg["yahoo_overrides"])
            if not sym or not t.endswith("_US_EQ") or self.earn_day.get(t) == today:
                continue
            try:
                cik = self._sec_cik(t)
                if not cik:
                    raise ValueError("no SEC CIK")
                self.s.renew_lease()
                self.sleep(0.2)
                sub = self.sec_get(stock_screen.SUBMISSIONS.format(cik=cik), {})
                sub = json.loads(sub) if isinstance(sub, str) else sub
                due = review.earnings_due(stock_screen.recent_filings(sub), today, block_days)
                self.earn[sym] = due  # None: no results date near
                self.earn_day[t] = today
            except Exception as e:  # noqa: BLE001 - unknown results date blocks the name's entries
                self.earn[sym] = f"UNVERIFIED (SEC check failed: {str(e)[:80]})"
        self.earn_t = now

    def _efts_8k(self, complete: list[str], d0: str, earnings: bool) -> list[dict]:
        """8-Ks filed for session d0 (SEC full-text search, paged): results releases (item 2.02) when `earnings`,
        else the non-earnings ones. Raises when SEC is unreachable, so the day is retried."""
        if self.sec_get is None:
            ua = feeds.sec_user_agent(self.s.root)
            if ua:
                self.sec_get = feeds.sec_get(ua, max_bytes=5_000_000)
        if self.sec_get is None:
            raise feeds.FeedError("SEC: no contact User-Agent")
        w = news_shock.window(complete, d0)
        rows, frm = [], 0
        while w:
            self.s.renew_lease()
            self.sleep(0.3)
            r = self.sec_get(news_shock.EFTS, {"forms": "8-K", "dateRange": "custom", "startdt": w[0], "enddt": w[1],
                                               "from": frm})
            hits = (r.get("hits") or {}).get("hits") or []
            rows += news_shock.filings(hits, earnings=earnings)
            frm += len(hits)
            if not hits or frm >= ((r.get("hits") or {}).get("total") or {}).get("value", 0) or frm >= 5000:
                break
        return rows

    def _liquid_enough(self, syms: list[str], min_dollar_vol: float, min_mcap: float = 0, label: str = "") -> list[str]:
        """agent-1.21 pre-filter before per-name bars are fetched (one Tiingo snapshot call). Drops names whose latest
        session traded under a third of the liquidity floor, and (agent-1.21.2, research 7 Nov) names below the
        tested market-cap floor: Q203/Q218b/Q222 were run on large US names only, so a name whose cap cannot be
        measured (SEC cover-page shares x latest price) is UNVERIFIED and skipped too."""
        try:
            snap = self.data.snapshot() if self.data is not None else None
        except feeds.FeedError:
            snap = None
        if min_mcap and not snap:
            raise feeds.FeedError("no price snapshot for the market-cap check (retried)")
        keep, small = [], []
        for s in syms:
            r = (snap or {}).get(s.upper())
            px, vol = r and (r.get("tngoLast") or r.get("prevClose")), r and r.get("volume")
            if r and px is not None and vol is not None and px * vol < min_dollar_vol / 3:
                continue
            if min_mcap:
                cap = self._mcap(s, px)
                if cap is None or cap < min_mcap:
                    small.append((s, None if cap is None else round(cap / 1e9, 2)))
                    continue
            keep.append(s)
        if small:
            self.s.event("cap_filter", strategy=label, min_mcap=min_mcap, dropped=small[:200], n=len(small))
        return keep

    def _mcap(self, sym: str, px: float | None) -> float | None:
        """Market cap from SEC cover-page shares (dei frames, latest of the last four quarters) x `px`; None if unknown."""
        if px is None:
            return None
        today = gap_rebound.ny_now(self.clock()).date()
        if getattr(self, "_shares_day", None) != today.isoformat():
            shares: dict[int, float] = {}
            y, q = today.year, (today.month - 1) // 3 + 1
            periods = []
            for _ in range(4):
                periods.append(f"CY{y}Q{q}I")
                y, q = (y, q - 1) if q > 1 else (y - 1, 4)
            got = 0
            for per in reversed(periods):  # oldest first, so later cover pages win
                try:
                    self.s.renew_lease()
                    d = self.sec_get(FRAMES.format(p=per), {})
                    d = json.loads(d) if isinstance(d, str) else d
                    shares.update({int(r["cik"]): float(r["val"]) for r in d.get("data") or [] if r.get("val")})
                    got += 1
                except Exception:  # noqa: BLE001 - a missing quarter leaves older counts in place
                    continue
            if not got:
                raise feeds.FeedError("SEC share counts unavailable for the market-cap check (retried)")
            self._shares, self._shares_day = shares, today.isoformat()
        cik = self._sec_cik(f"{sym}_US_EQ")
        n = self._shares.get(cik) if cik else None
        return n * px if n else None

    def _sec_cik(self, t212: str) -> int | None:
        """CIK for a US T212 ticker from SEC company_tickers.json (fetched once per process); None if unknown."""
        sym = feeds.yahoo_symbol(t212, self.cfg.get("yahoo_overrides") or {})
        if not sym:
            return None
        if self.sec_get is None:
            ua = feeds.sec_user_agent(self.s.root)
            if ua:
                self.sec_get = feeds.sec_get(ua, max_bytes=5_000_000)
        if self.sec_get is None:
            return None
        if not getattr(self, "sec_ciks", None):
            raw = self.sec_get(gap_rebound.TICKERS, {})
            raw = json.loads(raw) if isinstance(raw, str) else raw
            self.sec_ciks = {v["ticker"]: int(v["cik_str"]) for v in raw.values()}
        return self.sec_ciks.get(sym) or self.sec_ciks.get(sym.replace("-", "."))

    def _exit_rules_why(self, ticker: str, strategy: str | None) -> str | None:
        """agent-1.19 sell rules beside each strategy's own: a hard SEC event, a broken buyback thesis, a profit lock."""
        xc = self._exit_cfg()
        if not xc or not strategy:
            return None
        if strategy in xc.get("hard_events_for", []):
            hard = ((self.s.read("stock_screen.json") or {}).get("exit") or {}).get(ticker)
            if hard:
                return hard["why"]
        st = self.s.read("exit_review.json") or {}
        th = xc.get("thesis") or {}
        if th.get("enabled") and strategy in th.get("strategies", []) and ((st.get("thesis") or {}).get(ticker) or {}).get("broken"):
            return "thesis_broken"
        pl = xc.get("profit_lock") or {}
        pk = (st.get("peak") or {}).get(ticker)
        q = self._quote(ticker)
        if pl.get("enabled") and strategy in pl.get("strategies", []) and pk and q and pk.get("entry_px"):
            if exits.profit_lock(q["price"] / pk["entry_px"] - 1, pk["peak"], pl["arm"], pl["keep"]):
                return "profit_lock"
        return None

    def refresh_exit_review(self) -> None:
        """A recorded hold-or-sell decision for every open trade: peak return, the buyback thesis (SEC share count,
        once a day per name), and an exit_review event per trade once a day or when its verdict changes."""
        xc = self._exit_cfg()
        now = self.clock()
        day = feeds_ts(now)[:10]
        st = self.s.read("exit_review.json") or {}
        peaks, thesis, last = dict(st.get("peak") or {}), dict(st.get("thesis") or {}), dict(st.get("last") or {})
        opens = active.open_trades(self.s.intents())
        th = xc.get("thesis") or {}
        stops = {v.get("ticker"): v.get("stop_px") for v in (self.s.read("stops.json") or {}).values()
                 if isinstance(v, dict) and v.get("order_id") and not v.get("cancelled") and not v.get("filled")}
        for e in opens:
            tk, sig = e["ticker"], e["signal"]
            q = self._quote(tk)
            if q and sig.get("entry_px"):
                ret = q["price"] / sig["entry_px"] - 1
                pk = peaks.get(tk)
                if not pk or pk.get("entry_id") != e["id"]:
                    pk = {"entry_id": e["id"], "entry_px": sig["entry_px"], "peak": ret}
                peaks[tk] = {**pk, "peak": max(pk["peak"], ret)}
            if th.get("enabled") and sig.get("strategy") in th.get("strategies", []) and (thesis.get(tk) or {}).get("day") != day:
                try:
                    cik = self._sec_cik(tk)
                    if cik is None:
                        r = {"broken": None, "why": "UNVERIFIED: no CIK"}
                    else:
                        self.s.renew_lease()
                        self.sleep(0.3)
                        r = exits.shares_thesis(self.sec_get(gap_rebound.FACTS.format(cik=cik), {}),
                                                feeds_ts(e.get("t", now))[:10])
                except Exception as ex:  # noqa: BLE001 - an unreadable filing confirms nothing: hold
                    r = {"broken": None, "why": f"UNVERIFIED: SEC read failed ({str(ex)[:120]})"}
                thesis[tk] = {**r, "day": day}
        open_tk = {e["ticker"] for e in opens}
        peaks = {k: v for k, v in peaks.items() if k in open_tk}
        thesis = {k: v for k, v in thesis.items() if k in open_tk}
        self.s._replace("exit_review.json", {**st, "peak": peaks, "thesis": thesis, "last": last})
        rules = xc.get("hold_rules") or {}
        pl = xc.get("profit_lock") or {}
        rows, sell = [], False
        for e in opens:
            tk, strat = e["ticker"], e["signal"].get("strategy")
            q = self._quote(tk)
            ret = q["price"] / e["signal"]["entry_px"] - 1 if q and e["signal"].get("entry_px") else None
            why = self._review_why(tk, strat) if q else None
            pk = (peaks.get(tk) or {}).get("peak")
            row = exits.plan(e, ret, pk, now, rules.get(strat), why,
                             (thesis.get(tk) or {}).get("why") if th.get("enabled") else None,
                             stops.get(tk), pl if pl.get("enabled") and strat in pl.get("strategies", []) else None)
            row["sells_if"] += (xc.get("sell_rules") or {}).get(strat, [])
            rows.append(row)
            sell = sell or bool(why)
            if last.get(tk, {}).get("day") != day or last.get(tk, {}).get("verdict") != row["verdict"]:
                last[tk] = {"day": day, "verdict": row["verdict"]}
                self.s.event("exit_review", **row)
        last = {k: v for k, v in last.items() if k in open_tk}
        self.s._replace("exit_review.json", {"peak": peaks, "thesis": thesis, "last": last, "plans": rows,
                                             "ts": feeds_ts(now)})
        if sell:
            self.need_decide = True

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
        ew_trims, self._ew_tops = self._ew(recs, vwrp_px, notes)
        sells = (self._exit_orders(notes) + self._active_exits(recs, vwrp_px) + self._rebalance_orders(notes)
                 + ew_trims)
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
        if order and (order[6] or {}).get("type") in ("active_trim", "active_topup"):
            self._ew_mark(order[0])
        self.s.event("decision", orders=[a for a in acted if a],
                     no_trade=not any(a and a.get("status") == "placed" for a in acted), notes=notes)

    def _ew(self, recs, vwrp_px, notes) -> tuple[list, list]:
        """Q237b bench: this month's equal-weight trims (sells) and top-ups (buys) for the stock_screen basket."""
        sc = self._screen()
        disabled = self.s.read("strategies.json") or {}
        if not sc or stock_screen.NAME in disabled or stock_screen.missing(sc, recs, self.positions, disabled):
            return [], []  # only a complete basket is re-weighted
        fxq = self.quotes.get(self.cfg["benchmark"]["fx"])
        state = self.s.read("stock_screen.json") or {}
        trims, tops, n = stock_screen.ew_orders(sc, recs, self.positions, self._quote, fxq["price"] if fxq else None,
                                                self.clock(), vwrp_px, state, self.market_open,
                                                self.s.read("precision.json") or {}, sc.get("qty_decimals", 3))
        notes += n
        ew = sc.get("ew_rebalance") or {}
        month = time.strftime("%Y-%m", time.gmtime(self.clock()))
        if ew.get("enabled") and month >= ew.get("from", "9999") and state.get("ew_month") != month \
                and not trims and not tops and not n and len(self.positions):
            self.s._replace("stock_screen.json", {**state, "ew_month": month})
            self.s.event("ew_rebalance_done", strategy=stock_screen.NAME, month=month)
        return trims, tops

    def _ew_mark(self, ticker: str) -> None:
        state = self.s.read("stock_screen.json") or {}
        month = time.strftime("%Y-%m", time.gmtime(self.clock()))
        done = dict(state.get("ew_done") or {})
        done[month] = sorted({*(done.get(month) or []), ticker})
        self.s._replace("stock_screen.json", {**state, "ew_done": done})

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
        if not a.get("enabled"):
            return []
        return (list(a.get("watchlist", [])) + sorted((self._social() or {}).get("universe", {}))
                + (list(self.mstate.get("watch", [])) if self._merger() else [])
                + [t for vc in self._vt() for t in (vc["factor_ticker"], vc.get("market_ticker")) if t]
                + stock_screen.watch(a.get("stock_screen"))
                + self._gap_rebound_watch() + self._news_shock_watch() + self._buyback_watch())

    def _buyback_watch(self) -> list[str]:
        bc = self._buyback()
        if not bc:
            return []
        recs = self.s.intents()
        w = buyback_value.wanted(bc, self._buyback_picks(), recs, self.positions, self._us_tradeable,
                                 self.s.read("strategies.json") or {})
        return sorted({x["ticker"] for x in w} | {e["ticker"] for e in active.open_trades(recs)
                                                   if e["signal"].get("strategy") == buyback_value.NAME})

    def _news_shock_watch(self) -> list[str]:
        if not self._news_shock():
            return []
        today = gap_rebound.ny_now(self.clock()).date().isoformat()
        st = self.s.read("news_shock.json") or {}
        return sorted({tk for tk, s in (st.get("signals") or {}).items()
                       if s.get("eligible") and (s.get("buy_day") or "") >= today}
                      | {e["ticker"] for e in active.open_trades(self.s.intents())
                         if e["signal"].get("strategy") == news_shock.NAME})

    def _gap_rebound_watch(self) -> list[str]:
        if not self._gap_rebound():
            return []
        today = gap_rebound.ny_now(self.clock()).date().isoformat()
        st = self.s.read("gap_rebound.json") or {}
        return sorted({tk for tk, s in (st.get("signals") or {}).items() if s.get("eligible") and s["buy_day"] >= today}
                      | {e["ticker"] for e in active.open_trades(self.s.intents())
                         if e["signal"].get("strategy") == gap_rebound.NAME})

    def _active_exits(self, recs, vwrp_px) -> list[tuple]:
        if not self._watch():
            return []
        stops = self.s.read("stops.json") or {}
        resting = {v["ticker"]: (k, v) for k, v in stops.items() if v.get("order_id")}
        # a resting sell stop holds the shares, so the trade's whole quantity counts as available to exit
        pos = {t: ({**p, "quantityAvailableForTrading": p.get("quantity")} if t in resting else p)
               for t, p in self.positions.items()}
        out = []
        rv = self._review_why if (self.cfg["active"].get("review") or {}).get("enabled") else None
        for o in active.exit_orders(recs, pos, self._quote, self.clock(), vwrp_px, rv):
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
        for n in active.stops_needed(recs, self.positions, stops, self.cfg["active"].get("disaster_stop")):
            if not self.market_open(n["ticker"]):
                continue  # placed during the market's own hours, when the broker accepts and works it
            if n.get("replace"):
                self.alert("warn", f"stop_lapsed:{n['ticker']}", f"broker stop for {n['ticker']} was cancelled while "
                           "still held: placing it again")
            retry = n["entry_id"] in stops and not n.get("replace")  # "too far" before: straight to the clamp ladder
            tries = ([] if retry else [n["stop_px"]]) + active.clamp_ladder(n["stop_px"], n.get("px") or 0)
            err, ack, px = None, None, None
            for px in tries:
                try:
                    ack = self.c.place_stop_order(n["ticker"], -n["qty"], px)
                    err = None
                    break
                except Exception as e:  # noqa: BLE001 - a refusal other than "too far" ends the ladder
                    err = e
                    if not active.too_far(e):
                        break
            if tries and err is None:
                stops[n["entry_id"]] = {"order_id": (ack or {}).get("id"), "ticker": n["ticker"], "qty": n["qty"],
                                        "stop_px": px, "ts": feeds_ts(self.clock()), "ack": ack}
                if px != n["stop_px"]:
                    stops[n["entry_id"]]["clamped_from"] = n["stop_px"]
                self.s.event("stop_placed", entry=n["entry_id"], ticker=n["ticker"], qty=n["qty"], stop_px=px,
                             rule_stop_px=n["stop_px"], order_id=stops[n["entry_id"]]["order_id"],
                             disaster=n.get("disaster", False))
                notes.append(f"broker stop placed: {n['ticker']} {n['qty']} at {px}"
                             + (f" (clamped from {n['stop_px']})" if px != n["stop_px"] else ""))
            else:  # recorded once; the agent's own stop still watches while it runs
                msg = str(err)[:300] if err else "no stop price inside the broker's band"
                stops[n["entry_id"]] = {"order_id": None, "ticker": n["ticker"], "failed": msg,
                                        "ts": feeds_ts(self.clock()), "clamp_tried": True}
                self.s.event("stop_failed", entry=n["entry_id"], ticker=n["ticker"], error=msg, tried=tries)
                self.alert("warn", f"stop_failed:{n['ticker']}", f"broker stop for {n['ticker']} refused: {msg[:150]}")
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
        for vc in self._vt():
            if vc["name"] in disabled:
                continue
            k = value_timing.kill(recs, self.positions, self.clock(), vwrp_px, vc, feeds_ts(self.clock()))
            if k:
                disabled = {**disabled, vc["name"]: k}
                self.s._replace("strategies.json", disabled)
                self.s.event("strategy_disabled", strategy=vc["name"], **k)
                self.alert("warn", f"strategy_disabled:{vc['name']}", f"strategy {vc['name']} switched off: {k['why']}")
        sc = self._screen()
        if sc and sc["name"] not in disabled:
            k = value_timing.kill(recs, self.positions, self.clock(), vwrp_px, sc, feeds_ts(self.clock()))
            if k:
                disabled = {**disabled, sc["name"]: k}
                self.s._replace("strategies.json", disabled)
                self.s.event("strategy_disabled", strategy=sc["name"], **k)
                self.alert("warn", f"strategy_disabled:{sc['name']}", f"strategy {sc['name']} switched off: {k['why']}")
        gc = self._gap_rebound()
        if gc and gc["name"] not in disabled:
            k = value_timing.kill(recs, self.positions, self.clock(), vwrp_px, gc, feeds_ts(self.clock()))
            if k:
                disabled = {**disabled, gc["name"]: k}
                self.s._replace("strategies.json", disabled)
                self.s.event("strategy_disabled", strategy=gc["name"], **k)
                self.alert("warn", f"strategy_disabled:{gc['name']}", f"strategy {gc['name']} switched off: {k['why']}")
        bc = self._buyback()
        if bc and bc["name"] not in disabled:
            k = value_timing.kill(recs, self.positions, self.clock(), vwrp_px, bc, feeds_ts(self.clock()))
            if k:
                disabled = {**disabled, bc["name"]: k}
                self.s._replace("strategies.json", disabled)
                self.s.event("strategy_disabled", strategy=bc["name"], **k)
                self.alert("warn", f"strategy_disabled:{bc['name']}", f"strategy {bc['name']} switched off: {k['why']}")
        nc = self._news_shock()
        if nc and nc["name"] not in disabled:
            k = value_timing.kill(recs, self.positions, self.clock(), vwrp_px, nc, feeds_ts(self.clock()))
            if k:
                disabled = {**disabled, nc["name"]: k}
                self.s._replace("strategies.json", disabled)
                self.s.event("strategy_disabled", strategy=nc["name"], **k)
                self.alert("warn", f"strategy_disabled:{nc['name']}", f"strategy {nc['name']} switched off: {k['why']}")
        total = float((self.summary or {}).get("totalValue") or 0)
        cash = float(((self.summary or {}).get("cash") or {}).get("availableToTrade") or 0)
        fxq = self.quotes.get(self.cfg["benchmark"]["fx"])
        if sc:  # the basket first: it is funded from VWRP, so it never competes with the sleeve for cash
            keep = self.cfg["active"].get("cash_reserve_weight", 0) * total
            for o in getattr(self, "_ew_tops", None) or []:  # Q237b top-ups, paid from this month's trims
                if cash - keep >= o[2] * (1 + self.cfg["core"].get("buy_reserve", 0)):
                    return o
                notes.append(f"stock_screen: equal-weight top-up of {o[0]} waits for cash")
                break
            need = stock_screen.need_gbp(sc, self.cfg, recs, self.positions, total, disabled)
            so, n = stock_screen.entry_orders(sc, self.cfg, recs, self.positions, self._quote,
                                              fxq["price"] if fxq else None, total, cash - keep, self.clock(),
                                              vwrp_px, disabled, self.market_open, self.s.read("precision.json") or {})
            notes += n
            if so:
                return so[0]
            fo = stock_screen.fund_order(sc, self.cfg, self.positions, self._quote, total, cash, keep, need, day, recs)
            if fo and self.market_open(fo[0]):
                return fo
        if bc:  # funded from VWRP like the screen basket, after it
            keep = self.cfg["active"].get("cash_reserve_weight", 0) * total
            keep += stock_screen.need_gbp(sc, self.cfg, recs, self.positions, total, disabled) if sc else 0.0
            picks = self._buyback_picks()
            bo, n = buyback_value.entry_orders(bc, self.cfg, recs, self.positions, self._quote,
                                               fxq["price"] if fxq else None, total, cash - keep, self.clock(),
                                               vwrp_px, disabled, picks, self._us_tradeable, self.market_open,
                                               self.s.read("precision.json") or {})
            notes += n
            if bo:
                return bo[0]
            need = buyback_value.need_gbp(bc, self.cfg, picks, recs, self.positions, self._us_tradeable, total,
                                          disabled)
            fo = stock_screen.fund_order(bc, self.cfg, self.positions, self._quote, total, cash, keep, need, day, recs)
            if fo and self.market_open(fo[0]):
                return fo
        orders, n = active.entry_orders(self.cfg, recs, self.positions, self._quote, fxq["price"] if fxq else None,
                                        total, cash, day, self.clock(), vwrp_px, disabled,
                                        self._gate if (self.cfg["active"].get("review") or {}).get("enabled") else None)
        notes += n
        if any("FROZEN" in x for x in n):
            self.alert("critical", "active_frozen", n[0])
        if self._social() and not active.sleeve_block(self.cfg, recs, self.positions, day, total):
            so, n = social.entry_orders(self.cfg, recs, self.positions, self._quote, fxq["price"] if fxq else None,
                                        total, cash, self.clock(), vwrp_px, disabled, self.s.read("social.json"),
                                        self.reviews)
            notes += n
            orders += so
        if (self._swing("squeeze") or self._swing("gap")) and not active.sleeve_block(self.cfg, recs, self.positions, day, total):
            orders += self._swing_entries(recs, day, total, cash, fxq["price"] if fxq else None, vwrp_px, disabled, notes)
        if self._merger() and not active.sleeve_block(self.cfg, recs, self.positions, day, total):
            mo, n = merger.entry_orders(self.cfg, recs, self.positions, self._quote, fxq["price"] if fxq else None,
                                        total, cash, day, self.clock(), vwrp_px, disabled, self.mstate)
            notes += n
            orders += mo
        if gc and not active.sleeve_block(self.cfg, recs, self.positions, day, total):
            go, n = gap_rebound.entry_orders(gc, self.cfg, recs, self.positions, self._quote,
                                             fxq["price"] if fxq else None, total, cash, self.clock(), vwrp_px,
                                             disabled, self.s.read("gap_rebound.json"),
                                             self.s.read("precision.json") or {})
            notes += n
            orders += go
        if nc and not active.sleeve_block(self.cfg, recs, self.positions, day, total):
            no, n = news_shock.entry_orders(nc, self.cfg, recs, self.positions, self._quote,
                                            fxq["price"] if fxq else None, total, cash, self.clock(), vwrp_px,
                                            disabled, self.s.read("news_shock.json"),
                                            self.s.read("precision.json") or {})
            notes += n
            orders += no
        for vc in (self._vt() if not active.sleeve_block(self.cfg, recs, self.positions, day, total) else []):
            vo, n = value_timing.entry_orders({**vc, "_cfg": self.cfg}, recs, self.positions, self._quote,
                                              fxq["price"] if fxq else None, total, cash, self.clock(), vwrp_px,
                                              disabled, self.s.read(f"{vc['name']}.json"))
            notes += n
            orders += vo
        orders = self._momentum_switch(orders, notes)
        return next((o for o in orders if self.market_open(o[0])), None)

    def _momentum_switch(self, orders: list, notes: list) -> list:
        """Q219 OFF-switch (unproven, demo): no new momentum-family entries while SPY is below its 10-month average or
        VIX closed at 25 or more; open trades keep their exits. Each blocked entry is logged once a day."""
        mc = self.cfg["active"].get("momentum_off") or {}
        fam = set(mc.get("strategies") or [])
        if not mc.get("enabled") or not any((o[6] or {}).get("strategy") in fam for o in orders):
            return orders
        now = self.clock()
        today = gap_rebound.ny_now(now).date().isoformat()
        c = getattr(self, "_mom", None)
        if not c or now - c["t"] > mc.get("refresh_s", 3600) or c["today"] != today:
            try:
                spy = gap_rebound.bars("SPY", self.get, "2y")
                vix = gap_rebound.bars("^VIX", self.get)
            except Exception:  # noqa: BLE001 - unreadable: UNVERIFIED, so the switch blocks
                spy, vix = [], []
            off, det = active.momentum_off(spy, vix, today, mc.get("vix_hi", 25.0), mc.get("months", 10))
            c = self._mom = {"t": now, "today": today, "off": off, "det": det, "logged": (c or {}).get("logged", set())}
        if c["off"] is False:
            return orders
        keep = []
        for o in orders:
            st = (o[6] or {}).get("strategy")
            if st not in fam:
                keep.append(o)
                continue
            why = active.MOMENTUM_OFF_WHY if c["off"] else f"{active.MOMENTUM_OFF_WHY}; {c['det']['why']}"
            notes.append(f"{st}: {o[0]} entry blocked: {why}")
            k = (today, st, o[0])
            if k not in c["logged"]:
                c["logged"].add(k)
                self.s.event("momentum_blocked", strategy=st, ticker=o[0], why=why, **c["det"],
                             would_buy_gbp=round(o[2], 2))
        return keep

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
        keep += stock_screen.need_gbp(self._screen(), self.cfg, self.s.intents(), self.positions, total,
                                      self.s.read("strategies.json") or {})  # cash freed for the basket stays
        keep += buyback_value.need_gbp(self._buyback(), self.cfg, self._buyback_picks(), self.s.intents(),
                                       self.positions, self._us_tradeable, total, self.s.read("strategies.json") or {})
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
        limits = self.cfg["limits"]
        if (signal or {}).get("strategy") == merger.NAME and (self.mstate.get("deals", {}).get(ticker) or {}).get("eligible"):
            limits = {**limits, "buy_whitelist": [*limits["buy_whitelist"], ticker]}  # a deal that passed every filter
        if (signal or {}).get("strategy") == gap_rebound.NAME and (
                ((self.s.read("gap_rebound.json") or {}).get("signals") or {}).get(ticker) or {}).get("eligible"):
            limits = {**limits, "buy_whitelist": [*limits["buy_whitelist"], ticker]}  # a signal that passed every filter
        if (signal or {}).get("strategy") == news_shock.NAME and (
                ((self.s.read("news_shock.json") or {}).get("signals") or {}).get(ticker) or {}).get("eligible"):
            limits = {**limits, "buy_whitelist": [*limits["buy_whitelist"], ticker]}  # a signal that passed every filter
        if (signal or {}).get("strategy") == buyback_value.NAME and signal.get("type") == "active_entry":
            limits = {**limits, "buy_whitelist": [*limits["buy_whitelist"], ticker]}  # a pick from the month's file
        refusals = execution.risk_check(order, control=self.s.control(), records=self.s.intents(),
                                        pending=self.pending, positions=self.positions, limits=limits,
                                        day=day, consecutive_errors=self.ex.consecutive_errors, quote_ok=quote_ok,
                                        market_open=self.market_open(ticker))
        key = f"{ticker}:{qty}:{';'.join(refusals)}"
        if refusals and key in self.alerted:
            return None  # the same refusal is recorded once, not every five minutes
        self.alerted.add(key)
        rec = self.ex.submit(order, refusals)
        if rec["status"] == "placed":
            self.due["broker"] = min(self.due.get("broker", 0), self.clock() + 20)  # confirm the fill quickly
        if rec["status"] == "rejected" and "quantity-precision-mismatch" in rec.get("error", ""):
            # T212 allows fewer decimals on some lines than others and names none in its metadata: learn one fewer
            prec = self.s.read("precision.json") or {}
            d = len(f"{abs(qty):.8f}".rstrip("0").split(".")[1]) if "." in f"{abs(qty):.8f}".rstrip("0") else 0
            prec[ticker] = max(0, min(prec.get(ticker, 8), d) - 1)
            self.s._replace("precision.json", prec)
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
