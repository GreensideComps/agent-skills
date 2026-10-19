"""B5 evidence and controls: the summaries `edge_b5.verdict` needs, defined before any trial runs.

Owner, 2026-10-16 13:03Z, item 5: preparatory engineering only, synthetic tests first
(research/tests/test_edge_b5_stats.py). Nothing here reads data or runs a trial. Definitions are in
docs/edge/B5_PREREGISTRATION_ADDENDUM_1.md §5:

* net excess: the arithmetic mean of the monthly net excess returns over the months the statistic covers;
  "net excess > 0" in P4-P11 means this mean is > 0;
* thirds (P10): the T excess months split in date order into three consecutive blocks with `numpy.array_split`
  (sizes differ by at most one, earlier blocks larger), each block's mean;
* largest contributor (P11): the company with the largest summed contribution (`edge_backtest.Result.contrib`)
  across all tranches of the primary run, ties broken by lower CIK; the trial is rerun with that company never
  bought, and its net excess must stay > 0;
* FF5 + momentum alpha (P3): OLS of the combined USD return less the risk-free rate on Mkt-RF, SMB, HML, RMW,
  CMA and Mom, with a Newey-West (Bartlett) standard error at the trial's lag (H1 3, S2a 12);
* robustness drivers (P4-P9): each is the primary configuration with exactly one change (`robustness_variants`).
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

import edge_b5 as b5

FACTORS = ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom")


def net_excess(excess: pd.Series) -> float:
    x = pd.Series(excess, dtype=float).dropna()
    return float(x.mean()) if len(x) else float("nan")


def thirds(excess: pd.Series) -> list[float]:
    x = pd.Series(excess, dtype=float).dropna().sort_index()
    return [float(b.mean()) if len(b) else float("nan") for b in np.array_split(x.to_numpy(), 3)]


def largest_contributor(contribs: list[dict]) -> int | None:
    """The CIK with the largest total contribution across tranches (ties: lower CIK)."""
    tot: dict = {}
    for c in contribs:
        for k, v in c.items():
            tot[k] = tot.get(k, 0.0) + v
    if not tot:
        return None
    return min(tot, key=lambda k: (-tot[k], k))


def without(panel: pd.DataFrame, cik) -> pd.DataFrame:
    """The panel with one company never eligible (its score removed in every month)."""
    return panel.assign(score=panel["score"].where(panel["cik"] != cik))


def hac_ols(y: np.ndarray, X: np.ndarray, lags: int) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients and Newey-West (Bartlett) standard errors, no small-sample correction:
    V = (X'X)^-1 S (X'X)^-1, S = sum_t u_t^2 x_t x_t' + sum_l w_l sum_t u_t u_(t-l) (x_t x_(t-l)' + x_(t-l) x_t'),
    w_l = 1 - l / (lags + 1)."""
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    Z = X * u[:, None]
    S = Z.T @ Z
    for L in range(1, lags + 1):
        G = Z[L:].T @ Z[:-L]
        S += (1 - L / (lags + 1)) * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return b, np.sqrt(np.diag(V))


def factor_alpha(r_usd: pd.Series, factors: pd.DataFrame, lags: int) -> dict:
    """FF5 + momentum alpha of a monthly USD return series. `factors` holds FACTORS and RF (decimal, monthly),
    indexed by month. Months missing either side are dropped; fewer than 24 months or a missing factor fails."""
    missing = [c for c in FACTORS + ("RF",) if c not in factors]
    if missing:
        raise KeyError(f"factor columns missing: {missing}")
    r = pd.Series(r_usd, dtype=float).copy()
    r.index = pd.to_datetime(r.index).to_period("M")
    f = factors.copy()
    f.index = pd.to_datetime(f.index).to_period("M")
    j = pd.concat([r.rename("r"), f], axis=1, join="inner").dropna()
    if len(j) < 24:
        return {"alpha": float("nan"), "alpha_t": float("nan"), "months": int(len(j))}
    y = (j["r"] - j["RF"]).to_numpy()
    X = np.column_stack([np.ones(len(j))] + [j[c].to_numpy() for c in FACTORS])
    b, se = hac_ols(y, X, lags)
    return {"alpha": float(b[0]), "alpha_t": float(b[0] / se[0]) if se[0] > 0 else float("nan"),
            "betas": dict(zip(FACTORS, map(float, b[1:]))), "months": int(len(j))}


