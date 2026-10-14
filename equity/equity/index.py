"""Searchable SQLite index, rebuilt from the JSONL ledgers (which stay the source of truth).

The index file lives in equity/cache/ (gitignored) and can be deleted at any time.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .ingest import latest_securities
from .pipeline import all_statuses
from .store import Store

INDEX_PATH = Path(__file__).resolve().parent.parent / "cache" / "index.sqlite"

SUMMARY_COLS = ["revenue", "fcf_per_share", "fcf_per_share_cagr_5y", "revenue_cagr_5y", "revenue_growth_yoy",
                "gross_margin", "operating_margin", "fcf_margin", "roic", "roic_avg_5y", "net_debt_to_ebitda",
                "sbc_pct_revenue", "share_change_cagr_3y", "latest_fy_end", "latest_filed"]


def _listing_rank(s: dict) -> tuple:
    """Primary listing: the SEC-verified line, then home-market currencies, then T212 id."""
    cur = {"USD": 0, "GBX": 1, "GBP": 1, "EUR": 2}.get(s.get("currency"), 3)
    return (s.get("sec_match") != "high", cur, s["t212_ticker"])


def build(store: Store, path: Path = INDEX_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.execute("""CREATE TABLE securities (t212_ticker TEXT PRIMARY KEY, symbol TEXT, isin TEXT, name TEXT,
                  currency TEXT, isin_country TEXT, company_id TEXT, cik INTEGER, sec_match TEXT, absent INTEGER)""")
    db.execute(f"""CREATE TABLE companies (company_id TEXT PRIMARY KEY, symbol TEXT, primary_listing TEXT,
                  name TEXT, status TEXT, confidence TEXT, taxonomy TEXT, reporting_currency TEXT, sic TEXT,
                  industry_template TEXT, screen_supported INTEGER,
                  flags TEXT, snapshot_rid TEXT, {', '.join(c + ' ' + ('TEXT' if c.startswith('latest') else 'REAL')
                                                            for c in SUMMARY_COLS)})""")
    db.execute("""CREATE TABLE transitions (company_id TEXT, seq INTEGER, ts_utc TEXT, from_status TEXT,
                  to_status TEXT, reason TEXT, evidence TEXT, actor TEXT)""")
    secs = latest_securities(store)
    db.executemany("INSERT INTO securities VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (s["t212_ticker"], s.get("symbol"), s.get("isin"), s.get("name"), s.get("currency"), s.get("isin_country"),
         s.get("company_id"), s.get("cik"), s.get("sec_match"), int(bool(s.get("absent")))) for s in secs.values()])
    statuses = all_statuses(store)
    snaps: dict[str, dict] = {}
    for s in store.fundamentals.read():
        if s["company_id"] not in snaps or s["retrieved_utc"] > snaps[s["company_id"]]["retrieved_utc"]:
            snaps[s["company_id"]] = s
    primary: dict[str, dict] = {}
    for s in secs.values():
        if not s.get("absent") and (s["company_id"] not in primary or
                                    _listing_rank(s) < _listing_rank(primary[s["company_id"]])):
            primary[s["company_id"]] = s
    names = {cid: s.get("name") for cid, s in primary.items()}
    for c in store.companies.read():
        names.setdefault(c["company_id"], c.get("name"))
    for cid in set(statuses) | set(snaps):
        sn = snaps.get(cid, {})
        summ = sn.get("summary", {})
        pl = primary.get(cid, {})
        db.execute(f"INSERT INTO companies VALUES ({','.join('?' * (13 + len(SUMMARY_COLS)))})",
                   [cid, pl.get("symbol"), pl.get("t212_ticker"), sn.get("entity_name") or names.get(cid),
                    statuses.get(cid), sn.get("confidence"),
                    sn.get("taxonomy", "us-gaap") if sn else None, sn.get("reporting_currency"), sn.get("sic"),
                    sn.get("industry_template"), None if sn.get("screen_supported") is None else int(sn["screen_supported"]),
                    json.dumps(sn.get("flags", [])), sn.get("rid")] + [summ.get(c) for c in SUMMARY_COLS])
    db.executemany("INSERT INTO transitions VALUES (?,?,?,?,?,?,?,?)", [
        (t["company_id"], t["seq"], t["ts_utc"], t["from"], t["to"], t["reason"], json.dumps(t["evidence"]),
         t["actor"]) for t in store.transitions.read()])
    db.execute("CREATE INDEX sec_sym ON securities(symbol)")
    db.execute("CREATE INDEX sec_cid ON securities(company_id)")
    db.commit()
    db.close()
    tmp.replace(path)
    return path
