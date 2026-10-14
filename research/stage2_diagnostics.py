"""Stage 2 diagnostics for the edge-discovery programme (Phase A). Information only: no Stage 2 verdict, definition,
window or pass rule changes, and `stage2.py` is not modified.

For each of the 15 Stage 2 trials, per size band and at 1, 3, 6 and 12-month horizons, on exploration data only:

* IC mean, standard deviation, hit rate, naive t, Newey-West t with max(3, h) lags (h-month returns overlap
  when decisions are monthly), and the t on non-overlapping decisions (every h-th month) as a cross-check;
* the minimum detectable effect: the mean IC that would have reached t = 2 given the IC noise actually seen
  (2 x the Newey-West standard error), and the power to detect a mean IC of 0.02;
* the top-minus-bottom decile return per month of holding;
* at 1 month, large caps: Fama-French five-factor plus momentum loadings of the decile spread, to check each
  signal carries the exposure it was meant to.

Holdout discipline: the dataset is cut at 2022-12 *before* any feature is built (`edge_split.exploration_view`),
so no score or outcome can use a 2023 value. The 1-month large-cap IC is compared with the published Stage 2
result; a match shows Stage 2's scores did not depend on post-2022 data either.

The 3, 6 and 12-month horizons are new looks at the data. They are registered as diagnostic trials in
`edge/trials.jsonl` before they run and count toward the programme's deflated Sharpe.

    RESEARCH_DATA=/path python3 stage2_diagnostics.py [out.md]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

import data_sources
import edge_registry
import edge_split
import stage2
import xsection

START = stage2.START
EXTRA_HORIZONS = (3, 6, 12)
HORIZONS = (1,) + EXTRA_HORIZONS
PUBLISHED = Path(__file__).resolve().parent.parent / "equity" / "reports" / "research" / "stage2_signals.json"
_N = NormalDist()


def nw_se(x: np.ndarray, lags: int) -> float | None:
    """Newey-West (Bartlett) standard error of the mean."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 12:
        return None
    e = x - x.mean()
    s = (e @ e) / n
    for k in range(1, min(lags, n - 1) + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return math.sqrt(s / n) if s > 0 else None


def ic_stats(ic: pd.Series, horizon: int) -> dict:
    """Summary of a monthly IC series for h-month outcomes."""
    x = ic.dropna()
    n = len(x)
    if n < 12:
        return {"months": n}
    lags = max(3, horizon)
    se = nw_se(x.to_numpy(), lags)
    sd = float(x.std(ddof=1))
    nonov = x.iloc[::horizon]
    t_nonov = float(nonov.mean() / (nonov.std(ddof=1) / math.sqrt(len(nonov)))) if len(nonov) > 2 and nonov.std(ddof=1) > 0 else None
    return {
        "months": n, "mean_ic": float(x.mean()), "ic_sd": sd, "hit_rate": float((x > 0).mean()),
        "t_naive": float(x.mean() / (sd / math.sqrt(n))) if sd > 0 else None,
        "nw_lags": lags, "t_nw": float(x.mean() / se) if se else None,
        "t_nonoverlap": t_nonov, "n_nonoverlap": len(nonov),
        "mde_ic_t2": 2 * se if se else None,
        "power_ic_0.02": float(1 - _N.cdf(2 - 0.02 / se)) if se else None,
    }


def investable(df: pd.DataFrame, quality: bool = False) -> pd.DataFrame:
    """Stage 2's universe filter without the outcome condition: from START, price >= $1, a size band. With
    `quality`, also the programme's data-quality exclusion (`quality_ok`, EVALUATION_SPEC §1). The published
    diagnostics reproduce Stage 2, which had no exclusion, so they run without it; `quality_sensitivity` shows
    what the exclusion changes."""
    d = df[(df["month"] >= START) & (df["close_raw"] >= xsection.MIN_PRICE) & df["band"].notna()]
    return d[d["quality_ok"]] if quality else d


def scored(d: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Every trial's score, as Stage 2 computes it: on each month's cross-section of companies that have the
    outcome (all bands together, so within-group ranks match Stage 2 at h = 1)."""
    col = f"ret_{horizon}m"
    d = d[d[col].notna()].copy()
    for tid, (_, _, fn) in stage2.TRIALS.items():
        d[tid] = np.nan
        for _, g in d.groupby("month"):
            d.loc[g.index, tid] = fn(g)
    return d


def run(d: pd.DataFrame, factors: pd.DataFrame | None = None) -> dict:
    """Diagnostics per trial, band and horizon from an investable exploration frame (columns ret_{h}m)."""
    out: dict = {tid: {b: {} for b in ("large", "mid", "small")} for tid in stage2.TRIALS}
    for h in HORIZONS:
        col = f"ret_{h}m"
        s_h = scored(d, h)
        for tid in stage2.TRIALS:
            for band in ("large", "mid", "small"):
                x = s_h[s_h["band"] == band]
                rows = []
                for mo, g in x.groupby("month"):
                    g = g[[tid, col]].dropna()
                    if len(g) < 30:
                        continue
                    q = pd.qcut(g[tid].rank(method="first"), 10, labels=False)
                    rows.append({"month": mo, "n": len(g), "ic": g[tid].rank().corr(g[col].rank()),
                                 "spread": g.loc[q == 9, col].mean() - g.loc[q == 0, col].mean()})
                r = pd.DataFrame(rows)
                if r.empty:
                    out[tid][band][h] = {"months": 0}
                    continue
                s = ic_stats(r.set_index("month")["ic"], h)
                se_sp = nw_se(r["spread"].to_numpy(), max(3, h))
                s.update({"avg_names": float(r["n"].mean()), "min_names": int(r["n"].min()),
                          "first": str(r["month"].min().date()), "last": str(r["month"].max().date()),
                          "d10_d1_per_month": float(r["spread"].mean() / h),
                          "d10_d1_t_nw": float(r["spread"].mean() / se_sp) if se_sp else None})
                if h == 1 and band == "large" and factors is not None:
                    sp = r.set_index(pd.DatetimeIndex(r["month"]) + pd.offsets.MonthEnd(1))["spread"]
                    s["d10_d1_factor"] = stage2.factor_alpha(sp, factors)
                out[tid][band][h] = s
    return out


def compare_published(diag: dict, published: dict) -> dict:
    """Large-cap 1-month mean IC and NW t here vs the committed Stage 2 results."""
    out = {}
    for tid, p in published.items():
        b, mine = p["bands"]["large"], diag.get(tid, {}).get("large", {}).get(1, {})
        out[tid] = {"published_ic": b["mean_ic"], "ic": mine.get("mean_ic"), "published_t": b["ic_t_nw"],
                    "t": mine.get("t_nw"), "published_months": b["months"], "months": mine.get("months"),
                    "match": mine.get("mean_ic") is not None and abs(mine["mean_ic"] - b["mean_ic"]) < 5e-4
                    and mine.get("months") == b["months"]}
    return out


def register_diagnostics(path: Path = edge_registry.PATH) -> list[str]:
    """Register the 3/6/12-month horizon looks before running them (idempotent). Returns new ids."""
    have = edge_registry.registered(edge_registry.load(path))
    new = []
    for tid, (fam, desc, _) in stage2.TRIALS.items():
        for h in EXTRA_HORIZONS:
            i = f"DIAG-{tid}-h{h}"
            if i in have:
                continue
            last = edge_split.last_exploration_decision(h)
            edge_registry.append({
                "event": "register", "id": i, "kind": "diagnostic", "phase": "exploration", "hypothesis": fam,
                "definition": f"Stage 2 {tid} ({desc}) scored monthly, IC vs {h}-month forward return",
                "universe": "US large, mid and small bands as Stage 2", "horizon_months": h,
                "window": {"decisions": [START[:7], f"{last:%Y-%m}"], "outcomes": ["2015-02", "2022-12"]},
                "counts_for_dsr": True, "touched_holdout": False, "source": "research/stage2_diagnostics.py",
                "note": "Phase A diagnostic. A new horizon is a new look at the data, so it counts."}, path)
            new.append(i)
    return new


def record_results(diag: dict, path: Path = edge_registry.PATH, evidence: str = "") -> None:
    for tid in stage2.TRIALS:
        for h in EXTRA_HORIZONS:
            s = diag[tid]["large"].get(h, {})
            edge_registry.append({"event": "result", "id": f"DIAG-{tid}-h{h}", "band": "large",
                                  "mean_ic": s.get("mean_ic"), "ic_t_nw": s.get("t_nw"), "evidence": evidence}, path)


def _f(v, fmt):
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else format(v, fmt)


def report(diag: dict, cmp: dict, n_trials: int) -> str:
    L = ["# Stage 2 diagnostics (Phase A, exploration data only)", "",
         f"Decisions from {START[:7]}; outcomes end by 2022-12 at every horizon (last decision: 1 month 2022-11, 3 months "
         "2022-09, 6 months 2022-06, 12 months 2021-12). The dataset was cut at 2022-12 before any score was built. "
         "Information only: Stage 2 verdicts are unchanged. Survivor bias as in the Stage 1 report.", "",
         f"Programme trial count after registering these looks: {n_trials} (`research/edge/trials.jsonl`).", "",
         "## Reproduction of Stage 2 (large caps, 1 month)", "",
         "| Trial | Published IC | IC here | Published t | t here | Months | Match |", "|---|---:|---:|---:|---:|---:|---|"]
    for tid, c in cmp.items():
        L.append(f"| {tid} | {c['published_ic']:.4f} | {_f(c['ic'], '.4f')} | {c['published_t']:.2f} | {_f(c['t'], '.2f')} | "
                 f"{c['months']} | {'yes' if c['match'] else '**no**'} |")
    L += ["", "## Power: what the 1-month large-cap test could detect", "",
          "MDE = the mean IC that would have reached t = 2 given the IC noise observed. Typical published large-cap "
          "ICs for these families are 0.01 to 0.03.", "",
          "| Trial | Mean IC | IC sd | Hit rate | t (NW) | MDE for t = 2 | Power at IC 0.02 | Names (avg / min) |",
          "|---|---:|---:|---:|---:|---:|---:|---|"]
    for tid in stage2.TRIALS:
        s = diag[tid]["large"][1]
        L.append(f"| {tid} | {_f(s.get('mean_ic'), '.4f')} | {_f(s.get('ic_sd'), '.3f')} | {_f(s.get('hit_rate'), '.0%')} | "
                 f"{_f(s.get('t_nw'), '.2f')} | {_f(s.get('mde_ic_t2'), '.4f')} | {_f(s.get('power_ic_0.02'), '.0%')} | "
                 f"{_f(s.get('avg_names'), '.0f')} / {s.get('min_names', '')} |")
    L += ["", "## Horizons (large caps)", "",
          "Mean IC and Newey-West t with max(3, h) lags; in brackets the t on non-overlapping decisions only. "
          "D10-D1 is the top-minus-bottom decile return per month of holding, gross.", "",
          "| Trial | 1m IC (t) | 3m IC (t) [non-overlap] | 6m IC (t) [non-overlap] | 12m IC (t) [non-overlap] | D10-D1 a month: 1m / 12m |",
          "|---|---:|---:|---:|---:|---:|"]
    for tid in stage2.TRIALS:
        c = []
        for h in HORIZONS:
            s = diag[tid]["large"][h]
            cell = f"{_f(s.get('mean_ic'), '.3f')} ({_f(s.get('t_nw'), '.2f')})"
            if h > 1:
                cell += f" [{_f(s.get('t_nonoverlap'), '.2f')}]"
            c.append(cell)
        d1, d12 = diag[tid]["large"][1], diag[tid]["large"][12]
        c.append(f"{_f(d1.get('d10_d1_per_month'), '+.2%')} / {_f(d12.get('d10_d1_per_month'), '+.2%')}")
        L.append(f"| {tid} | " + " | ".join(c) + " |")
    L += ["", "## Horizons (mid and small caps, information only)", "",
          "| Trial | Mid 1m | Mid 12m | Small 1m | Small 12m |", "|---|---:|---:|---:|---:|"]
    for tid in stage2.TRIALS:
        c = []
        for band in ("mid", "small"):
            for h in (1, 12):
                s = diag[tid][band][h]
                c.append(f"{_f(s.get('mean_ic'), '.3f')} ({_f(s.get('t_nw'), '.2f')})")
        L.append(f"| {tid} | " + " | ".join(c) + " |")
    L += ["", "## Factor exposure of the 1-month large-cap decile spread", "",
          "Fama-French five factors plus momentum, monthly, Newey-West t on alpha. Checks each signal carried the "
          "exposure it was designed to; it is not a pass rule.", "",
          "| Trial | Alpha a year (t) | Mkt-RF | SMB | HML | RMW | CMA | Mom |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for tid in stage2.TRIALS:
        a = diag[tid]["large"][1].get("d10_d1_factor") or {}
        be = a.get("betas", {})
        L.append(f"| {tid} | {_f(a.get('alpha_ann'), '+.1%')} ({_f(a.get('alpha_t'), '.2f')}) | "
                 + " | ".join(_f(be.get(k), '+.2f') for k in ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom")) + " |")
    L += ["", "## How to read this", "",
          "- A t below 2 with an MDE above about 0.02 means the test could not have seen a typical-sized effect: "
          "'not detected', not 'shown ineffective'.",
          "- A significantly negative IC or alpha is evidence against the signal in the form tested.",
          "- Longer horizons use overlapping outcomes; the non-overlapping t is the honest check when the two differ.",
          "- These are exploration-period numbers. Any idea they suggest is a new hypothesis that must be registered "
          "and later confirmed on the holdout; it is not evidence on its own.", ""]
    return "\n".join(L)


def load_exploration() -> pd.DataFrame:
    # cut before anything is built; ret_next of 2022-12 is a 2023 return, so it goes too (recomputed below).
    # Quality flags are computed on the cut frame, so their share-count medians use no 2023-26 data.
    df = edge_split.with_quality(edge_split.cut_exploration(xsection.load()))
    months = sorted(df.loc[(df["month"] >= START) & (df["month"] <= edge_split.last_exploration_decision(1)), "month"].unique())
    df = stage2.build_features(df, months)
    p = pd.read_csv(xsection.DATA / "prices_monthly.csv.gz", dtype={"cik": int})
    p = p[p["currency"] == "USD"].sort_values(["cik", "month"]).drop_duplicates(["cik", "month"], keep="last")
    return edge_split.exploration_view(df, prices=p[["cik", "month", "adjclose"]])


def factors_to_2022() -> pd.DataFrame:
    f5 = data_sources.french("F-F_Research_Data_5_Factors_2x3")
    mom = data_sources.french("F-F_Momentum_Factor")
    f = pd.concat([f5.drop(columns=["RF"]), mom], axis=1, sort=True)
    f.columns = [c.strip() for c in f.columns]
    return f[f.index <= edge_split.EXPLORATION_LAST_OUTCOME]


QX_PREFIX = "QX-"


def register_quality_sensitivity(path: Path = edge_registry.PATH) -> list[str]:
    """Register the data-quality sensitivity looks (large caps, 1 month, one per Stage 2 trial) before they run."""
    have = edge_registry.registered(edge_registry.load(path))
    new = []
    for tid, (fam, desc, _) in stage2.TRIALS.items():
        i = f"{QX_PREFIX}{tid}"
        if i in have:
            continue
        edge_registry.append({
            "event": "register", "id": i, "kind": "diagnostic", "phase": "exploration", "hypothesis": fam,
            "definition": f"Stage 2 {tid} ({desc}), IC vs 1-month return, large caps, with the programme's "
                          "data-quality exclusion (edge_split.quality_flags on data cut at 2022-12)",
            "universe": "US large band, Stage 2 filters plus quality_ok", "horizon_months": 1,
            "window": {"decisions": [START[:7], f"{edge_split.last_exploration_decision(1):%Y-%m}"],
                       "outcomes": ["2015-02", "2022-12"]},
            "counts_for_dsr": True, "touched_holdout": False, "source": "research/stage2_diagnostics.py --quality",
            "note": "Phase A verification (owner decision D5): does the exclusion change any Stage 2 conclusion?"},
            path)
        new.append(i)
    return new


def quality_sensitivity(d: pd.DataFrame) -> dict:
    """Large-cap 1-month IC per trial without and with the quality exclusion, on the same scoring as Stage 2.
    Scores are computed on the full cross-section (as Stage 2 does) and the exclusion then removes company-months
    from the evaluation, which is how a universe filter acts on a portfolio."""
    s_h = scored(d, 1)
    out = {}
    for tid in stage2.TRIALS:
        row = {}
        for name, x in (("all", s_h), ("quality_ok", s_h[s_h["quality_ok"]])):
            ics = []
            for mo, g in x[x["band"] == "large"].groupby("month"):
                g = g[[tid, "ret_1m"]].dropna()
                if len(g) >= 30:
                    ics.append((mo, g[tid].rank().corr(g["ret_1m"].rank())))
            st = ic_stats(pd.Series(dict(ics)), 1)
            row[name] = {k: st.get(k) for k in ("months", "mean_ic", "t_nw")}
        row["excluded_rows"] = int((s_h["band"].eq("large") & ~s_h["quality_ok"] & s_h[tid].notna()).sum())
        out[tid] = row
    return out


def quality_report(q: dict, n_trials: int) -> str:
    L = ["# Stage 2 with and without the data-quality exclusion (edge-discovery Phase A verification)", "",
         "Large caps, 1-month IC, decisions 2015-01 to 2022-11 (outcomes to 2022-12), Stage 2's scoring. The "
         "exclusion drops company-months with an adjusted close <= 0 or a share count over 10x or under 1/10 of the "
         "company's median, the median taken on data up to 2022-12 only. Registered before running as "
         f"`{QX_PREFIX}<trial>` diagnostics; the programme's trial count is now {n_trials}.", "",
         "| Trial | IC (all) | t (all) | IC (excl.) | t (excl.) | Months | Large rows excluded |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for tid, r in q.items():
        a, b = r["all"], r["quality_ok"]
        L.append(f"| {tid} | {_f(a['mean_ic'], '.4f')} | {_f(a['t_nw'], '.2f')} | {_f(b['mean_ic'], '.4f')} | "
                 f"{_f(b['t_nw'], '.2f')} | {b['months']} | {r['excluded_rows']:,} |")
    return "\n".join(L) + "\n"


def main_quality(out: Path) -> None:
    new = register_quality_sensitivity()
    print(f"registered {len(new)} quality-sensitivity looks before running")
    for tid in stage2.TRIALS:
        edge_registry.require(f"{QX_PREFIX}{tid}")
    d = investable(load_exploration())
    edge_split.assert_exploration_only(d)
    q = quality_sensitivity(d)
    rel = out.resolve()
    try:
        rel = rel.relative_to(Path(__file__).resolve().parent.parent)
    except ValueError:
        pass
    for tid, r in q.items():
        edge_registry.append({"event": "result", "id": f"{QX_PREFIX}{tid}", "band": "large",
                              "mean_ic": r["quality_ok"]["mean_ic"], "ic_t_nw": r["quality_ok"]["t_nw"],
                              "evidence": f"{rel.with_suffix('.json')}"})
    out.write_text(quality_report(q, edge_registry.n_trials(edge_registry.load())))
    out.with_suffix(".json").write_text(json.dumps(q, indent=1, default=str))
    print(out.read_text())


def main(out: Path) -> None:
    new = register_diagnostics()
    print(f"registered {len(new)} diagnostic looks before running")
    for tid in stage2.TRIALS:  # refuses once results exist: a rerun is a new look and needs new trial ids
        for h in EXTRA_HORIZONS:
            edge_registry.require(f"DIAG-{tid}-h{h}")
    d = investable(load_exploration())
    edge_split.assert_exploration_only(d)
    diag = run(d, factors_to_2022())
    cmp = compare_published(diag, json.loads(PUBLISHED.read_text()))
    events = edge_registry.load()
    rel = out.resolve()
    try:
        rel = rel.relative_to(Path(__file__).resolve().parent.parent)
    except ValueError:
        pass
    record_results(diag, evidence=f"{rel.with_suffix('.json')}")
    out.write_text(report(diag, cmp, edge_registry.n_trials(events)))
    out.with_suffix(".json").write_text(json.dumps({"diagnostics": diag, "reproduction": cmp}, indent=1, default=str))
    print(out.read_text())


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--quality"]:
        main_quality(Path(args[1]) if len(args) > 1 else Path("stage2_quality_sensitivity.md"))
    else:
        main(Path(args[0]) if args else Path("stage2_diagnostics.md"))
