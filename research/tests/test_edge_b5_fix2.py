"""B5 run fix 2 (docs/edge/B5_RUN_FIX_2.md): every robustness variant through the real combined-portfolio path.

Run 1 (D26) stopped in the variant loop because `run_combined` rebased every run at the next-day-close trade date
of the 2015-01-31 decision, and P7 (next-month close) first trades at the 2015-02 month-end. The earlier tests
replaced `run_combined` with a stub, so no test ran a variant through it. These tests run `run_one` and `finish`
end to end on a synthetic world (no research data is read) with the gate's paths pointed at a test copy.

Synthetic only: the numbers here say nothing about any strategy."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_b5 as b5  # noqa: E402
import edge_b5_run as run  # noqa: E402
import edge_b5_stats as st  # noqa: E402
import edge_backtest as bt  # noqa: E402
import edge_registry  # noqa: E402
from test_edge_b5_run import env, make_env, opened, point_gate  # noqa: E402,F401
from test_edge_backtest import flat_fx, month_ends, world  # noqa: E402

MONTHS = month_ends("2014-02-28", 106)  # the first S2a tranche start to the last decision, 2022-11-30
N_COS = 45


def synthetic(crash=None, seed=0):
    """A 45-company world over every month the trials touch. `crash`: (month, factor) multiplies every price from
    that month on, so a loss lands in a known period."""
    rng = np.random.default_rng(seed)
    px = 50 * np.cumprod(1 + 0.01 + 0.05 * rng.standard_normal((len(MONTHS), N_COS)), axis=0)
    if crash is not None:
        k = MONTHS.index(pd.Timestamp(crash[0]))
        px[k:] *= crash[1]
    prices = {c: list(px[:, c - 1]) for c in range(1, N_COS + 1)}
    scores = {c: list(rng.standard_normal(len(MONTHS))) for c in range(1, N_COS + 1)}
    groups = {c: f"g{c % 9}" for c in range(1, N_COS + 1)}
    panel, ex = world(prices, scores, MONTHS, group=groups)
    days = pd.bdate_range("2014-01-01", "2022-12-30")
    bench = pd.DataFrame({"VWRL": 100 * np.cumprod(1 + 0.0003 + 0.008 * rng.standard_normal(len(days)))}, index=days)
    bench["VWRP"] = bench["VWRL"].where(days >= "2019-09-02")
    fm = pd.date_range("2014-01-31", "2022-12-31", freq="ME")
    factors = pd.DataFrame(0.01 * rng.standard_normal((len(fm), len(st.FACTORS))), index=fm, columns=st.FACTORS)
    factors["RF"] = 0.001
    data = {"exec": ex, "fx": flat_fx(MONTHS), "bench": bench, "factors": factors,
            "data_errors": frozenset({(3, pd.Timestamp("2016-03-31")), (7, pd.Timestamp("2019-06-30"))})}
    p9 = panel.assign(quality_ok=~((panel["cik"] == 4) & (panel["month"] >= "2018-01-31")))
    panels = {t: {"primary": panel, "P9": p9} for t in run.TRIALS}
    return panels, data


@pytest.fixture(scope="module")
def world_data():
    return synthetic()


def trade_dates(ex, convention):
    return bt.price_table(ex, convention)[1]


# ---------- the evaluation start under each convention ----------

def test_the_evaluation_start_is_the_first_trade_of_the_2015_01_decision_under_each_convention(world_data):
    ex = world_data[1]["exec"]
    assert run.first_exec_date(ex) == pd.Timestamp("2015-02-02")  # next-day close
    assert run.first_exec_date(ex, "next_month_close") == pd.Timestamp("2015-02-28")  # the 2015-02 month-end
    # next-day close is unchanged from run 1's rule (the earliest execution date of that decision month)
    old = min(pd.Timestamp(d) for d in ex.loc[pd.to_datetime(ex["month"]) == b5.EVAL_FIRST_DECISION, "exec_date"])
    assert run.first_exec_date(ex) == old
    # never before the decision: no trade, and so no evaluation, uses a price before the decision is known
    for conv in ("next_day_close", "next_month_close"):
        assert run.first_exec_date(ex, conv) > pd.Timestamp(b5.EVAL_FIRST_DECISION)


def test_a_missing_first_decision_is_refused_rather_than_moved(world_data):
    ex = world_data[1]["exec"]
    without = ex[pd.to_datetime(ex["month"]) != b5.EVAL_FIRST_DECISION]
    for conv in ("next_day_close", "next_month_close"):
        with pytest.raises(ValueError, match="no .* trade date"):
            run.first_exec_date(without, conv)


# ---------- every variant through run_combined ----------

def variant_runs(env, panels, data, trial):
    k, starts = run.SCHEDULE[trial]
    cfg = run.config(k)
    out = {"primary": (cfg, run.run_combined(run.TRIALS[trial], env["registry"], panels[trial]["primary"], data,
                                             cfg, starts))}
    for gate, (vcfg, transform) in st.robustness_variants(cfg, data["data_errors"]).items():
        panel = panels[trial]["P9"] if gate == "P9" else transform(panels[trial]["primary"])
        rid = run.TRIALS[trial] if gate == "P5" else run.rob_id(trial, gate)
        out[gate] = (vcfg, run.run_combined(rid, env["registry"], panel, data, vcfg, starts))
    return out


@pytest.fixture(scope="module")
def all_runs(world_data, tmp_path_factory):
    """Every primary and variant run of both trials, on a test registry with the run open (module scope: computed
    once)."""
    mp = pytest.MonkeyPatch()
    e = make_env(tmp_path_factory.mktemp("fix2"))
    run.preflight(e["registry"], e["status"], e["manifest"], e["repo"], e["lock"])
    point_gate(mp, e)
    panels, data = world_data
    try:
        yield {t: variant_runs(e, panels, data, t) for t in run.TRIALS}, data
    finally:
        mp.undo()


@pytest.mark.parametrize("trial", sorted(run.TRIALS))
@pytest.mark.parametrize("gate", ["primary", "P4", "P5", "P6", "P7", "P8", "P9"])
def test_each_run_starts_at_its_own_first_trade_and_keeps_every_period_to_the_last_decision(all_runs, trial, gate):
    runs, data = all_runs
    cfg, v = runs[trial][gate]
    dates = trade_dates(data["exec"], cfg.convention)
    first = run.first_exec_date(data["exec"], cfg.convention)
    expected = dates[(dates.index >= b5.EVAL_FIRST_DECISION) & (dates.index <= b5.EVAL_LAST_DECISION)]
    for nav in (v["nav_gbp"], v["nav_usd"]):
        assert nav.index[0] == first and nav.iloc[0] == pytest.approx(1.0)
        assert list(nav.index) == list(expected.values)  # every trade date in the window, none dropped or added
        assert nav.notna().all() and (nav > 0).all()


@pytest.mark.parametrize("trial", sorted(run.TRIALS))
def test_the_window_is_the_primarys_for_every_variant_except_p7_which_is_shifted_one_month(all_runs, trial):
    runs, _ = all_runs
    prim = runs[trial]["primary"][1]["nav_gbp"].index
    assert prim[0] == pd.Timestamp("2015-02-02") and prim[-1] == pd.Timestamp("2022-12-01") and len(prim) == 95
    for gate in ("P4", "P5", "P6", "P8", "P9"):
        assert runs[trial][gate][1]["nav_gbp"].index.equals(prim)
    p7 = runs[trial]["P7"][1]["nav_gbp"].index
    # next-month close: the 2015-01 decision trades at the 2015-02 month-end; the 2022-11 decision would trade at
    # the 2022-12 month-end, which the execution file (decisions to 2022-11) does not carry, so P7's last trade is
    # the 2022-10 decision's, at 2022-11-30: 94 valuation dates against the primary's 95 (B5_RUN_FIX_2 §3)
    assert p7[0] == pd.Timestamp("2015-02-28") and p7[-1] == pd.Timestamp("2022-11-30") and len(p7) == 94
    assert list(p7) == list(pd.date_range("2015-02-28", "2022-11-30", freq="ME"))


@pytest.mark.parametrize("trial", sorted(run.TRIALS))
@pytest.mark.parametrize("gate", ["primary", "P4", "P5", "P6", "P7", "P8", "P9"])
def test_the_combined_nav_is_the_mean_of_every_tranche_rebased_at_that_runs_start(all_runs, trial, gate):
    """Independent recomputation: nothing dropped, nothing filled. The combined NAV's returns compound exactly to
    its last value, so no period's return (gain or loss) is left out."""
    runs, data = all_runs
    cfg, v = runs[trial][gate]
    first = run.first_exec_date(data["exec"], cfg.convention)
    tranches = [r.nav_gbp[r.nav_gbp.index >= first] for r in v["results"]]
    assert len(tranches) == len(run.SCHEDULE[trial][1])
    for t in tranches:
        assert t.index.equals(v["nav_gbp"].index)
    mean = sum(t / t.iloc[0] for t in tranches) / len(tranches)
    assert np.allclose(v["nav_gbp"].to_numpy(), mean.to_numpy(), rtol=0, atol=1e-12)
    r = v["nav_gbp"].pct_change().dropna()
    assert len(r) == len(v["nav_gbp"]) - 1 and np.isclose(np.prod(1 + r), v["nav_gbp"].iloc[-1])


