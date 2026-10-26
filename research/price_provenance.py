"""Daily-price provenance (mini fund Stage 2 §2, owner approval U2 of 2026-10-23).

Turns a stored Yahoo chart response into price records that say exactly what each number is:

* `close`      split-adjusted close **as retrieved** (Yahoo rewrites it after later splits);
* `adjclose`   split- and dividend-adjusted close **as retrieved** (a total-return series, for window returns only);
* `close_unadjusted`  the decision-time price: `close` times the ratio of every split after that session. It is
  computed only when the response was requested with split events and the vendor reported at least one split;
  otherwise it is `None` (`split_history_missing`, or `split_history_unverified` when the vendor reported none: an
  empty split list is not proof that there were none, review finding P33-1). Even when computed, the value is
  flagged `vendor_reported_unverified`: Yahoo's split list is not independently checked, so no consumer may treat
  it as decision-grade until a verified split source exists (a separate approval).

`available_at` of a price is the session's close time from a **sourced and approved** session calendar (columns
date, close_et, source, source_retrieved_at), identified by sha256 in `APPROVED_CALENDARS`. That list is empty
(compiling and approving a calendar is owner decision U7), so in real use `available_at` is `None` with
`close_time_unverified`, while `session_date` is still recorded. Bar timestamps are not used as close times; a bar
whose exchange-local time is outside 04:00-18:00 gets no session date at all (P33-2).

Holdout: a response is parsed or stored only if its URL has `period2` on or before 2023-01-01T00:00Z, and no bar may
fall after 2022-12-31 (P33-3).

Every response is kept as raw bytes with its SHA-256, URL and `retrieved_at`; records point to it. Missing values
are `None` with a reason, never filled in (owner review point 5). Nothing here makes a network request.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import edge_split

SCHEMA = "DataRecord"
SCHEMA_VERSION = "contracts-0.1"
METHOD_VERSION = "price-provenance-0.2"
SOURCE = "yahoo chart v8 (unofficial; not licensed for redistribution)"
LIMITATIONS = (
    "Survivorship: Yahoo has no prices for most delisted companies, so any universe built from it is biased.",
    "Vendor revisions: Yahoo rewrites close and adjclose after splits and dividends; values are as retrieved.",
    "Licence: Yahoo data is unofficial and not redistributable; raw files stay in the project folder.",
    "available_at is null until a sourced session calendar (with early closes) is approved.",
    "close_unadjusted relies on Yahoo's unverified split list and is not decision-grade.",
)
ADJUSTMENT_TOL = 1e-6
HOLDOUT_PERIOD2_MAX = 1672531200  # 2023-01-01T00:00:00Z
LAST_SESSION = "2022-12-31"
# bar times allowed in exchange-local hours [04:00, 18:00). A daily bar is stamped at or before the open; 00:00 UTC
# is 19:00 or 20:00 in New York, after every close, so the matrix's 20:00 bound would let it through (P33-2).
SESSION_HOURS = (4, 18)
# sha256 of session calendars the owner has approved (U7). Empty: no calendar is accepted yet.
APPROVED_CALENDARS: frozenset[str] = frozenset()


class PriceError(ValueError):
    pass


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_sessions(path, expected_sha256: str | None = None) -> dict[str, dict]:
    """Sourced session calendar: {date: {'close_et': 'HH:MM', 'source', 'source_retrieved_at', 'calendar_sha256'}}.
    The file's sha256 must equal `expected_sha256` and be in APPROVED_CALENDARS (P33-4). Rows without a source are
    refused rather than trusted."""
    body = Path(path).read_bytes()
    h = sha256(body)
    if expected_sha256 is None or h != expected_sha256:
        raise PriceError(f"calendar sha256 {h} does not match the expected {expected_sha256}")
    if h not in APPROVED_CALENDARS:
        raise PriceError(f"calendar {h} is not an approved calendar")
    out = {}
    for row in csv.DictReader(io.StringIO(body.decode())):
        if not row.get("source") or not row.get("source_retrieved_at"):
            raise PriceError(f"calendar row {row.get('date')} has no source")
        if row["close_et"] not in ("16:00", "13:00"):
            raise PriceError(f"calendar row {row['date']}: unexpected close {row['close_et']}")
        row["calendar_sha256"] = h
        out[row["date"]] = row
    return out


def close_available_at(session_date: str, sessions: dict | None, tz: ZoneInfo) -> tuple[str | None, str | None]:
    if not sessions or session_date not in sessions:
        return None, "close_time_unverified"
    hh, mm = map(int, sessions[session_date]["close_et"].split(":"))
    d = datetime.fromisoformat(session_date).replace(hour=hh, minute=mm, tzinfo=tz)
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), None


def assert_request_cut(url: str) -> None:
    """HoldoutViolation unless the request URL ends on or before 2023-01-01T00:00Z (`period2`)."""
    vals = parse_qs(urlparse(url).query).get("period2")
    try:
        p2 = int(vals[0]) if vals else None
    except ValueError:
        p2 = None
    if p2 is None or p2 > HOLDOUT_PERIOD2_MAX:
        raise edge_split.HoldoutViolation(f"request period2 {vals} is missing or after 2023-01-01: {url}")


def _in_session_hours(t: datetime) -> bool:
    return SESSION_HOURS[0] <= t.hour < SESSION_HOURS[1]


def requested_split_events(url: str) -> bool:
    q = parse_qs(urlparse(url).query)
    return any("split" in v for vals in q.get("events", []) for v in vals.split("|"))


def parse_chart(body: bytes, *, symbol: str, url: str, retrieved_at: str, sessions: dict | None = None) -> dict:
    """{'raw': {...}, 'records': [...], 'splits': [...], 'flags': [...], 'limitations': [...]} from one response."""
    assert_request_cut(url)
    res = (json.loads(body).get("chart", {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise PriceError(f"{symbol}: no chart result")
    meta = res.get("meta", {})
    tzname = meta.get("exchangeTimezoneName")
    if not tzname:
        raise PriceError(f"{symbol}: exchange time zone missing; session dates would be guesses")
    tz = ZoneInfo(tzname)
    bars = [datetime.fromtimestamp(int(ts), tz) for ts in res["timestamp"]]
    late = [t for t in bars if t.date().isoformat() > LAST_SESSION]
    if late:
        raise edge_split.HoldoutViolation(f"{symbol}: {len(late)} bars after {LAST_SESSION}")
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    adj_block = res.get("indicators", {}).get("adjclose")
    adjs = (adj_block or [{}])[0].get("adjclose") if adj_block else None

    asked_splits = requested_split_events(url)
    splits = []
    for sp in (res.get("events", {}).get("splits") or {}).values():
        t = datetime.fromtimestamp(int(sp["date"]), tz)
        splits.append({"date": t.date().isoformat(), "numerator": float(sp["numerator"]),
                       "denominator": float(sp["denominator"]), "time_verified": _in_session_hours(t)})
    splits.sort(key=lambda sp: sp["date"])
    split_basis = ("vendor_reported_unverified" if splits else "vendor_reported_none") if asked_splits \
        else "not_requested"
    # a split stamped outside session hours has an uncertain date, so every session up to it is affected
    unverified_through = max((sp["date"] for sp in splits if not sp["time_verified"]), default=None)
    cal_sha = next(iter(sessions.values())).get("calendar_sha256") if sessions else None

    raw = {"url": url, "sha256": sha256(body), "retrieved_at": retrieved_at, "symbol": symbol, "source": SOURCE}
    records, seen, flags = [], set(), set()
    for i, t in enumerate(bars):
        reasons = []
        if _in_session_hours(t):
            session = t.date().isoformat()
            if session in seen:
                raise PriceError(f"{symbol}: two bars for {session}")
            seen.add(session)
        else:
            session = None
            reasons.append("bar_time_outside_session")
            flags.add("bar_time_outside_session")
        close = closes[i] if i < len(closes) else None
        adj = adjs[i] if adjs is not None and i < len(adjs) else None
        if close is None:
            reasons.append("close_missing")
        if adjs is None:
            reasons.append("adjclose_not_in_response")
        elif adj is None:
            reasons.append("adjclose_missing")
        unadj = None
        if not asked_splits:
            reasons.append("split_history_missing")
        elif not splits:
            reasons.append("split_history_unverified")
        else:
            reasons.append("split_history_unverified")
            if session is None:
                pass
            elif unverified_through is not None and session <= unverified_through:
                reasons.append("split_date_unverified")
            elif close is not None:
                factor = 1.0
                for sp in splits:
                    if sp["date"] > session:
                        factor *= sp["numerator"] / sp["denominator"]
                unadj = close * factor
        if session is None:
            avail, why = None, "close_time_unverified"
        else:
            avail, why = close_available_at(session, sessions, tz)
        if why:
            reasons.append(why)
        rec = {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "kind": "daily_price", "symbol": symbol,
            "session_date": session, "bar_time": t.isoformat(), "close": close, "adjclose": adj,
            "close_unadjusted": unadj,
            "price_kinds": {"close": "split_adjusted_as_retrieved", "adjclose": "total_return_as_retrieved",
                            "close_unadjusted": "decision_unadjusted_unverified"},
            "split_basis": split_basis, "currency": meta.get("currency"),
            "available_at": avail, "available_at_basis": "exchange_close_from_sourced_calendar",
            "calendar_sha256": cal_sha,
            "missing_reasons": sorted(set(reasons)),
            "source": {"raw_sha256": raw["sha256"], "url": url},
        }
        rec["record_id"] = sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode())
        rec["source"]["retrieved_at"] = retrieved_at
        rec["writer"] = {"component": "research.price_provenance", "method_version": METHOD_VERSION}
        records.append(rec)
    return {"raw": raw, "records": records, "splits": splits, "split_basis": split_basis,
            "flags": sorted(flags), "limitations": list(LIMITATIONS)}


def store_raw(body: bytes, root, url: str) -> Path:
    """Write the response once under root/raw/<sha256>; identical bytes are not written again. The request URL must
    end before the holdout (P33-3), checked before anything is written."""
    assert_request_cut(url)
    p = Path(root) / "raw" / sha256(body)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(p)
    elif sha256(p.read_bytes()) != p.name:
        raise PriceError(f"stored raw file {p.name} is corrupt")
    return p
