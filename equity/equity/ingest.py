"""Fetch SEC fundamentals for a company and store a snapshot only when it changed."""
from __future__ import annotations

from datetime import date

from .fundamentals import METHODS, analyse
from .sec import FACTS_URL, SecClient
from .store import Store, content_hash, utc_now


def latest_securities(store: Store) -> dict[str, dict]:
    """t212_ticker -> latest version of each listing (absent ones included, flagged)."""
    latest: dict[str, dict] = {}
    for r in store.securities.read():
        latest[r["t212_ticker"]] = r
    return latest


def resolve(store: Store, symbol: str | None = None, company_id: str | None = None,
            isin: str | None = None) -> dict | None:
    """Find a present security by symbol, ISIN or company id (symbols are not unique
    across exchanges, so a US SEC-linked line is preferred for a bare symbol)."""
    secs = [s for s in latest_securities(store).values() if not s.get("absent")]
    if isin:
        hits = [s for s in secs if s["isin"] == isin]
    elif company_id:
        hits = [s for s in secs if s["company_id"] == company_id]
    else:
        hits = [s for s in secs if s["symbol"] == symbol.upper()]
    hits.sort(key=lambda s: (s.get("sec_match") != "high", s["t212_ticker"]))
    return hits[0] if hits else None


def last_snapshot(store: Store, company_id: str) -> dict | None:
    snaps = [s for s in store.fundamentals.read() if s["company_id"] == company_id]
    return max(snaps, key=lambda s: s["retrieved_utc"]) if snaps else None


def ingest_company(store: Store, sec: SecClient, security: dict, today: date | None = None,
                   max_age_s: float = 86400) -> tuple[dict, bool]:
    """Returns (snapshot, written). written=False when nothing changed since the last snapshot."""
    if security.get("sec_match") != "high" or not security.get("cik"):
        raise ValueError(f"{security['symbol']}: no verified SEC link (sec_match={security.get('sec_match')})")
    facts = sec.company_facts(security["cik"], max_age_s=max_age_s)
    a = analyse(facts, today)
    # The snapshot identity is the filed data plus the method version, not the fetch time,
    # so re-fetching unchanged filings writes nothing.
    input_hash = content_hash({"years": a["years"], "method": a["method_version"]})
    prev = last_snapshot(store, security["company_id"])
    if prev and prev["input_hash"] == input_hash:
        return prev, False
    snap = {
        "rid": f"{security['company_id']}:{input_hash}",
        "company_id": security["company_id"], "cik": security["cik"], "entity_name": a["entity_name"],
        "source": "SEC EDGAR XBRL companyfacts (us-gaap, annual forms)",
        "source_url": FACTS_URL.format(cik=int(security["cik"])),
        "retrieved_utc": utc_now(), "input_hash": input_hash, "method_version": a["method_version"],
        "reporting_currency": a["reporting_currency"], "value_types": {
            "years": "reported (XBRL as filed; 'orig' = first filed value, 'v' = latest filed)",
            "derived": "calculated (see methods)", "summary": "calculated"},
        "methods": METHODS,
        "summary": a["summary"], "flags": a["flags"], "confidence": a["confidence"],
        "years": a["years"], "derived": a["derived"],
        "previous_snapshot": prev["rid"] if prev else None,
    }
    store.fundamentals.append(snap)
    return snap, True
