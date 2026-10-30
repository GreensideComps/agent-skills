"""Market data: Yahoo prices (polled; no free streaming feed exists for these symbols), validated before use, the
broker's own market calendar, and Yahoo news headlines.

Every quote carries its source timestamp. A quote is usable only if it is a positive finite number, its timestamp is
not in the future and is fresh for the market's state, and it has not moved more than `abnormal_move` from the
previous close without a confirming second reading.
"""
from __future__ import annotations

import math
from typing import Callable

import requests

UA = {"User-Agent": "Mozilla/5.0 (market-agent; demo research)"}
SPARK = "https://query1.finance.yahoo.com/v8/finance/spark"
SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"


class FeedError(RuntimeError):
    pass


def http_get(url: str, params: dict, timeout: float = 20.0) -> dict:
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    if r.status_code != 200:
        raise FeedError(f"{url.rsplit('/', 1)[-1]}: HTTP {r.status_code}")
    return r.json()


def yahoo_symbol(t212: str, overrides: dict) -> str | None:
    if t212 in overrides:
        return overrides[t212]
    if t212.endswith("_US_EQ"):
        return t212[: -len("_US_EQ")].replace(".", "-")
    if t212.endswith("l_EQ"):
        return t212[: -len("l_EQ")] + ".L"
    return None


def fetch_quotes(symbols: list[str], get: Callable = http_get) -> dict[str, dict]:
    """Last 1-minute bar per symbol: {sym: {price, t, prev_close}}. Symbols missing from the reply are absent."""
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), 20):
        chunk = symbols[i:i + 20]
        d = get(SPARK, {"symbols": ",".join(chunk), "range": "1d", "interval": "1m"})
        for sym in chunk:
            v = d.get(sym) if isinstance(d, dict) else None
            if not isinstance(v, dict):
                continue
            ts, cl = v.get("timestamp") or [], v.get("close") or []
            last = next(((t, c) for t, c in zip(reversed(ts), reversed(cl)) if c is not None), None)
            if last:
                out[sym] = {"price": last[1], "t": float(last[0]), "prev_close": v.get("previousClose")}
    return out


def validate(sym: str, q: dict | None, now: float, market_open: bool, fresh: dict, abnormal: float,
             last_good: dict | None) -> tuple[bool, str]:
    if not q:
        return False, "missing"
    p = q.get("price")
    if not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0:
        return False, f"bad price {p!r}"
    if q["t"] > now + 120:
        return False, "timestamp in the future"
    age = now - q["t"]
    delayed = any(sym.endswith(x) for x in fresh.get("delayed_suffixes", []))
    limit = (fresh["market_open_delayed"] if delayed else fresh["market_open"]) if market_open else fresh["market_closed"]
    if age > limit:
        return False, f"stale: {age:.0f} s old (limit {limit} s, market {'open' if market_open else 'closed'})"
    ref = q.get("prev_close") or (last_good or {}).get("price")
    if ref and abs(p / ref - 1) > abnormal:
        # A huge move is accepted only when a second, later reading agrees with it.
        if not last_good or last_good.get("t", 0) >= q["t"] or abs(last_good["price"] / p - 1) > 0.02:
            return False, f"abnormal move {p / ref - 1:+.1%} vs {ref}; waiting for confirmation"
    return True, "ok"


# ---------------------------------------------------------------- market calendar from the broker
def session_state(events: list[dict], now: float) -> dict:
    """Regular session state from a broker working schedule (timeEvents). Open means the latest event at or before
    now is OPEN. Returns {open, last_event, next_open, next_close} (epoch seconds or None)."""
    evs = sorted((_epoch(e["date"]), e["type"]) for e in events if e.get("date") and e.get("type"))
    past = [e for e in evs if e[0] <= now]
    last = past[-1] if past else None
    nxt_open = next((t for t, k in evs if t > now and k == "OPEN"), None)
    nxt_close = next((t for t, k in evs if t > now and k in ("CLOSE", "AFTER_HOURS_OPEN")), None)
    return {"open": bool(last and last[1] == "OPEN"), "last_event": last, "next_open": nxt_open,
            "next_close": nxt_close, "covered_until": evs[-1][0] if evs else None}


def _epoch(s: str) -> float:
    import datetime as dt
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# ---------------------------------------------------------------- news
def fetch_news(query: str, get: Callable = http_get, count: int = 5) -> list[dict]:
    d = get(SEARCH, {"q": query, "newsCount": count, "quotesCount": 0})
    out = []
    for n in d.get("news", []) if isinstance(d, dict) else []:
        if n.get("uuid") and n.get("title"):
            out.append({"id": n["uuid"], "title": n["title"], "publisher": n.get("publisher"),
                        "published": n.get("providerPublishTime"), "link": n.get("link"),
                        "tickers": n.get("relatedTickers", [])})
    return out



WIKI = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{a}/daily/{s}/{e}"
WIKI_UA = {"User-Agent": "market-agent/1.4 (demo research; github.com/GreensideComps/agent-skills)"}


def wiki_get(url: str, params: dict, timeout: float = 20.0) -> dict:
    r = requests.get(url, params=params, headers=WIKI_UA, timeout=timeout)
    if r.status_code != 200:
        raise FeedError(f"pageviews: HTTP {r.status_code}")
    return r.json()


def pageviews(article: str, start: str, end: str, get: Callable = wiki_get) -> list[tuple[str, int]]:
    """Daily human (user-agent) views of one English Wikipedia article: [(YYYYMMDD, views)] oldest first."""
    d = get(WIKI.format(a=article, s=start, e=end), {})
    return [(i["timestamp"][:8], int(i["views"])) for i in d.get("items", [])]


def attention_z(series: list[tuple[str, int]], lookback: int) -> dict | None:
    """The last day's views against the `lookback` days before it, as a z-score on log views."""
    if len(series) < lookback + 1:
        return None
    lv = [math.log1p(v) for _, v in series[-(lookback + 1):]]
    base, last = lv[:-1], lv[-1]
    mu = sum(base) / len(base)
    sd = (sum((x - mu) ** 2 for x in base) / (len(base) - 1)) ** 0.5
    return {"day": series[-1][0], "views": series[-1][1], "base_mean": round(math.expm1(mu)),
            "z": round((last - mu) / sd, 2) if sd > 0 else None}
