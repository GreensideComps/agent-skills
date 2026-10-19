"""Edge-discovery Phase A: the holdout guard, the trial registry, diagnostics maths and integrity flags."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_integrity  # noqa: E402
import edge_registry  # noqa: E402
import edge_split  # noqa: E402
import stage2_diagnostics  # noqa: E402

REGISTRY = Path(__file__).resolve().parent.parent / "edge" / "trials.jsonl"


def panel(start="2021-01-31", months=30, ciks=(1, 2)):
    rows = []
    for c in ciks:
        px = 100.0
        for i, m in enumerate(pd.date_range(start, periods=months, freq="ME")):
            px *= 1.01 + 0.01 * c
            rows.append({"cik": c, "month": m, "adjclose": px, "ret_next": 0.01})
    return pd.DataFrame(rows)


# --- split ---------------------------------------------------------------------------------------------------

def test_last_exploration_decision_per_horizon():
    assert edge_split.last_exploration_decision(1) == pd.Timestamp("2022-11-30")
    assert edge_split.last_exploration_decision(3) == pd.Timestamp("2022-09-30")
    assert edge_split.last_exploration_decision(12) == pd.Timestamp("2021-12-31")
    with pytest.raises(ValueError):
        edge_split.last_exploration_decision(0)


def test_period_of_outcome():
    assert edge_split.period_of_outcome("2022-11-30", 1) == "exploration"
    assert edge_split.period_of_outcome("2022-12-31", 1) == "holdout"
    assert edge_split.period_of_outcome("2022-06-30", 12) == "holdout"  # overlapping outcome reaches 2023
    assert edge_split.period_of_outcome("2026-09-30", 1) == "prospective"
    assert edge_split.period_of_outcome("2026-10-31", 1) == "prospective"
    assert edge_split.period_of_outcome("2011-11-30", 1) == "pre-sample"


def test_exploration_view_cannot_see_a_2023_price():
    df = panel()
    v = edge_split.exploration_view(df)
    assert v["month"].max() == pd.Timestamp("2022-12-31")
    assert v.loc[v["month"] == "2022-12-31", "ret_next"].isna().all()
    assert v.loc[v["month"] > "2021-12-31", "ret_12m"].isna().all()
    assert v.loc[v["month"] == "2022-11-30", "ret_1m"].notna().all()
    # changing every 2023+ price changes nothing in the view
    df2 = df.copy()
    df2.loc[df2["month"] > "2022-12-31", "adjclose"] *= 7
    pd.testing.assert_frame_equal(v, edge_split.exploration_view(df2))


def test_exploration_view_uses_a_separate_price_history():
    df = panel()
    prices = panel()[["cik", "month", "adjclose"]]
    sparse = df[df["month"] != "2022-02-28"]  # a missing metrics row must not break the 1-month return
    v = edge_split.exploration_view(sparse, prices=prices)
    r = v.loc[(v["cik"] == 1) & (v["month"] == "2022-01-31"), "ret_1m"].iloc[0]
    assert abs(r - 0.02) < 1e-12


def test_assert_exploration_only_catches_leaks():
    df = panel()
    with pytest.raises(edge_split.HoldoutViolation):
        edge_split.assert_exploration_only(df)  # rows after 2022
    v = edge_split.exploration_view(df)
    v.loc[v["month"] == "2022-06-30", "ret_12m"] = 0.1
    with pytest.raises(edge_split.HoldoutViolation):
        edge_split.assert_exploration_only(v)


def test_holdout_gate_refuses_by_default():
    assert edge_split.holdout_gate(None, set()) == ["no batch"]
    reasons = edge_split.holdout_gate({"id": "B1", "trials": ["X1"], "prereg_commit": "abc"}, set())
    assert reasons == ["owner has not approved the data split", "portfolio backtester not validated"]
    loose = {"id": "B1", "trials": ["X1"], "prereg_commit": "abc", "owner_split_approval": "yes",
             "backtester_validated": True}
    assert edge_split.holdout_gate(loose, set()) == ["owner has not approved the data split"]
    ok = {**loose, "owner_split_approval": edge_split.OWNER_SPLIT_APPROVAL}
    assert edge_split.holdout_gate(ok, set()) == []
    assert edge_split.holdout_gate(ok, {"B1"}) == ["batch B1 already used the holdout"]


def test_holdout_gate_allows_one_batch_only():
    ok = {"id": "B2", "trials": ["X1"], "prereg_commit": "abc", "owner_split_approval": edge_split.OWNER_SPLIT_APPROVAL,
          "backtester_validated": True}
    assert any("1 confirmation batch" in r for r in edge_split.holdout_gate(ok, {"B1"}))


def test_assert_exploration_only_refuses_unlabelled_forward_columns():
    df = panel("2021-01-31", 12)
    for col in ("fwd_ret", "future_price", "ret_next_q", "outcome"):
        with pytest.raises(edge_split.HoldoutViolation):
            edge_split.assert_exploration_only(df.drop(columns=["ret_next"]).assign(**{col: 0.0}))


def test_quality_flags_use_only_the_cut_period():
    """A share count only seen in 2024 must not change which 2022 rows are flagged."""
    months = list(pd.date_range("2021-01-31", periods=24, freq="ME")) + list(pd.date_range("2023-01-31", periods=30, freq="ME"))
    sh = [100.0] * 24 + [5000.0] * 30  # 50x issuance after the cut
    df = pd.DataFrame({"cik": 1, "month": months, "shares_out": sh, "shares_diluted": sh, "adjclose": 10.0,
                       "close_raw": 10.0})
    full = edge_split.quality_flags(df)
    assert full["share_outlier"].iloc[:24].all()  # uncut: the 2023+ counts dominate the median
    cut = edge_split.with_quality(edge_split.cut_exploration(df))
    assert len(cut) == 24 and cut["quality_ok"].all()
    with pytest.raises(edge_split.HoldoutViolation):
        edge_split.with_quality(df)


def test_cut_exploration_drops_later_rows_and_ret_next():
    df = panel("2022-06-30", 12)
    cut = edge_split.cut_exploration(df)
    assert cut["month"].max() == pd.Timestamp("2022-12-31") and "ret_next" not in cut


def test_cut_series_cuts_benchmarks_and_factors():
    x = pd.Series(1.0, index=pd.date_range("2022-10-31", periods=5, freq="ME"))
    assert edge_split.cut_series(x).index.max() == pd.Timestamp("2022-12-31")


def test_complete_months_drops_the_unfinished_month():
    p = pd.DataFrame({"cik": 1, "month": ["2026-09-30", "2026-10-31"], "adjclose": [1.0, 1.1]})
    assert list(edge_split.complete_months(p, "2026-10-14")["month"]) == ["2026-09-30"]
    late = edge_integrity.check_prices(p.assign(ticker="A", close_raw=1.0, currency="USD"), "2026-10-14")
    flag = [c for c in late if c["check"].startswith("prices: no row labelled")][0]
    assert flag["status"] == "WARN" and "2026-10-31" in flag["detail"]


def test_new_research_code_reads_data_only_through_the_guard():
    """Only these modules may read the research dataset directly. Anything new must go through edge_split
    (cut_exploration / exploration_view), so a holdout outcome cannot be read by a path the guard does not see."""
    allowed = {"xsection.py", "stage2.py", "stage1_coverage.py", "signal_log.py", "edge_integrity.py",
               "stage2_diagnostics.py", "edge_exec_prices.py", "edge_exec_audit.py", "edge_b3_reproduce.py",
               "edge_ttm_checks.py", "edge_b5_handcheck.py", "edge_b5_run.py", "edge_b5_share_pit_audit.py",
               "edge_b5_manifest.py"}
    root = Path(__file__).resolve().parent.parent
    offenders = [f.name for f in root.glob("*.py") if f.name not in allowed
                 and any(k in f.read_text() for k in ("xsection.load(", "prices_monthly", "monthly_metrics"))]
    assert offenders == []
    diag = (root / "stage2_diagnostics.py").read_text()
    assert "edge_split.cut_exploration(xsection.load())" in diag
    b1 = (root / "edge_exec_prices.py").read_text()
    assert "monthly = edge_split.cut_exploration(monthly)" in b1  # cut straight after reading
    audit = (root / "edge_exec_audit.py").read_text()
    assert "edge_split.cut_exploration(xsection.load())" in audit
    b3 = (root / "edge_b3_reproduce.py").read_text()
    assert "x = x[pd.to_datetime(x[\"month\"]) <= CUT]" in b3 and "xsection.load(tmp)" in b3
    assert "edge_split.cut_exploration(pd.read_csv(xsection.DATA / \"prices_monthly.csv.gz\"" in audit
    pit = (root / "edge_b5_share_pit_audit.py").read_text()
    assert "edge_split.cut_exploration(xsection.load())" in pit and 'r["filed"] <= tc.CUT' in pit
    man = (root / "edge_b5_manifest.py").read_text()
    assert "read_csv" not in man and "import xsection" not in man and "gzip" not in man  # hashes, never parses
    ttm = (root / "edge_ttm_checks.py").read_text()
    assert "edge_split.with_quality(edge_split.cut_exploration(xsection.load()))" in ttm
    assert 'r["filed"] <= CUT' in ttm  # SEC facts filed after 2022 are never read into the checks
    hc = (root / "edge_b5_handcheck.py").read_text()
    assert "edge_split.with_quality(edge_split.cut_exploration(xsection.load()))" in hc
    assert hc.count("<= CUT]") >= 3  # raw metrics, raw prices and execution rows cut on read
    rs = (root / "edge_b5_run.py").read_text()
    assert "edge_split.with_quality(edge_split.cut_exploration(xsection.load()))" in rs
    assert 'r["filed"] <= str(CUT.date())' in rs and rs.count("<= CUT]") >= 1  # facts and execution rows cut on read
    ia = (root / "edge_b5_input_audit.py").read_text()
    assert "u = tc.universe()" in ia and 'r["filed"] <= tc.CUT' in ia  # cut universe; no SEC fact filed after 2022
    assert "ret_next" not in ia and "adjclose" not in ia  # input audit reads no price or return


# --- registry ------------------------------------------------------------------------------------------------

def _reg(i, phase="exploration", touched=False, counts=True):
    return {"event": "register", "id": i, "kind": "trial", "phase": phase, "hypothesis": "H1", "definition": "d",
            "universe": "large", "horizon_months": 1, "window": {}, "counts_for_dsr": counts, "touched_holdout": touched}


def test_registry_append_validate_and_count(tmp_path):
    p = tmp_path / "t.jsonl"
    edge_registry.append(_reg("X1"), p)
    edge_registry.append(_reg("X2", counts=False), p)
    edge_registry.append({"event": "result", "id": "X1", "evidence": "f", "sr_monthly": 0.1}, p)
    ev = edge_registry.load(p)
    assert edge_registry.validate(p) == []
    assert edge_registry.n_trials(ev) == 1 and edge_registry.sharpe_list(ev) == [0.1]


def test_registry_rejects_bad_events_and_leaves_file_untouched(tmp_path):
    p = tmp_path / "t.jsonl"
    edge_registry.append(_reg("X1"), p)
    before = p.read_text()
    for bad in (_reg("X1"),                                            # duplicate id
                {"event": "result", "id": "NOPE", "evidence": "f"},     # unknown trial
                _reg("X3", touched=True),                               # exploration trial touching the holdout
                {"event": "holdout_run", "batch": "B9", "evidence": "f"}):  # no such batch
        with pytest.raises(ValueError):
            edge_registry.append(bad, p)
        assert p.read_text() == before


@pytest.fixture
def check4_done(tmp_path, monkeypatch):
    """Batch rules are tested as if the owner had recorded TTM check 4 complete (B5 ADDENDUM_1 §6)."""
    s = tmp_path / "status.json"
    s.write_text('{"ttm_check4_independent_source": {"complete": true}}')
    monkeypatch.setattr(edge_registry, "STATUS", s)
    monkeypatch.setattr(edge_registry.append, "__defaults__", (edge_registry.PATH, s))
    return s


def test_confirmation_batch_is_refused_while_check4_is_open(tmp_path):
    p = tmp_path / "t.jsonl"
    edge_registry.append(_reg("X1"), p)
    before = p.read_text()
    assert edge_registry.check4_complete() is False  # the real status file
    with pytest.raises(ValueError, match="check 4"):
        edge_registry.append({"event": "batch", "batch": "B1", "trials": ["X1"], "prereg_commit": "abc"}, p)
    assert p.read_text() == before


def test_registry_one_holdout_run_per_batch_and_one_batch_per_trial(tmp_path, check4_done):
    p = tmp_path / "t.jsonl"
    edge_registry.append(_reg("X1"), p)
    edge_registry.append({"event": "batch", "batch": "B1", "trials": ["X1"], "prereg_commit": "abc"}, p)
    with pytest.raises(ValueError):
        edge_registry.append({"event": "batch", "batch": "B2", "trials": ["X1"], "prereg_commit": "def"}, p)
    edge_registry.append({"event": "holdout_run", "batch": "B1", "evidence": "f"}, p)
    with pytest.raises(ValueError):
        edge_registry.append({"event": "holdout_run", "batch": "B1", "evidence": "f"}, p)
    assert edge_registry.holdout_runs(edge_registry.load(p)) == {"B1"}


def test_registry_allows_one_batch_ever(tmp_path, check4_done):
    p = tmp_path / "t.jsonl"
    edge_registry.append(_reg("X1"), p)
    edge_registry.append(_reg("X2"), p)
    edge_registry.append({"event": "batch", "batch": "B1", "trials": ["X1"], "prereg_commit": "abc"}, p)
    with pytest.raises(ValueError, match="exceeds"):
        edge_registry.append({"event": "batch", "batch": "B2", "trials": ["X2"], "prereg_commit": "def"}, p)


def test_registry_require_blocks_unregistered_and_repeated_looks(tmp_path):
    p = tmp_path / "t.jsonl"
    with pytest.raises(KeyError):
        edge_registry.require("X1", p)
    edge_registry.append(_reg("X1"), p)
    assert edge_registry.require("X1", p)["id"] == "X1"
    edge_registry.append({"event": "result", "id": "X1", "evidence": "e"}, p)
    with pytest.raises(ValueError):
        edge_registry.require("X1", p)
    with pytest.raises(ValueError, match="second result"):
        edge_registry.append({"event": "result", "id": "X1", "evidence": "e"}, p)


def test_registry_detects_an_edited_line(tmp_path):
    p = tmp_path / "t.jsonl"
    edge_registry.append(_reg("X1"), p)
    edge_registry.append(_reg("X2"), p)
    lines = p.read_text().splitlines()
    e = json.loads(lines[0])
    e["definition"] = "changed after the fact"
    p.write_text(json.dumps(e, sort_keys=True) + "\n" + lines[1] + "\n")
    assert any("hash chain" in x for x in edge_registry.validate(p))


def test_committed_registry_is_valid():
    assert edge_registry.validate(REGISTRY) == []
    ev = edge_registry.load(REGISTRY)
    reg = edge_registry.registered(ev)
    assert all(f"S2-{t}" in reg for t in stage2_diagnostics.stage2.TRIALS)  # Stage 2's 15 count
    assert not edge_registry.holdout_runs(ev)  # Phase A ran no confirmation
    touched = {i for i, e in reg.items() if e["touched_holdout"]}
    assert {"M8-T1", "M8-AUDIT-fcf_per_share", "PROGRAMME-DOC-FACTOR-TABLE"} <= touched
    # no exploration trial touched the holdout; the one exploration-time exposure is recorded as such, uncounted
    assert all(e["phase"] != "exploration" or (e["kind"] == "exposure" and not e["counts_for_dsr"])
               for i, e in reg.items() if i in touched)


# --- diagnostics maths ---------------------------------------------------------------------------------------

def test_nw_se_matches_iid_se_without_autocorrelation_and_grows_with_it():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 5000)
    assert abs(stage2_diagnostics.nw_se(x, 3) / (x.std() / np.sqrt(len(x))) - 1) < 0.1
    ar = np.convolve(rng.normal(0, 1, 5012), np.ones(12), "valid")  # 12-month overlap
    assert stage2_diagnostics.nw_se(ar, 12) > 2 * ar.std() / np.sqrt(len(ar))


def test_ic_stats_mde_and_power():
    rng = np.random.default_rng(1)
    ic = pd.Series(rng.normal(0.0, 0.10, 95))
    s = stage2_diagnostics.ic_stats(ic, 1)
    assert 0.012 < s["mde_ic_t2"] < 0.03  # about 2 x 0.10 / sqrt(95) = 0.021
    se = s["mde_ic_t2"] / 2
    assert abs(s["power_ic_0.02"] - (1 - stage2_diagnostics._N.cdf(2 - 0.02 / se))) < 1e-12
    assert s["n_nonoverlap"] == 95
    s12 = stage2_diagnostics.ic_stats(ic, 12)
    assert s12["nw_lags"] == 12 and s12["n_nonoverlap"] == 8


def test_diagnostics_find_a_planted_signal_at_every_horizon():
    rng = np.random.default_rng(2)
    months = pd.date_range("2015-01-31", "2022-12-31", freq="ME")
    rows = []
    for c in range(80):
        px, z = 100.0, rng.normal()
        for m in months:
            px *= 1 + 0.01 * z + rng.normal(0, 0.05)
            rows.append({"cik": c, "month": m, "adjclose": px, "close_raw": 50.0, "band": "large", "z": z})
    df = edge_split.exploration_view(pd.DataFrame(rows))
    trials = {"P": ("P", "planted", lambda g: g["z"])}
    orig = stage2_diagnostics.stage2.TRIALS
    stage2_diagnostics.stage2.TRIALS = trials
    try:
        out = stage2_diagnostics.run(stage2_diagnostics.investable(df))
    finally:
        stage2_diagnostics.stage2.TRIALS = orig
    for h in (1, 3, 6, 12):
        s = out["P"]["large"][h]
        assert s["mean_ic"] > 0.1 and s["t_nw"] > 3
        assert pd.Timestamp(s["last"]) == edge_split.last_exploration_decision(h)


def test_register_diagnostics_is_idempotent(tmp_path):
    p = tmp_path / "t.jsonl"
    first = stage2_diagnostics.register_diagnostics(p)
    assert len(first) == 15 * 3 and stage2_diagnostics.register_diagnostics(p) == []
    assert edge_registry.validate(p) == []


# --- integrity -----------------------------------------------------------------------------------------------

def test_quality_flags():
    df = pd.DataFrame({"cik": [1] * 5, "shares_out": [100, 100, 100, 1e6, 100], "shares_diluted": [100] * 5,
                       "adjclose": [10, 10, -1, 10, 10], "close_raw": [10] * 5})
    f = edge_integrity.quality_flags(df)
    assert list(f["share_outlier"]) == [False, False, False, True, False]
    assert list(f["bad_price"]) == [False, False, True, False, False]


def test_metrics_checks_catch_look_ahead():
    m = pd.DataFrame({"cik": [1, 1], "month": ["2020-01-31", "2020-02-29"], "last_filed": ["2020-01-15", "2020-03-05"],
                      "ttm_end": ["2019-12-31", "2019-12-31"], "shares_out": [1, 1]})
    res = {c["check"]: c["status"] for c in edge_integrity.check_metrics(m)}
    assert res["metrics: point in time (last filing on or before the month)"] == "FAIL"
    assert res["metrics: one row per company-month"] == "PASS"


def test_stage2_factor_alpha_recovers_planted_alpha_and_betas():
    """Phase A verification of an existing Stage 2 helper that had no test."""
    rng = np.random.default_rng(4)
    idx = pd.date_range("2010-01-31", periods=240, freq="ME")
    f = pd.DataFrame(rng.normal(0, 0.03, (240, 2)), index=idx, columns=["Mkt-RF", "HML"])
    y = 0.004 + 1.2 * f["Mkt-RF"] - 0.5 * f["HML"] + rng.normal(0, 0.005, 240)
    a = stage2_diagnostics.stage2.factor_alpha(y, f)
    assert abs(a["alpha_ann"] - 0.048) < 0.01 and a["alpha_t"] > 5
    assert abs(a["betas"]["Mkt-RF"] - 1.2) < 0.05 and abs(a["betas"]["HML"] + 0.5) < 0.05
    noise = stage2_diagnostics.stage2.factor_alpha(pd.Series(rng.normal(0, 0.02, 240), index=idx), f)
    assert abs(noise["alpha_t"]) < 3


def test_stage2_deflated_sharpe_matches_a_hand_computation():
    """DSR with 10 trials: the benchmark Sharpe is the expected maximum of 10 unskilled trials."""
    from statistics import NormalDist
    N = NormalDist()
    srs = [0.0, 0.05, -0.05, 0.1, -0.1, 0.02, -0.02, 0.08, -0.08, 0.15]
    st = {"sr": 0.15, "skew": 0.0, "kurt": 3.0, "n": 96}
    v = np.var(srs, ddof=1)
    g = 0.5772156649
    sr0 = np.sqrt(v) * ((1 - g) * N.inv_cdf(1 - 1 / 10) + g * N.inv_cdf(1 - 1 / (10 * np.e)))
    want = N.cdf((0.15 - sr0) * np.sqrt(95) / np.sqrt(1 + 0.5 * 0.15 ** 2))
    assert abs(stage2_diagnostics.stage2.deflated_sharpe(st, srs) - want) < 1e-12


def test_backtester_validated_status_is_scoped_to_exploration():
    """D12: the recorded status is exploration-only and authorises neither confirmation nor demo allocation."""
    import json
    s = json.loads((Path(__file__).resolve().parents[1] / "edge" / "status.json").read_text())
    bv = s["backtester_validated"]
    assert bv["value"] is True and bv["scope"].startswith("exploratory research only")
    assert bv["authorises_confirmation"] is False and bv["authorises_demo_allocation"] is False
    assert s["survivorship_limitation_accepted"]["scope"].startswith("exploratory research only")
