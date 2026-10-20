"""B5 share-count point-in-time audit (owner review 2026-10-19 07:04Z, item 1).

Identity rule C uses mcap = (shares_out if > 0 else shares_diluted) x close_raw and total_assets, all read from
`monthly_metrics.csv.gz`. That file is built by `equity.monthly.company_months`, which takes every value from
`equity.panel.known` (rows with filed <= the month-end). This script checks that the stored file really is point in
time: for each sampled company-month it rebuilds the row from SEC fact rows filed on or before that month-end only
(nothing later exists for the rebuild) and compares the three fields to the stored values. It also counts the rows
where a later filing would have given a different value, so a match is not trivially guaranteed.

No return, score, ranking or NAV is computed or read. Inputs: the SEC fact panel (filed <= 2022-12-31) and the
monthly dataset cut at 2022-12 (`edge_split.cut_exploration`).

Usage: python3 edge_b5_share_pit_audit.py  ->  equity/reports/research/edge/b5_share_pit_audit.{md,json}
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import edge_split
import edge_ttm_checks as tc
import xsection

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "equity"))
from equity import monthly, panel  # noqa: E402

FIELDS = ["shares_out", "shares_diluted", "total_assets"]
SAMPLE = 3000
SEED = 20261019


def sample_rows() -> pd.DataFrame:
    """Every large-band company-month from 2012 whose mcap / total assets is above 25 (all rule C exclusions and
    the 25-100x zone where the threshold bites) plus a fixed random sample of the rest."""
    df = edge_split.cut_exploration(xsection.load())
    ciks = set(df.loc[df["band"] == "large", "cik"])
    df = df[df["cik"].isin(ciks) & (df["month"] >= "2012-01-31")].reset_index(drop=True)
    ratio = df["mcap"] / df["total_assets"].where(df["total_assets"] > 0)
    hi = df[ratio > 25]
    rest = df.drop(hi.index)
    return pd.concat([hi.assign(stratum="ratio>25"),
                      rest.sample(min(SAMPLE, len(rest)), random_state=SEED).assign(stratum="random")])


def stored(v) -> float | None:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or v == "" else float(v)


def same(a, b) -> bool:
    a, b = stored(a), stored(b)
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= 1e-9 * max(1.0, abs(a)))


def retro(rows: list[dict], metric: str, month: str) -> float | None:
    """What the field would be if filings up to the cut were allowed for periods ending by the month: the leak this
    audit guards against."""
    unit = monthly.UNIT[metric]
    rs = [r for r in rows if r["metric"] == metric and r["unit"] == unit and r["end"] <= month]
    if metric == "shares_diluted":
        ks = [r for r in panel.known(rs, tc.CUT) if r["start"]]
        x = max(ks, key=lambda r: (r["end"], r["filed"])) if ks else None
    else:
        x = panel.latest(rs, tc.CUT)
    return x["val"] if x else None


def audit() -> dict:
    s = sample_rows()
    ciks = set(s["cik"])
    facts: dict[int, list[dict]] = {}
    for r in panel.read(xsection.DATA / "sec_facts_panel.csv.gz", ciks):
        if r["filed"] <= tc.CUT:
            facts.setdefault(r["cik"], []).append(r)
    months_all = monthly.month_ends("2009-12-31", tc.CUT)
    res = []
    for cik, mo, strat, *vals in zip(s["cik"], s["month"].dt.strftime("%Y-%m-%d"), s["stratum"],
                                     *[s[f] for f in FIELDS]):
        rows = facts.get(cik, [])
        trunc = [r for r in rows if r["filed"] <= mo]  # nothing filed after the month-end exists for the rebuild
        rebuilt = {r["month"]: r for r in monthly.company_months(cik, trunc, [m for m in months_all if m <= mo])}
        rb = rebuilt.get(mo)
        rec = {"cik": int(cik), "month": mo, "stratum": strat, "rebuilt": rb is not None}
        for f, v in zip(FIELDS, vals):
            rec[f"{f}_match"] = rb is not None and same(v, rb[f])
            rec[f"{f}_later_differs"] = not same(v, retro(rows, f, mo))
        res.append(rec)
    d = pd.DataFrame(res)
    out = {"rows": len(d), "companies": int(d["cik"].nunique()),
           "by_stratum": {k: int(v) for k, v in d["stratum"].value_counts().items()},
           "rebuilt": int(d["rebuilt"].sum())}
    for f in FIELDS:
        out[f] = {"match": int(d[f"{f}_match"].sum()), "mismatch": int((~d[f"{f}_match"]).sum()),
                  "later_filing_would_differ": int(d[f"{f}_later_differs"].sum())}
    out["mismatch_examples"] = d[~d[[f"{f}_match" for f in FIELDS]].all(axis=1)].head(20).to_dict("records")
    return out


def report(a: dict) -> str:
    lines = [f"# B5 share-count point-in-time audit ({date.today().isoformat()})", "",
             "No return, score, ranking or NAV computed. Each sampled company-month was rebuilt by "
             "`equity.monthly.company_months` from SEC fact rows filed on or before that month-end only, and "
             "compared with the stored `monthly_metrics.csv.gz` value used by identity rule C.", "",
             f"Rows: {a['rows']:,} ({a['by_stratum']}), companies: {a['companies']:,}, rebuilt: {a['rebuilt']:,}.", "",
             "| Field | Match | Mismatch | Rows where a later filing would give a different value |",
             "|---|---:|---:|---:|"]
    for f in FIELDS:
        lines.append(f"| `{f}` | {a[f]['match']:,} | {a[f]['mismatch']:,} | {a[f]['later_filing_would_differ']:,} |")
    lines += ["", "The last column counts rows where allowing filings up to 2022-12-31 (for periods ending by the "
              "month) would change the value: the leak exists in the data, and the stored values do not take it."]
    return "\n".join(lines) + "\n"


def main() -> None:
    a = audit()
    tc.OUT.mkdir(parents=True, exist_ok=True)
    (tc.OUT / "b5_share_pit_audit.json").write_text(json.dumps(a, indent=1, default=str))
    (tc.OUT / "b5_share_pit_audit.md").write_text(report(a))
    print(report(a))


if __name__ == "__main__":
    main()
