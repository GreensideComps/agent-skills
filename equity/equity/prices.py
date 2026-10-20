"""Daily closing prices for valuation (milestone 3).

Source: Yahoo Finance's chart endpoint, the same free source the demo bot uses for order
sizing. It is unofficial, delayed (~15 minutes intraday) and not licensed for
redistribution, so it is used only to compute valuation ratios here, never republished.
No free official source covers the whole universe: SEC has no prices, Stooq's CSV API
returned nothing when tried on 2026-10-14, and T212's API has no quote endpoint.

Each fetched close is one record in the `prices` ledger, keyed by listing and date, so a
re-run on the same day writes nothing, and every valuation can name the exact price it used.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .store import Store, utc_now

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"
SOURCE = "yahoo chart v8 (unofficial, delayed, check-only licence)"


class PriceError(RuntimeError):
    pass


def yahoo_symbol(security: dict) -> str:
    """Yahoo uses '-' for share classes (BRK-B); only US lines are priced for now. A security may name its Yahoo
    symbol outright (`yahoo`), as the London-listed VWRP benchmark (VWRP.L) and the GBPUSD rate do."""
    if security.get("yahoo"):
        return security["yahoo"]
    return security["symbol"].replace(".", "-").replace("/", "-")


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise PriceError(f"HTTP {e.code} for {url}") from None


def parse_chart(body: bytes) -> dict:
    """Latest daily close from a chart response: {close, date, currency, exchange}."""
    res = (json.loads(body).get("chart", {}).get("result") or [None])[0]
    if not res:
        raise PriceError("no chart result")
    meta = res["meta"]
    ts = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    pts = [(t, c) for t, c in zip(ts, closes) if c is not None]
    if not pts:
        raise PriceError("no closes")
    t, c = pts[-1]
    return {"close": float(c), "date": datetime.fromtimestamp(t, timezone.utc).date().isoformat(),
            "currency": meta.get("currency"), "exchange": meta.get("fullExchangeName") or meta.get("exchangeName")}


def fetch_price(security: dict, get=_get) -> dict:
    sym = yahoo_symbol(security)
    p = parse_chart(get(CHART_URL.format(sym=sym)))
    return {"rid": f"{security['t212_ticker']}:{p['date']}", "t212_ticker": security["t212_ticker"],
            "company_id": security["company_id"], "symbol": security["symbol"], "source_symbol": sym,
            "source": SOURCE, "retrieved_utc": utc_now(), **p}


def update_prices(store: Store, securities: list[dict], get=_get, pause: float = 0.3, sleep=time.sleep) -> dict:
    written, failed = 0, []
    for i, s in enumerate(securities):
        if i:
            sleep(pause)
        try:
            written += store.prices.append(fetch_price(s, get))
        except (PriceError, OSError, ValueError, KeyError) as e:
            failed.append(f"{s['symbol']}: {e}")
    return {"requested": len(securities), "written": written, "failed": failed}


def latest_prices(store: Store) -> dict[str, dict]:
    """company_id -> latest price record (the primary listing priced for that company)."""
    out: dict[str, dict] = {}
    for p in store.prices.read():
        cur = out.get(p["company_id"])
        if cur is None or (p["date"], p["retrieved_utc"]) > (cur["date"], cur["retrieved_utc"]):
            out[p["company_id"]] = p
    return out
