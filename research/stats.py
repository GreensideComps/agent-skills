"""One tested home for the statistics the research loop and the scoreboard rely on.

Why this exists (11 Nov 2026 audit): the deflated Sharpe ratio had been re-typed into about ten research scripts,
each a little different from the registry's pinned formula (no skew or kurtosis term, a fixed 1/T variance, a rounded
constant); the scoreboard carried its own t-distribution code; and the go-live t-test treated trades opened on the
same days as independent. Nothing here changes a past result. New work imports from here, and tests/test_stats.py
checks every function against scipy and against published or hand-worked values.

Pure Python, no third-party imports, so the hosted agent can run the scoreboard with it.

Contents
  t_stat, t_sf, t_crit                 Student t (one-sided tail and critical value)
  cluster_t                            cluster-robust t for trades that share dates (CR1, df = clusters - 1)
  nw_t                                 Newey-West t for an autocorrelated return series
  moments                              mean, sd, per-period Sharpe, skew, raw kurtosis
  expected_max_sharpe, deflated_sharpe Bailey and Lopez de Prado (2014)
  bonferroni, holm, bh_fdr             multiple-testing adjustments
  dsr_bar_t, power, months_needed      what a test can and cannot detect before it is run
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict

EULER_GAMMA = 0.5772156649015329
_ND = statistics.NormalDist()


# ---------------------------------------------------------------- Student t
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularised incomplete beta (Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / (c if abs(c) > tiny else tiny)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / (c if abs(c) > tiny else tiny)
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(ln) * _betacf(a, b, x) / a
    return 1.0 - math.exp(ln) * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """One-sided tail P(T > t) of Student's t with `df` degrees of freedom."""
    if df <= 0:
        raise ValueError("df must be positive")
    half = 0.5 * _betai(df / 2.0, 0.5, df / (df + t * t))
    return half if t >= 0 else 1.0 - half


def t_crit(df: float, p: float) -> float:
    """The t that leaves one-sided tail probability `p` (0 < p < 0.5)."""
    if not 0.0 < p < 0.5:
        raise ValueError("p must be between 0 and 0.5")
    lo, hi = 0.0, 1e6
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_sf(mid, df) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def t_stat(x: list[float]) -> float | None:
    """Plain one-sample t of the mean against zero; None when it cannot be computed."""
    n = len(x)
    if n < 2:
        return None
    sd = statistics.stdev(x)
    return statistics.fmean(x) / (sd / math.sqrt(n)) if sd > 0 else None


# ---------------------------------------------------------------- dependence-robust t
def cluster_t(x: list[float], clusters: list) -> dict:
    """Cluster-robust t of the mean against zero.

    Trades opened in the same period share the market's move, so they are not independent pieces of evidence: thirty
    trades opened in three weeks are closer to three observations than to thirty. This sums the deviations inside
    each cluster before squaring (the CR1 sandwich estimator for a mean), and judges the result against Student's t
    with clusters - 1 degrees of freedom.

    Returns {n, clusters, mean, t_plain, t_cluster, df}; t_cluster is None with fewer than two clusters."""
    n = len(x)
    if n != len(clusters):
        raise ValueError("x and clusters must have the same length")
    if n == 0:
        return {"n": 0, "clusters": 0, "mean": None, "t_plain": None, "t_cluster": None, "df": None}
    mu = statistics.fmean(x)
    sums: dict = defaultdict(float)
    for v, c in zip(x, clusters):
        sums[c] += v - mu
    g = len(sums)
    out = {"n": n, "clusters": g, "mean": mu, "t_plain": t_stat(x), "t_cluster": None, "df": g - 1 if g > 1 else None}
    if g < 2:
        return out
    var = (g / (g - 1)) * sum(s * s for s in sums.values()) / (n * n)
    out["t_cluster"] = mu / math.sqrt(var) if var > 0 else None
    return out


def nw_t(x: list[float], lags: int | None = None) -> float | None:
    """Newey-West t of the mean against zero (Bartlett kernel). Default lags: floor(4 (n/100)^(2/9))."""
    n = len(x)
    if n < 3:
        return None
    if lags is None:
        lags = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lags = max(0, min(lags, n - 1))
    mu = statistics.fmean(x)
    d = [v - mu for v in x]
    lr = sum(v * v for v in d) / n
    for L in range(1, lags + 1):
        lr += 2 * (1 - L / (lags + 1)) * sum(d[i] * d[i - L] for i in range(L, n)) / n
    return mu / math.sqrt(lr / n) if lr > 0 else None


