"""Independent worked test of the registered deflated Sharpe ratio (owner, 2026-10-16 13:03Z, item 3).

The reference below re-derives the B5 v2 §5 formula with nothing from the implementation: its own normal CDF
(math.erf), its own inverse CDF (bisection), its own moment estimators and its own choice of which Sharpes enter V.
It is checked against `edge_registry.deflated_sharpe` and `edge_backtest.metrics` / `edge_backtest.dsr` on a
synthetic registry, against numbers fixed in the pre-registration, at every edge case, and at the 0.80 gate.

Spec, exactly as registered (v2 §5; ADDENDUM_1 §4 restates it, no change):
* sr = mean / standard deviation (ddof = 1) of the T monthly excess returns; T = months with both a portfolio and
  a benchmark return (`metrics()["excess_months"]`).
* skew = pandas `Series.skew()`: the adjusted Fisher-Pearson G1 = g1 * sqrt(n(n-1)) / (n-2), g1 = m3 / m2^1.5.
* kurt = pandas `Series.kurt()` + 3: G2 + 3, G2 = ((n+1) g2 + 6)(n-1) / ((n-2)(n-3)), g2 = m4 / m2^2 - 3.
* N = registrations with counts_for_dsr (whatever their result or statistic).
* V = max(sample variance (ddof = 1) of the comparable Sharpes, 1/T). Comparable = results of counted trials whose
  statistic is `portfolio_excess_vs_vwrp`, finite `sr_monthly`; with fewer than two, V = 1/T.
* SR0 = sqrt(V) ((1 - g) Phi^-1(1 - 1/N) + g Phi^-1(1 - 1/(N e))), g = 0.5772156649; SR0 = 0 when N <= 1.
* DSR = Phi((sr - SR0) sqrt(T - 1) / sqrt(max(1 - skew sr + (kurt - 1)/4 sr^2, 1e-12))).
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_b5 as b5  # noqa: E402
import edge_backtest as bt  # noqa: E402
import edge_registry as reg  # noqa: E402

EULER = 0.5772156649
STAT = "portfolio_excess_vs_vwrp"


# ---------- independent reference ----------

def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def phi_inv(p):
    lo, hi = -40.0, 40.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if phi(mid) < p else (lo, mid)
    return (lo + hi) / 2


def moments(x):
    x = [float(v) for v in x]
    n = len(x)
    mu = sum(x) / n
    m2 = sum((v - mu) ** 2 for v in x) / n
    m3 = sum((v - mu) ** 3 for v in x) / n
    m4 = sum((v - mu) ** 4 for v in x) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in x) / (n - 1))
    g1, g2 = m3 / m2 ** 1.5, m4 / m2 ** 2 - 3
    G1 = g1 * math.sqrt(n * (n - 1)) / (n - 2)
    G2 = ((n + 1) * g2 + 6) * (n - 1) / ((n - 2) * (n - 3))
    return {"sr": mu / sd, "skew": G1, "kurt": G2 + 3, "T": n}


def sample_var(v):
    m = sum(v) / len(v)
    return sum((a - m) ** 2 for a in v) / (len(v) - 1)


def ref_dsr(sr, T, skew, kurt, N, comparable):
    V = max(sample_var(comparable), 1 / T) if len(comparable) >= 2 else 1 / T
    sr0 = math.sqrt(V) * ((1 - EULER) * phi_inv(1 - 1 / N) + EULER * phi_inv(1 - 1 / (N * math.e))) if N > 1 else 0.0
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return phi((sr - sr0) * math.sqrt(T - 1) / den), sr0, V


# ---------- synthetic registry ----------

def registry(tmp_path, n_counted=100, comparable=(0.40, 0.10)):
    """n_counted counted registrations. Results: the comparable Sharpes, plus four that must NOT enter V: a legacy
    Stage 2 statistic, a NaN, a counted trial on another statistic, and an uncounted robustness run."""
    p = tmp_path / "trials.jsonl"
    base = {"phase": "exploration", "hypothesis": "h", "definition": "d", "universe": "u", "horizon_months": 1,
            "window": {}, "touched_holdout": False}
    for i in range(n_counted):
        reg.append({"event": "register", "id": f"C{i}", "kind": "trial", "counts_for_dsr": True, **base}, p)
    reg.append({"event": "register", "id": "ROB", "kind": "diagnostic", "counts_for_dsr": False, **base}, p)
    for i, s in enumerate(comparable):
        reg.append({"event": "result", "id": f"C{i}", "evidence": "x", "stat": STAT, "sr_monthly": s}, p)
    k = len(comparable)
    if n_counted >= k + 3:
        reg.append({"event": "result", "id": f"C{k}", "evidence": "x", "sr_monthly": 0.9}, p)  # legacy stat
        reg.append({"event": "result", "id": f"C{k + 1}", "evidence": "x", "stat": STAT, "sr_monthly": float("nan")}, p)
        reg.append({"event": "result", "id": f"C{k + 2}", "evidence": "x", "stat": "other", "sr_monthly": 0.7}, p)
    reg.append({"event": "result", "id": "ROB", "evidence": "x", "stat": STAT, "sr_monthly": 2.0}, p)
    return p


def excess_series(T=94, seed=11):
    rng = np.random.default_rng(seed)
    x = 0.004 + 0.02 * rng.standard_normal(T) - 0.01 * rng.exponential(1.0, T)  # skewed left, fat-ish tails
    return pd.Series(x, index=pd.date_range("2015-02-28", periods=T, freq="ME"))


# ---------- tests ----------

def test_reference_normal_functions_are_accurate():
    assert phi(1.959963984540054) == pytest.approx(0.975, abs=1e-12)
    assert phi_inv(0.99) == pytest.approx(2.3263478740408408, abs=1e-10)


def test_moment_estimators_are_the_ones_pandas_uses():
    x = excess_series()
    m = moments(x)
    assert m["sr"] == pytest.approx(x.mean() / x.std(), rel=1e-12)
    assert m["skew"] == pytest.approx(x.skew(), rel=1e-10) and m["kurt"] == pytest.approx(x.kurt() + 3, rel=1e-10)


def test_v_contains_exactly_the_comparable_counted_finite_sharpes(tmp_path):
    p = registry(tmp_path)
    ev = reg.load(p)
    assert reg.n_trials(ev) == 100  # the uncounted robustness run is not in N
    assert sorted(reg.sharpe_list(ev, STAT)) == [0.10, 0.40]  # legacy, NaN, other-stat and robustness left out


def test_implementation_matches_the_independent_calculation_end_to_end(tmp_path):
    """Excess returns -> metrics() -> dsr() against the reference, on a registry with N = 100 and two comparable
    Sharpes (V = var(0.40, 0.10) = 0.045 > 1/94)."""
    p = registry(tmp_path)
    x = excess_series()
    dates = list(x.index - pd.Timedelta(days=0))
    nav = pd.Series(np.concatenate([[1.0], np.cumprod(1 + x.to_numpy())]),
                    index=pd.DatetimeIndex([x.index[0] - pd.offsets.MonthEnd(1)] + dates))
    bench = pd.DataFrame({"VWRP": 100.0}, index=nav.index)  # flat benchmark: excess = portfolio return
    m = bt.metrics(nav, bench)
    ref = moments(x)
    assert m["excess_months"] == ref["T"] == 94
    assert m["sr_excess_monthly"] == pytest.approx(ref["sr"], rel=1e-10)
    assert m["excess_skew"] == pytest.approx(ref["skew"], rel=1e-9) and m["excess_kurt"] == pytest.approx(ref["kurt"], rel=1e-9)
    got = bt.dsr(m, p)
    want, sr0, V = ref_dsr(ref["sr"], 94, ref["skew"], ref["kurt"], 100, [0.40, 0.10])
    assert V == pytest.approx(0.045) and got["var_used"] == pytest.approx(V, rel=1e-12) and not got["floor_used"]
    assert got["n_trials"] == 100 and got["n_comparable"] == 2
    assert got["sr0"] == pytest.approx(sr0, rel=1e-9) and got["dsr"] == pytest.approx(want, abs=1e-9)


def test_numbers_fixed_in_the_preregistration(tmp_path):
    """N = 100, T = 94, V = 1/94: SR0 = 0.2610; DSR = 0.80 at sr 0.3509 (normal); t = 3 gives 0.68."""
    p = registry(tmp_path, comparable=())
    ev = reg.load(p)
    for sr, skew, kurt in ((0.3509, 0.0, 3.0), (0.3596, -0.5, 4.0), (0.3693, -1.0, 6.0)):
        got = reg.deflated_sharpe(sr, 94, skew, kurt, STAT, ev)
        want, sr0, _ = ref_dsr(sr, 94, skew, kurt, 100, [])
        assert got["sr0"] == pytest.approx(0.2610, abs=5e-5) == sr0
        assert got["dsr"] == pytest.approx(want, abs=1e-9) and got["dsr"] == pytest.approx(0.80, abs=1e-3)
    t3 = reg.deflated_sharpe(3 / math.sqrt(94), 94, 0.0, 3.0, STAT, ev)["dsr"]
    assert t3 == pytest.approx(0.68, abs=0.005)
    two = registry(tmp_path / "b", comparable=(0.10 + math.sqrt(2 / 94 / 2), 0.10 - math.sqrt(2 / 94 / 2)))
    # sample variance of two values d apart is d^2 / 2: here 2/94, the table's last row
    g = reg.deflated_sharpe(0.4609, 94, 0.0, 3.0, STAT, reg.load(two))
    assert g["var_used"] == pytest.approx(2 / 94) and g["dsr"] == pytest.approx(0.80, abs=1e-3)


def test_edge_cases(tmp_path):
    # one comparable result: V is the floor 1/T
    one = reg.load(registry(tmp_path / "one", comparable=(0.4,)))
    g = reg.deflated_sharpe(0.3, 94, 0.0, 3.0, STAT, one)
    assert g["floor_used"] and g["var_used"] == pytest.approx(1 / 94)
    assert g["dsr"] == pytest.approx(ref_dsr(0.3, 94, 0.0, 3.0, reg.n_trials(one), [0.4])[0], abs=1e-9)
    # empirical variance below the floor: floor used
    close = reg.load(registry(tmp_path / "close", comparable=(0.30, 0.31)))
    assert reg.deflated_sharpe(0.3, 94, 0.0, 3.0, STAT, close)["floor_used"]
    # N = 1: SR0 = 0
    single = reg.load(registry(tmp_path / "single", n_counted=1, comparable=()))
    g = reg.deflated_sharpe(0.2, 94, 0.0, 3.0, STAT, single)
    assert g["n_trials"] == 1 and g["sr0"] == 0.0
    assert g["dsr"] == pytest.approx(phi(0.2 * math.sqrt(93) / math.sqrt(1 + 2 / 4 * 0.04)), abs=1e-12)
    # denominator floor: 1 - skew sr + (kurt - 1)/4 sr^2 <= 0 is floored at 1e-12, never a math error
    ev = reg.load(registry(tmp_path / "den", comparable=()))
    g = reg.deflated_sharpe(0.5, 94, 10.0, 1.0, STAT, ev)  # 1 - 5 + 0 = -4
    assert g["dsr"] == pytest.approx(ref_dsr(0.5, 94, 10.0, 1.0, 100, [])[0], abs=1e-12) == 1.0


def test_the_080_gate_is_applied_to_the_computed_dsr():
    base = {"trial": "H1", "t_nw": 3.5, "alpha": 0.01, "alpha_t": 2.5, "excess_2x": 0.1, "excess_vs_universe": 0.1,
            "excess_miss100": 0.1, "excess_nextmonth": 0.1, "excess_dataerr": 0.1, "excess_winq": 0.1,
            "excess_thirds": [0.1, 0.1, 0.1], "excess_without_top_contributor": 0.1}
    assert b5.GATES["P2_dsr"] == 0.80
    assert b5.verdict({**base, "dsr": 0.80})["checks"]["P2"]
    assert not b5.verdict({**base, "dsr": 0.7999})["checks"]["P2"]
    assert not b5.verdict({**base, "dsr": float("nan")})["checks"]["P2"]
    assert not b5.verdict({**base})["checks"]["P2"]  # missing DSR fails closed
