"""Insider open-market trades from SEC's Form 3/4/5 quarterly data sets (STRATEGY_V2 signal S7).

SEC publishes every Form 4 as tab-separated tables, one zip per quarter, from 2006:
https://www.sec.gov/dera/data/form-345. This keeps only open-market purchases (code P) and sales (code S) of
non-derivative securities on Form 4, by officers and directors, dated by the **filing** date, which is when
the market could know about the trade.
"""
from __future__ import annotations

import csv
import gzip
import io
import zipfile
from datetime import datetime
from pathlib import Path

URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip"
FIELDS = ["issuer_cik", "filed", "owner_cik", "code", "shares", "price"]


def quarters(first: str, last: str) -> list[str]:
    y, q = int(first[:4]), int(first[-1])
    out = []
    while f"{y}q{q}" <= last:
        out.append(f"{y}q{q}")
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def _date(s: str) -> str:
    return datetime.strptime(s.strip(), "%d-%b-%Y").date().isoformat() if s.strip() else ""


def _tsv(z: zipfile.ZipFile, name: str):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t",
                                  quoting=csv.QUOTE_NONE)


def parse_quarter(data: bytes) -> list[dict]:
    """Officer/director open-market purchases and sales from one quarterly zip."""
    z = zipfile.ZipFile(io.BytesIO(data))
    subs = {}
    for r in _tsv(z, "SUBMISSION.tsv"):
        if r["DOCUMENT_TYPE"].strip() in ("4", "4/A"):
            subs[r["ACCESSION_NUMBER"]] = (int(r["ISSUERCIK"]), _date(r["FILING_DATE"]))
    owner = {}
    for r in _tsv(z, "REPORTINGOWNER.tsv"):
        a = r["ACCESSION_NUMBER"]
        rel = r["RPTOWNER_RELATIONSHIP"] or ""
        if a in subs and a not in owner and ("Officer" in rel or "Director" in rel):
            owner[a] = int(r["RPTOWNERCIK"])
    out = []
    for r in _tsv(z, "NONDERIV_TRANS.tsv"):
        a = r["ACCESSION_NUMBER"]
        code = (r["TRANS_CODE"] or "").strip()
        if a not in owner or code not in ("P", "S"):
            continue
        try:
            shares = float(r["TRANS_SHARES"] or 0)
            price = float(r["TRANS_PRICEPERSHARE"] or 0)
        except ValueError:
            continue
        issuer, filed = subs[a]
        out.append({"issuer_cik": issuer, "filed": filed, "owner_cik": owner[a], "code": code,
                    "shares": shares, "price": price})
    return out


def build(out_path: Path, first: str, last: str, get, log=print) -> dict:
    """Fetch quarters first..last (e.g. 2014q1..2022q4) into one gzip CSV."""
    stats = {"quarters": 0, "trades": 0}
    with gzip.open(out_path, "wt", newline="") as gz:
        w = csv.DictWriter(gz, fieldnames=FIELDS)
        w.writeheader()
        qs = quarters(first, last)
        for i, q in enumerate(qs):
            try:
                body = get(URL.format(q=q))
            except Exception:  # noqa: BLE001 - SEC publishes a quarter some weeks after it ends
                if i >= len(qs) - 2:
                    stats["missing_recent"] = q
                    break
                raise
            rows = parse_quarter(body)
            w.writerows(rows)
            stats["quarters"] += 1
            stats["trades"] += len(rows)
            if log:
                log(f"{q}: {len(rows):,} trades")
    return stats