# ---------------------------------------------------------------- Sharpe and its deflation
def moments(x: list[float]) -> dict:
    """{n, mean, sd, sr, skew, kurt}: sd uses n - 1; skew and kurt are the population moments; kurt is raw (normal 3)."""
    n = len(x)
    if n < 3:
        raise ValueError("need at least three observations")
    mu = statistics.fmean(x)
    sd = statistics.stdev(x)
    m2 = sum((v - mu) ** 2 for v in x) / n
    if m2 <= 0:
        raise ValueError("the series is constant")
    m3 = sum((v - mu) ** 3 for v in x) / n
    m4 = sum((v - mu) ** 4 for v in x) / n
    return {"n": n, "mean": mu, "sd": sd, "sr": mu / sd, "skew": m3 / m2 ** 1.5, "kurt": m4 / m2 ** 2}


def expected_max_sharpe(n_trials: int, var: float) -> float:
    """The best per-period Sharpe expected from `n_trials` unrelated tries with no real edge, when Sharpe estimates
    vary across trials with variance `var` (Bailey and Lopez de Prado 2014, eq. 6)."""
    if n_trials < 1:
        raise ValueError("n_trials must be at least 1")
    if n_trials == 1:
        return 0.0
    return math.sqrt(var) * ((1 - EULER_GAMMA) * _ND.inv_cdf(1 - 1 / n_trials)
                             + EULER_GAMMA * _ND.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(sr: float, n_obs: int, skew: float, kurt: float, n_trials: int, var: float | None = None) -> dict:
    """Deflated Sharpe ratio: the chance the true Sharpe is above the best one luck alone would produce in
    `n_trials` tries. `sr` is per period (not annualised), `kurt` is raw (normal = 3), and `var` is the variance of
    Sharpe estimates across trials, never taken below 1/n_obs (its value when no trial has any edge).

    The same formula as edge_registry.deflated_sharpe (which stays pinned); tests check the two agree."""
    if n_obs < 2:
        raise ValueError("n_obs must be at least 2")
    floor = 1.0 / n_obs
    v = max(var or 0.0, floor)
    sr0 = expected_max_sharpe(n_trials, v)
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return {"dsr": _ND.cdf((sr - sr0) * math.sqrt(n_obs - 1) / den), "sr0": sr0, "var_used": v,
            "floor_used": v == floor, "n_trials": n_trials}


def deflated_sharpe_of(x: list[float], n_trials: int, var: float | None = None) -> dict:
    """`deflated_sharpe` straight from a return series, with its own skew and kurtosis (the term the copied
    versions dropped)."""
    m = moments(x)
    return {**deflated_sharpe(m["sr"], m["n"], m["skew"], m["kurt"], n_trials, var), **m}


# ---------------------------------------------------------------- multiple testing
def bonferroni(alpha: float, k: int) -> float:
    return alpha / max(k, 1)


def holm(pvals: list[float], alpha: float = 0.05) -> list[bool]:
    """Holm step-down: which hypotheses are rejected with the family-wise error rate held at `alpha`."""
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    out = [False] * len(pvals)
    for rank, i in enumerate(order):
        if pvals[i] > alpha / (len(pvals) - rank):
            break
        out[i] = True
    return out


def bh_fdr(pvals: list[float], q: float = 0.10, dependent: bool = False) -> list[bool]:
    """Benjamini-Hochberg: which results count as discoveries when at most a share `q` of the discoveries may be
    false. `dependent=True` applies the Benjamini-Yekutieli correction, valid under any dependence between tests."""
    m = len(pvals)
    if m == 0:
        return []
    c = sum(1.0 / i for i in range(1, m + 1)) if dependent else 1.0
    order = sorted(range(m), key=lambda i: pvals[i])
    cut = -1
    for rank, i in enumerate(order, 1):
        if pvals[i] <= q * rank / (m * c):
            cut = rank
    out = [False] * m
    for rank, i in enumerate(order, 1):
        if rank <= cut:
            out[i] = True
    return out


# ---------------------------------------------------------------- what a test can detect
def dsr_bar_t(n_trials: int, confidence: float = 0.95) -> float:
    """The t-statistic a result needs for a deflated Sharpe of `confidence` after `n_trials` tries, when the
    cross-trial variance is at its floor and returns are normal (large-sample form)."""
    return expected_max_sharpe(n_trials, 1.0) + _ND.inv_cdf(confidence)


def power(expected_t: float, needed_t: float) -> float:
    """The chance a test whose true t is `expected_t` comes out at `needed_t` or more."""
    return 1 - _ND.cdf(needed_t - expected_t)


def months_needed(ann_excess: float, ann_te: float, needed_t: float, target_power: float = 0.8) -> float:
    """Months of data for `target_power` to reach `needed_t`, for a true annual excess return `ann_excess` with
    annual tracking error `ann_te`."""
    if ann_excess <= 0:
        return math.inf
    sr_m = (ann_excess / 12) / (ann_te / math.sqrt(12))
    return ((needed_t + _ND.inv_cdf(target_power)) / sr_m) ** 2
