#!/usr/bin/env python3
"""Why the companies missing from the backtest price file left, and how much that can bias a backtest.

The price panel has almost none of the $1bn+ revenue companies that stopped filing with the SEC in 2013-2022
(survivorship_coverage.py: 3 of 1,484). A backtest therefore only ever holds survivors. Whether that flatters a result
depends on HOW the missing companies left:

  acquired     a takeover usually pays a premium, so leaving these out makes a backtest look WORSE than reality;
  distressed   bankruptcy or a performance delisting usually ends near zero, so leaving them out makes it look BETTER;
  other        going private by other routes, re-domiciling, a holding-company reorganisation, or unknown.

For each vanished company this reads its SEC filing history (data.sec.gov submissions, free, fair-access rate) and
classifies the exit from the filings near the end:

  distressed  any 8-K item 1.03 (bankruptcy or receivership), or a Form 15 / 25 within a year after an item 3.01
              (delisting notice) without a merger filing
  acquired    a merger proxy (DEFM14A, DEFM14C), a tender-offer response (SC 14D9), a going-private statement
              (SC 13E3), or an 8-K item 5.01 (change in control) or 2.01 filed in the last 18 months
  other       none of the above

Then it bounds the bias per year for an equal-weighted universe of the big companies:

  bias = share_distressed x (survivor return - distressed exit return)
       + share_acquired   x (survivor return - acquired exit return)

with the exit returns from the literature (Shumway 1997, Beaver-McNichols-Price 2007: performance delistings about
-30% to -100%; takeovers about +20 to +30% premium). A positive bias means survivor-only data flatters a long-only
strategy. Only presence and SEC metadata are read: no price, no data from 2023 on.

Run:  python3 research/always_on/exit_classes.py   (needs SEC_USER_AGENT; caches to research-data/sec_exits.json)
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA = Path(os.environ.get("RESEARCH_DATA", "/mnt/project-files/research-data"))
CACHE = DATA / "sec_exits.json"
MERGER_FORMS = {"DEFM14A", "DEFM14C", "SC 14D9", "SC 13E3", "PREM14A", "PREM14C", "SC TO-T", "S-4"}
DEREG_FORMS = {"15-12B", "15-12G", "15-15D", "25", "25-NSE"}
# literature exit returns (fraction): survivors' annual return is measured; these are the leaving companies' last move
EXIT_RETURNS = {"acquired": {"low": 0.15, "central": 0.25}, "distressed": {"central": -0.55, "worst": -1.0}}


def fetch_submissions(cik: int, ua: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return json.loads(body)


def filings(sub: dict) -> list[dict]:
    """The recent filings block as a list of {form, date, items}. Older pages are not needed: the exit is recent."""
    rec = (sub.get("filings") or {}).get("recent") or {}
    forms, dates, items = rec.get("form") or [], rec.get("filingDate") or [], rec.get("items") or []
    return [{"form": f, "date": d, "items": (items[i] if i < len(items) else "") or ""}
            for i, (f, d) in enumerate(zip(forms, dates))]


def _months_before(d: str, end: str) -> int:
    return (int(end[:4]) - int(d[:4])) * 12 + int(end[5:7]) - int(d[5:7])


def classify(fs: list[dict], last_ym: str) -> dict:
    """Classify the exit from a filing list. last_ym is the last month the company appears in the panel."""
    near = [f for f in fs if f["date"][:7] <= _shift(last_ym, 18) and _months_before(f["date"], _shift(last_ym, 18)) <= 36]
    items = lambda f: {x.strip() for x in f["items"].split(",") if x.strip()}  # noqa: E731
    bankrupt = any("1.03" in items(f) for f in fs if f["form"].startswith("8-K"))
    merger = any(f["form"] in MERGER_FORMS for f in near) or any(
        f["form"].startswith("8-K") and items(f) & {"5.01", "2.01"} for f in near)
    delist_notice = any(f["form"].startswith("8-K") and "3.01" in items(f) for f in near)
    dereg = any(f["form"] in DEREG_FORMS for f in near)
    if bankrupt:
        cls = "distressed"
    elif merger:
        cls = "acquired"
    elif delist_notice and dereg:
        cls = "distressed"
    else:
        cls = "other"
    return {"class": cls, "bankrupt_8k": bankrupt, "merger_filing": merger, "delist_notice": delist_notice,
            "deregistered": dereg, "n_filings": len(fs)}


def _shift(ym: str, months: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def vanished(min_revenue: float = 1e9, df=None) -> dict[int, dict]:
    """{cik: {'last': 'YYYY-MM', 'first_big': 'YYYY-MM'}} for $1bn+ companies whose filings stop before 2020-01, so
    their exit is at least three years before the end of the exploration data."""
    if df is None:
        import edge_split  # noqa: PLC0415
        import xsection  # noqa: PLC0415
        df = edge_split.cut_exploration(xsection.load())
    df = df[["cik", "month", "ttm_revenue"]].copy()
    df["ym"] = df["month"].astype(str).str[:7]
    last = df.groupby("cik")["ym"].max()
    big = df[df["ttm_revenue"] >= min_revenue].groupby("cik")["ym"].min()
    return {int(c): {"last": last[c], "first_big": big[c]} for c in big.index if last[c] < "2020-01"}


def collect(gone: dict[int, dict], ua: str, cache: Path = CACHE, pause: float = 0.15, fetch=fetch_submissions) -> dict:
    """Fetch and classify every vanished company, reusing the cache. Returns {cik: record}."""
    out = json.loads(cache.read_text()) if cache.exists() else {}
    for cik, meta in sorted(gone.items()):
        if str(cik) in out and "class" in out[str(cik)]:
            continue
        try:
            sub = fetch(cik, ua)
            rec = {**classify(filings(sub), meta["last"]), "name": sub.get("name"), **meta}
        except Exception as e:  # noqa: BLE001 - one bad CIK must not stop the run; it is recorded as unknown
            rec = {"class": "other", "error": str(e)[:120], **meta}
        out[str(cik)] = rec
        time.sleep(pause)
    cache.write_text(json.dumps(out, indent=0, sort_keys=True))
    return out


def bias_table(records: dict, universe_by_year: dict[int, int], survivor_ret: float = 0.10) -> list[dict]:
    """Per exit year: how many big companies left by each route, as a share of that year's big universe, and the
    annual bias of a survivor-only equal-weighted backtest (central and worst case), in percentage points."""
    by_year: dict[int, dict] = {}
    for r in records.values():
        y = int(r["last"][:4])
        by_year.setdefault(y, {"acquired": 0, "distressed": 0, "other": 0})[r["class"]] += 1
    rows = []
    for y in sorted(by_year):
        n = universe_by_year.get(y)
        if not n:
            continue
        c = by_year[y]
        sa, sd, so = c["acquired"] / n, c["distressed"] / n, c["other"] / n
        central = sd * (survivor_ret - EXIT_RETURNS["distressed"]["central"]) \
            + sa * (survivor_ret - EXIT_RETURNS["acquired"]["central"])
        # worst case for a long-only backtest: every unknown exit was a failure, every failure went to zero, and the
        # acquired premium is at the low end
        worst = (sd + so) * (survivor_ret - EXIT_RETURNS["distressed"]["worst"]) \
            + sa * (survivor_ret - EXIT_RETURNS["acquired"]["low"])
        rows.append({"year": y, "universe": n, **c, "bias_central_pp": 100 * central, "bias_worst_pp": 100 * worst})
    return rows


def universe_by_year(min_revenue: float = 1e9, df=None) -> dict[int, int]:
    if df is None:
        import edge_split  # noqa: PLC0415
        import xsection  # noqa: PLC0415
        df = edge_split.cut_exploration(xsection.load())
    d = df[df["ttm_revenue"] >= min_revenue].copy()
    d["y"] = d["month"].astype(str).str[:4].astype(int)
    return d.groupby("y")["cik"].nunique().to_dict()


def main() -> None:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        print("SEC_USER_AGENT is not set")
        return
    import edge_split  # noqa: PLC0415
    import xsection  # noqa: PLC0415
    df = edge_split.cut_exploration(xsection.load())
    recs = collect(vanished(df=df), ua)
    rows = bias_table(recs, universe_by_year(df=df))
    tot = {k: sum(r[k] for r in rows) for k in ("acquired", "distressed", "other")}
    print(f"vanished $1bn+ companies (filings stop 2013-2019): {sum(tot.values())}  {tot}")
    print("| Exit year | $1bn+ universe | Acquired | Distressed | Other | Bias, central (pp/yr) | Bias, worst (pp/yr) |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['year']} | {r['universe']} | {r['acquired']} | {r['distressed']} | {r['other']} | "
              f"{r['bias_central_pp']:+.2f} | {r['bias_worst_pp']:+.2f} |")
    if rows:
        print(f"mean bias: central {sum(r['bias_central_pp'] for r in rows) / len(rows):+.2f} pp/yr, "
              f"worst {sum(r['bias_worst_pp'] for r in rows) / len(rows):+.2f} pp/yr")


if __name__ == "__main__":
    main()
