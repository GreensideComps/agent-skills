"""Check 4, step 0: selection-only reconstruction of B5 run 2's historical holdings (owner decision O6, 2026-10-20).

Approved by the owner (message cmsg_01U4KMvkBYNknqm4HRVie8uvWBGcbQVLRwVrW8HKHTK5JK, 07:19Z) for one purpose: to build
the Check 4 sampling frame (docs/edge/CHECK4_PROCEDURE.md §4) and, later, to test whether a fact discrepancy would
have changed a selection. Run 2 (D31, commit a4a07d7) recorded statistics but no holdings, so every holding written
here is RECONSTRUCTED, not originally recorded.

What it does
* Reads the frozen run-2 code from a separate checkout of a4a07d7 (``--frozen``), refuses unless that checkout is
  exactly a4a07d7 with no local changes, and verifies every input and code file named in the registered
  B5-V3-RUN-MANIFEST-3 (sha256 f3f4fd71...) before reading any data. It writes nothing into that checkout.
* Builds the primary panels with the frozen functions (``edge_b5_run.attach_fundamentals``, ``score_panels``,
  ``config``), as ``edge_b5_run.load_inputs`` does, without the run gate and without the FX, benchmark, factor or
  data-error inputs, which only valuation needs.
* Replays the frozen engine's selection loop (``edge_backtest.run``) with its own selection functions
  (``edge_rules.decision_frame``, ``edge_backtest.price_table``, ``eligible``, ``select``), for each tranche of the
  primary run only.

What it does not do
* It computes no return, NAV, cost, contribution or statistic. A held name's exit between rebalances depends only
  on whether its execution price is valid (``edge_rules.holding_return``'s "missing" status); ``price_missing``
  reproduces that test without computing the return. Weights are equal, so the names held are the whole selection.
* It changes no registry, report, verdict, status, lock or B5 file, and calls no ``run_trial`` or ``record``.

Usage:  python3 research/check4/reconstruct_holdings.py --frozen /path/to/a4a07d7-checkout --out docs/edge/check4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
from pathlib import Path

FROZEN_COMMIT = "a4a07d7d6a3242d2fd06dd5fb133262f28172b9f"
MANIFEST = "docs/edge/B5_RUN_MANIFEST_3.json"
MANIFEST_SHA = "f3f4fd71bae5ddf4932211c1983edac7dcb1d6d152d8d087c73550409a4b9671"
FRAME_FIRST, FRAME_LAST = "2015-01-31", "2022-11-30"
LABEL = "reconstructed"  # every output row says so: run 2 recorded no holdings


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_frozen(frozen: Path) -> dict:
    """Refuse unless `frozen` is a clean checkout of a4a07d7 whose manifest files all match MANIFEST-3."""
    head = subprocess.run(["git", "-C", str(frozen), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    if head.stdout.strip() != FROZEN_COMMIT:
        raise SystemExit(f"STOP: {frozen} is at {head.stdout.strip()}, not run 2's commit {FROZEN_COMMIT}")
    dirty = subprocess.run(["git", "-C", str(frozen), "status", "--porcelain"], capture_output=True, text=True,
                           check=True).stdout.strip()
    if dirty:
        raise SystemExit(f"STOP: the frozen checkout has local changes:\n{dirty}")
    man = frozen / MANIFEST
    if sha(man) != MANIFEST_SHA:
        raise SystemExit("STOP: the manifest is not the registered MANIFEST-3")
    files = json.loads(man.read_text())
    checked = {}
    for section in ("inputs", "code"):
        for name, want in files[section].items():
            p = Path(name) if Path(name).is_absolute() else frozen / name
            if not p.exists():
                raise SystemExit(f"STOP: manifest file missing: {name}")
            got = sha(p)
            if got != want:
                raise SystemExit(f"STOP: {name} has sha256 {got}, manifest says {want}")
            checked[name] = got
    return {"commit": FROZEN_COMMIT, "manifest": MANIFEST, "manifest_sha256": MANIFEST_SHA, "files": checked}


def import_frozen(frozen: Path):
    for p in (frozen / "research", frozen / "equity"):
        sys.path.insert(0, str(p))
    import edge_b5 as b5
    import edge_b5_run as run
    import edge_b5_stats as st
    import edge_backtest as bt
    import edge_rules
    import edge_split
    for m in (b5, run, st, bt, edge_rules, edge_split):
        if not Path(m.__file__).resolve().is_relative_to(frozen.resolve()):
            raise SystemExit(f"STOP: {m.__name__} was imported from {m.__file__}, not the frozen checkout")
    return b5, run, st, bt, edge_rules, edge_split


def load_panel(frozen_mods):
    """`edge_b5_run.load_inputs`, lines for the panel and execution prices only (no gate, no valuation inputs)."""
    import pandas as pd
    b5, run, st, bt, edge_rules, edge_split = frozen_mods
    import stage2
    import xsection
    from equity import panel as epanel

    df = st.with_quality_columns(edge_split.cut_exploration(xsection.load()))
    comp = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(comp, on="cik", how="left")
    df["group"] = df["sic"].map(stage2.sic_group)
    df["financial"] = df["group"] == "finance"
    ciks = set(df.loc[df["band"] == "large", "cik"])
    df = df[df["cik"].isin(ciks) & (df["month"] >= "2012-01-31")].reset_index(drop=True)
    metrics = {"revenue", "ocf", "capex", "gross_profit", "cost_of_revenue", "total_assets"}
    fx_rows: dict = {}
    for r in epanel.read(xsection.DATA / "sec_facts_panel.csv.gz", ciks):
        if r["metric"] in metrics and r["unit"] == "USD" and r["filed"] <= str(run.CUT.date()):
            fx_rows.setdefault(r["cik"], {}).setdefault(r["metric"], []).append(r)
    df = run.attach_fundamentals(df, fx_rows)
    edge_dir = Path(__import__("edge_exec_prices").OUT_DIR)
    ex = pd.read_csv(edge_dir / "exec_prices_to_2022.csv.gz")
    ex = ex[pd.to_datetime(ex["month"]) <= run.CUT]
    return df, ex


def price_missing(series, start, end) -> bool:
    """`edge_rules.holding_return(...)[1] == "missing"`, without computing the return: True when any price in
    (start, end] is absent or <= 0, or `end` has no price. Raises as the engine does when there is no entry price."""
    import pandas as pd
    s = series.sort_index()
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    p0 = s.get(t0)
    if p0 is None or not p0 > 0:
        raise ValueError(f"no valid price to buy at on {t0.date()}")
    for v in s[(s.index > t0) & (s.index <= t1)]:
        if not v > 0:
            return True
    return t1 not in s.index


def replay(bt, edge_rules, edge_split, panel, exec_rows, cfg, start, end) -> dict:
    """The selection path of `edge_backtest.run` for one tranche: same months, rebalance set, exits, decision frame,
    eligibility, buyable set and `select`. Returns {decision month: {"trade_date", "chosen", "ranked", "events"}}."""
    import pandas as pd
    panel = panel.copy()
    panel["month"] = pd.to_datetime(panel["month"])
    edge_split.assert_exploration_only(panel)
    prices, trade_dates, entry_ok = bt.price_table(exec_rows, cfg.convention)
    months = [m for m in trade_dates.index if (start is None or m >= pd.Timestamp(start))
              and (end is None or m <= pd.Timestamp(end))]
    if not months:
        raise ValueError("no decision months in range")
    rebal = set(months[::cfg.rebalance_every])
    held: dict = {}  # cik -> entry (trade) date
    out = {}
    pending_exits: list = []
    for m in months:
        d = trade_dates[m]
        for c in list(held):
            series = prices[c] if c in prices else pd.Series(dtype=float)
            if price_missing(series, held[c], d):
                pending_exits.append({"date": d, "event": "exit", "cik": c, "reason": "missing or invalid price"})
                del held[c]
        if m in rebal:
            frame = edge_rules.decision_frame(panel, m)
            frame = frame[frame["month"] == m]
            ranked = bt.eligible(frame, cfg)
            ok_d = entry_ok.loc[d] if d in entry_ok.index else pd.Series(dtype=bool)
            buyable = {c for c in ranked["cik"] if c in ok_d.index and bool(ok_d[c]) and (c, m) not in cfg.no_buy}
            if cfg.selection != "top_n" or cfg.select_all:
                raise ValueError("the reconstruction covers the B5 primary configuration (top_n) only")
            chosen, passed = bt.select(ranked, set(held), buyable, cfg)
            events = pending_exits + [{"date": d, "event": "skipped_entry" if why == "no execution price"
                                       else "skipped_cap", "cik": c, "reason": why} for c, why in passed]
            if not chosen:
                events.append({"date": d, "event": "all_cash", "reason": "no eligible names"})
            elif len(chosen) < cfg.n:
                events.append({"date": d, "event": "short", "reason": f"{len(chosen)} of {cfg.n} names"})
            out[m] = {"trade_date": d, "chosen": list(chosen), "ranked": ranked, "events": events}
            pending_exits = []
            held = {c: d for c in chosen}
    return out


def decile(rank: int, n: int) -> int:
    """10 = best score. Rank 1..n in the engine's order (score descending, then CIK)."""
    return 10 - math.floor((rank - 1) * 10 / n)


