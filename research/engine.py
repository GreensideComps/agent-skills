"""Monthly-rebalance backtest engine with costs, drift, and statistical tests.

Timing (no look-ahead): at month-end t the strategy sees returns up to and
including month t and returns target weights. Those weights earn month t+1's
returns. Trading cost is charged at the start of t+1 on the one-way turnover
from the drifted weights to the new target (per-asset cost in decimal).

This assumes execution at the month-end close. A daily robustness check with a
one-day execution lag is run separately for the finalists.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

IS_END = "2010-12-31"   # training / in-sample ends
OOS_START = "2011-01-31"

# One-way trading cost (spread + slippage) per asset, decimal. GBP/GBX lines on
# Trading 212 => no 0.15% FX fee; ETFs => no stamp duty. Stressed x3 elsewhere.
COSTS = {"WORLD": 0.0010, "US": 0.0010, "INTL": 0.0015, "EM": 0.0025, "BOND": 0.0010,
         "GOLD": 0.0015, "CASH": 0.0005, "MOM": 0.0020, "VALUE": 0.0020, "QUALITY": 0.0020,
         "MINVOL": 0.0020, "WORLD_ETF": 0.0010}


@dataclass
class Result:
    name: str
    returns: pd.Series      # net monthly returns
    weights: pd.DataFrame   # target weights held during each month
    turnover: pd.Series     # one-way turnover traded at the start of each month


def run(name, R: pd.DataFrame, weight_fn, start=None, end=None, cost_mult=1.0, costs=COSTS) -> Result:
    dates = R.index
    if start is not None:
        dates = dates[dates >= pd.Timestamp(start)]
    if end is not None:
        dates = dates[dates <= pd.Timestamp(end)]
    w_prev = None
    out_r, out_w, out_t = {}, {}, {}
    for t1 in dates:
        i = R.index.get_loc(t1)
        if i == 0:
            continue
        hist = R.iloc[:i]  # data through month t (= t1 - 1), never t1
        w = weight_fn(hist)
        if w is None:
            continue
        w = pd.Series(w, dtype=float)
        w = w[w.abs() > 1e-12]
        assert (w >= -1e-12).all() and w.sum() <= 1 + 1e-9, f"{name}: leverage/shorts not allowed"
        r1 = R.loc[t1, w.index]
        if r1.isna().any():
            raise ValueError(f"{name}: missing return for {list(r1[r1.isna()].index)} at {t1.date()}")
        if w_prev is None:
            turn = w.abs().sum()
            tc = sum(abs(w[a]) * costs.get(a, 0.002) for a in w.index) * cost_mult
        else:
            allk = w.index.union(w_prev.index)
            d = w.reindex(allk, fill_value=0) - w_prev.reindex(allk, fill_value=0)
            turn = d.abs().sum() / 2
            tc = sum(abs(d[a]) * costs.get(a, 0.002) for a in allk) * cost_mult
        cash_w = 1 - w.sum()
        gross = float((w * r1).sum()) + cash_w * float(R.loc[t1, "CASH"])
        net = (1 - tc) * (1 + gross) - 1
        out_r[t1], out_w[t1], out_t[t1] = net, w, turn
        # drift weights to end of month
        grown = w * (1 + r1)
        tot = grown.sum() + cash_w * (1 + R.loc[t1, "CASH"])
        w_prev = grown / tot
    return Result(name, pd.Series(out_r), pd.DataFrame(out_w).T.fillna(0), pd.Series(out_t))


# ---------------------------------------------------------------- metrics

def metrics(r: pd.Series, cash: pd.Series, turnover: pd.Series | None = None) -> dict:
    r = r.dropna()
    c = cash.reindex(r.index)
    n = len(r)
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (12 / n) - 1
    vol = r.std() * np.sqrt(12)
    ex = r - c
    sharpe = ex.mean() / ex.std() * np.sqrt(12) if ex.std() > 0 else np.nan
    dn = ex[ex < 0]
    sortino = ex.mean() * 12 / (np.sqrt((dn ** 2).sum() / n) * np.sqrt(12)) if len(dn) else np.nan
    dd = eq / eq.cummax() - 1
    mdd = dd.min()
    roll12 = (1 + r).rolling(12).apply(np.prod, raw=True) - 1
    return {
        "start": r.index[0].strftime("%Y-%m"), "end": r.index[-1].strftime("%Y-%m"), "months": n,
        "CAGR": cagr, "vol": vol, "Sharpe": sharpe, "Sortino": sortino, "maxDD": mdd,
        "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "worst12m": roll12.min(), "pct_up_months": (r > 0).mean(),
        "turnover_pa": (turnover.reindex(r.index).sum() / n * 12) if turnover is not None else np.nan,
    }


def stationary_bootstrap_idx(n, block, rng):
    idx = np.empty(n, dtype=int)
    p = 1.0 / block
    idx[0] = rng.integers(n)
    for i in range(1, n):
        idx[i] = rng.integers(n) if rng.random() < p else (idx[i - 1] + 1) % n
    return idx


def compare(r_s: pd.Series, r_b: pd.Series, cash: pd.Series, n_boot=5000, block=12, seed=7) -> dict:
    """Paired stationary block bootstrap of Sharpe and CAGR differences.

    Returns one-sided p-values for H0: strategy <= benchmark."""
    j = pd.concat([r_s, r_b, cash.reindex(r_s.index)], axis=1, keys=["s", "b", "c"]).dropna()
    X = j.values
    n = len(X)
    rng = np.random.default_rng(seed)

    def sh(x, c):
        e = x - c
        return e.mean() / e.std() * np.sqrt(12)

    def cg(x):
        return np.exp(np.log1p(x).mean() * 12) - 1

    d_sh0 = sh(X[:, 0], X[:, 2]) - sh(X[:, 1], X[:, 2])
    d_cg0 = cg(X[:, 0]) - cg(X[:, 1])
    d_sh, d_cg = np.empty(n_boot), np.empty(n_boot)
    for k in range(n_boot):
        ii = stationary_bootstrap_idx(n, block, rng)
        x = X[ii]
        d_sh[k] = sh(x[:, 0], x[:, 2]) - sh(x[:, 1], x[:, 2])
        d_cg[k] = cg(x[:, 0]) - cg(x[:, 1])
    # p-value: share of bootstrap draws (centred on the null) at least as large as observed
    p_sh = np.mean(d_sh - d_sh.mean() >= d_sh0)
    p_cg = np.mean(d_cg - d_cg.mean() >= d_cg0)
    return {"dSharpe": d_sh0, "dSharpe_CI90": (np.percentile(d_sh, 5), np.percentile(d_sh, 95)), "p_Sharpe": p_sh,
            "dCAGR": d_cg0, "dCAGR_CI90": (np.percentile(d_cg, 5), np.percentile(d_cg, 95)), "p_CAGR": p_cg}


def deflated_sharpe(sr_monthly_obs: float, n_obs: int, skew: float, kurt: float, sr_trials_monthly: np.ndarray) -> float:
    """Bailey & Lopez de Prado (2014) deflated Sharpe ratio: probability the true
    Sharpe > 0 after correcting for the number/variance of trials tried."""
    from scipy.stats import norm
    N = len(sr_trials_monthly)
    v = np.var(sr_trials_monthly, ddof=1) if N > 1 else 0.0
    emc = 0.5772156649
    sr0 = np.sqrt(v) * ((1 - emc) * norm.ppf(1 - 1 / N) + emc * norm.ppf(1 - 1 / (N * np.e))) if N > 1 else 0.0
    z = (sr_monthly_obs - sr0) * np.sqrt(n_obs - 1) / np.sqrt(1 - skew * sr_monthly_obs + (kurt - 1) / 4 * sr_monthly_obs ** 2)
    return float(norm.cdf(z))
