"""B5 evidence and controls on synthetic data only (owner, 2026-10-16 13:03Z, items 4 and 5). Written before any
trial runs: FF5 + momentum alpha, net excess and thirds, the largest contributor and leave-one-out rerun, the
robustness drivers, the data-error purchase bar, the point-in-time quality flag, and the missing-price paths under
the frozen B5 portfolio configuration."""
import dataclasses
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import edge_b5 as b5  # noqa: E402
import edge_b5_stats as st  # noqa: E402
import edge_backtest as bt  # noqa: E402
from test_edge_backtest import cfg, flat_fx, month_ends, world  # noqa: E402


# ---------- net excess and thirds (P4-P11, P10) ----------

def test_net_excess_is_the_mean_and_thirds_are_consecutive_blocks():
    idx = pd.date_range("2015-02-28", periods=94, freq="ME")
    x = pd.Series(np.arange(94, dtype=float), index=idx)
    assert st.net_excess(x) == pytest.approx(46.5)
    t = st.thirds(x)
    assert t == pytest.approx([np.mean(range(0, 32)), np.mean(range(32, 63)), np.mean(range(63, 94))])  # 32/31/31
    shuffled = x.sample(frac=1, random_state=1)
    assert st.thirds(shuffled) == pytest.approx(t)  # date order, not input order
    assert st.thirds(pd.Series([1.0, -1.0, np.nan, 2.0], index=idx[:4])) == pytest.approx([1.0, -1.0, 2.0])


def test_thirds_feed_p10_two_of_three():
    r = {k: 1.0 for k in ("t_nw", "dsr", "alpha", "alpha_t", "excess_2x", "excess_vs_universe", "excess_miss100",
                          "excess_nextmonth", "excess_dataerr", "excess_pitq", "excess_without_top_contributor")}
    r.update(t_nw=3.5, dsr=0.9, alpha_t=2.5)
    x = pd.Series([1.0] * 32 + [-1.0] * 31 + [1.0] * 31, index=pd.date_range("2015-02-28", periods=94, freq="ME"))
    assert b5.verdict({**r, "excess_thirds": st.thirds(x)})["checks"]["P10"]
    y = pd.Series([1.0] * 32 + [-1.0] * 62, index=x.index)
    assert not b5.verdict({**r, "excess_thirds": st.thirds(y)})["checks"]["P10"]


# ---------- contributions and the leave-one-out rerun (P11) ----------

def test_engine_contributions_match_a_hand_calculation_and_sum_to_each_period_return():
    months = month_ends("2020-01-31", 4)
    prices = {1: [10, 12, 15, 18], 2: [10, 9, 9, 9], 3: [10, 10, 10, 10]}
    panel, ex = world(prices, {1: [3] * 4, 2: [2] * 4, 3: [1] * 4}, months)
    res = bt.run(panel, ex, flat_fx(months), cfg(rebalance_every=2))
    # period 1 (months 0 to 2, half each, base NAV 1): name 1 gains 0.5 x 0.5, name 2 loses 0.5 x 0.1 -> NAV 1.2
    # period 2 (months 2 to 3, half each of 1.2, base 1.2, still open at the end): name 1 gains 0.6 x 0.2 / 1.2
    assert res.contrib[1] == pytest.approx(0.25 + 0.1) and res.contrib[2] == pytest.approx(-0.05)
    nav = res.nav_usd.to_numpy()
    assert 0.25 - 0.05 == pytest.approx(nav[2] / nav[0] - 1) and 0.1 == pytest.approx(nav[3] / nav[2] - 1)  # zero cost


def test_contribution_of_an_exit_uses_the_marked_down_value():
    months = month_ends("2020-01-31", 3)
    prices = {1: [10, 12, 12], 2: [10, 10, 10], 3: [10, 10, 10]}
    panel, ex = world(prices, {1: [3] * 3, 2: [2] * 3, 3: [1] * 3}, months, status={(1, 2): "missing_exec"})
    res = bt.run(panel, ex, flat_fx(months), cfg(rebalance_every=3, missing_return=-0.3))
    assert res.contrib[1] == pytest.approx(0.5 * (1.2 * 0.7 - 1))


def test_largest_contributor_sums_tranches_breaks_ties_by_cik_and_leave_one_out_removes_it():
    assert st.largest_contributor([{1: 0.1, 2: 0.3}, {1: 0.25, 3: 0.0}]) == 1  # 0.35 beats 0.30
    assert st.largest_contributor([{7: 0.2, 5: 0.2}]) == 5
    assert st.largest_contributor([{}]) is None
    months = month_ends("2020-01-31", 3)
    prices = {1: [10, 20, 20], 2: [10, 10, 10], 3: [10, 10, 10]}
    panel, ex = world(prices, {1: [3] * 3, 2: [2] * 3, 3: [1] * 3}, months)
    res = bt.run(panel, ex, flat_fx(months), cfg(rebalance_every=3))
    top = st.largest_contributor([res.contrib])
    assert top == 1
    res2 = bt.run(st.without(panel, top), ex, flat_fx(months), cfg(rebalance_every=3))
    assert all(1 not in h for h in res2.holdings.values()) and res2.nav_usd.iloc[-1] == pytest.approx(1.0)


