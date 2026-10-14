"""Security master: Trading 212's tradable stocks, keyed by ISIN, linked to SEC issuers.

Identifiers
* A row is one *listing*, keyed by T212's ticker id (`t212_ticker`). That id is T212's
  internal key and survives renames (BRKS_US_EQ now trades as AZTA), so it is stable,
  but it is NOT the market symbol: the symbol comes from `shortName`.
* ISIN identifies the security (T212 supplies it for 100% of instruments). One ISIN can
  have several listings (Stantec: STN_CA_EQ in CAD and STN_US_EQ in USD), so ISIN alone
  cannot be the row key.
* A company (issuer) is keyed `SEC:<cik>` when it files with the SEC, otherwise
  `ISIN:<isin>` until a better issuer identifier is available. Several share classes
  (GOOGL/GOOG, BRK.A/BRK.B) map to one company.

Matching T212 -> SEC is by symbol on US lines, then checked by company name.
`match` = "high" (symbol + name agree), "low" (symbol only: needs review) or None.
Low-confidence links are recorded but never used for fundamentals without review.
"""
from __future__ import annotations

import re
from collections import Counter

from .store import Store, content_hash, utc_now

_STOP = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "holdings",
         "holding", "group", "the", "class", "sa", "nv", "ag", "se", "adr", "ads", "new", "de", "a", "b", "c",
         "and", "of", "trust", "lp", "llc", "international", "intl", "technologies", "technology"}


def _tokens(name: str) -> list[str]:
    name = re.sub(r"['’`]", "", (name or "").lower())  # "Lowe's" -> "lowes", matching SEC's "LOWES"
    words = re.sub(r"[^a-z0-9 ]", " ", name).split()
    return list(dict.fromkeys(w for w in words if w not in _STOP and len(w) > 1))


def name_match(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if len(set(ta) & set(tb)) / min(len(ta), len(tb)) >= 0.5:
        return True
    # Spacing differences: "RealReal" vs "TheRealReal", "Car-Mart" vs "CARMART".
    ca, cb = "".join(ta), "".join(tb)
    return len(min(ca, cb, key=len)) >= 5 and (ca in cb or cb in ca)


def market_symbol(inst: dict) -> str:
    return (inst.get("shortName") or inst["ticker"].split("_")[0]).upper()


def build_security_master(instruments: list[dict], sec_tickers: list[dict]) -> tuple[list[dict], dict]:
    """Returns (security rows, coverage summary). Pure function: no I/O."""
    by_symbol: dict[str, list[dict]] = {}
    for t in sec_tickers:
        if t.get("ticker"):
            by_symbol.setdefault(t["ticker"].upper(), []).append(t)

    rows, excluded = [], Counter()
    for inst in instruments:
        if inst.get("type") != "STOCK":
            excluded[inst.get("type") or "unknown"] += 1
            continue
        if not inst.get("isin"):
            excluded["STOCK without ISIN"] += 1
            continue
        sym = market_symbol(inst)
        us_line = inst["ticker"].endswith("_US_EQ") or inst.get("currencyCode") == "USD"
        cik, match, sec_name, sec_exchange = None, None, None, None
        if us_line:
            for cand_sym in (sym, sym.replace(".", "-"), sym.replace("/", "-")):
                cands = by_symbol.get(cand_sym)
                if cands:
                    c = cands[0]
                    cik, sec_name, sec_exchange = int(c["cik"]), c["name"], c.get("exchange")
                    match = "high" if name_match(inst.get("name", ""), c["name"]) else "low"
                    break
        row = {
            "isin": inst["isin"], "t212_ticker": inst["ticker"], "symbol": sym,
            "name": inst.get("name"), "currency": inst.get("currencyCode"),
            "isin_country": inst["isin"][:2], "t212_added_on": inst.get("addedOn"),
            "cik": cik, "sec_name": sec_name, "sec_exchange": sec_exchange, "sec_match": match,
        }
        rows.append(row)

    # All listings of one ISIN are one security of one company: share the verified SEC link.
    best: dict[str, dict] = {}
    for r in rows:
        if r["sec_match"] == "high":
            best.setdefault(r["isin"], r)
    for r in rows:
        b = best.get(r["isin"])
        r["company_id"] = f"SEC:{b['cik']}" if b else f"ISIN:{r['isin']}"
        if b and r["sec_match"] != "high":
            r["sec_link_via"] = b["t212_ticker"]

    matched = Counter(r["sec_match"] for r in rows)
    summary = {
        "instruments_total": len(instruments),
        "stocks_in_master": len(rows),
        "unique_isins": len({r["isin"] for r in rows}),
        "companies": len({r["company_id"] for r in rows}),
        "excluded_by_type": dict(excluded),
        "stocks_by_currency": dict(Counter(r["currency"] for r in rows).most_common()),
        "sec_linked_high": matched.get("high", 0),
        "sec_linked_low_needs_review": matched.get("low", 0),
        "companies_with_sec_fundamentals": len({r["company_id"] for r in rows if r["company_id"].startswith("SEC:")}),
        "companies_without_fundamentals_source": len({r["company_id"] for r in rows if r["company_id"].startswith("ISIN:")}),
    }
    return rows, summary


def sync_security_master(store: Store, instruments: list[dict], sec_tickers: list[dict],
                         source: str = "trading212 demo /equity/metadata/instruments + SEC company_tickers_exchange") -> dict:
    """Append changed security versions and a scan record. Unchanged securities write nothing."""
    rows, summary = build_security_master(instruments, sec_tickers)
    latest = {}
    for r in store.securities.read():
        latest[r["t212_ticker"]] = r
    now = utc_now()
    new_records, changed, added = [], 0, 0
    current = set()
    for row in rows:
        current.add(row["t212_ticker"])
        h = content_hash(row)
        prev = latest.get(row["t212_ticker"])
        if prev and prev.get("hash") == h and not prev.get("absent"):
            continue
        if prev:
            changed += 1
        else:
            added += 1
        # Chain the rid to the previous version so A -> B -> A (or absent -> back) is
        # recorded, while re-running the same sync from the same state stays a no-op.
        rid = f"{row['t212_ticker']}:{h}:{content_hash(prev['rid'] if prev else '')[:8]}"
        new_records.append({"rid": rid, "hash": h, "observed_utc": now, **row})
    removed = []
    for listing, prev in latest.items():
        if listing not in current and not prev.get("absent"):
            removed.append(listing)
            new_records.append({"rid": f"{listing}:absent:{now}", "t212_ticker": listing, "absent": True,
                                "observed_utc": now, "note": "no longer in Trading 212 instrument list "
                                "(delisting, corporate action or T212 removal; check before treating as delisted)",
                                **{k: prev.get(k) for k in ("isin", "symbol", "name", "company_id", "cik")}})
    store.securities.append(new_records)
    scan = {"rid": f"universe:{now}", "kind": "universe_sync", "ts_utc": now, "source": source,
            "added": added, "changed": changed, "removed": len(removed), **summary,
            "limitations": [
                "Universe = stocks tradable on Trading 212 only, not the whole global market.",
                "Fundamentals source in this milestone: SEC XBRL (US GAAP filers). Non-SEC issuers have no fundamentals yet.",
                "Symbol-only SEC matches (sec_match=low) are excluded from fundamentals until reviewed.",
            ]}
    store.scans.append(scan)
    return scan