# ---------- losses are not hidden by the rebasing ----------

def combined(panels, data, env, trial, gate):
    k, starts = run.SCHEDULE[trial]
    cfg = run.config(k)
    vcfg, transform = st.robustness_variants(cfg, data["data_errors"])[gate] if gate != "primary" else (cfg, None)
    rid = run.TRIALS[trial] if gate == "primary" else run.rob_id(trial, gate)
    return run.run_combined(rid, env["registry"], panels[trial]["primary"], data, vcfg, starts)["nav_gbp"]


def test_a_crash_inside_the_window_shows_in_both_conventions_and_one_before_it_in_neither(opened):
    # every price falls 40% at the 2015-03 month: a full-invested portfolio loses about 40% in one period
    panels, data = synthetic(crash=("2015-03-31", 0.6), seed=1)
    calm_p, calm_d = synthetic(seed=1)
    for gate in ("primary", "P7"):
        hit = combined(panels, data, opened, "H1", gate).pct_change().dropna()
        calm = combined(calm_p, calm_d, opened, "H1", gate).pct_change().dropna()
        gap = (1 + hit) / (1 + calm) - 1
        assert gap.min() == pytest.approx(-0.4, abs=0.01)  # the loss is in the evaluated returns
        assert (gap.drop(gap.idxmin()).abs() < 1e-9).all()  # and only in the one period it happened
        # P7's first evaluated period (2015-02-28 to 2015-03-31) holds it; the primary's comes a period later
        assert gap.idxmin() == (pd.Timestamp("2015-03-31") if gate == "P7" else pd.Timestamp("2015-04-01"))
    # a crash at the 2015-01 month falls before the evaluation start under both conventions: neither run sees it
    panels, data = synthetic(crash=("2015-01-31", 0.6), seed=1)
    for gate in ("primary", "P7"):
        hit = combined(panels, data, opened, "H1", gate)
        calm = combined(calm_p, calm_d, opened, "H1", gate)
        assert np.allclose(hit.to_numpy(), calm.to_numpy(), atol=1e-9)


