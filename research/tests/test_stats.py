"""research/stats.py against scipy, the pinned registry formula and hand-worked values."""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import edge_registry  # noqa: E402
import stats  # noqa: E402

scipy_stats = pytest.importorskip("scipy.stats")


def series(n, mu=0.0, sd=1.0, seed=1):
    r = random.Random(seed)
    return [r.gauss(mu, sd) for _ in range(n)]


@pytest.mark.parametrize("df", [1, 2, 5, 13, 29, 120, 1000])
@pytest.mark.parametrize("t", [-3.2, -0.4, 0.0, 0.7, 1.96, 2.61, 4.5, 9.0])
def test_t_tail_matches_scipy(df, t):
    assert stats.t_sf(t, df) == pytest.approx(scipy_stats.t.sf(t, df), rel=1e-9, abs=1e-14)


@pytest.mark.parametrize("df,p", [(29, 0.05), (29, 0.05 / 7), (29, 0.05 / 14), (5, 0.025), (200, 0.001), (3, 0.0001)])
def test_t_critical_value_matches_scipy(df, p):
    assert stats.t_crit(df, p) == pytest.approx(scipy_stats.t.isf(p, df), rel=1e-9)


def test_go_live_rule_worked_figures():
    # GO_LIVE_RULE.md: k = 6 and 30 trades "about 2.54"; Amendment 1: k = 7 "about 2.61"
    assert round(stats.t_crit(29, 0.05 / 6), 2) == 2.54
    assert round(stats.t_crit(29, 0.05 / 7), 2) == 2.61


def test_plain_t_matches_scipy():
    x = series(40, 0.3)
    assert stats.t_stat(x) == pytest.approx(scipy_stats.ttest_1samp(x, 0.0).statistic, rel=1e-12)
    assert stats.t_stat([1.0]) is None and stats.t_stat([2.0, 2.0, 2.0]) is None


def test_cluster_t_equals_plain_t_when_every_trade_is_its_own_cluster():
    x = series(30, 0.2)
    c = stats.cluster_t(x, list(range(30)))
    assert c["clusters"] == 30 and c["df"] == 29
    # with singleton clusters CR1 is the plain estimator apart from the n/(n-1) convention: identical here
    assert c["t_cluster"] == pytest.approx(c["t_plain"], rel=1e-12)


def test_cluster_t_shrinks_when_trades_in_a_cluster_move_together():
    r = random.Random(7)
    x, cl = [], []
    for week in range(6):
        shock = r.gauss(0.01, 0.05)                      # the market's move that week, shared by its 5 trades
        for _ in range(5):
            x.append(shock + r.gauss(0, 0.005))
            cl.append(week)
    c = stats.cluster_t(x, cl)
    assert c["n"] == 30 and c["clusters"] == 6 and c["df"] == 5
    assert abs(c["t_cluster"]) < abs(c["t_plain"]) / 1.5  # thirty trades, about six independent bets
    # the cluster t is the plain t of the six weekly sums' mean, by hand
    mu = sum(x) / 30
    sums = [sum(v - mu for v, k in zip(x, cl) if k == w) for w in range(6)]
    var = (6 / 5) * sum(s * s for s in sums) / 30 ** 2
    assert c["t_cluster"] == pytest.approx(mu / math.sqrt(var), rel=1e-12)


def test_cluster_t_edge_cases():
    assert stats.cluster_t([], [])["t_cluster"] is None
    assert stats.cluster_t([0.1, 0.2, 0.3], ["a", "a", "a"])["t_cluster"] is None   # one cluster: no evidence of spread
    with pytest.raises(ValueError):
        stats.cluster_t([0.1], [])


def test_newey_west_t():
    x = series(120, 0.1)
    assert stats.nw_t(x, 0) == pytest.approx(stats.t_stat(x) * math.sqrt(120 / 119), rel=1e-12)  # no lags: plain, n not n-1
    r = random.Random(3)
    y, prev = [], 0.0
    for _ in range(400):                                  # strongly autocorrelated series
        prev = 0.8 * prev + r.gauss(0.05, 1)
        y.append(prev)
    assert abs(stats.nw_t(y, 12)) < abs(stats.nw_t(y, 0)) / 1.5
    # the improvement track's harness uses the same estimator with 6 lags
    improve = Path("/mnt/project-files/research/improve/")
    if (improve / "harness.py").exists():
        sys.path.insert(0, str(improve))
        import harness  # noqa: PLC0415
        assert round(stats.nw_t(y, 6), 2) == harness.nw_stats(y)["t_nw"]


def test_moments_match_scipy():
    x = [v ** 3 for v in series(200, 0.2)]                # skewed, fat-tailed
    m = stats.moments(x)
    assert m["skew"] == pytest.approx(scipy_stats.skew(x), rel=1e-10)
    assert m["kurt"] == pytest.approx(scipy_stats.kurtosis(x, fisher=False), rel=1e-10)
    assert m["sr"] == pytest.approx(m["mean"] / m["sd"])


