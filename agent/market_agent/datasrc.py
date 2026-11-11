"""agent-1.21 honest market data (7 Nov 2026). The agent used to read Yahoo (and Nasdaq) with a browser-like
User-Agent; both refuse an honest client, so that was a workaround of their access controls and it is gone. This
module answers the same calls (the Yahoo spark/chart shapes the rest of the agent parses) from sources that accept an
honest client:

- Tiingo (the owner's free API key, state/tiingo_token.txt, never committed or logged): IEX real-time last prices
  for US symbols in one batch call, daily bars (split- and dividend-adjusted), 1-minute IEX bars, GBP/USD;
- CBOE's public delayed VIX quote and history;
- the broker's own position prices for London lines (T212 currentPrice), which no free honest source covers.

Anything else fails with FeedError, which the agent already treats as UNVERIFIED (no trade). Tiingo's free plan
allows 50 requests an hour and 1,000 a day: calls are counted in state/tiingo_usage.json and refused above
`hour_cap`/`day_cap`, and daily bars are cached on disk for `bars_ttl_s`.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import requests

from . import feeds

TIINGO = "https://api.tiingo.com"
CBOE_QUOTE = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json"
CBOE_HIST = "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_VIX.json"
CHART_PREFIX = "https://query1.finance.yahoo.com/v8/finance/chart/"
RANGE_DAYS = {"5d": 10, "1mo": 35, "3mo": 100, "6mo": 190, "1y": 370, "2y": 740}
NY = ZoneInfo("America/New_York")


class BudgetError(feeds.FeedError):
    """Tiingo's free request budget is used up for now: callers retry later instead of dropping the work."""


def us_hours(now: float) -> bool:
    d = datetime.fromtimestamp(now, NY)
    return d.weekday() < 5 and (9, 25) <= (d.hour, d.minute) < (16, 10)


def last_eod(now: float) -> float:
    """The latest weekday 18:00 New York at or before `now`: Tiingo's daily bar for that day is in by then."""
    d = datetime.fromtimestamp(now, NY).replace(hour=18, minute=0, second=0, microsecond=0)
    while d.timestamp() > now or d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.timestamp()