def data_error_months(moves: pd.DataFrame) -> frozenset:
    """The B1-SENS-DATA-ERRORS company-months (registered 2026-10-15): eligible-universe rows (banded, quality ok)
    whose decision-to-execution move edge_exec_audit labels split_like, extreme or reversal."""
    m = moves[moves["class"].isin(["split_like", "extreme", "reversal"]) & moves["band"].isin(["large", "mid", "small"])
              & (moves["quality_ok"] == True)]  # noqa: E712
    return frozenset((int(c), pd.Timestamp(d)) for c, d in zip(m["cik"], m["month"]))


def robustness_variants(cfg, data_errors: frozenset) -> dict:
    """Gate -> (Config, panel transform). Exactly one change from the primary configuration each.

    P4 2x costs; P5 the equal-weighted eligible universe at zero cost (benchmark, compared with the primary);
    P6 missing prices at -100%; P7 next-month-close execution; P8 the data-error company-months barred from new
    purchases; P9 the reverse veto of ADDENDUM_3: the Phase A full-window quality rule (the panel's `quality_ok`,
    which is the point-in-time rule in the primary, replaced by `quality_ok_window`). `edge_b5_run` builds the P9
    panel itself (`score_panels`) so that S2a is re-ranked within that rule's population."""
    rep = dataclasses.replace
    keep = lambda p: p  # noqa: E731
    return {
        "P4": (rep(cfg, cost_mult=2.0 * cfg.cost_mult), keep),
        "P5": (rep(cfg, select_all=True, cost_mult=0.0), keep),
        "P6": (rep(cfg, missing_return=-1.0), keep),
        "P7": (rep(cfg, convention="next_month_close"), keep),
        "P8": (rep(cfg, no_buy=frozenset(data_errors)), keep),
        "P9": (cfg, lambda p: p.assign(quality_ok=p[b5.VETO_QUALITY])),
    }


def verdict_inputs(primary_excess: pd.Series, variants: dict, nonoverlap_t: float | None, t_nw: float,
                   dsr: float, alpha: dict, trial: str) -> dict:
    """The dict `edge_b5.verdict` reads. `variants` maps gate -> that run's monthly excess series (P5: the
    primary's excess over the universe's return). Any missing piece stays missing, so the verdict fails closed."""
    ne = lambda k: net_excess(variants[k]) if k in variants else None  # noqa: E731
    return {"trial": trial, "t_nw": t_nw, "t_nonoverlap": nonoverlap_t, "dsr": dsr,
            "alpha": alpha.get("alpha"), "alpha_t": alpha.get("alpha_t"),
            "excess_2x": ne("P4"), "excess_vs_universe": ne("P5"), "excess_miss100": ne("P6"),
            "excess_nextmonth": ne("P7"), "excess_dataerr": ne("P8"), "excess_winq": ne("P9"),
            "excess_thirds": thirds(primary_excess), "excess_without_top_contributor": ne("P11")}


def with_pit_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `quality_ok_pit`, the B5 PRIMARY quality rule from ADDENDUM_3 (D20): the price flag plus the share-count
    outlier flag with the median taken point in time (`edge_split.share_outliers_pit`). Until ADDENDUM_3 this was
    the P9 sensitivity rule."""
    import edge_split
    bad = (df["adjclose"] <= 0) | (df["close_raw"] <= 0) | edge_split.share_outliers_pit(df)
    return df.assign(quality_ok_pit=~bad)


def with_quality_columns(df: pd.DataFrame) -> pd.DataFrame:
    """ADDENDUM_3: both quality rules side by side, and NO `quality_ok` column, so no code can pick one implicitly.
    `quality_ok_pit` (primary) and `quality_ok_window` (the Phase A rule, D5, P9 reverse veto only). `df` must be
    cut to the exploration period (`edge_split.with_quality` refuses otherwise)."""
    import edge_split
    out = edge_split.with_quality(df).rename(columns={"quality_ok": b5.VETO_QUALITY})
    return with_pit_quality(out)
