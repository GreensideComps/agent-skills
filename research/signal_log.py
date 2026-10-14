"""Prospective signal log (STRATEGY_V2 §2.4, satellite mode chosen by the owner on 2026-10-14).

Every month, every Stage 2 signal is scored for the whole universe as it stood at the last month-end, and
the scores are saved before the outcome exists. Later runs join each logged month to the return that
followed and report the live information coefficient per signal and size band. This is the only evidence
that can show a signal working (or decaying) out of sample; it cannot be back-filled.

The log starts with decisions at 2026-10-31: the 2023-01..2026-09 holdout stays unread.

    RESEARCH_DATA=/path python3 signal_log.py score      # score the latest complete month (once)
    RESEARCH_DATA=/path python3 signal_log.py evaluate [out.md]
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import stage2
import xsection

FIRST_MONTH = "2026-10-31"
LOG = xsection.DATA / "signal_log"
ID_COLS = ["cik", "ticker", "band", "mcap", "group"]


def latest_complete_month(df: pd.DataFrame, today: date) -> pd.Timestamp:
    """The last month-end strictly before today that has fundamentals rows."""
    months = df.loc[df["month"] < pd.Timestamp(today), "month"]
    return months.max()


def score(df: pd.DataFrame, month: pd.Timestamp) -> pd.DataFrame:
    """Scores for every trial at `month`, for companies with a price >= $1 and a size band."""
    feats = stage2.build_features(df, [month])
    g = feats[(feats["month"] == month) & (feats["close_raw"] >= xsection.MIN_PRICE) & feats["band"].notna()]
    out = g[ID_COLS].copy()
    for tid, (_, _, fn) in stage2.TRIALS.items():
        out[tid] = fn(g)
    out.insert(0, "month", month.date().isoformat())
    return out


def run_score(today: date | None = None, log_dir: Path = LOG) -> Path | None:
    today = today or date.today()
    df = xsection.load()
    month = latest_complete_month(df, today)
    if month < pd.Timestamp(FIRST_MONTH):
        print(f"latest complete month {month.date()} is before the log start {FIRST_MONTH}; nothing logged")
        return None
    path = log_dir / f"{month:%Y-%m}.csv.gz"
    if path.exists():  # a logged month is never rewritten: scores must predate their outcome
        print(f"{path} already logged")
        return path
    log_dir.mkdir(parents=True, exist_ok=True)
    s = score(df, month)
    s.to_csv(path, index=False)
    print(f"logged {len(s):,} companies x {len(stage2.TRIALS)} signals for {month.date()} -> {path}")
    return path


def outcomes(logged: pd.DataFrame, df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Join each logged score to the next month's return, only once that month has fully ended."""
    logged = logged.copy()
    logged["month"] = pd.to_datetime(logged["month"])
    done = logged["month"] + pd.offsets.MonthEnd(1) < pd.Timestamp(today)
    r = df[["cik", "month", "ret_next"]]
    return logged[done].merge(r, on=["cik", "month"], how="left")


def ic_table(x: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tid in stage2.TRIALS:
        for band in ("large", "mid", "small"):
            ics = []
            for _, g in x[(x["band"] == band)].groupby("month"):
                g = g[[tid, "ret_next"]].dropna()
                if len(g) >= 30:
                    ics.append(g[tid].rank().corr(g["ret_next"].rank()))
            ic = pd.Series(ics, dtype=float)
            rows.append({"trial": tid, "band": band, "months": len(ic), "mean_ic": ic.mean() if len(ic) else np.nan,
                         "ic_t": xsection.newey_west_t(ic) if len(ic) >= 12 else None})
    return pd.DataFrame(rows)


def run_evaluate(out: Path, today: date | None = None, log_dir: Path = LOG) -> None:
    today = today or date.today()
    files = sorted(log_dir.glob("*.csv.gz"))
    lines = ["# Prospective signal log", "",
             f"Scores logged before outcomes, monthly from {FIRST_MONTH[:7]}. Updated {today.isoformat()}.", ""]
    if not files:
        lines.append("No months logged yet.")
        out.write_text("\n".join(lines) + "\n")
        print("\n".join(lines))
        return
    logged = pd.concat([pd.read_csv(f) for f in files])
    x = outcomes(logged, xsection.load(), today)
    t = ic_table(x)
    lines += [f"Months logged: {len(files)}; with a completed outcome: {x['month'].nunique()}.", "",
              "| Trial | Large: months | Large: mean IC | Large: t | Mid: mean IC | Small: mean IC |",
              "|---|---:|---:|---:|---:|---:|"]
    for tid in stage2.TRIALS:
        r = t[t["trial"] == tid].set_index("band")
        def f(v):
            return "" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.3f}"
        lines.append(f"| {tid} | {int(r.loc['large', 'months'])} | {f(r.loc['large', 'mean_ic'])} | "
                     f"{f(r.loc['large', 'ic_t'])} | {f(r.loc['mid', 'mean_ic'])} | {f(r.loc['small', 'mean_ic'])} |")
    lines += ["", "Kill rule (STRATEGY_V2 §2.5): after 36 months, a signal with large-cap IC <= 0 stays research-only. "
              "Fewer than about 44 months cannot show a typical IC of 0.03 at t = 2, so early numbers are noise.", ""]
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "score"
    if cmd == "score":
        run_score()
    else:
        run_evaluate(Path(sys.argv[2]) if len(sys.argv) > 2 else Path("signal_log.md"))