def test_expected_max_sharpe_grows_with_trials_and_matches_simulation():
    assert stats.expected_max_sharpe(1, 1.0) == 0.0
    assert stats.expected_max_sharpe(10, 1.0) < stats.expected_max_sharpe(100, 1.0) < stats.expected_max_sharpe(486, 1.0)
    r = random.Random(11)
    sim = sum(max(r.gauss(0, 1) for _ in range(486)) for _ in range(2000)) / 2000
    assert stats.expected_max_sharpe(486, 1.0) == pytest.approx(sim, abs=0.05)


def test_deflated_sharpe_is_the_registry_formula():
    events = []
    for i in range(40):
        events.append({"event": "register", "id": f"T{i}", "counts_for_dsr": True})
        events.append({"event": "result", "id": f"T{i}", "sr_monthly": 0.02 * (i % 7) - 0.05, "stat": "s"})
    n = edge_registry.n_trials(events)
    var = __import__("statistics").variance(edge_registry.sharpe_list(events, "s"))
    for sr, T, sk, ku in [(0.25, 96, -0.4, 5.0), (0.1, 240, 0.0, 3.0), (0.6, 60, 0.8, 9.0)]:
        want = edge_registry.deflated_sharpe(sr, T, sk, ku, "s", events)
        got = stats.deflated_sharpe(sr, T, sk, ku, n, var)
        assert got["dsr"] == pytest.approx(want["dsr"], rel=1e-9)
        assert got["sr0"] == pytest.approx(want["sr0"], rel=1e-9)
        assert got["floor_used"] == want["floor_used"]


def test_deflated_sharpe_basics():
    assert stats.deflated_sharpe(0.2, 100, 0.0, 3.0, 1)["dsr"] == pytest.approx(
        __import__("statistics").NormalDist().cdf(0.2 * math.sqrt(99) / math.sqrt(1 + 0.5 * 0.04)))
    lone = stats.deflated_sharpe(0.3, 96, 0.0, 3.0, 1)["dsr"]
    many = stats.deflated_sharpe(0.3, 96, 0.0, 3.0, 486)["dsr"]
    assert many < lone
    # negative skew and fat tails make the same Sharpe less convincing: the term the copied versions dropped
    assert stats.deflated_sharpe(0.6, 96, -1.0, 8.0, 486)["dsr"] < stats.deflated_sharpe(0.6, 96, 0.0, 3.0, 486)["dsr"]
    x = series(96, 0.3)
    d = stats.deflated_sharpe_of(x, 50)
    assert d["n"] == 96 and 0 <= d["dsr"] <= 1


def test_multiple_testing_adjustments():
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216, 0.222, 0.251, 0.269, 0.275, 0.34]
    # by hand: BH at q = 0.05 keeps only 0.001 (0.008 > 0.05 * 2 / 15); at q = 0.25 the largest rank that fits is 7
    # (0.074 <= 0.25 * 7 / 15 = 0.117, while 0.205 > 0.133)
    assert stats.bonferroni(0.05, 15) == pytest.approx(0.05 / 15)
    assert sum(stats.holm(p, 0.05)) == 1
    assert sum(stats.bh_fdr(p, 0.05)) == 1
    assert sum(stats.bh_fdr(p, 0.25)) == 7
    assert sum(stats.bh_fdr(p, 0.25, dependent=True)) <= sum(stats.bh_fdr(p, 0.25))
    assert stats.bh_fdr([], 0.1) == []
    sm = pytest.importorskip("statsmodels.stats.multitest")
    for q in (0.05, 0.1, 0.25):
        assert stats.bh_fdr(p, q) == list(sm.multipletests(p, q, method="fdr_bh")[0])
        assert stats.bh_fdr(p, q, dependent=True) == list(sm.multipletests(p, q, method="fdr_by")[0])
        assert stats.holm(p, q) == list(sm.multipletests(p, q, method="holm")[0])


def test_power_and_the_bar_after_486_trials():
    bar = stats.dsr_bar_t(486)
    assert 4.5 < bar < 4.8                                # what "DSR >= 0.95 at N = 486" means in t
    assert stats.dsr_bar_t(1) == pytest.approx(1.645, abs=1e-3)
    assert stats.power(bar, bar) == pytest.approx(0.5)
    assert stats.power(2.0, bar) < 0.01                   # a real edge with t = 2 almost never clears it
    # a 3%/yr edge at 10% tracking error needs centuries of months for 80% power at that bar
    assert stats.months_needed(0.03, 0.10, bar) / 12 > 300
    assert stats.months_needed(0.0, 0.10, bar) == math.inf