# ---------- FF5 + momentum alpha (P3) ----------

def factor_world(alpha, n=120, seed=3, ar=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2013-01-31", periods=n, freq="ME")
    F = pd.DataFrame(rng.normal(0.005, 0.04, (n, 6)), index=idx, columns=list(st.FACTORS))
    F["RF"] = 0.001
    beta = np.array([1.0, 0.3, -0.2, 0.1, 0.0, 0.2])
    e = rng.normal(0, 0.01, n)
    for i in range(1, n):
        e[i] += ar * e[i - 1]
    r = F["RF"] + alpha + F[list(st.FACTORS)].to_numpy() @ beta + e
    return pd.Series(r, index=idx), F, beta


def test_factor_alpha_recovers_a_planted_alpha_and_the_betas():
    r, F, beta = factor_world(0.004)
    a = st.factor_alpha(r, F, lags=3)
    assert a["alpha"] == pytest.approx(0.004, abs=0.002) and a["alpha_t"] > 2.0 and a["months"] == 120
    assert list(a["betas"].values()) == pytest.approx(list(beta), abs=0.1)
    z = st.factor_alpha(*factor_world(0.0)[:2], lags=3)
    assert abs(z["alpha_t"]) < 2.0


def test_newey_west_errors_match_statsmodels_hac():
    sm = pytest.importorskip("statsmodels.api")
    r, F, _ = factor_world(0.002, ar=0.5)
    y = (r - F["RF"]).to_numpy()
    X = np.column_stack([np.ones(len(y))] + [F[c].to_numpy() for c in st.FACTORS])
    for lags in (0, 3, 12):
        b, se = st.hac_ols(y, X, lags)
        ref = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": False})
        assert b == pytest.approx(ref.params, rel=1e-10) and se == pytest.approx(ref.bse, rel=1e-8)


def test_factor_alpha_aligns_by_month_and_fails_closed():
    r, F, _ = factor_world(0.004)
    shifted = r.copy()
    shifted.index = shifted.index - pd.Timedelta(days=2)  # trade dates near month-end still map to the month
    assert st.factor_alpha(shifted, F, 3)["alpha"] == pytest.approx(st.factor_alpha(r, F, 3)["alpha"])
    with pytest.raises(KeyError):
        st.factor_alpha(r, F.drop(columns="Mom"), 3)
    assert np.isnan(st.factor_alpha(r.iloc[:20], F, 3)["alpha_t"])


# ---------- robustness drivers (P4-P9) ----------

def test_each_robustness_variant_changes_exactly_one_thing():
    base = bt.Config(n=20, buffer=2.0, sector_cap=4, rebalance_every=3)
    errs = frozenset({(5, pd.Timestamp("2016-01-31"))})
    v = st.robustness_variants(base, errs)
    assert set(v) == {"P4", "P5", "P6", "P7", "P8", "P9"}
    diff = lambda c: {k for k, x in dataclasses.asdict(c).items() if x != dataclasses.asdict(base)[k]}  # noqa: E731
    assert diff(v["P4"][0]) == {"cost_mult"} and v["P4"][0].cost_mult == 2.0
    assert diff(v["P5"][0]) == {"select_all", "cost_mult"} and v["P5"][0].cost_mult == 0.0  # universe, zero cost
    assert diff(v["P6"][0]) == {"missing_return"} and v["P6"][0].missing_return == -1.0
    assert diff(v["P7"][0]) == {"convention"} and v["P7"][0].convention == "next_month_close"
    assert diff(v["P8"][0]) == {"no_buy"} and v["P8"][0].no_buy == errs
    assert diff(v["P9"][0]) == set()
    p = pd.DataFrame({"quality_ok": [True, True], "quality_ok_pit": [True, False]})
    assert list(v["P9"][1](p)["quality_ok"]) == [True, False]
    for k in ("P4", "P5", "P6", "P7", "P8"):
        assert v[k][1](p) is p


def test_data_error_bar_blocks_new_purchases_only():
    months = month_ends("2020-01-31", 4)
    prices = {1: [10] * 4, 2: [10] * 4, 3: [10] * 4}
    panel, ex = world(prices, {1: [3] * 4, 2: [2] * 4, 3: [1] * 4}, months)
    barred = bt.run(panel, ex, flat_fx(months), cfg(no_buy=frozenset({(1, months[0])})))
    assert 1 not in barred.holdings[months[0]] and 1 in barred.holdings[months[1]]
    held = bt.run(panel, ex, flat_fx(months), cfg(no_buy=frozenset({(1, months[1])})))
    assert 1 in held.holdings[months[0]] and 1 in held.holdings[months[1]]  # already held: kept


def test_data_error_months_are_the_registered_twelve():
    moves = pd.read_csv(ROOT.parent / "equity" / "reports" / "research" / "edge" / "exec_prices_audit_moves.csv")
    s = st.data_error_months(moves)
    assert len(s) == 12 and (1540684, pd.Timestamp("2015-01-31")) in s and (1650101, pd.Timestamp("2022-08-31")) in s


def test_point_in_time_quality_uses_no_later_share_counts():
    months = pd.date_range("2015-01-31", periods=6, freq="ME")
    df = pd.DataFrame({"cik": 1, "month": months, "shares_out": [1e6, 1e6, 1e6, 5e7, 5e7, 5e7],
                       "shares_diluted": 1e6, "adjclose": 10.0, "close_raw": 10.0})
    q = st.with_pit_quality(df)
    # point in time: months 3 and 4 are 50x the median of the rows up to them (1e6); by month 5 the median is
    # 2.55e7 and nothing is flagged. A full-window median (2.55e7) would flag none of the six rows either way.
    assert list(q["quality_ok_pit"]) == [True, True, True, False, False, True]


# ---------- verdict inputs fail closed ----------

def test_verdict_inputs_leave_missing_variants_missing_so_the_verdict_fails():
    x = pd.Series([0.01] * 94, index=pd.date_range("2015-02-28", periods=94, freq="ME"))
    full = {k: x for k in ("P4", "P5", "P6", "P7", "P8", "P9", "P11")}
    alpha = {"alpha": 0.003, "alpha_t": 2.5}
    ok = st.verdict_inputs(x, full, None, 3.5, 0.9, alpha, "H1")
    assert all(b5.verdict(ok)["checks"].values())
    part = dict(full)
    del part["P8"]
    r = st.verdict_inputs(x, part, None, 3.5, 0.9, alpha, "H1")
    assert r["excess_dataerr"] is None and not b5.verdict(r)["checks"]["P8"] and b5.verdict(r)["label"] != "E2 candidate"


# ---------- missing-price paths under the frozen B5 configuration (item 4) ----------

def test_missing_price_exit_and_skip_under_the_frozen_b5_portfolio_rules():
    """45 names, N = 20, buffer 2.0, sector cap 4, quarterly, 1x costs: a held name loses its price mid-quarter
    (exit at last price less 30%, logged) and a top-ranked new name has no execution price (skipped, logged, next
    name takes the slot), all inside one `run` call, then combined across the three H1 tranches."""
    months = month_ends("2015-01-31", 7)
    n = 45
    prices = {c: [50.0 + c * 0.1] * 7 for c in range(1, n + 1)}
    scores = {c: [float(n - c)] * 7 for c in range(1, n + 1)}  # cik 1 ranks first
    groups = {c: f"g{c % 9}" for c in range(1, n + 1)}  # 9 groups of 5: the cap of 4 binds
    status = {**{(2, i): "missing_exec" for i in range(2, 7)}, (21, 3): "missing_exec"}  # 2 delists in month 2
    panel, ex = world(prices, scores, months, group=groups, status=status)
    config = bt.Config(n=20, buffer=2.0, sector_cap=4, rebalance_every=3, cost_mult=1.0, missing_return=-0.3)
    navs = []
    for k in range(3):
        res = bt.run(panel, ex, flat_fx(months), config, start=months[k])
        exits = [e for e in res.log if e["event"] == "exit"]
        if k == 0:
            assert [e["cik"] for e in exits] == [2] and exits[0]["return"] == pytest.approx(-0.3)
            assert len(res.holdings[months[0]]) == 20
            assert all(sum(1 for c in res.holdings[months[0]] if groups[c] == g) <= 4 for g in set(groups.values()))
            assert 2 not in res.holdings[months[3]]
        skipped = [e for e in res.log if e["event"] == "skipped_entry"]
        if k == 0:
            # at the 2nd rebalance both the delisted name 2 and name 21 rank in and have no execution price
            assert [e["cik"] for e in skipped] == [2, 21]
            assert len(res.holdings[months[3]]) == 20  # the next eligible name took the slot
        navs.append(res.nav_gbp)
    start = navs[2].index[0]
    combined = b5.combine_tranches(navs, start)
    assert combined.iloc[0] == pytest.approx(1.0) and (combined > 0).all()