# ---------- the defect itself, and the full run ----------

def test_run_1s_start_rule_fails_p7_through_the_real_path(opened, monkeypatch, world_data):
    """How the end-to-end tests catch the run 1 defect: with run 1's rule (next-day close for every run) the same
    call stops exactly as run 1 did."""
    panels, data = world_data
    monkeypatch.setattr(run, "first_exec_date", lambda ex, convention=None: pd.Timestamp("2015-02-02"))
    with pytest.raises(ValueError, match="every tranche must have a NAV on the evaluation start date"):
        run.run_one("H1", panels, data, opened["registry"])


def test_both_trials_run_every_gate_end_to_end_and_finish_records_all_twelve_results_at_once(opened, world_data):
    panels, data = world_data
    runs = {t: run.run_one(t, panels, data, opened["registry"]) for t in run.TRIALS}
    for t, r in runs.items():
        assert set(r["variants"]) == set(run.VARIANT_GATES) and set(r["variant_metrics"]) == set(run.ROB_IDS)
        assert all(len(x.dropna()) > 0 for x in r["variants"].values())
    before = len(edge_registry.load(opened["registry"]))
    report = opened["repo"] / "b5_trials.md"
    pre = {"owner_message": "cmsg_TEST", "manifest_sha256": "test", "n_trials": 102, "check4_complete": False}
    out = run.finish(runs, opened["registry"], opened["status"], "test", report, pre)
    ev = edge_registry.load(opened["registry"])
    assert len(ev) == before + 12 and not edge_registry.validate(opened["registry"])
    assert {e["id"] for e in ev[before:]} == set(run.TRIALS.values()) | {run.rob_id(t, g) for t in run.TRIALS
                                                                          for g in run.ROB_IDS}
    assert report.exists() and not report.with_name(report.name + ".pending").exists()
    assert not list(opened["registry"].parent.glob("*.staged"))
    for t in run.TRIALS:
        assert set(out[t]["verdict"]["checks"]) == set(run.GATES)
        assert out[t]["verdict"]["label"] != "E2 candidate"  # check 4 open in the test status
    assert report.read_text().count("survivorship") >= 1
    text = report.read_text()  # D29: the P7 window disclosure and each trial's own counts (94 and 93 here)
    assert run.P7_WINDOW_DISCLOSURE in text
    for t in run.TRIALS.values():
        assert f"- {t}: primary 94 monthly returns; P7 93 monthly returns." in text


