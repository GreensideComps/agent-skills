"""Read-only integrity checks on the research dataset (edge-discovery Phase A).

Nothing here writes to the dataset or changes production code. It answers: is the data the programme will
explore on point-in-time, unique, plausible, and the same data the last run used? Each check returns PASS, WARN
(a known limitation that results must state) or FAIL (a defect to fix before trusting results).

Holdout discipline: return statistics are computed on months up to 2022-12 only. For 2023-01..2026-09 the checks
count rows (does the data exist for a later confirmation run) and never look at returns.

The manifest records each file's SHA-256, size, rows and month range. `monthly_signal_log.sh` rebuilds these
files with `--refresh` every month, so a result is only reproducible if its manifest is saved with it.

    RESEARCH_DATA=/path python3 edge_integrity.py [out.md]
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import edge_split
import xsection

FILES = ["sec_facts_panel.csv.gz", "sec_companies.csv.gz", "monthly_metrics.csv.gz", "prices_monthly.csv.gz",
         "insider_trades.csv.gz"]
MONTH_COL = {"monthly_metrics.csv.gz": "month", "prices_monthly.csv.gz": "month", "insider_trades.csv.gz": "filed"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(data: Path = xsection.DATA) -> dict:
    out = {}
    for name in FILES:
        p = data / name
        if not p.exists():
            out[name] = {"missing": True}
            continue
        with gzip.open(p, "rt") as f:
            rows = sum(1 for _ in f) - 1
        rec = {"sha256": sha256(p), "bytes": p.stat().st_size, "rows": rows,
               "modified_utc": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
        if name in MONTH_COL:
            s = pd.read_csv(p, usecols=[MONTH_COL[name]])[MONTH_COL[name]]
            rec["first"], rec["last"] = str(s.min()), str(s.max())
        out[name] = rec
    return out


def _r(check: str, ok: bool | None, detail: str, warn: bool = False, scope: str = "source") -> dict:
    """scope "source": a property of the data files (a FAIL is a defect in the data, which the programme may
    already neutralise). scope "programme": whether a defect can still reach a programme result (a FAIL here
    means results cannot be trusted)."""
    status = "PASS" if ok else ("WARN" if warn or ok is None else "FAIL")
    return {"check": check, "status": status, "detail": detail, "scope": scope}


def check_metrics(m: pd.DataFrame) -> list[dict]:
    out = []
    dup = int(m.duplicated(["cik", "month"]).sum())
    out.append(_r("metrics: one row per company-month", dup == 0, f"{dup:,} duplicate (cik, month) rows"))
    month = pd.to_datetime(m["month"])
    out.append(_r("metrics: months are month-ends", bool((month == month + pd.offsets.MonthEnd(0)).all()),
                  "every month value is a calendar month-end"))
    filed = pd.to_datetime(m["last_filed"], errors="coerce")
    late = int((filed > month).sum())
    out.append(_r("metrics: point in time (last filing on or before the month)", late == 0,
                  f"{late:,} rows use a filing dated after their month"))
    end = pd.to_datetime(m["ttm_end"], errors="coerce")
    fut = int((end > month).sum())
    out.append(_r("metrics: TTM period ends on or before the month", fut == 0,
                  f"{fut:,} rows ({m.loc[end > month, 'cik'].nunique()} companies) report a period ending after the "
                  "month, though filed before it: mis-tagged XBRL period dates, not look-ahead", warn=True))
    neg = int((m["shares_out"] < 0).sum())
    out.append(_r("metrics: no negative share counts", neg == 0, f"{neg:,} rows", warn=True))
    return out


# One definition of the programme's quality exclusions, in edge_split; re-exported for the checks below.
share_outliers = edge_split.share_outliers
quality_flags = edge_split.quality_flags


def check_universe(df: pd.DataFrame) -> list[dict]:
    """How much of the Stage 2 large-cap universe (2015-01..2022-11) the flags touch. Flags are computed on the
    frame cut at 2022-12, as exploration computes them; the full-dataset median is shown only to measure how much
    computing it on uncut data would have changed (that would use 2023-26 share counts)."""
    cut = df[df["month"] <= edge_split.EXPLORATION_LAST_OUTCOME]
    f = quality_flags(cut)
    leak = share_outliers(df).loc[cut.index] != f["share_outlier"]
    inv = xsection.investable(cut[(cut["month"] >= "2015-01-31") & (cut["month"] <= "2022-11-30")])
    big = inv[inv["band"] == "large"]
    fl = f.loc[big.index]
    so, bp = int(fl["share_outlier"].sum()), int(fl["bad_price"].sum())
    nl = int(leak[cut["band"].notna()].sum())
    return [
        _r("programme: quality flags computed without 2023-26 data", True, scope="programme", detail=
           (f"flags use the share-count median of 2022-12 and earlier only. Computed on the whole dataset, {nl:,} "
           "banded company-months up to 2022-12 would have been flagged differently; the Phase A draft did that "
           "in its report, fixed on 2026-10-14 (exploration never used the exclusion before the fix).")),
        _r("universe: share-count outliers in the large band (2015-01..2022-11)", so == 0,
           f"{so:,} of {len(big):,} large-cap company-months ({big.loc[fl['share_outlier'], 'cik'].nunique()} companies) "
           "have a share count over 10x or under 1/10 of the company's median, e.g. 1.9e14 shares. Most are XBRL "
           "scaling errors that inflate market cap and put a small company in the large band.", warn=True),
        _r("universe: negative adjusted prices in the large band (2015-01..2022-11)", bp == 0,
           f"{bp:,} large-cap company-months have an adjusted close <= 0 (a Yahoo adjustment error: NFE's adjusted "
           "close is negative from 2019-01 to 2022-12). Stage 2 included them unchanged. Programme exposure: see "
           "the programme checks."),
    ]


def check_prices(p: pd.DataFrame, as_of=None) -> list[dict]:
    out = []
    usd = p[p["currency"] == "USD"]
    dup = int(usd.duplicated(["cik", "month"]).sum())
    out.append(_r("prices: one USD row per company-month", dup == 0, f"{dup:,} duplicates (xsection.load keeps the last)",
                  warn=True))
    tick = p.groupby("cik")["ticker"].nunique()
    out.append(_r("prices: one ticker per company", None,
                  f"{len(tick):,} companies priced, {int((tick > 1).sum()):,} with more than one ticker. Each company "
                  "is priced from the first ticker in today's SEC list (equity/monthly.py), so other share classes "
                  "are ignored and a ticker since reused by another company can be mis-linked.", warn=True))
    nonusd = float((p["currency"] != "USD").mean())
    out.append(_r("prices: non-USD rows excluded from tests", None, f"{nonusd:.1%} of price rows are not USD", warn=True))
    if as_of is not None:
        late = p[pd.to_datetime(p["month"]) > pd.Timestamp(as_of)]
        lab = ", ".join(sorted(late["month"].astype(str).unique()))
        out.append(_r("prices: no row labelled after the fetch date", late.empty,
                      f"{len(late):,} rows labelled {lab or '-'} in a file fetched {pd.Timestamp(as_of).date()}. The "
                      "builder labels the unfinished month with its month-end, so these rows hold the price on the "
                      "fetch date, not a month-end close. Not future data, but not a monthly return either: "
                      "`edge_split.complete_months` drops them. Exploration (to 2022-12) and the holdout (to "
                      "2026-09) never reach them; the signal log only scores a month once it has ended.",
                      warn=True))
    bad = int(((p["adjclose"] <= 0) | (p["close_raw"] <= 0)).sum())
    out.append(_r("prices: positive prices", bad == 0, f"{bad:,} rows with a price <= 0"))
    e = usd[pd.to_datetime(usd["month"]) <= edge_split.EXPLORATION_LAST_OUTCOME].sort_values(["cik", "month"])
    r = e.groupby("cik")["adjclose"].pct_change()
    big = int((r.abs() > 1.0).sum())
    out.append(_r("prices: monthly moves over 100% (to 2022-12)", None,
                  f"{big:,} of {r.notna().sum():,} monthly returns; largest {r.max():+.0%}, smallest {r.min():+.0%}. "
                  "Review before trusting small-cap results; large caps rarely move this much.", warn=True))
    return out


def check_companies(c: pd.DataFrame) -> list[dict]:
    return [_r("companies: SIC code is today's, not point in time", None,
               f"{c['sic'].notna().sum():,} companies have one SIC from today's SEC submissions. Sector-neutral "
               "signals and sector caps use today's industry, a mild look-ahead.", warn=True)]


def check_insiders(t: pd.DataFrame) -> list[dict]:
    last = pd.to_datetime(t["filed"]).max()
    ok = last >= edge_split.HOLDOUT_LAST_OUTCOME
    return [_r("insiders: Form 4 data covers the holdout", ok,
               f"filings {t['filed'].min()} to {t['filed'].max()}. A confirmation run of any insider signal needs "
               "2023-2026 quarters built first (`python -m equity research-data --step insiders`).", warn=True)]


def check_holdout_rows(m: pd.DataFrame, p: pd.DataFrame) -> list[dict]:
    """Counts only: does data exist for 2023-01..2026-09 (needed later), without reading any return."""
    def rows(df):
        mo = pd.to_datetime(df["month"])
        return int(((mo >= edge_split.HOLDOUT_FIRST_OUTCOME) & (mo <= edge_split.HOLDOUT_LAST_OUTCOME)).sum())
    a, b = rows(m), rows(p)
    return [_r("holdout: rows exist for a later confirmation run (counted, not read)", a > 0 and b > 0,
               f"{a:,} metric rows and {b:,} price rows in 2023-01..2026-09")]


def check_programme(df: pd.DataFrame, p: pd.DataFrame) -> list[dict]:
    """Can a non-positive price still reach a programme result? On exploration data only (to 2022-12)."""
    usd = p[(p["currency"] == "USD") & (pd.to_datetime(p["month"]) <= edge_split.EXPLORATION_LAST_OUTCOME)]
    usd = usd.sort_values(["cik", "month"]).drop_duplicates(["cik", "month"], keep="last").reset_index(drop=True)
    new = edge_split.forward_return(usd, 1)
    nxt = usd.groupby("cik")["adjclose"].shift(-1)
    gap = (pd.to_datetime(usd.groupby("cik")["month"].shift(-1)).dt.to_period("M")
           - pd.to_datetime(usd["month"]).dt.to_period("M"))
    consecutive = gap.map(lambda x: getattr(x, "n", None) == 1)
    invalid_end = consecutive & ((usd["adjclose"] <= 0) | (nxt <= 0))
    leaked = int((invalid_end & new.notna()).sum())
    cross = invalid_end & ((usd["adjclose"] > 0) != (nxt > 0))
    names = ", ".join(sorted(usd.loc[invalid_end, "ticker"].unique()))
    out = [_r("programme: no return starts or ends on a price <= 0", leaked == 0, scope="programme", detail=(
        f"{int(invalid_end.sum()):,} month-to-month returns to 2022-12 touch a price <= 0 ({names}); "
        f"{int(cross.sum())} of them cross the sign change and would be nonsense (a ratio of a positive and a negative price). "
        f"`edge_split.forward_return` treats such prices as missing: {leaked} reach a programme return."))]
    cut = df[df["month"] <= edge_split.EXPLORATION_LAST_OUTCOME]
    q = edge_split.quality_flags(cut)
    bad = cut["adjclose"].le(0) | cut["close_raw"].le(0)
    elig = int((bad & ~q.any(axis=1)).sum())
    lb = int((bad & cut["band"].eq("large")).sum())
    out.append(_r("programme: company-months with a price <= 0 are never eligible", elig == 0, scope="programme",
                  detail=f"{int(bad.sum()):,} such company-months to 2022-12 ({lb} in the large band) are flagged "
                         f"`bad_price`, so `quality_ok` is False; {elig} would be eligible. A holding whose next "
                         "price is invalid is treated as a missing price (`edge_rules.holding_return`)."))
    return out


def run(data: Path = xsection.DATA) -> dict:
    m = pd.read_csv(data / "monthly_metrics.csv.gz", usecols=["cik", "month", "last_filed", "ttm_end", "shares_out"])
    p = pd.read_csv(data / "prices_monthly.csv.gz")
    c = pd.read_csv(data / "sec_companies.csv.gz", dtype={"sic": str})
    t = pd.read_csv(data / "insider_trades.csv.gz", usecols=["filed"])
    fetched = datetime.fromtimestamp((data / "prices_monthly.csv.gz").stat().st_mtime, timezone.utc).date()
    df = xsection.load(data)
    checks = (check_metrics(m) + check_prices(p, fetched) + check_universe(df) + check_companies(c)
              + check_insiders(t) + check_holdout_rows(m, p) + check_programme(df, p))
    return {"manifest": manifest(data), "checks": checks}


def report(res: dict) -> str:
    L = ["# Research dataset integrity (edge-discovery Phase A)", "",
         "Read-only checks. FAIL = a defect to fix before trusting results; WARN = a known limitation results must "
         "state. Returns are inspected only up to 2022-12.", "",
         "Two kinds of check. **Source** checks describe the data files: a FAIL there is a defect in the data, which "
         "the programme may already neutralise. **Programme** checks ask whether a defect can still reach a "
         "programme result: a FAIL there means programme results cannot be trusted. The script exits 1 only on a "
         "programme FAIL.", "", "## Programme exposure", "", "| Check | Status | Detail |", "|---|---|---|"]
    L += [f"| {c['check']} | **{c['status']}** | {c['detail']} |" for c in res["checks"] if c.get("scope") == "programme"]
    L += ["", "## Source data", "", "| Check | Status | Detail |", "|---|---|---|"]
    L += [f"| {c['check']} | **{c['status']}** | {c['detail']} |" for c in res["checks"] if c.get("scope") != "programme"]
    L += ["", "## Manifest", "", "Results are reproducible only against these exact files; the monthly signal log "
          "rebuilds them.", "", "| File | Rows | Months | Modified (UTC) | SHA-256 (first 16) |", "|---|---:|---|---|---|"]
    for k, v in res["manifest"].items():
        if v.get("missing"):
            L.append(f"| {k} | missing | | | |")
            continue
        L.append(f"| {k} | {v['rows']:,} | {v.get('first', '')} to {v.get('last', '')} | {v.get('modified_utc', '')} | `{v['sha256'][:16]}` |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dataset_integrity.md")
    res = run()
    out.write_text(report(res))
    out.with_suffix(".json").write_text(json.dumps(res, indent=1, default=str))
    print(out.read_text())
    sys.exit(1 if any(c["status"] == "FAIL" and c.get("scope") == "programme" for c in res["checks"]) else 0)
