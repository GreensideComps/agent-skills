"""B2 validation tests for the portfolio backtester, on synthetic data only (docs/edge/PHASE_B_PLAN.md §3).

Each test maps to a numbered validation item in the plan; the numbers are in the test names."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_backtest as bt  # noqa: E402
import edge_registry  # noqa: E402
import edge_rules  # noqa: E402
import edge_split  # noqa: E402


# ---------- synthetic worlds ----------

def month_ends(start, n):
    return list(pd.date_range(start, periods=n, freq="ME"))


def exec_date(m):
    return m + pd.offsets.BDay(1)


def world(prices: dict, scores: dict, months, band="large", group=None, quality=None, status=None):
    """prices: cik -> list of execution prices (one per month); scores: cik -> list of scores (None = no score).
    Returns (panel, exec_rows). me_adjclose equals the execution price (no overnight move) unless overridden."""
    pan, ex = [], []
    for c in prices:
        for i, m in enumerate(months):
            s = scores[c][i] if c in scores else None
            pan.append({"cik": c, "month": m, "score": s, "band": band if isinstance(band, str) else band[c],
                        "quality_ok": True if quality is None else quality.get((c, i), True),
                        "group": (group or {}).get(c, f"g{c}"), "close_raw": 50.0, "vol12": 0.2})
            p = prices[c][i]
            st = (status or {}).get((c, i), "ok")
            if st == "absent":
                continue
            ex.append({"cik": c, "ticker": f"T{c}", "month": m.date().isoformat(), "me_date": m.date().isoformat(),
                       "me_adjclose": p, "exec_date": exec_date(m).date().isoformat(),
                       "exec_adjclose": p if st not in ("missing_exec",) else float("nan"),
                       "exec_close": p, "status": st})
    return pd.DataFrame(pan), pd.DataFrame(ex)


def flat_fx(months, rate=1.25):
    idx = pd.bdate_range(months[0] - pd.Timedelta(days=10), exec_date(months[-1]) + pd.Timedelta(days=3))
    return pd.Series(rate, index=idx)


def cfg(**kw):
    base = dict(n=2, buffer=1.0, sector_cap=0, rebalance_every=1, cost_mult=0.0)
    base.update(kw)
    return bt.Config(**base)


def random_world(n_cos=200, n_months=48, alpha=0.02, noise=0.05, seed=0, planted=True):
    rng = np.random.default_rng(seed)
    months = month_ends("2015-01-31", n_months)
    sc = rng.standard_normal((n_months, n_cos))
    px = np.empty((n_months, n_cos))
    px[0] = 50
    for k in range(1, n_months):
        drift = alpha * sc[k - 1] if planted else 0.0
        px[k] = px[k - 1] * (1 + drift + noise * rng.standard_normal(n_cos))
    score_used = sc if planted else rng.standard_normal((n_months, n_cos))
    prices = {c: list(px[:, c]) for c in range(n_cos)}
    scores = {c: list(score_used[:, c]) for c in range(n_cos)}
    return months, *world(prices, scores, months)


# ---------- 1. planted signal ----------

def test_1_planted_signal_earns_the_planted_excess_and_random_scores_do_not():
    months, panel, ex = random_world(seed=1)
    fx = flat_fx(months)
    c = cfg(n=20, cost_mult=0.0)
    s = bt.run(panel, ex, fx, c)
    u = bt.run(panel, ex, fx, cfg(select_all=True))
    excess = (s.nav_usd.pct_change() - u.nav_usd.pct_change()).dropna()
    # expected: alpha x mean score of the top 20 of 200 standard normals (about 1.75)
    top = panel.groupby("month")["score"].apply(lambda x: x.nlargest(20).mean()).mean()
    assert excess.mean() == pytest.approx(0.02 * top, rel=0.25)
    assert excess.mean() / (excess.std() / math.sqrt(len(excess))) > 5
    means = []
    for seed in range(8):
        months, panel, ex = random_world(seed=100 + seed, planted=False)
        s = bt.run(panel, ex, flat_fx(months), cfg(n=20))
        u = bt.run(panel, ex, flat_fx(months), cfg(select_all=True))
        means.append((s.nav_usd.pct_change() - u.nav_usd.pct_change()).dropna().mean())
    assert abs(np.mean(means)) < 0.003


# ---------- 2. hand-computed portfolio ----------

def test_2_hand_computed_portfolio():
    months = month_ends("2020-01-31", 4)
    prices = {1: [10, 11, 12.1, 12.1], 2: [20, 20, 22, 22], 3: [5, 5.5, 5.5, 6], 4: [8, 8, 8, 8], 5: [4, 4, 4, 4]}
    scores = {1: [5, 4, 4, 4], 2: [4, 3, 3, 3], 3: [3, 5, 5, 5], 4: [2, 2, 2, 2], 5: [1, 1, 1, 1]}
    panel, ex = world(prices, scores, months)
    res = bt.run(panel, ex, flat_fx(months, 1.0), cfg(cost_mult=1.0))
    c = 0.0015 + 0.0015  # large band: FX fee + spread
    # month 0: buy 1 and 2 at 50% each; turnover 1.0
    nav0 = 1 * (1 - c)
    a, b = nav0 / 2, nav0 / 2
    # month 1: 1 rises 10%, 2 flat; target 3 and 1 at 50%
    a1, b1 = a * 1.1, b
    nav1 = a1 + b1
    dw1 = abs(0.5 - a1 / nav1) + abs(0 - b1 / nav1) + abs(0.5 - 0)
    nav1c = nav1 * (1 - c * dw1)
    # month 2: 1 rises 10%, 3 flat; rebalance back to 50/50
    a2, c2 = nav1c / 2 * 1.1, nav1c / 2
    nav2 = a2 + c2
    dw2 = abs(0.5 - a2 / nav2) + abs(0.5 - c2 / nav2)
    nav2c = nav2 * (1 - c * dw2)
    # month 3: 1 flat, 3 rises 6/5.5; rebalance again
    a3, c3 = nav2c / 2, nav2c / 2 * 6 / 5.5
    nav3 = a3 + c3
    dw3 = abs(0.5 - a3 / nav3) + abs(0.5 - c3 / nav3)
    nav3c = nav3 * (1 - c * dw3)
    assert list(res.nav_usd.round(12)) == pytest.approx([nav0, nav1c, nav2c, nav3c], abs=1e-12)
    assert res.holdings[months[1]] == {3: 0.5, 1: 0.5}
    assert res.turnover[months[1]] == pytest.approx(dw1 / 2)
    assert res.costs[months[0]] == pytest.approx(c)


# ---------- 3. buffers and sector cap ----------

def test_3_buffer_keeps_ranks_up_to_2n_and_sells_beyond():
    months = month_ends("2020-01-31", 2)
    prices = {i: [10, 10] for i in range(1, 7)}
    scores = {1: [6, 4], 2: [5, 2], 3: [4, 6], 4: [3, 5], 5: [2, 3], 6: [1, 1]}
    panel, ex = world(prices, scores, months)
    res = bt.run(panel, ex, flat_fx(months), cfg(buffer=2.0))
    assert set(res.holdings[months[0]]) == {1, 2}
    # month 1 ranks: 3, 4, 1 (held, rank 3 <= 4: buffer), 5, 2 (held, rank 5 > 4: sold)
    assert set(res.holdings[months[1]]) == {1, 3}
    res = bt.run(panel, ex, flat_fx(months), cfg(buffer=1.0))
    assert set(res.holdings[months[1]]) == {3, 4}


def test_3_sector_cap_is_never_exceeded_and_skips_are_logged():
    months = month_ends("2020-01-31", 1)
    prices = {i: [10] for i in range(1, 6)}
    scores = {1: [5], 2: [4], 3: [3], 4: [2], 5: [1]}
    group = {1: "tech", 2: "tech", 3: "tech", 4: "energy", 5: "energy"}
    panel, ex = world(prices, scores, months, group=group)
    res = bt.run(panel, ex, flat_fx(months), cfg(n=3, sector_cap=2))
    assert set(res.holdings[months[0]]) == {1, 2, 4}
    assert [e["cik"] for e in res.log if e["event"] == "skipped_cap"] == [3]


# ---------- 4. costs by band, scaled exactly ----------

@pytest.mark.parametrize("band,rate", [("large", 0.003), ("mid", 0.0045), ("small", 0.0075)])
def test_4_costs_by_band_and_multiplier(band, rate):
    months = month_ends("2020-01-31", 1)
    panel, ex = world({1: [10], 2: [10]}, {1: [2], 2: [1]}, months, band=band)
    for mult in (1, 2, 3):
        res = bt.run(panel, ex, flat_fx(months), cfg(bands=(band,), cost_mult=mult))
        assert res.costs[months[0]] == pytest.approx(rate * mult)
        assert res.nav_usd.iloc[0] == pytest.approx(1 - rate * mult)


# ---------- 5. exclusions ----------

def test_5_quality_flagged_company_month_is_never_bought():
    months = month_ends("2020-01-31", 2)
    panel, ex = world({1: [10, 10], 2: [10, 10], 3: [10, 10]}, {1: [9, 9], 2: [2, 2], 3: [1, 1]}, months,
                      quality={(1, 0): False, (1, 1): False})
    res = bt.run(panel, ex, flat_fx(months), cfg())
    assert all(1 not in h for h in res.holdings.values())


def test_5_price_below_one_dollar_and_other_bands_are_not_bought():
    months = month_ends("2020-01-31", 1)
    panel, ex = world({1: [10], 2: [10], 3: [10]}, {1: [9], 2: [5], 3: [1]}, months,
                      band={1: "mid", 2: "large", 3: "large"})
    panel.loc[panel["cik"] == 2, "close_raw"] = 0.8
    res = bt.run(panel, ex, flat_fx(months), cfg(n=3))
    assert set(res.holdings[months[0]]) == {3}


# ---------- 6. timing ----------

def test_6_holdings_ignore_everything_after_the_decision():
    months, panel, ex = random_world(n_cos=60, n_months=12, seed=3)
    fx = flat_fx(months)
    base = bt.run(panel, ex, fx, cfg(n=10))
    k = months[5]
    p2 = panel.copy()
    later = pd.to_datetime(p2["month"]) > k
    p2.loc[later, "score"] = -p2.loc[later, "score"]
    e2 = ex.copy()
    e2.loc[pd.to_datetime(e2["exec_date"]) > bt.price_table(ex)[1][k], "exec_adjclose"] *= 3
    alt = bt.run(p2, e2, fx, cfg(n=10))
    for m in months[:6]:
        assert alt.holdings[m] == base.holdings[m]
    assert alt.nav_usd.loc[:bt.price_table(ex)[1][k]].equals(base.nav_usd.loc[:bt.price_table(ex)[1][k]])


def test_6_trades_execute_strictly_after_the_decision_and_never_after_2022():
    months = month_ends("2022-09-30", 3)
    panel, ex = world({1: [10, 10, 10], 2: [10, 10, 10]}, {1: [2, 2, 2], 2: [1, 1, 1]}, months)
    _, dates, _ = bt.price_table(ex)
    assert all(d > m for m, d in dates.items())
    _, dates2, _ = bt.price_table(ex, "next_month_close")
    assert all(d == m + pd.offsets.MonthEnd(1) for m, d in dates2.items())
    late = ex.copy()
    late.loc[late.index[-1], "exec_date"] = "2023-01-03"
    with pytest.raises(edge_split.HoldoutViolation):
        bt.price_table(late)
    p23 = pd.concat([panel, panel.iloc[[0]].assign(month=pd.Timestamp("2023-01-31"))])
    with pytest.raises(edge_split.HoldoutViolation):
        bt.run(p23, ex, flat_fx(months), cfg())
    same_day = ex.copy()
    same_day["exec_date"] = same_day["month"]
    with pytest.raises(edge_rules.LookAhead):
        bt.price_table(same_day)


def test_6_decision_inputs_never_include_execution_columns():
    months = month_ends("2020-01-31", 1)
    panel, ex = world({1: [10], 2: [10]}, {1: [2], 2: [1]}, months)
    panel["exec_adjclose"] = 999.0  # if a decision could see it, it would be dropped before ranking anyway
    panel["ret_1m"] = 0.0
    frame = edge_rules.decision_frame(panel.assign(month=pd.to_datetime(panel["month"])), months[0])
    assert "exec_adjclose" not in frame and "ret_1m" not in frame


# ---------- 7. missing prices ----------

def _two_names(status, months=None, prices=None):
    months = months or month_ends("2020-01-31", 3)
    prices = prices or {1: [10, 12, 12], 2: [10, 10, 10], 3: [10, 10, 10]}
    return months, *world(prices, {1: [3, 3, 3], 2: [2, 2, 2], 3: [1, 1, 1]}, months, status=status)


@pytest.mark.parametrize("st", ["missing_exec", "invalid_price", "absent"])
def test_7_new_entry_without_usable_price_is_skipped_and_logged(st):
    months, panel, ex = _two_names({(1, 0): st})
    if st == "invalid_price":
        ex.loc[(ex["cik"] == 1) & (ex["month"] == months[0].date().isoformat()), "exec_adjclose"] = -1.0
    res = bt.run(panel, ex, flat_fx(months), cfg())
    assert set(res.holdings[months[0]]) == {2, 3}
    assert {"event": "skipped_entry", "cik": 1, "reason": "no execution price"}.items() <= next(
        e for e in res.log if e["event"] == "skipped_entry").items()


def test_7_stale_month_end_blocks_a_new_entry_but_values_a_holding():
    months, panel, ex = _two_names({(1, 0): "stale_month_end"})
    res = bt.run(panel, ex, flat_fx(months), cfg())
    assert 1 not in res.holdings[months[0]]
    months, panel, ex = _two_names({(1, 1): "stale_month_end"})
    res = bt.run(panel, ex, flat_fx(months), cfg(rebalance_every=3))
    assert not [e for e in res.log if e["event"] == "exit"]  # execution close usable, so no exit


@pytest.mark.parametrize("st", ["missing_exec", "invalid_price", "absent"])
def test_7_held_name_losing_its_price_exits_at_last_price_less_markdown(st):
    months, panel, ex = _two_names({(1, 2): st})
    if st == "invalid_price":
        ex.loc[(ex["cik"] == 1) & (ex["month"] == months[2].date().isoformat()), "exec_adjclose"] = 0.0
    res = bt.run(panel, ex, flat_fx(months), cfg(rebalance_every=3, missing_return=-0.3))
    exits = [e for e in res.log if e["event"] == "exit"]
    assert [e["cik"] for e in exits] == [1]
    assert exits[0]["return"] == pytest.approx(12 / 10 * 0.7 - 1)  # last valid 12, then -30%
    assert res.nav_usd.iloc[-1] == pytest.approx(0.5 * 1.2 * 0.7 + 0.5 * 1.0)  # nothing disappears silently


def test_7_missing_price_never_helps():
    navs = {}
    for mr in (0.0, -0.3, -1.0):
        months, panel, ex = _two_names({(1, 2): "missing_exec"}, prices={1: [10, 12, 30], 2: [10, 10, 10],
                                                                        3: [10, 10, 10]})
        navs[mr] = bt.run(panel, ex, flat_fx(months), cfg(rebalance_every=3, missing_return=mr)).nav_usd.iloc[-1]
    assert navs[0.0] >= navs[-0.3] >= navs[-1.0]
    assert navs[-1.0] == pytest.approx(0.5)  # -100% removes the position, the rest stays
    assert navs[0.0] == pytest.approx(0.5 * 1.2 + 0.5)  # even the bound stops at the last price, not 30
    with pytest.raises(ValueError):
        months, panel, ex = _two_names({(1, 2): "missing_exec"})
        bt.run(panel, ex, flat_fx(months), cfg(missing_return=0.1))


def test_7_cash_from_an_exit_earns_nothing_until_the_next_rebalance():
    months = month_ends("2020-01-31", 5)
    prices = {1: [10, 10, 10, 10, 10], 2: [10, 11, 12, 13, 14], 3: [10] * 5}
    panel, ex = world(prices, {1: [3] * 5, 2: [2] * 5, 3: [1] * 5}, months, status={(1, 1): "missing_exec"})
    res = bt.run(panel, ex, flat_fx(months), cfg(rebalance_every=4, missing_return=-0.3))
    cash = 0.5 * 0.7
    assert list(res.nav_usd.iloc[1:4]) == pytest.approx([cash + 0.5 * 1.1, cash + 0.5 * 1.2, cash + 0.5 * 1.3])


# ---------- 8. currency ----------

def test_8_constant_fx_leaves_returns_unchanged_and_a_known_path_converts_exactly():
    months, panel, ex = random_world(n_cos=30, n_months=6, seed=5)
    res = bt.run(panel, ex, flat_fx(months, 1.3), cfg(n=5))
    assert list(res.nav_gbp) == pytest.approx(list(res.nav_usd / res.nav_usd.iloc[0]))
    months = month_ends("2020-01-31", 3)
    panel, ex = world({1: [10, 10, 10], 2: [10, 10, 10]}, {1: [2, 2, 2], 2: [1, 1, 1]}, months)
    fx = flat_fx(months, 1.25)
    fx[fx.index >= exec_date(months[1])] = 1.20
    fx[fx.index >= exec_date(months[2])] = 1.30
    res = bt.run(panel, ex, fx, cfg())
    assert list(res.nav_gbp) == pytest.approx([1.0, 1.25 / 1.20, 1.25 / 1.30])


# ---------- 9. benchmarks ----------

def test_9_tracking_error_and_information_ratio_match_a_hand_calculation():
    idx = pd.DatetimeIndex([exec_date(m) for m in month_ends("2020-01-31", 7)])
    s = pd.Series([1.0, 1.02, 1.01, 1.05, 1.04, 1.08, 1.10], index=idx)
    b_ret = [0.01, 0.0, 0.03, -0.01, 0.02, 0.01]
    bench = pd.DataFrame({"VWRP": np.cumprod([1.0] + [1 + x for x in b_ret])}, index=idx)
    m = bt.metrics(s, bench)
    ex = np.array(s.pct_change().dropna()) - np.array(b_ret)
    assert m["te"] == pytest.approx(ex.std(ddof=1) * math.sqrt(12))
    assert m["ir"] == pytest.approx(ex.mean() * 12 / (ex.std(ddof=1) * math.sqrt(12)))
    assert m["share_months_ahead"] == pytest.approx((ex > 0).mean())
    rel = np.cumprod(1 + np.array(s.pct_change().dropna())) / np.cumprod(1 + np.array(b_ret))
    assert m["relative_drawdown"] == pytest.approx((rel / np.maximum.accumulate(rel) - 1).min())


def test_9_benchmark_labels_switch_at_the_first_valid_vwrp_period():
    days = pd.bdate_range("2019-05-01", "2019-12-31")
    bench = pd.DataFrame({"VWRL": np.linspace(70, 80, len(days))}, index=days)
    bench["VWRP"] = np.where(days >= pd.Timestamp("2019-07-25"), np.linspace(60, 70, len(days)), np.nan)
    dates = pd.DatetimeIndex([exec_date(m) for m in month_ends("2019-05-31", 6)])
    b = bt.benchmark_returns(bench, dates)
    labels = dict(zip(b["start"].dt.date.astype(str), b["label"]))
    assert labels["2019-07-01"] == "VWRL-based"  # VWRP has no price on 1 July
    assert labels["2019-08-01"] == "actual VWRP"  # first period with VWRP at both ends: Aug 2019
    late = bench.copy()
    late.loc[pd.Timestamp("2023-01-03")] = [80, 70]
    with pytest.raises(edge_split.HoldoutViolation):
        bt.benchmark_returns(late, dates)


# ---------- 10. registration and DSR ----------

def _register(path, tid):
    edge_registry.append({"event": "register", "id": tid, "kind": "trial", "phase": "exploration",
                          "hypothesis": "synthetic", "definition": "test", "universe": "synthetic",
                          "horizon_months": 3, "window": {"decisions": ["2015-01", "2018-12"]},
                          "counts_for_dsr": True, "touched_holdout": False}, path)


def test_10_unregistered_or_repeated_trials_are_refused_and_results_record_their_stat(tmp_path):
    reg = tmp_path / "trials.jsonl"
    months, panel, ex = random_world(n_cos=40, n_months=12, seed=7)
    days = pd.bdate_range("2014-12-01", "2016-03-31")
    bench = pd.DataFrame({"VWRP": np.linspace(50, 60, len(days)), "VWRL": np.linspace(50, 60, len(days))}, index=days)
    with pytest.raises(KeyError):
        bt.run_trial("B2-SYN-1", reg, panel, ex, flat_fx(months), cfg(n=5))
    _register(reg, "B2-SYN-1")
    res = bt.run_trial("B2-SYN-1", reg, panel, ex, flat_fx(months), cfg(n=5))
    m = bt.metrics(res.nav_gbp, bench, res)
    bt.record("B2-SYN-1", m, reg, "synthetic test")
    assert json.loads(reg.read_text().splitlines()[-1])["stat"] == bt.STAT
    with pytest.raises(ValueError):
        bt.run_trial("B2-SYN-1", reg, panel, ex, flat_fx(months), cfg(n=5))
    d = bt.dsr(m, reg)
    assert d["n_trials"] == 1 and d["n_comparable"] == 1 and d["floor_used"] and d["stat"] == bt.STAT


def test_10_dsr_pools_only_portfolio_results(tmp_path):
    reg = tmp_path / "trials.jsonl"
    for i, (sr, stat) in enumerate([(0.1, bt.STAT), (0.3, bt.STAT), (0.9, edge_registry.LEGACY_STAT)]):
        _register(reg, f"T{i}")
        edge_registry.append({"event": "result", "id": f"T{i}", "evidence": "x", "stat": stat, "sr_monthly": sr}, reg)
    d = edge_registry.deflated_sharpe(0.2, 96, 0.0, 3.0, bt.STAT, edge_registry.load(reg))
    assert d["n_trials"] == 3 and d["n_comparable"] == 2


def test_report_opens_with_the_standing_limitations():
    r = bt.report("Synthetic", {"cagr": 0.1})
    assert r.split("\n", 2)[2].startswith(edge_rules.STANDING_LIMITATIONS.strip()[:40])


# ---------- weighting and the robustness convention ----------

def test_3_score_and_inverse_volatility_weights():
    months = month_ends("2020-01-31", 1)
    panel, ex = world({1: [10], 2: [10], 3: [10]}, {1: [3], 2: [2], 3: [1]}, months)
    panel["vol12"] = panel["cik"].map({1: 0.1, 2: 0.2, 3: 0.4})
    res = bt.run(panel, ex, flat_fx(months), cfg(n=3, weighting="score"))
    assert res.holdings[months[0]] == pytest.approx({1: 3 / 6, 2: 2 / 6, 3: 1 / 6})
    res = bt.run(panel, ex, flat_fx(months), cfg(n=3, weighting="inv_vol"))
    assert res.holdings[months[0]] == pytest.approx({1: 10 / 17.5, 2: 5 / 17.5, 3: 2.5 / 17.5})
    assert sum(res.holdings[months[0]].values()) == pytest.approx(1.0)


def test_6_next_month_close_convention_trades_at_the_following_month_end():
    months = month_ends("2020-01-31", 4)
    prices = {1: [10, 11, 12.1, 13.31], 2: [10, 10, 10, 10], 3: [10, 10, 10, 10]}
    panel, ex = world(prices, {1: [3] * 4, 2: [2] * 4, 3: [1] * 4}, months)
    res = bt.run(panel, ex, flat_fx(months), cfg(convention="next_month_close"))
    assert list(res.nav_usd.index) == [m + pd.offsets.MonthEnd(1) for m in months[:-1]]
    # held 1 and 2 at equal weight; each period name 1 earns 10%, name 2 nothing, then rebalanced, no costs
    assert list(res.nav_usd) == pytest.approx([1.0, 1.05, 1.05 ** 2])


# ---------- B3 reproduction modes ----------

def test_b3_stage2_top_quintile_matches_the_stage2_harness_rule_including_ties():
    months = month_ends("2020-01-31", 1)
    rng = np.random.default_rng(11)
    n = 47
    scores = {c: [float(rng.integers(0, 6))] for c in range(1, n + 1)}  # many ties
    panel, _ = world({c: [10] for c in scores}, scores, months)
    q = pd.qcut(panel["score"].rank(method="first"), 10, labels=False)
    expected = list(panel.loc[q >= 8, "cik"])
    assert bt.stage2_top_quintile(panel, cfg(n=0)) == expected
    assert bt.stage2_top_quintile(panel.iloc[:29], cfg(n=0)) == []  # Stage 2 skipped such a month


def test_b3_decision_close_is_refused_for_registered_trials(tmp_path):
    reg = tmp_path / "trials.jsonl"
    _register(reg, "B3-X")
    months, panel, ex = random_world(n_cos=40, n_months=3, seed=2)
    with pytest.raises(ValueError):
        bt.run_trial("B3-X", reg, panel, ex, flat_fx(months), cfg(convention=bt.REPRO_CONVENTION))


def test_b3_decision_close_returns_month_end_to_month_end():
    months = month_ends("2020-01-31", 3)
    rows = []
    for c, px in {1: [10, 11, 12.1], 2: [10, 10, 10]}.items():
        for m, p in zip(months, px):
            rows.append({"cik": c, "month": m.date().isoformat(), "me_adjclose": p, "status": "ok",
                         "exec_date": m.date().isoformat()})
    panel, _ = world({1: [10, 11, 12.1], 2: [10, 10, 10]}, {1: [2, 2, 2], 2: [1, 1, 1]}, months)
    res = bt.run(panel, pd.DataFrame(rows), flat_fx(months), cfg(convention=bt.REPRO_CONVENTION))
    assert list(res.nav_usd.index) == months
    assert list(res.nav_usd) == pytest.approx([1.0, 1.05, 1.05 ** 2])
