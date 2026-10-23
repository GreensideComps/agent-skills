"""Daily-price provenance (mini fund Stage 2 §2, owner approval U2 of 2026-10-23).

Turns a stored Yahoo chart response into price records that say exactly what each number is:

* `close`      split-adjusted close **as retrieved** (Yahoo rewrites it after later splits);
* `adjclose`   split- and dividend-adjusted close **as retrieved** (a total-return series, for window returns only);
* `close_unadjusted`  the decision-time price: `close` times the ratio of every split after that session. It is
  computed only when the response was requested with split events; otherwise it is `None`
  (`split_history_missing`). A vendor that reports no splits is recorded as such (`split_basis`), not as proof.

`available_at` of a price is the session's close time from a **sourced** session calendar
(`research/calendars/nyse_sessions.csv`, columns date, close_et, source, source_retrieved_at). No sourced calendar
exists yet (compiling it needs a live read: owner decision U7), so in real use `available_at` is `None` with
`close_time_unverified`, while `session_date` is still recorded. Bar timestamps are not used as close times.

Every response is kept as raw bytes with its SHA-256, URL and `retrieved_at`; records point to it. Missing values
are `None` with a reason, never filled in (owner review point 5). Nothing here makes a network request.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

SCHEMA = "DataRecord"
SCHEMA_VERSION = "contracts-0.1"
METHOD_VERSION = "price-provenance-0.1"
SOURCE = "yahoo chart v8 (unofficial; not licensed for redistribution)"
LIMITATIONS = (
    "Survivorship: Yahoo has no prices for most delisted companies, so any universe built from it is biased.",
    "Vendor revisions: Yahoo rewrites close and adjclose after splits and dividends; values are as retrieved.",
    "Licence: Yahoo data is unofficial and not redistributable; raw files stay in the project folder.",
    "available_at is null until a sourced session calendar (with early closes) exists.",
)
ADJUSTMENT_TOL = 1e-6


class PriceError(ValueError):
    pass


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_sessions(path) -> dict[str, dict]:
    """Sourced session calendar: {date: {'close_et': 'HH:MM', 'source', 'source_retrieved_at'}}. Rows without a
    source are refused rather than trusted."""
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("source") or not row.get("source_retrieved_at"):
                raise PriceError(f"calendar row {row.get('date')} has no source")
            if row["close_et"] not in ("16:00", "13:00"):
                raise PriceError(f"calendar row {row['date']}: unexpected close {row['close_et']}")
            out[row["date"]] = row
    return out


def close_available_at(session_date: str, sessions: dict | None, tz: ZoneInfo) -> tuple[str | None, str | None]:
    if not sessions or session_date not in sessions:
        return None, "close_time_unverified"
    hh, mm = map(int, sessions[session_date]["close_et"].split(":"))
    d = datetime.fromisoformat(session_date).replace(hour=hh, minute=mm, tzinfo=tz)
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), None


def requested_split_events(url: str) -> bool:
    q = parse_qs(urlparse(url).query)
    return any("split" in v for vals in q.get("events", []) for v in vals.split("|"))


def parse_chart(body: bytes, *, symbol: str, url: str, retrieved_at: str, sessions: dict | None = None) -> dict:
    """{'raw': {...}, 'records': [...], 'splits': [...], 'limitations': [...]} from one chart response."""
    res = (json.loads(body).get("chart", {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise PriceError(f"{symbol}: no chart result")
    meta = res.get("meta", {})
    tzname = meta.get("exchangeTimezoneName")
    if not tzname:
        raise PriceError(f"{symbol}: exchange time zone missing; session dates would be guesses")
    tz = ZoneInfo(tzname)
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    adj_block = res.get("indicators", {}).get("adjclose")
    adjs = (adj_block or [{}])[0].get("adjclose") if adj_block else None

    asked_splits = requested_split_events(url)
    splits = sorted(
        ({"date": datetime.fromtimestamp(int(s["date"]), tz).date().isoformat(),
          "numerator": float(s["numerator"]), "denominator": float(s["denominator"])}
         for s in (res.get("events", {}).get("splits") or {}).values()),
        key=lambda s: s["date"])
    split_basis = ("vendor_reported" if splits else "vendor_reported_none") if asked_splits else "not_requested"

    raw = {"url": url, "sha256": sha256(body), "retrieved_at": retrieved_at, "symbol": symbol, "source": SOURCE}
    records, seen = [], set()
    for i, ts in enumerate(res["timestamp"]):
        session = datetime.fromtimestamp(int(ts), tz).date().isoformat()
        if session in seen:
            raise PriceError(f"{symbol}: two bars for {session}")
        seen.add(session)
        reasons = []
        close = closes[i] if i < len(closes) else None
        adj = adjs[i] if adjs is not None and i < len(adjs) else None
        if close is None:
            reasons.append("close_missing")
        if adjs is None:
            reasons.append("adjclose_not_in_response")
        elif adj is None:
            reasons.append("adjclose_missing")
        if not asked_splits:
            unadj = None
            reasons.append("split_history_missing")
        elif close is None:
            unadj = None
        else:
            factor = 1.0
            for s in splits:
                if s["date"] > session:
                    factor *= s["numerator"] / s["denominator"]
            unadj = close * factor
        avail, why = close_available_at(session, sessions, tz)
        if why:
            reasons.append(why)
        rec = {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "kind": "daily_price", "symbol": symbol,
            "session_date": session, "close": close, "adjclose": adj, "close_unadjusted": unadj,
            "price_kinds": {"close": "split_adjusted_as_retrieved", "adjclose": "total_return_as_retrieved",
                            "close_unadjusted": "decision_unadjusted"},
            "split_basis": split_basis, "currency": meta.get("currency"),
            "available_at": avail, "available_at_basis": "exchange_close_from_sourced_calendar",
            "missing_reasons": sorted(set(reasons)),
            "source": {"raw_sha256": raw["sha256"], "url": url},
        }
        rec["record_id"] = sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode())
        rec["source"]["retrieved_at"] = retrieved_at
        rec["writer"] = {"component": "research.price_provenance", "method_version": METHOD_VERSION}
        records.append(rec)
    return {"raw": raw, "records": records, "splits": splits, "split_basis": split_basis,
            "limitations": list(LIMITATIONS)}


def store_raw(body: bytes, root) -> Path:
    """Write the response once under root/raw/<sha256>; identical bytes are not written again."""
    p = Path(root) / "raw" / sha256(body)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(p)
    elif sha256(p.read_bytes()) != p.name:
        raise PriceError(f"stored raw file {p.name} is corrupt")
    return p