# ---------- tranche combination edge cases (edge_b5.combine_tranches, unchanged) ----------

IDX = pd.date_range("2015-02-28", periods=6, freq="ME")


def test_a_tranche_without_a_nav_on_the_start_date_is_refused():
    a = pd.Series(np.linspace(1, 1.5, 6), index=IDX)
    with pytest.raises(ValueError, match="evaluation start"):
        b5.combine_tranches([a, a.iloc[1:]], IDX[0])  # starts a month late
    with pytest.raises(ValueError, match="evaluation start"):
        b5.combine_tranches([a, a.iloc[:0]], IDX[0])  # empty
    with pytest.raises(ValueError, match="evaluation start"):
        b5.combine_tranches([a, a], IDX[0] - pd.Timedelta(days=1))  # a start no tranche trades on


def test_an_incomplete_tranche_is_refused_rather_than_filled_or_trimmed():
    a = pd.Series(np.linspace(1, 1.5, 6), index=IDX)
    with pytest.raises(ValueError, match="dates differ"):
        b5.combine_tranches([a, a.drop(IDX[3])], IDX[0])  # a missing middle valuation
    with pytest.raises(ValueError, match="dates differ"):
        b5.combine_tranches([a, a.iloc[:-1]], IDX[0])  # ends early


def test_values_before_the_start_are_excluded_from_every_tranche_equally():
    early = pd.Series([1.0, 0.5, 1.0, 1.1, 1.2, 1.3], index=IDX)  # a loss before the start
    late = pd.Series([1.0, 1.0, 2.0, 2.2, 2.4, 2.6], index=IDX)
    c = b5.combine_tranches([early, late], IDX[1])
    assert c.index[0] == IDX[1] and c.iloc[0] == pytest.approx(1.0)
    assert c.iloc[1] == pytest.approx((1.0 / 0.5 + 2.0 / 1.0) / 2)
