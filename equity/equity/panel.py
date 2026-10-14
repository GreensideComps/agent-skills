"""Point-in-time research panel from SEC's bulk XBRL file (STRATEGY_V2, Stage 1).

The live database (`fundamentals.py`) keeps annual figures for companies listed on Trading 212 today.
Signal research needs more: quarterly figures, and **every** company that filed, including those that
later stopped (delisted, acquired, bankrupt), or the tests inherit survivorship bias.

`extract_company` turns one company's `companyfacts` JSON into compact fact rows. Each distinct value of
a (concept, period) is kept once, at the date it was **first filed**: an original figure and a later
restatement are two rows with two filing dates, so a test at any date sees only what was public then.

`ttm` and `latest` read those rows as of a date: trailing-twelve-month flows from the latest annual
figure plus the current year-to-date minus the prior year's matching year-to-date, and the latest
instant value. Nothing is estimated or filled.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import zipfile
from datetime import date
from pathlib import Path

from .fundamentals import ANNUAL_FORMS, CONCEPTS, IFRS_CONCEPTS

QUARTERLY_FORMS = {"10-Q", "10-Q/A"}
FORMS = ANNUAL_FORMS | QUARTERLY_FORMS
# Cover-page shares outstanding: the point-in-time share count for market cap.
DEI = {"shares_out": "EntityCommonStockSharesOutstanding"}
FIELDS = ["cik", "metric", "rank", "taxonomy", "concept", "unit", "start", "end", "val", "filed", "form", "fp", "accn"]


def _concept_index() -> dict[tuple[str, str], tuple[str, int]]:
    idx = {}
    for metric, (_, _, names) in CONCEPTS.items():
        for i, n in enumerate(names):
            idx[("us-gaap", n)] = (metric, i)
        for i, n in enumerate(IFRS_CONCEPTS[metric]):
            idx[("ifrs-full", n)] = (metric, i)
    for metric, n in DEI.items():
        idx[("dei", n)] = (metric, 0)
    return idx


INDEX = _concept_index()


def extract_company(facts: dict) -> list[dict]:
    """Fact rows for one company: each distinct (concept, unit, start, end, value) at its first filing."""
    cik = facts.get("cik")
    first: dict[tuple, dict] = {}
    for tax, concepts in (facts.get("facts") or {}).items():
        for name, c in concepts.items():
            hit = INDEX.get((tax, name))
            if not hit:
                continue
            metric, rank = hit
            for unit, vals in (c.get("units") or {}).items():
                for e in vals:
                    if e.get("form") not in FORMS or e.get("val") is None or not e.get("end") or not e.get("filed"):
                        continue
                    key = (tax, name, unit, e.get("start", ""), e["end"], e["val"])
                    if key not in first or e["filed"] < first[key]["filed"]:
                        first[key] = {"cik": cik, "metric": metric, "rank": rank, "taxonomy": tax, "concept": name,
                                      "unit": unit, "start": e.get("start", ""), "end": e["end"], "val": e["val"],
                                      "filed": e["filed"], "form": e["form"], "fp": e.get("fp") or "",
                                      "accn": e.get("accn") or ""}
    return sorted(first.values(), key=lambda r: (r["metric"], r["rank"], r["end"], r["start"], r["filed"]))


def build(zip_path: Path, out_path: Path, log=print, limit: int | None = None) -> dict:
    """Stream SEC's companyfacts.zip into one gzip CSV of fact rows. Returns counts."""
    stats = {"companies": 0, "with_rows": 0, "rows": 0, "bad_json": 0}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z, gzip.open(out_path, "wt", newline="") as gz:
        w = csv.DictWriter(gz, fieldnames=FIELDS)
        w.writeheader()
        names = [n for n in z.namelist() if n.endswith(".json")]
        for i, n in enumerate(names[:limit] if limit else names):
            stats["companies"] += 1
            try:
                facts = json.loads(z.read(n))
            except ValueError:
                stats["bad_json"] += 1
                continue
            if not facts.get("cik"):  # a few files leave the field empty; the file name carries it
                facts["cik"] = int(n[3:13])
            rows = extract_company(facts)
            if rows:
                stats["with_rows"] += 1
                stats["rows"] += len(rows)
                w.writerows(rows)
            if log and i % 2000 == 0:
                log(f"{i}/{len(names)} companies, {stats['rows']:,} rows")
    return stats


def read(path: Path, ciks: set[int] | None = None):
    """Iterate fact rows (values parsed) from a panel file, optionally for some companies only."""
    with gzip.open(path, "rt", newline="") as f:
        for r in csv.DictReader(f):
            cik = int(r["cik"])
            if ciks is not None and cik not in ciks:
                continue
            r["cik"], r["rank"], r["val"] = cik, int(r["rank"]), float(r["val"])
            yield r


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def known(rows: list[dict], as_of: str) -> list[dict]:
    """Rows public on `as_of`, keeping per (start, end) the best-ranked concept's latest filing."""
    best: dict[tuple, dict] = {}
    for r in rows:
        if r["filed"] > as_of:
            continue
        k = (r["start"], r["end"])
        b = best.get(k)
        if b is None or (r["rank"], b["filed"]) < (b["rank"], r["filed"]):
            best[k] = r
    return list(best.values())


