"""PR #18 review: invalid prices, execution timing, missing prices, point-in-time flags and the deflated Sharpe."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_integrity  # noqa: E402
import edge_registry  # noqa: E402
import edge_rules  # noqa: E402
import edge_split  # noqa: E402
import stage2  # noqa: E402

# --- invalid (non-positive) prices ---------------------------------------------------------------------------


def _prices(vals, start="2021-01-31", cik=1):
    m = pd.date_range(start, periods=len(vals), freq="ME")
    return pd.DataFrame({"cik": cik, "month": m, "adjclose": vals, "close_raw": [abs(v) for v in vals],
                         "ticker": "X", "currency": "USD"})


def test_no_return_starts_or_ends_on_a_non_positive_price():
    p = _prices([10.0, 11.0, -50.0, -55.0, 12.0, 13.0])
    r = edge_split.forward_return(p, 1)
    assert r.iloc[0] == pytest.approx(0.1)
    assert r.iloc[1:4].isna().all()          # into, within and out of the invalid stretch
    assert r.iloc[4] == pytest.approx(1 / 12)
    r3 = edge_split.forward_return(p, 3)
    assert r3.iloc[:3].isna().all()          # any h-month window touching an invalid price has no return


def test_exploration_view_drops_returns_touching_invalid_prices():
    p = _prices([10.0, 11.0, -50.0, 12.0])
    df = p.drop(columns=["ticker", "currency"])
    v = edge_split.exploration_view(df, horizons=(1,), prices=p[["cik", "month", "adjclose"]])
    assert v["ret_1m"].notna().tolist() == [True, False, False, False]


def test_invalid_price_months_are_never_eligible():
    p = _prices([10.0, -1.0, 10.0]).assign(shares_out=100.0, shares_diluted=100.0)
    q = edge_split.with_quality(p)
    assert q["quality_ok"].tolist() == [True, False, True]


def test_integrity_separates_source_defects_from_programme_exposure():
    p = _prices([10.0, 11.0, -50.0, -55.0, 12.0])
    df = p.assign(shares_out=100.0, shares_diluted=100.0, band="large")
    checks = edge_integrity.check_programme(df, p)
    assert {c["scope"] for c in checks} == {"programme"}
    assert all(c["status"] == "PASS" for c in checks)
    src = [c for c in edge_integrity.check_prices(p) if c["check"] == "prices: positive prices"][0]
    assert src["scope"] == "source" and src["status"] == "FAIL"   # the data defect is still reported as such


# --- execution timing ------------------------------------------------------------------------------------------

def test_execution_is_after_the_information_it_uses():
    t = pd.Timestamp("2020-06-30")
    nd = edge_rules.execution_time(t, "next_day_close")
    nm = edge_rules.execution_time(t, "next_month_close")
    assert nd == pd.Timestamp("2020-07-01") and nm == pd.Timestamp("2020-07-31")
    for ex in (nd, nm):
        edge_rules.assert_executable(t, ex)
    with pytest.raises(edge_rules.LookAhead):
        edge_rules.assert_executable(t, t)            # trading at the decision close is refused
    assert edge_rules.execution_time("2021-07-31") == pd.Timestamp("2021-08-02")  # a Saturday month-end
    with pytest.raises(ValueError):
        edge_rules.execution_time(t, "decision_close")


def test_exploration_trades_cannot_execute_in_the_holdout():
    assert edge_rules.exploration_execution("2022-11-30") == pd.Timestamp("2022-12-01")
    with pytest.raises(edge_split.HoldoutViolation):
        edge_rules.exploration_execution("2022-12-31")
    assert edge_rules.exploration_execution("2022-11-30", "next_month_close") == pd.Timestamp("2022-12-31")
    with pytest.raises(edge_split.HoldoutViolation):
        edge_rules.exploration_execution("2022-12-31", "next_month_close")


def _panel():
    rows = []
    for c in range(1, 41):
        for i, m in enumerate(pd.date_range("2020-01-31", periods=6, freq="ME")):
            rows.append({"cik": c, "month": m, "score_input": c * (1 + 0.01 * i), "last_filed": m - pd.Timedelta(days=5),
                         "ret_1m": 0.0, "exec_price": 100.0})
    return pd.DataFrame(rows)


def _select(frame, t, n=10):
    g = frame[frame["month"] == t]
    return set(g.nlargest(n, "score_input")["cik"])


def test_decision_inputs_exclude_future_rows_returns_and_execution_prices():
    panel, t = _panel(), pd.Timestamp("2020-03-31")
    d = edge_rules.decision_frame(panel, t)
    assert d["month"].max() == t and "ret_1m" not in d and "exec_price" not in d
    base = _select(d, t)
    # change everything a decision must not see: later rows, forward returns, execution prices
    leak = panel.copy()
    later = leak["month"] > t
    leak.loc[later, "score_input"] = -leak.loc[later, "score_input"]
    leak["ret_1m"] = np.random.default_rng(0).normal(size=len(leak))
    leak["exec_price"] = leak["cik"] * 1000.0
    assert _select(edge_rules.decision_frame(leak, t), t) == base


def test_decision_frame_refuses_a_filing_dated_after_its_month():
    panel = _panel()
    panel.loc[0, "last_filed"] = panel.loc[0, "month"] + pd.Timedelta(days=1)
    with pytest.raises(edge_rules.LookAhead):
        edge_rules.decision_frame(panel, "2020-06-30")


# --- missing prices and delistings ---------------------------------------------------------------------------

def _series(vals):
    return pd.Series(vals, index=pd.date_range("2021-01-31", periods=len(vals), freq="ME"), dtype=float)


def test_priced_holding():
    s = _series([10.0, 11.0, 12.0])
    assert edge_rules.holding_return(s, s.index[0], s.index[2]) == (pytest.approx(0.2), "priced")


@pytest.mark.parametrize("mr", [-0.30, -1.0])
def test_disappearing_holding_is_marked_down_from_its_last_price(mr):
    s = _series([10.0, 12.0])  # no price at the third month-end: delisted, acquired or a ticker change
    end = s.index[1] + pd.offsets.MonthEnd(1)
    r, status = edge_rules.holding_return(s, s.index[0], end, missing_return=mr)
    assert status == "missing" and r == pytest.approx(1.2 * (1 + mr) - 1)
    assert r < 12.0 / 10.0 - 1   # never as good as selling at the last observed price


def test_minus_100_percent_stress_loses_the_whole_position():
    s = _series([10.0, 15.0, np.nan])
    assert edge_rules.holding_return(s, s.index[0], s.index[2], missing_return=-1.0)[0] == pytest.approx(-1.0)


def test_invalid_price_mid_holding_ends_the_position():
    s = _series([10.0, 11.0, -40.0, 30.0])   # an adjustment error, then a price again
    r, status = edge_rules.holding_return(s, s.index[0], s.index[3])
    assert status == "missing" and r == pytest.approx(1.1 * 0.7 - 1)


def test_a_missing_price_cannot_be_assumed_favourable():
    s = _series([10.0, 11.0])
    with pytest.raises(ValueError):
        edge_rules.holding_return(s, s.index[0], s.index[1], missing_return=0.05)
    r0, _ = edge_rules.holding_return(s, s.index[0], s.index[1] + pd.offsets.MonthEnd(1), missing_return=0.0)
    assert r0 == pytest.approx(0.1)   # 0% is the optimistic bound: exactly the last-price exit, never more


def test_cannot_buy_at_an_invalid_price():
    s = _series([-5.0, 11.0])
    with pytest.raises(ValueError):
        edge_rules.holding_return(s, s.index[0], s.index[1])


# --- point-in-time share-count flags --------------------------------------------------------------------------

def test_point_in_time_share_flags_use_no_later_rows():
    m = pd.date_range("2018-01-31", periods=24, freq="ME")
    sh = [100.0] * 8 + [2000.0] * 16   # a permanent 20x change, e.g. a merger paid in shares
    df = pd.DataFrame({"cik": 1, "month": m, "shares_out": sh, "shares_diluted": sh})
    pit = edge_split.share_outliers_pit(df)
    assert not pit.iloc[:8].any()              # nothing before the change is flagged with later information
    assert pit.iloc[8]                         # the first months after it are, until the median catches up
    assert not pit.iloc[-1]
    period = edge_split.share_outliers(df)
    assert period.iloc[:8].all()               # the period median flags the earlier months using later rows
    changed = df.copy()
    changed.loc[20:, "shares_out"] = 1e9
    assert edge_split.share_outliers_pit(changed).iloc[:20].equals(pit.iloc[:20])


# --- deflated Sharpe ---------------------------------------------------------------------------------------------

def _reg(i):
    return {"event": "register", "id": i, "kind": "trial", "phase": "exploration", "hypothesis": "H", "definition": "d",
            "universe": "large", "horizon_months": 1, "window": {}, "counts_for_dsr": True, "touched_holdout": False}


def test_dsr_pools_only_comparable_sharpes_but_counts_every_trial(tmp_path):
    p = tmp_path / "t.jsonl"
    srs = [0.05, -0.02, 0.10, 0.01]
    for i, v in enumerate(srs):
        edge_registry.append(_reg(f"P{i}"), p)
        edge_registry.append({"event": "result", "id": f"P{i}", "evidence": "e", "sr_monthly": v,
                              "stat": "portfolio_excess_vs_vwrp"}, p)
    for i in range(3):   # IC-only diagnostics: count as trials, contribute no Sharpe
        edge_registry.append(_reg(f"D{i}"), p)
        edge_registry.append({"event": "result", "id": f"D{i}", "evidence": "e", "mean_ic": 0.01}, p)
    edge_registry.append(_reg("Q0"), p)   # a different Sharpe statistic: never pooled
    edge_registry.append({"event": "result", "id": "Q0", "evidence": "e", "sr_monthly": 3.0}, p)
    edge_registry.append(_reg("M0"), p)   # registered, no result yet: counts, no Sharpe
    ev = edge_registry.load(p)
    assert edge_registry.n_trials(ev) == 9
    assert sorted(edge_registry.sharpe_list(ev, "portfolio_excess_vs_vwrp")) == sorted(srs)
    assert edge_registry.sharpe_list(ev, edge_registry.LEGACY_STAT) == [3.0]
    out = edge_registry.deflated_sharpe(0.3, 96, 0.0, 3.0, "portfolio_excess_vs_vwrp", ev)
    assert out["n_trials"] == 9 and out["n_comparable"] == 4
    assert out["var_used"] == pytest.approx(max(np.var(srs, ddof=1), 1 / 96))


def test_dsr_matches_stage2_formula_when_inputs_agree(tmp_path):
    p = tmp_path / "t.jsonl"
    srs = [0.30, -0.25, 0.10, 0.45, -0.05]   # variance well above the 1/T floor
    for i, v in enumerate(srs):
        edge_registry.append(_reg(f"P{i}"), p)
        edge_registry.append({"event": "result", "id": f"P{i}", "evidence": "e", "sr_monthly": v, "stat": "s"}, p)
    st = {"sr": 0.2, "skew": -0.3, "kurt": 4.0, "n": 120}
    mine = edge_registry.deflated_sharpe(0.2, 120, -0.3, 4.0, "s", edge_registry.load(p))
    assert not mine["floor_used"]
    assert mine["dsr"] == pytest.approx(stage2.deflated_sharpe(st, srs))


def test_dsr_floor_applies_with_too_few_comparable_results(tmp_path):
    p = tmp_path / "t.jsonl"
    for i in range(5):
        edge_registry.append(_reg(f"D{i}"), p)
    out = edge_registry.deflated_sharpe(0.2, 100, 0.0, 3.0, "portfolio_excess_vs_vwrp", edge_registry.load(p))
    assert out["floor_used"] and out["var_used"] == pytest.approx(0.01) and out["n_comparable"] == 0
    assert 0 < out["dsr"] < 1 and math.isfinite(out["sr0"])


def test_committed_registry_dsr_inputs_reconcile():
    ev = edge_registry.load()
    assert edge_registry.n_trials(ev) == 96
    assert len(edge_registry.sharpe_list(ev, edge_registry.LEGACY_STAT)) == 15   # Stage 2's top-quintile Sharpes
    assert edge_registry.sharpe_list(ev, "portfolio_excess_vs_vwrp") == []      # none yet: Phase B adds them


def test_exposures_are_recorded_but_never_counted(tmp_path):
    p = tmp_path / "t.jsonl"
    e = {**_reg("X1"), "kind": "exposure", "touched_holdout": True, "counts_for_dsr": False}
    edge_registry.append(e, p)
    assert edge_registry.n_trials(edge_registry.load(p)) == 0
    with pytest.raises(ValueError):
        edge_registry.append({**e, "id": "X2", "counts_for_dsr": True}, p)
    with pytest.raises(ValueError):   # an exploration trial (not an exposure) still may not touch the holdout
        edge_registry.append({**_reg("X3"), "touched_holdout": True}, p)


def test_report_must_open_with_standing_limitations():
    ok = "# Backtest\n\n" + edge_rules.STANDING_LIMITATIONS + "\nResults..."
    assert edge_rules.require_disclosure(ok) == ok
    assert "Survivorship bias" in edge_rules.STANDING_LIMITATIONS
    with pytest.raises(ValueError):
        edge_rules.require_disclosure("# Backtest\n\nResults first.\n\n" + edge_rules.STANDING_LIMITATIONS)
    with pytest.raises(ValueError):
        edge_rules.require_disclosure("# Backtest\n\nNo disclosure.")
