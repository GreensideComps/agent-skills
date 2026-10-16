"""Audit of the B1 execution-price dataset requested by the owner on 2026-10-15 (docs/edge/PHASE_B_PLAN.md §7).

Read-only. Uses data dated 2022-12-31 or earlier only (the B1 files are cut there at download; the research
dataset is cut with `edge_split.cut_exploration`). Nothing here computes a signal or a strategy return.

1. Overnight moves: every usable row whose decision-close-to-execution-close move exceeds 50% is classified as
   * `split_like`: the price ratio is within 2% of a common split ratio (2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40,
     50, 100 or its inverse), the signature of a split or reverse split applied on the wrong day;
   * `extreme`: a move of more than 10x either way in one day, which on this data is a listing change or a
     mis-scaled history far more often than a market move;
   * `reversal`: the next month-end close is within 20% of the decision close, so the jump was undone within a
     month, the signature of a one-day bad print;
   * `penny`: neither, but the decision close (as traded) is below $1, so the row is outside the programme's
     universe anyway;
   * `plausible`: none of these; treated as a genuine market move and kept.
   The first three are "probable data error". No row is excluded here: the proposed exclusion is registered as a
   sensitivity and runs only alongside a registered trial.
2. Coverage by month and by eligibility group (size band x quality flag).
3. Benchmark dates: first price, first month-end close and first full monthly return of each series.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edge_exec_prices as ep  # noqa: E402
import edge_split  # noqa: E402

SPLIT_RATIOS = (2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50, 100)
MOVE = 0.5
REVERSAL_BAND = 0.2
REPORT = Path(__file__).resolve().parent.parent / "equity" / "reports" / "research" / "edge" / "exec_prices_audit"


def classify_moves(rows: pd.DataFrame, next_close: pd.Series, close_raw: pd.Series) -> pd.DataFrame:
    """Classify usable rows whose overnight move exceeds 50%. `next_close` and `close_raw` are aligned to `rows`:
    the next month-end adjusted close and the decision close as traded."""
    ok = rows["status"] == "ok"
    ratio = rows["exec_adjclose"] / rows["me_adjclose"]
    big = ok & ((ratio - 1).abs() > MOVE)
    d = rows[big].assign(ratio=ratio[big], next_close=next_close[big], close_raw=close_raw[big])
    r = np.where(d["ratio"] >= 1, d["ratio"], 1 / d["ratio"])
    split = np.zeros(len(d), bool)
    for k in SPLIT_RATIOS:
        split |= np.abs(r - k) / k < 0.02
    extreme = r > 10
    rev = ((d["next_close"] / d["me_adjclose"] - 1).abs() <= REVERSAL_BAND).to_numpy()
    penny = (d["close_raw"] < 1).to_numpy()
    d["class"] = np.select([split, extreme, rev, penny], ["split_like", "extreme", "reversal", "penny"], "plausible")
    return d


def coverage(monthly: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """Per research-dataset USD company-month (decisions 2009-12..2022-11): its band, quality flag and B1 status
    ('absent' when B1 has no row)."""
    m = monthly[(monthly["currency"] == "USD") & (pd.to_datetime(monthly["month"]) >= ep.FIRST_DECISION)
                & (pd.to_datetime(monthly["month"]) <= ep.LAST_DECISION)].copy()
    m["month"] = pd.to_datetime(m["month"]).dt.strftime("%Y-%m-%d")
    j = m.merge(rows[["cik", "month", "status"]], on=["cik", "month"], how="left")
    j["status"] = j["status"].fillna("absent")
    j["band"] = j["band"].fillna("unbanded")
    return j


def run() -> dict:
    import xsection  # noqa: PLC0415
    rows = ep.load()
    panel = edge_split.with_quality(edge_split.cut_exploration(xsection.load()))
    panel["month"] = pd.to_datetime(panel["month"]).dt.strftime("%Y-%m-%d")
    prices = edge_split.cut_exploration(pd.read_csv(xsection.DATA / "prices_monthly.csv.gz", dtype={"cik": int}))
    prices["month"] = pd.to_datetime(prices["month"]).dt.strftime("%Y-%m-%d")
    prices = prices.merge(panel[["cik", "month", "band", "quality_ok"]], on=["cik", "month"], how="left")

    # next month-end adjusted close and decision close as traded, from the research dataset (to 2022-12)
    nxt = prices[["cik", "month", "adjclose"]].copy()
    nxt["month"] = (pd.to_datetime(nxt["month"]) - pd.offsets.MonthEnd(1)).dt.strftime("%Y-%m-%d")
    k = rows[["cik", "month"]]
    nc = k.merge(nxt, on=["cik", "month"], how="left")["adjclose"]
    cr = k.merge(prices[["cik", "month", "close_raw"]], on=["cik", "month"], how="left")["close_raw"]
    # the research dataset's adjusted closes were fetched on another day; rescale to the B1 basis by the ratio of
    # the two month-end closes for the same month
    base = k.merge(prices[["cik", "month", "adjclose"]], on=["cik", "month"], how="left")["adjclose"]
    nc = pd.Series((nc / base * rows["me_adjclose"]).to_numpy(), index=rows.index)
    moves = classify_moves(rows, nc, pd.Series(cr.to_numpy(), index=rows.index))
    moves = moves.merge(panel[["cik", "month", "band", "quality_ok"]], on=["cik", "month"], how="left")
    moves["band"] = moves["band"].fillna("unbanded")

    cov = coverage(prices, rows)
    bench = pd.read_csv(ep.OUT_DIR / "benchmarks_daily_gbp_to_2022.csv.gz", index_col=0, parse_dates=True)
    bd = {}
    for c in bench:
        s = bench[c].dropna()
        me = s.groupby(s.index.to_period("M")).tail(1)
        first_me = me.index[0]
        ex = [d for d in s.index if d > first_me][0]
        bd[c] = {"first_price": str(s.index[0].date()), "first_month_end_close": str(first_me.date()),
                 "first_full_monthly_return": str(first_me.to_period("M") + 1),
                 "first_price_on_or_after_first_execution_date": str(ex.date())}
    return {"moves": moves, "coverage": cov, "bench_dates": bd, "rows": rows}


def report(res: dict) -> str:
    mv, cov, bd, rows = res["moves"], res["coverage"], res["bench_dates"], res["rows"]
    L = ["# B1 execution prices: audit requested on 2026-10-15", "",
         "Read-only; data to 2022-12-31 only. No signal or strategy return is computed.", ""]
    L += ["## 1. Overnight moves over 50% (decision close to execution close)", "",
          f"{len(mv):,} usable rows of {int((rows['status'] == 'ok').sum()):,}. Classes: `split_like` and `reversal` "
          "are probable data errors, as is `extreme`; `penny` rows (decision close under $1) are outside the universe; `plausible` "
          "moves are kept as genuine.", "",
          "| Band | Quality ok | split_like | extreme | reversal | penny | plausible | Total |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    t = mv.assign(q=mv["quality_ok"].map({True: "yes", False: "no"}).fillna("n/a")).pivot_table(
        index=["band", "q"], columns="class", values="cik", aggfunc="count", fill_value=0)
    cls = ("split_like", "extreme", "reversal", "penny", "plausible")
    for c in cls:
        if c not in t:
            t[c] = 0
    for (b, q), r in t.iterrows():
        L.append(f"| {b} | {q} | " + " | ".join(str(r[c]) for c in cls) + f" | {int(r[list(cls)].sum())} |")
    tot = mv["class"].value_counts()
    L.append("| **all** | | " + " | ".join(str(tot.get(c, 0)) for c in cls) + f" | {len(mv)} |")
    elig = mv[(mv["band"].isin(["large", "mid", "small"])) & (mv["quality_ok"] == True)]  # noqa: E712
    L += ["", f"In the programme's eligible universe (banded, quality ok): {len(elig)} rows; "
          f"{int(elig['class'].isin(['split_like', 'extreme', 'reversal']).sum())} probable data errors, "
          f"{int((elig['class'] == 'plausible').sum())} plausible, {int((elig['class'] == 'penny').sum())} penny.", "",
          "Large and mid band rows, all listed:", "",
          "| Ticker | Decision month | Band | Ratio | Next month-end vs decision | Class |", "|---|---|---|---:|---:|---|"]
    for _, r in mv[mv["band"].isin(["large", "mid"])].sort_values(["band", "month"]).iterrows():
        L.append(f"| {r['ticker']} | {r['month']} | {r['band']} | {r['ratio']:.3f} | "
                 f"{(r['next_close'] / r['me_adjclose'] - 1):+.1%} | {r['class']} |")
    L += ["", "Largest 10 absolute moves (all bands):", "",
          "| Ticker | Decision month | Band | Ratio | Class |", "|---|---|---|---:|---|"]
    top = mv.assign(a=(np.log(mv["ratio"])).abs()).sort_values("a", ascending=False).head(10)
    for _, r in top.iterrows():
        L.append(f"| {r['ticker']} | {r['month']} | {r['band']} | {r['ratio']:.3g} | {r['class']} |")

    L += ["", "## 2. Coverage", "",
          "Share of the research dataset's USD company-months (decisions 2009-12 to 2022-11) with a usable ('ok') "
          "execution row, by eligibility group:", "",
          "| Band | Quality ok | Company-months | ok | missing_exec | invalid_price | stale_month_end | absent | Coverage |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    c = cov.assign(q=cov["quality_ok"].map({True: "yes", False: "no"}).fillna("n/a"))
    g = c.pivot_table(index=["band", "q"], columns="status", values="cik", aggfunc="count", fill_value=0)
    for s in ("ok", "missing_exec", "invalid_price", "stale_month_end", "absent"):
        if s not in g:
            g[s] = 0
    for (b, q), r in g.iterrows():
        n = int(r.sum())
        L.append(f"| {b} | {q} | {n:,} | {r['ok']:,} | {r['missing_exec']} | {r['invalid_price']} | "
                 f"{r['stale_month_end']} | {r['absent']} | {r['ok'] / n:.2%} |")
    bym = c[c["band"].isin(["large", "mid", "small"]) & (c["quality_ok"] == True)].groupby("month")[  # noqa: E712
        "status"].apply(lambda s: (s == "ok").mean())
    L += ["", f"By month, eligible universe (banded, quality ok): minimum {bym.min():.2%} ({bym.idxmin()}), median "
          f"{bym.median():.2%}; {int((bym < 0.99).sum())} of {len(bym)} months below 99%. Full table: "
          "`exec_prices_audit_coverage_by_month.csv`.", ""]
    big_bym = c[(c["band"] == "large") & (c["quality_ok"] == True)].groupby("month")["status"].apply(  # noqa: E712
        lambda s: (s == "ok").mean())
    L += [f"Large band, quality ok: minimum {big_bym.min():.2%} ({big_bym.idxmin()}), "
          f"{int((big_bym < 1).sum())} of {len(big_bym)} months below 100%.", ""]

    L += ["## 3. Benchmark dates", "", "| Series | First price | First month-end close | First full monthly return | "
          "First execution-date price |", "|---|---|---|---|---|"]
    for k, v in bd.items():
        L.append(f"| {k} | {v['first_price']} | {v['first_month_end_close']} | {v['first_full_monthly_return']} | "
                 f"{v['first_price_on_or_after_first_execution_date']} |")
    L += ["", "VWRP's first price is 25 July 2019 and its first month-end close is 31 July 2019, so its first full "
          "monthly return is **August 2019** (31 July to 30 August). Earlier documents said September 2019; that "
          "was one month late and is corrected. On the backtester's execution dates the first VWRP period starts "
          "on 1 August 2019 (the first trading day after the July decision)."]
    return "\n".join(L) + "\n"


def main() -> int:
    res = run()
    md = report(res)
    REPORT.with_suffix(".md").write_text(md)
    c = res["coverage"]
    c[c["band"].isin(["large", "mid", "small"])].assign(ok=c["status"] == "ok").groupby(["month", "band"])[
        "ok"].agg(["size", "mean"]).rename(columns={"size": "company_months", "mean": "coverage"}).to_csv(
        REPORT.parent / "exec_prices_audit_coverage_by_month.csv")
    res["moves"].to_csv(REPORT.parent / "exec_prices_audit_moves.csv", index=False)
    (REPORT.with_suffix(".json")).write_text(json.dumps({"bench_dates": res["bench_dates"],
                                                        "move_classes": res["moves"]["class"].value_counts().to_dict()},
                                                       indent=1))
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