def latest(rows: list[dict], as_of: str) -> dict | None:
    """Latest instant value public on `as_of` (balance-sheet items, shares outstanding)."""
    ks = [r for r in known(rows, as_of) if not r["start"]]
    return max(ks, key=lambda r: (r["end"], r["filed"])) if ks else None


def ttm(rows: list[dict], as_of: str) -> dict | None:
    """Trailing-twelve-month value of a flow metric public on `as_of`.

    TTM = latest fiscal year + current year-to-date - the prior year's year-to-date of the same length,
    when a year-to-date period ends after that fiscal year. Returns {val, end, filed, basis}.
    """
    ks = [r for r in known(rows, as_of) if r["start"]]
    years = [r for r in ks if 350 <= _days(r["start"], r["end"]) <= 380]
    if not years:
        return None
    fy = max(years, key=lambda r: r["end"])
    ytds = [r for r in ks if r["end"] > fy["end"] and 80 <= _days(r["start"], r["end"]) <= 290
            and abs(_days(fy["end"], r["start"])) <= 10]
    if ytds:
        cur = max(ytds, key=lambda r: r["end"])
        n = _days(cur["start"], cur["end"])
        prev = [r for r in ks if abs(_days(r["start"], r["end"]) - n) <= 10
                and abs(_days(r["end"], cur["end"]) - 365) <= 10]
        if prev:
            p = max(prev, key=lambda r: r["filed"])
            return {"val": fy["val"] + cur["val"] - p["val"], "end": cur["end"],
                    "filed": max(fy["filed"], cur["filed"], p["filed"]), "basis": "fy+ytd-prior_ytd"}
    return {"val": fy["val"], "end": fy["end"], "filed": fy["filed"], "basis": "fy"}


def by_company_metric(rows) -> dict[int, dict[str, list[dict]]]:
    out: dict[int, dict[str, list[dict]]] = {}
    for r in rows:
        out.setdefault(r["cik"], {}).setdefault(r["metric"], []).append(r)
    return out


def write_rows(rows: list[dict]) -> str:
    """CSV text for rows (test helper)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


COMPANY_FIELDS = ["cik", "name", "entity_type", "sic", "sic_description", "category", "fiscal_year_end", "tickers",
                  "exchanges", "former_names", "first_periodic", "last_periodic", "deregistered"]
PERIODIC = {"10-K", "10-Q", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A", "40-F/A"}
DEREGISTRATION = {"15-12B", "15-12G", "15-15D", "15F-12B", "15F-12G", "15F-15D"}


def company_record(sub: dict, older: list[dict] | None = None) -> dict:
    """One row per company from SEC submissions JSON (plus its older-filings pages, if any).

    Fields describe the company **today** (name, SIC, tickers, filer category), except the filing
    dates, which give when it started and stopped filing periodic reports and when it deregistered:
    the evidence for companies that left the market.
    """
    forms, dates = [], []
    for page in [sub.get("filings", {}).get("recent", {})] + list(older or []):
        forms += page.get("form", [])
        dates += page.get("filingDate", [])
    per = sorted(d for f, d in zip(forms, dates) if f in PERIODIC)
    dereg = sorted(d for f, d in zip(forms, dates) if f in DEREGISTRATION)
    return {"cik": int(sub["cik"]), "name": sub.get("name"), "entity_type": sub.get("entityType"),
            "sic": sub.get("sic") or "", "sic_description": sub.get("sicDescription") or "",
            "category": sub.get("category") or "", "fiscal_year_end": sub.get("fiscalYearEnd") or "",
            "tickers": "|".join(sub.get("tickers") or []), "exchanges": "|".join(x or "" for x in sub.get("exchanges") or []),
            "former_names": "|".join(f.get("name", "") for f in sub.get("formerNames") or []),
            "first_periodic": per[0] if per else "", "last_periodic": per[-1] if per else "",
            "deregistered": dereg[-1] if dereg else ""}


def build_companies(zip_path: Path, out_path: Path, ciks: set[int] | None = None, log=print) -> int:
    """Company table from SEC's submissions.zip, for `ciks` (all if None)."""
    n = 0
    with zipfile.ZipFile(zip_path) as z, gzip.open(out_path, "wt", newline="") as gz:
        names = set(z.namelist())
        w = csv.DictWriter(gz, fieldnames=COMPANY_FIELDS)
        w.writeheader()
        for name in sorted(x for x in names if x.endswith(".json") and "-submissions-" not in x):
            cik = int(name[3:13])
            if ciks is not None and cik not in ciks:
                continue
            sub = json.loads(z.read(name))
            older = [json.loads(z.read(f["name"])) for f in sub.get("filings", {}).get("files", []) if f["name"] in names]
            w.writerow(company_record(sub, older))
            n += 1
            if log and n % 5000 == 0:
                log(f"{n} companies")
    return n
