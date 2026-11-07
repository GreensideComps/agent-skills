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
                 hour_cap: int = 45, day_cap: int = 900, bars_ttl_s: float = 900, raw_get=None):
        self.root = Path(root)
        self.positions_fn = positions_fn
        self.clock = clock
        self.hour_cap, self.day_cap, self.bars_ttl_s = hour_cap, day_cap, bars_ttl_s
        self.raw_get = raw_get or requests.get
        self._fx: dict | None = None
        self._iex: dict = {"at": -1e18, "key": None, "rows": []}
        self._snap: dict = {"at": -1e18, "rows": {}}

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

    def _budget(self) -> None:
        p = self.root / "tiingo_usage.json"
        now = self.clock()
        try:
            ts = [t for t in json.loads(p.read_text()).get("t", []) if now - t < 86400]
        except (OSError, ValueError):
            ts = []
        if sum(1 for t in ts if now - t < 3600) >= self.hour_cap or len(ts) >= self.day_cap:
            raise BudgetError(f"tiingo: request budget used ({self.hour_cap}/h, {self.day_cap}/day)")
        ts.append(now)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"t": ts}))
        tmp.replace(p)

    def tiingo(self, path: str, params: dict | None = None, timeout: float = 30.0):
        self._budget()
        r = self.raw_get(TIINGO + path, params=params or {}, timeout=timeout,
                         headers={**feeds.UA, "Authorization": f"Token {self._token()}"})
        if r.status_code != 200:
            raise feeds.FeedError(f"tiingo {path.split('?')[0]}: HTTP {r.status_code}")
        return r.json()

    # ------------------------------------------------------------ quotes
    def spark(self, symbols: list[str]) -> dict:
        out: dict[str, dict] = {}
        us = [s for s in symbols if not s.endswith((".L", "=X")) and not s.startswith("^")]
        if us:
            key = ",".join(sorted(s.lower() for s in us))
            ttl = 150 if us_hours(self.clock()) else 1800  # one batch call covers every US line; ~24 calls/h at most
            if self._iex["key"] != key or self.clock() - self._iex["at"] >= ttl:
                self._iex = {"at": self.clock(), "key": key, "rows": self.tiingo("/iex/", {"tickers": key}) or []}
            rows = self._iex["rows"]
            by = {r["ticker"].upper(): r for r in rows or []}
            for s in us:
                r = by.get(s.upper())
                px = r and (r.get("tngoLast") or r.get("last"))
                ts = r and (r.get("lastSaleTimestamp") or r.get("timestamp"))
                if px and ts:
                    out[s] = _spark_row(_epoch(ts), float(px), r.get("prevClose"))
        for s in symbols:
            if s.endswith("=X"):
                q = self.fx(s)
                if q:
                    out[s] = _spark_row(q[1], q[0], None)
            elif s == "^VIX":
                q = self.vix_quote()
                if q:
                    out[s] = _spark_row(q[1], q[0], q[2])
            elif s.endswith(".L"):
                q = (self.positions_fn() or {}).get(s)
                if q:
                    out[s] = _spark_row(q["t"], q["price"], None)
        return out

    def snapshot(self) -> dict[str, dict]:
        """Every US ticker's latest IEX/consolidated row ({SYMBOL: row}) in one call, cached 30 minutes."""
        if self.clock() - self._snap["at"] >= 1800:
            self._snap = {"at": self.clock(), "rows": {r["ticker"].upper(): r for r in self.tiingo("/iex/") or []}}
        return self._snap["rows"]

    def fx(self, sym: str) -> tuple[float, float] | None:
        """(mid, epoch) for e.g. GBPUSD=X, cached 15 minutes."""
        now = self.clock()
        if self._fx and self._fx["sym"] == sym and now - self._fx["at"] < 900:
            return self._fx["q"]
        rows = self.tiingo("/tiingo/fx/top", {"tickers": sym[:-2].lower()})
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
        rows = self.tiingo(f"/tiingo/daily/{sym.lower()}/prices", {"startDate": start}) or []
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