def reconstruct(frozen: Path, out: Path) -> dict:
    import numpy as np
    import pandas as pd
    provenance = verify_frozen(frozen)
    mods = import_frozen(frozen)
    b5, run, st, bt, edge_rules, edge_split = mods
    df, ex = load_panel(mods)
    panels = run.score_panels(df)
    out.mkdir(parents=True, exist_ok=True)
    summary = {"label": LABEL, "provenance": provenance, "trials": {},
               "environment": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
               "computed": "selection only: no returns, NAV, costs, contributions or statistics"}
    for key, tid in run.TRIALS.items():
        k, starts = run.SCHEDULE[key]
        cfg = run.config(k)
        panel = panels[key]["primary"]
        hold_rows, event_rows, by_month = [], [], {}
        for s in starts:
            path = replay(bt, edge_rules, edge_split, panel, ex, cfg, s, b5.EVAL_LAST_DECISION)
            for m, r in path.items():
                rank = dict(zip(r["ranked"]["cik"], r["ranked"]["rank"]))
                for c in r["chosen"]:
                    hold_rows.append({"trial": tid, "tranche_start": s, "decision_month": m.date().isoformat(),
                                      "trade_date": r["trade_date"].date().isoformat(), "cik": int(c),
                                      "rank": int(rank[c]), "source": LABEL})
                for e in r["events"]:
                    event_rows.append({"trial": tid, "tranche_start": s, "decision_month": m.date().isoformat(),
                                       "date": pd.Timestamp(e["date"]).date().isoformat(), "event": e["event"],
                                       "cik": e.get("cik"), "reason": e["reason"], "source": LABEL})
                by_month.setdefault(m, []).append((s, r))
        holdings = pd.DataFrame(hold_rows).sort_values(["decision_month", "tranche_start", "rank"])
        events = pd.DataFrame(event_rows)
        frame_months = [m for m in sorted(by_month) if pd.Timestamp(FRAME_FIRST) <= m <= pd.Timestamp(FRAME_LAST)]
        frame_rows, problems = [], []
        for m in frame_months:
            tranches = by_month[m]
            if len(tranches) != 1:
                problems.append(f"{m.date()}: {len(tranches)} tranches rebalance (expected exactly 1)")
                continue
            s, r = tranches[0]
            ranked, chosen = r["ranked"], set(r["chosen"])
            n = len(ranked)
            # names in any tranche's portfolio after this month's rebalance (others carry their last selection)
            held_any = set(chosen)
            for s2 in starts:
                if s2 == s:
                    continue
                prior = [mm for mm, lst in by_month.items() if mm <= m for (ss, _) in lst if ss == s2]
                if prior:
                    last = max(prior)
                    held_any |= set(next(rr for ss, rr in by_month[last] if ss == s2)["chosen"])
            for c, rk, sc in zip(ranked["cik"], ranked["rank"], ranked["score"]):
                frame_rows.append({"trial": tid, "decision_month": m.date().isoformat(), "year": m.year,
                                   "cik": int(c), "rank": int(rk), "n_eligible": n, "score": float(sc),
                                   "decile": decile(int(rk), n), "held": c in chosen,
                                   "held_any_tranche": c in held_any, "rebalancing_tranche": s, "source": LABEL})
        if problems:
            raise SystemExit("STOP: " + "; ".join(problems))
        frame = pd.DataFrame(frame_rows)
        # Missing inputs: decision rows that pass every other eligibility rule but have no score, so they are
        # outside the frame. Not guessed or filled; counted here (financials have no score by rule, so excluded).
        pm = pd.to_datetime(panel["month"])
        base = (panel["quality_ok"].astype(bool) & (panel["band"] == "large") & (panel["close_raw"] >= cfg.min_price)
                & pm.between(pd.Timestamp(FRAME_FIRST), pd.Timestamp(FRAME_LAST)) & ~df["financial"].astype(bool))
        unscored = int((base & panel["score"].isna()).sum())
        files = {}
        for name, d in (("holdings", holdings), ("events", events), ("frame", frame)):
            p = out / f"{name}_{key}.csv"
            d.to_csv(p, index=False, float_format="%.12g")
            files[p.name] = sha(p)
        n_dec = holdings.groupby(["tranche_start", "decision_month"]).size()
        summary["trials"][tid] = {
            "rebalance_months": k, "tranches": list(starts), "decisions": int(len(n_dec)),
            "decisions_short_of_20": int((n_dec < cfg.n).sum()), "min_names": int(n_dec.min()),
            "holding_rows": int(len(holdings)), "distinct_ciks_held": int(holdings["cik"].nunique()),
            "frame_months": len(frame_months), "frame_rows": int(len(frame)),
            "frame_held_rows": int(frame["held"].sum()),
            "missing_inputs": {"eligible_but_unscored_company_months": unscored,
                               "scored_company_months": int((base & panel["score"].notna()).sum()),
                               "note": "large, quality ok, price >= $1, non-financial, 2015-01..2022-11, no score: "
                                       "an input was unavailable at the decision date; left out, never filled"},
            "events": events["event"].value_counts().sort_index().to_dict() if len(events) else {},
            "files_sha256": files}
    p = out / "reconstruction_summary.json"
    p.write_text(json.dumps(summary, indent=1, default=str) + "\n")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", required=True, type=Path, help="a clean checkout of run 2's commit a4a07d7")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    s = reconstruct(a.frozen.resolve(), a.out.resolve())
    print(json.dumps({t: {k: v for k, v in d.items() if k != "files_sha256"} for t, d in s["trials"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
