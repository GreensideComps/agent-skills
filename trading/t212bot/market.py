"""Reference prices, FX and market hours.

Trading 212's API has no quote endpoint, so order sizing uses Yahoo Finance's
regularMarketPrice (LSE quotes are typically ~15 min delayed). Every price is
sanity-checked: it must be recent, positive, and, when Trading 212 reports a
currentPrice for a held position, within max_price_divergence of it.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import SafetyError


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float          # in `currency`, pounds not pence
    currency: str         # GBP or USD
    as_of: datetime       # UTC
    source: str


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (t212bot)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception:
        r = subprocess.run(["curl", "-sSf", "-m", "20", "-A", "Mozilla/5.0 (t212bot)", url], capture_output=True)
        if r.returncode != 0:
            raise
        return json.loads(r.stdout)


class YahooQuotes:
    def __init__(self, fetch: Callable[[str], dict] = _fetch_json):
        self._fetch = fetch

    def quote(self, symbol: str) -> Quote:
        js = self._fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d")
        meta = js["chart"]["result"][0]["meta"]
        px, cur = float(meta["regularMarketPrice"]), meta["currency"]
        if cur == "GBp":
            px, cur = px / 100.0, "GBP"
        if px <= 0:
            raise SafetyError(f"non-positive price for {symbol}")
        ts = datetime.fromtimestamp(int(meta["regularMarketTime"]), tz=timezone.utc)
        return Quote(symbol, px, cur, ts, "yahoo:regularMarketPrice")

    def gbpusd(self) -> Quote:
        return self.quote("GBPUSD=X")


def to_gbp(price: float, currency: str, gbpusd: float) -> float:
    if currency == "GBP":
        return price
    if currency == "USD":
        return price / gbpusd
    raise SafetyError(f"unsupported currency {currency}")


def check_fresh(q: Quote, now: datetime, max_age: timedelta = timedelta(hours=1)) -> None:
    if now - q.as_of > max_age:
        raise SafetyError(f"stale quote for {q.symbol}: {q.as_of.isoformat()} (now {now.isoformat()})")


def check_against_t212(q: Quote, t212_price: float | None, tol: float) -> None:
    if t212_price is None or t212_price <= 0:
        return
    div = abs(q.price / t212_price - 1)
    if div > tol:
        raise SafetyError(f"{q.symbol}: Yahoo {q.price:.4f} vs Trading 212 {t212_price:.4f} diverge {div:.1%} > {tol:.0%}")


# ------------------------------------------------------------------ hours

def session_window(exchanges: list[dict], schedule_id: int, now: datetime):
    """Return (open, close) UTC for the session containing `now`, else None."""
    for ex in exchanges:
        for ws in ex.get("workingSchedules", []):
            if ws.get("id") != schedule_id:
                continue
            evs = sorted(((datetime.fromisoformat(e["date"].replace("Z", "+00:00")), e["type"]) for e in ws["timeEvents"]))
            open_t = None
            for t, typ in evs:
                if typ == "OPEN":
                    open_t = t
                elif typ == "CLOSE" and open_t is not None:
                    if open_t <= now < t:
                        return open_t, t
                    open_t = None
            return None
    raise SafetyError(f"working schedule {schedule_id} not found")


def tradable_now(exchanges, schedule_id, now, open_buffer_min, close_buffer_min) -> tuple[bool, str]:
    w = session_window(exchanges, schedule_id, now)
    if w is None:
        return False, "market closed"
    o, c = w
    if now < o + timedelta(minutes=open_buffer_min):
        return False, f"within {open_buffer_min} min of open ({o:%H:%M} UTC)"
    if now > c - timedelta(minutes=close_buffer_min):
        return False, f"within {close_buffer_min} min of close ({c:%H:%M} UTC)"
    return True, f"open {o:%H:%M}-{c:%H:%M} UTC"