class Honest:
    def __init__(self, root: str | Path, positions_fn: Callable[[], dict], clock: Callable[[], float] = time.time,
                 hour_cap: int = 45, day_cap: int = 900, bars_ttl_s: float = 900, raw_get=None, quote_reserve: int = 20):
        self.root = Path(root)
        self.positions_fn = positions_fn
        self.clock = clock
        self.hour_cap, self.day_cap, self.bars_ttl_s, self.quote_reserve = hour_cap, day_cap, bars_ttl_s, quote_reserve
        self.raw_get = raw_get or requests.get
        self._fx: dict | None = None
        self._snap: dict = {"at": -1e18, "rows": {}}
        self._q: dict = {"at": -1e18, "want": [], "rows": {}}

    # ------------------------------------------------------------ entry point (Yahoo-shaped answers)
    def get(self, url: str, params: dict) -> dict:
        if url == feeds.SPARK:
            return self.spark([s for s in params["symbols"].split(",") if s])
        if url.startswith(CHART_PREFIX):
            return self.chart(url[len(CHART_PREFIX):], params.get("range", "1y"), params.get("interval", "1d"))
        if url == feeds.SEARCH:
            return {"news": []}  # Yahoo news search has no honest replacement; headlines were alert-only
        if "yahoo.com" in url or "nasdaq.com" in url:
            raise feeds.FeedError(f"{url.split('/')[2]}: refuses an honest client; no replacement (UNVERIFIED)")
        return feeds.http_get(url, params)

    # ------------------------------------------------------------ Tiingo with a request budget
    def _token(self) -> str:
        p = self.root / "tiingo_token.txt"
        if not p.exists():
            raise feeds.FeedError("tiingo: no token in state/tiingo_token.txt")
        return p.read_text().strip()

    def _budget(self, kind: str) -> None:
        p = self.root / "tiingo_usage.json"
        now = self.clock()
        try:
            ts = [t for t in json.loads(p.read_text()).get("t", []) if now - t < 86400]
        except (OSError, ValueError):
            ts = []
        cap = self.hour_cap if kind == "quotes" else self.hour_cap - self.quote_reserve  # prices never starve
        if sum(1 for t in ts if now - t < 3600) >= cap or len(ts) >= self.day_cap - (kind != "quotes") * 100:
            raise BudgetError(f"tiingo: request budget used ({self.hour_cap}/h, {self.day_cap}/day)")
        ts.append(now)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"t": ts}))
        tmp.replace(p)

    def tiingo(self, path: str, params: dict | None = None, timeout: float = 30.0, kind: str = "bars"):
        self._budget(kind)
        r = self.raw_get(TIINGO + path, params=params or {}, timeout=timeout,
                         headers={**feeds.UA, "Authorization": f"Token {self._token()}"})
        if r.status_code != 200:
            raise feeds.FeedError(f"tiingo {path.split('?')[0]}: HTTP {r.status_code}")
        return r.json()

    # ------------------------------------------------------------ quotes
    def spark(self, symbols: list[str]) -> dict:
        """agent-1.22.2: US lines from one small Tiingo IEX call for just the requested tickers (cached 4 min in US
        hours), not the full-market snapshot, which ran the free plan's monthly bandwidth out on 10 Nov 2026. When
        Tiingo fails (bandwidth, budget, outage) a held line falls back to the broker's own position price, and
        GBPUSD to the rate implied by the broker's USD positions; anything else stays UNVERIFIED."""
        out: dict[str, dict] = {}
        bq = self.positions_fn() or {}
        us = [s for s in symbols if not s.endswith((".L", "=X")) and not s.startswith("^")]
        if us:
            try:
                by = self.quotes(us, ttl=240 if us_hours(self.clock()) else 1800)
            except feeds.FeedError:
                by = {}
            for s in us:
                r = by.get(s.upper())
                px = r and (r.get("tngoLast") or r.get("last"))
                ts = r and (r.get("lastSaleTimestamp") or r.get("timestamp"))
                if px and ts:
                    out[s] = _spark_row(_epoch(ts), float(px), r.get("prevClose"))
                elif s in bq:
                    out[s] = _spark_row(bq[s]["t"], bq[s]["price"], None)
        for s in symbols:
            if s.endswith("=X"):
                try:
                    q = self.fx(s)
                except feeds.FeedError:
                    q = None
                if q:
                    out[s] = _spark_row(q[1], q[0], None)
                elif s in bq:
                    out[s] = _spark_row(bq[s]["t"], bq[s]["price"], None)
            elif s == "^VIX":
                q = self.vix_quote()
                if q:
                    out[s] = _spark_row(q[1], q[0], q[2])
            elif s.endswith(".L"):
                q = bq.get(s)
                if q:
                    out[s] = _spark_row(q["t"], q["price"], None)
        return out

    def quotes(self, syms: list[str], ttl: float = 240) -> dict[str, dict]:
        """Latest IEX rows for just `syms` ({SYMBOL: row}) in one call; a failed call is not retried for 15 min."""
        now, want = self.clock(), {s.upper() for s in syms}
        q = self._q
        if now < q.get("fail_until", 0):
            raise feeds.FeedError(q.get("why", "tiingo iex: backing off"))
        if now - q["at"] >= ttl or not want <= set(q["want"]):
            try:
                rows = self.tiingo("/iex/", {"tickers": ",".join(sorted(want))}, kind="quotes")
            except BudgetError:
                raise
            except feeds.FeedError as e:
                self._q = {**q, "fail_until": now + 900, "why": str(e)}
                raise
            if not isinstance(rows, list):
                raise feeds.FeedError(f"tiingo iex: unexpected reply {str(rows)[:80]}")
            self._q = {"at": now, "want": sorted(want),
                       "rows": {r["ticker"].upper(): r for r in rows if r.get("ticker")}}
        return self._q["rows"]

    def snapshot(self, ttl: float = 1800) -> dict[str, dict]:
        """Every US ticker's latest IEX/consolidated row ({SYMBOL: row}) in one call, for the liquidity pre-filter and
        the bars store only (agent-1.22.2: at most every 30 min; a failed call is not retried for 30 min)."""
        now = self.clock()
        if now < self._snap.get("fail_until", 0):
            raise feeds.FeedError(self._snap.get("why", "tiingo iex snapshot: backing off"))
        if now - self._snap["at"] >= max(ttl, 1800):
            try:
                rows = self.tiingo("/iex/", kind="quotes")
            except BudgetError:
                raise
            except feeds.FeedError as e:
                self._snap = {**self._snap, "fail_until": now + 1800, "why": str(e)}
                raise
            if not isinstance(rows, list):
                raise feeds.FeedError(f"tiingo iex: unexpected reply {str(rows)[:80]}")
            self._snap = {"at": self.clock(), "rows": {r["ticker"].upper(): r for r in rows if r.get("ticker")}}
            try:
                self._store_session(rows)
            except (OSError, ValueError, KeyError, TypeError):
                pass  # the store is a fallback; a failed write never blocks prices
        return self._snap["rows"]

    def _store_session(self, rows: list[dict]) -> None:
        """agent-1.21.4 bars store: each finished US session's OHLC and volume for every ticker, kept from the
        snapshot calls the agent makes anyway (no extra request, no per-symbol lookup). Tiingo's free plan allows 500
        distinct symbols a month for daily history; the store gives bars for any name once enough sessions are in."""
        now = datetime.fromtimestamp(self.clock(), NY)
        days: dict[str, int] = {}
        for r in rows:
            if r.get("timestamp"):
                days[r["timestamp"][:10]] = days.get(r["timestamp"][:10], 0) + 1
        if not days:
            return
        day = max(days, key=days.get)  # the session most tickers last traded in
        if now.date().isoformat() == day and (now.hour, now.minute) < (16, 20):
            return  # still trading (or the closing prints are not in yet)
        d = self.root / "bars_store"
        d.mkdir(exist_ok=True)
        p = d / f"{day}.json"
        if p.exists():
            return
        out = {}
        for r in rows:
            c = r.get("tngoLast") or r.get("last")
            if r.get("ticker") and (r.get("timestamp") or "")[:10] == day and c and r.get("volume"):
                out[r["ticker"].upper()] = [r.get("open"), r.get("high"), r.get("low"), c, r["volume"]]
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, separators=(",", ":")))
        tmp.replace(p)

    def _stored(self, sym: str, after: str = "") -> list[dict]:
        """Daily rows for `sym` from the bars store (raw prices: no split adjustment), sessions after `after`."""
        out = []
        for p in sorted((self.root / "bars_store").glob("*.json")):
            if p.stem <= after:
                continue
            try:
                r = json.loads(p.read_text()).get(sym.upper())
            except (OSError, ValueError):
                continue
            if r:
                out.append({"date": p.stem, "open": r[0], "high": r[1], "low": r[2], "close": r[3], "volume": r[4],
                            "adjClose": r[3], "splitFactor": 1.0})
        return out

    def fx(self, sym: str) -> tuple[float, float] | None:
        """(mid, epoch) for e.g. GBPUSD=X, cached 15 minutes."""
        now = self.clock()
        if self._fx and self._fx["sym"] == sym and now - self._fx["at"] < 900:
            return self._fx["q"]
        rows = self.tiingo("/tiingo/fx/top", {"tickers": sym[:-2].lower()}, kind="quotes")
        r = (rows or [{}])[0]
        if not r.get("midPrice"):
            return None
        q = (float(r["midPrice"]), _epoch(r["quoteTimestamp"]))
        self._fx = {"sym": sym, "at": now, "q": q}
        return q

    def _vix_raw(self) -> dict:
        r = self.raw_get(CBOE_QUOTE, headers=feeds.UA, timeout=20)
        if r.status_code != 200:
            raise feeds.FeedError(f"cboe vix: HTTP {r.status_code}")
        return r.json().get("data") or {}

    def vix_quote(self) -> tuple[float, float, float | None] | None:
        """(price, epoch, previous close). CBOE stamps the last trade in New York time."""
        d = self._vix_raw()
        px, ts = d.get("current_price") or d.get("close"), d.get("last_trade_time")
        if not px or not ts:
            return None
        return float(px), datetime.fromisoformat(ts).replace(tzinfo=NY).timestamp(), d.get("prev_day_close")

    # ------------------------------------------------------------ bars
    def chart(self, sym: str, rng: str, interval: str) -> dict:
        if interval != "1d":
            return self._intraday(sym, interval)
        if sym == "^VIX":
            return self._vix_hist(rng)
        if sym.endswith((".L", "=X")) or sym.startswith("^"):
            raise feeds.FeedError(f"{sym}: no honest daily-bar source (UNVERIFIED)")
        rows = self._daily(sym)
        # Yahoo's convention, which the callers expect: OHLC adjusted for later splits only, adjclose for dividends too
        out, k = [], 1.0
        for r in reversed(rows):
            out.append((r["date"][:10], *(None if r.get(f) is None else r[f] / k for f in ("open", "high", "low", "close")),
                        None if r.get("volume") is None else r["volume"] * k, r.get("adjClose")))
            k *= float(r.get("splitFactor") or 1.0)
        start = (datetime.fromtimestamp(self.clock(), timezone.utc) - timedelta(days=RANGE_DAYS.get(rng, 370))).date()
        return _chart([x for x in reversed(out) if x[0] >= start.isoformat()])

    def _daily(self, sym: str) -> list[dict]:
        d = self.root / "bars_cache"
        d.mkdir(exist_ok=True)
        p = d / f"{sym.replace('/', '_')}.json"
        now = self.clock()
        try:
            c = json.loads(p.read_text())
            if c["at"] >= last_eod(now) or now - c["at"] < self.bars_ttl_s:
                return c["rows"]
        except (OSError, ValueError, KeyError):
            pass
        start = (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=RANGE_DAYS["2y"])).date().isoformat()
        try:
            rows = self.tiingo(f"/tiingo/daily/{sym.lower()}/prices", {"startDate": start}) or []
            if not isinstance(rows, list):
                raise feeds.FeedError(f"tiingo daily {sym}: {str(rows)[:100]}")
        except BudgetError:
            raise
        except feeds.FeedError as e:  # e.g. the 500-symbol monthly cap: fall back to the cache plus the bars store
            try:
                old = json.loads(p.read_text())["rows"]
            except (OSError, ValueError, KeyError):
                old = []
            rows = old + self._stored(sym, old[-1]["date"][:10] if old else "")
            if len(rows) < 2:
                raise feeds.FeedError(f"{e} (bars store has {len(rows)} sessions: UNVERIFIED)") from e
            return rows
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": now, "rows": rows}))
        tmp.replace(p)
        return rows

    def _intraday(self, sym: str, interval: str) -> dict:
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        rows = self.tiingo(f"/iex/{sym.lower()}/prices", {"startDate": day, "resampleFreq": interval.replace("m", "min"),
                                                         "columns": "open,high,low,close,volume"}) or []
        return _chart([(r["date"], r.get("open"), r.get("high"), r.get("low"), r.get("close"), r.get("volume"))
                       for r in rows], intraday=True)

    def _vix_hist(self, rng: str) -> dict:
        r = self.raw_get(CBOE_HIST, headers=feeds.UA, timeout=30)
        if r.status_code != 200:
            raise feeds.FeedError(f"cboe vix history: HTTP {r.status_code}")
        start = (datetime.fromtimestamp(self.clock(), timezone.utc) - timedelta(days=RANGE_DAYS.get(rng, 370))).date()
        rows = [x for x in r.json().get("data") or [] if x.get("date", "") >= start.isoformat()]
        try:  # CBOE's history lags a day; a finished session's close comes from the quote
            q = self._vix_raw()
            lt = datetime.fromisoformat(q["last_trade_time"])
            if q.get("close") and (lt.hour, lt.minute) >= (16, 15) and (not rows or lt.date().isoformat() > rows[-1]["date"]):
                rows.append({"date": lt.date().isoformat(), "open": q["open"], "high": q["high"], "low": q["low"],
                             "close": q["close"]})
        except (feeds.FeedError, KeyError, ValueError, TypeError):
            pass
        return _chart([(x["date"], float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), 0.0,
                        float(x["close"])) for x in rows])


def _epoch(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _spark_row(t: float, px: float, prev) -> dict:
    return {"timestamp": [t], "close": [px], "previousClose": prev}


def _chart(rows: list[tuple], intraday: bool = False) -> dict:
    """Yahoo chart shape. A daily bar is stamped 20:00 UTC on its date, which is that date in New York."""
    ts = [int(_epoch(d)) if intraday else int(_epoch(f"{d[:10]}T20:00:00+00:00")) for d, *_ in rows]
    q = {"open": [r[1] for r in rows], "high": [r[2] for r in rows], "low": [r[3] for r in rows],
         "close": [r[4] for r in rows], "volume": [r[5] for r in rows]}
    ind = {"quote": [q]}
    if rows and len(rows[0]) > 6:
        ind["adjclose"] = [{"adjclose": [r[6] for r in rows]}]
    return {"chart": {"result": [{"timestamp": ts, "indicators": ind, "meta": {}}]}}
