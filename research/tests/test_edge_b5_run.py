"""Controls of the B5 run script (edge_b5_run). Synthetic only: no research data is read and no trial is run.

Owner, 2026-10-16 14:17Z, item 5: evidence that the script cannot silently omit a gate or selectively rerun a
trial, and that both results exist before the shared DSR."""
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_b5 as b5  # noqa: E402
import edge_b5_addendum3  # noqa: E402
import edge_b5_run as run  # noqa: E402
import edge_backtest as bt  # noqa: E402
import edge_registry  # noqa: E402
import edge_rules  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def env(tmp_path):
    """A copy of the repo's frozen specs and registry, with a manifest and an owner authorisation, in tmp."""
    docs = tmp_path / "docs" / "edge"
    docs.mkdir(parents=True)
    for f in ("B5_PREREGISTRATION.md", "B5_PREREGISTRATION_ADDENDUM_1.md", "B5_PREREGISTRATION_ADDENDUM_2.md",
              "B5_PREREGISTRATION_ADDENDUM_3.md"):
        shutil.copy(REPO / "docs" / "edge" / f, docs / f)
    (tmp_path / "in.csv").write_text("a,b\n1,2\n")
    (tmp_path / "code.py").write_text("x = 1\n")
    man = docs / "B5_RUN_MANIFEST.json"
    man.write_text(json.dumps({"inputs": {"in.csv": sha(tmp_path / "in.csv")},
                               "code": {"code.py": sha(tmp_path / "code.py")}}))
    reg = tmp_path / "trials.jsonl"
    shutil.copy(edge_registry.PATH, reg)
    have = edge_registry.registered(edge_registry.load(reg))
    base = {"event": "register", "kind": "diagnostic", "phase": "exploration", "hypothesis": "none",
            "universe": "as B5 v2", "horizon_months": 0, "window": {}, "counts_for_dsr": False,
            "touched_holdout": False}
    if "B5-V2-ADDENDUM-2" not in have:
        edge_registry.append({**base, "id": "B5-V2-ADDENDUM-2", "definition": "test",
                              "spec_sha256": sha(docs / "B5_PREREGISTRATION_ADDENDUM_2.md")}, reg)
    edge_b5_addendum3.register("cmsg_TEST_ADD3", reg, tmp_path)  # the prepared events, as the owner would approve
    edge_registry.append({**base, "id": "B5-V2-RUN-MANIFEST", "definition": "test", "spec_sha256": sha(man)}, reg)
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"ttm_check4_independent_source": {"complete": False},
                                  "b5_trial_run": {"authorised": True, "owner_message": "cmsg_TEST"}}))
    return {"registry": reg, "status": status, "manifest": man, "repo": tmp_path, "lock": tmp_path / "b5.lock"}


def pre(e):
    return run.preflight(e["registry"], e["status"], e["manifest"], e["repo"], e["lock"])


@pytest.fixture
def opened(env, monkeypatch):
    """env with the run open: the gate's fixed paths pointed at env's authorised status and a lock preflight took.
    Only a test can repoint them; production code has no parameter for it."""
    pre(env)
    monkeypatch.setattr(edge_registry, "STATUS", env["status"])
    monkeypatch.setattr(edge_registry, "B5_LOCK", env["lock"])
    return env


def test_preflight_passes_once_and_the_lock_refuses_a_second_start(env):
    out = pre(env)
    assert out["owner_message"] == "cmsg_TEST" and out["n_trials"] == 100 and out["check4_complete"] is False
    assert env["lock"].exists()
    with pytest.raises(ValueError, match="lock"):
        pre(env)


@pytest.mark.parametrize("auth", [None, {"authorised": False, "owner_message": "cmsg_X"},
                                  {"authorised": True}, {"authorised": "yes", "owner_message": "cmsg_X"}])
def test_refused_without_the_owners_recorded_authorisation(env, auth):
    s = json.loads(env["status"].read_text())
    s.pop("b5_trial_run")
    if auth is not None:
        s["b5_trial_run"] = auth
    env["status"].write_text(json.dumps(s))
    with pytest.raises(PermissionError):
        pre(env)
    assert not env["lock"].exists()  # nothing started


def test_the_real_status_does_not_authorise_the_run():
    s = json.loads(b5.STATUS.read_text())
    assert s.get("b5_trial_run", {}).get("authorised") is not True


@pytest.mark.parametrize("target", ["B5_PREREGISTRATION.md", "B5_PREREGISTRATION_ADDENDUM_1.md",
                                    "B5_PREREGISTRATION_ADDENDUM_2.md", "B5_PREREGISTRATION_ADDENDUM_3.md",
                                    "B5_RUN_MANIFEST.json"])
def test_refused_when_a_spec_or_the_manifest_differs_from_its_registered_hash(env, target):
    p = env["repo"] / "docs" / "edge" / target
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(ValueError, match="registered sha256"):
        pre(env)
    assert not env["lock"].exists()


@pytest.mark.parametrize("target", ["in.csv", "code.py"])
def test_refused_when_an_input_or_code_file_differs_from_the_manifest(env, target):
    (env["repo"] / target).write_text("changed\n")
    with pytest.raises(ValueError, match="manifest"):
        pre(env)
    assert not env["lock"].exists()


def test_refused_when_the_manifest_is_not_registered(env):
    lines = env["registry"].read_text().splitlines()
    env["registry"].write_text("\n".join(l for l in lines if "B5-V2-RUN-MANIFEST" not in l) + "\n")
    with pytest.raises(KeyError, match="B5-V2-RUN-MANIFEST is not registered"):
        pre(env)


def test_refused_when_n_is_not_100(env):
    edge_registry.append({"event": "register", "id": "EXTRA", "kind": "trial", "phase": "exploration",
                          "hypothesis": "x", "definition": "x", "universe": "x", "horizon_months": 1, "window": {},
                          "counts_for_dsr": True, "touched_holdout": False}, env["registry"])
    with pytest.raises(ValueError, match="N is 101"):
        pre(env)


@pytest.mark.parametrize("rid", ["B5-H1-FCFPS-ACCEL-V2", "B5-S2A-GP-12M-V2", "B5-S2A-V2-ROB-PITQ", "B5-H1-V2-ROB-2XCOST",
                                 "B5-H1-V2-ROB-WINQ", "B5-S2A-GP-12M"])
def test_refused_when_any_trial_or_robustness_run_already_has_a_result(env, rid):
    edge_registry.append({"event": "result", "id": rid, "evidence": "x"}, env["registry"])
    with pytest.raises(ValueError, match="already run"):
        pre(env)
    assert not env["lock"].exists()


def test_refused_when_the_registry_chain_is_broken(env):
    lines = env["registry"].read_text().splitlines()
    lines[5] = lines[5].replace('"date": "', '"date": "X', 1)
    env["registry"].write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="registry invalid"):
        pre(env)


def test_no_option_can_skip_a_gate_choose_a_trial_or_change_a_setting():
    src = Path(run.__file__).read_text()
    assert "argparse" not in src and "sys.argv" not in src and "environ" not in src
    assert run.GATES == tuple(f"P{i}" for i in range(1, 12))
    assert set(run.VARIANT_GATES) | {"P1", "P2", "P3", "P10"} == set(run.GATES)
    assert set(run.TRIALS) == {"H1", "S2A"}


# ---------- finish: both results before the shared DSR; a missing gate fails ----------

def synthetic_run(trial, seed):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-02-02", periods=94, freq="MS")
    ex = pd.Series(rng.normal(0.002, 0.02, 94), index=idx)
    m = {"sr_excess_monthly": float(ex.mean() / ex.std()), "excess_months": 94,
         "excess_skew": float(ex.skew()), "excess_kurt": float(ex.kurt() + 3)}
    variants = {g: ex + 0.001 for g in run.VARIANT_GATES}
    return {"trial": trial, "id": run.TRIALS[trial], "metrics": m, "excess": ex, "variants": variants,
            "variant_metrics": {g: m for g in run.ROB_IDS}, "alpha": {"alpha": 0.001, "alpha_t": 1.0},
            "top_contributor": 1, "t_nw": 1.0, "t_nonoverlap": 1.0 if trial == "S2A" else None}


def test_finish_records_both_results_before_any_dsr(opened, monkeypatch):
    seen = []
    real = bt.dsr

    def spy(m, registry):
        ev = edge_registry.load(registry)
        seen.append({e["id"] for e in ev if e.get("event") == "result"} >= set(run.TRIALS.values()))
        return real(m, registry)

    monkeypatch.setattr(bt, "dsr", spy)
    env = opened
    runs = {t: synthetic_run(t, i) for i, t in enumerate(run.TRIALS)}
    out = run.finish(runs, env["registry"], env["status"], "test")
    assert seen == [True, True]
    for t in run.TRIALS:
        assert out[t]["dsr"]["n_trials"] == 100 and out[t]["dsr"]["n_comparable"] == 2
        assert set(out[t]["verdict"]["checks"]) == set(run.GATES)
        assert out[t]["verdict"]["label"] != "E2 candidate"  # check 4 open
    ev = edge_registry.load(env["registry"])
    results = {e["id"] for e in ev if e.get("event") == "result"}
    assert {run.rob_id(t, g) for t in run.TRIALS for g in run.ROB_IDS} <= results
    with pytest.raises(ValueError):  # a second run of the same trial is refused by the registry
        run.finish(runs, env["registry"], env["status"], "test")


def test_finish_refuses_one_trial_alone(opened):
    env = opened
    with pytest.raises(RuntimeError, match="both trials"):
        run.finish({"H1": synthetic_run("H1", 0)}, env["registry"], env["status"], "test")
    assert not any(e.get("event") == "result" and e["id"].startswith("B5-H1-FCFPS")
                   for e in edge_registry.load(env["registry"]))


def results(registry):
    return [e["id"] for e in edge_registry.load(registry) if e.get("event") == "result"
            and e["id"] in edge_registry.B5_RUN_IDS]


@pytest.mark.parametrize("drop", [("variants", "P8"), ("variants", "P11"), ("variant_metrics", "P4"),
                                  ("variant_metrics", "P9")])
def test_a_partial_run_records_nothing(opened, drop):
    """Owner review 2026-10-19 item 4: a missing robustness run is refused before the first append."""
    runs = {t: synthetic_run(t, i) for i, t in enumerate(run.TRIALS)}
    del runs["S2A"][drop[0]][drop[1]]
    with pytest.raises(RuntimeError, match="incomplete"):
        run.finish(runs, opened["registry"], opened["status"], "test")
    assert results(opened["registry"]) == []


def test_a_missing_robustness_input_still_fails_its_gate_closed_in_the_verdict():
    r = synthetic_run("H1", 0)
    del r["variants"]["P8"]
    vi = run.st.verdict_inputs(r["excess"], r["variants"], None, 1.0, 0.99, r["alpha"], "H1")
    v = b5.verdict(vi)
    assert v["checks"]["P8"] is False and v["label"] == "fail"


# ---------- the gate: no alternate invocation or direct call runs or records a B5 trial ----------

def test_the_gate_ids_are_exactly_the_run_scripts_trials_and_robustness_runs():
    assert edge_registry.B5_RUN_IDS == set(run.TRIALS.values()) | {run.rob_id(t, g) for t in run.TRIALS
                                                                    for g in run.ROB_IDS}
    assert run.LOCK == edge_registry.B5_LOCK


def test_in_the_real_repo_the_run_is_closed():
    with pytest.raises(PermissionError):
        edge_registry.b5_run_open()
    assert not edge_registry.B5_LOCK.exists()


@pytest.mark.parametrize("rid", sorted(edge_registry.B5_RUN_IDS))
def test_no_b5_trial_or_robustness_id_can_run_or_be_recorded_while_closed(env, rid):
    with pytest.raises(PermissionError):
        edge_registry.require(rid, env["registry"])
    with pytest.raises(PermissionError):
        bt.run_trial(rid, env["registry"], pd.DataFrame(), None, None, None)
    with pytest.raises(PermissionError):
        bt.record(rid, {"sr_excess_monthly": 0.1, "excess_months": 94}, env["registry"], "x")
    assert results(env["registry"]) == []


def test_other_registered_ids_are_not_gated(env):
    edge_registry.append({"event": "register", "id": "B5-OTHER", "kind": "diagnostic", "phase": "exploration",
                          "hypothesis": "x", "definition": "x", "universe": "x", "horizon_months": 0, "window": {},
                          "counts_for_dsr": False, "touched_holdout": False}, env["registry"])
    assert edge_registry.require("B5-OTHER", env["registry"])["id"] == "B5-OTHER"


def test_a_copied_registry_and_status_cannot_open_the_run(env):
    """An alternate invocation that points preflight at copies passes preflight there, but the gate reads only the
    real status.json and lock, so nothing can be run, scored from loaded data, or recorded."""
    pre(env)
    assert env["lock"].exists()
    runs = {t: synthetic_run(t, i) for i, t in enumerate(run.TRIALS)}
    for call in (lambda: run.load_inputs(), lambda: run.finish(runs, env["registry"], env["status"], "x"),
                 lambda: run.run_one("H1", {}, {}, env["registry"]),
                 lambda: bt.run_trial(run.TRIALS["H1"], env["registry"], pd.DataFrame(), None, None, None)):
        with pytest.raises(PermissionError):
            call()
    assert results(env["registry"]) == []


@pytest.mark.parametrize("case", ["no_lock", "no_auth", "other_message", "not_true"])
def test_the_gate_needs_the_authorisation_and_a_lock_naming_the_same_message(env, monkeypatch, case):
    lock = env["lock"]
    status = json.loads(env["status"].read_text())
    if case != "no_lock":
        lock.write_text(json.dumps({"owner_message": "cmsg_OTHER" if case == "other_message" else "cmsg_TEST"}))
    if case == "no_auth":
        status.pop("b5_trial_run")
    if case == "not_true":
        status["b5_trial_run"]["authorised"] = "true"
    env["status"].write_text(json.dumps(status))
    monkeypatch.setattr(edge_registry, "STATUS", env["status"])
    monkeypatch.setattr(edge_registry, "B5_LOCK", lock)
    with pytest.raises(PermissionError):
        edge_registry.b5_run_open()
    lock.write_text(json.dumps({"owner_message": "cmsg_TEST"}))
    if case in ("no_lock", "other_message"):
        assert edge_registry.b5_run_open() == "cmsg_TEST"


def test_main_has_no_parameters_so_it_always_uses_the_real_files():
    import inspect
    assert inspect.signature(run.main).parameters == {}


def test_run_one_refuses_when_a_variant_run_is_missing(opened, monkeypatch):
    idx = pd.date_range("2015-02-02", periods=30, freq="MS")
    nav = pd.Series(np.linspace(1, 1.3, 30), index=idx)
    fake = {"results": [bt.Result(nav_usd=nav, nav_gbp=nav, contrib={1: 0.1})], "nav_gbp": nav, "nav_usd": nav}
    monkeypatch.setattr(run, "run_combined", lambda *a, **k: fake)
    monkeypatch.setattr(run.st, "robustness_variants",
                        lambda cfg, de: {g: (cfg, lambda p: p) for g in ("P4", "P5", "P6", "P7", "P9")})  # no P8
    bench = pd.DataFrame({"VWRP": np.linspace(1, 1.2, 30), "VWRL": np.nan}, index=idx)
    data = {"bench": bench, "data_errors": frozenset(), "factors": pd.DataFrame(), "exec": None, "fx": None}
    panels = {"H1": {"primary": pd.DataFrame({"cik": [1], "score": [1.0]}), "P9": pd.DataFrame()}}
    with pytest.raises(RuntimeError, match="P8"):
        run.run_one("H1", panels, data, Path("unused"))


# ---------- statistic definitions (ADDENDUM_2 §4) ----------

def test_nonoverlapping_t_uses_every_12th_month_from_the_first():
    x = pd.Series(np.arange(36, dtype=float), index=pd.date_range("2015-01-31", periods=36, freq="ME"))
    obs = x.iloc[[0, 12, 24]]
    assert run.nonoverlap_t(x) == pytest.approx(obs.mean() / (obs.std() / math.sqrt(3)))
    assert math.isnan(run.nonoverlap_t(x.iloc[:20]))  # 2 observations


def test_usd_return_is_labelled_by_the_period_start_month():
    nav = pd.Series([1.0, 1.1, 1.21], index=pd.to_datetime(["2015-02-02", "2015-03-02", "2015-04-01"]))
    r = run.usd_by_start_month(nav)
    assert list(r.index) == list(pd.to_datetime(["2015-02-02", "2015-03-02"])) and r.iloc[0] == pytest.approx(0.1)


def test_frozen_factor_files_stop_at_2022_and_later_rows_are_refused(tmp_path):
    for f in ("F-F_Research_Data_5_Factors_2x3_to_2022.csv", "F-F_Momentum_Factor_to_2022.csv"):
        df = run.read_factors(run.ROOT / "edge" / "factors" / f)
        assert df.index.max() == pd.Timestamp("2022-12-31")
    p = tmp_path / "f.csv"
    p.write_text("desc\n,Mom\n202212,1.0\n202301,2.0\n")
    with pytest.raises(ValueError, match="past 2022"):
        run.read_factors(p)


def test_s2a_rank_is_within_group_among_eligible_non_financial_names():
    df = pd.DataFrame({"month": ["2016-06-30"] * 5, "gross_profit": [100.0, 200.0, 300.0, 400.0, 500.0],
                       "gp_end": ["2016-03-31"] * 5, "gp_restated": [False] * 5, "revenue": np.nan,
                       "cost_of_revenue": np.nan, "rev_end": None, "cor_end": None, "rev_conflict": False,
                       "cor_restated": False, "total_assets": [1000.0] * 5, "cik": [1, 2, 3, 4, 5],
                       "mcap": [1e4] * 5, "quality_ok_pit": [True, True, True, False, True], "band": "large",
                       "close_raw": [10.0, 10.0, 10.0, 10.0, 0.5], "financial": False, "group": ["a", "a", "b", "a", "a"]})
    s = run.s2a_scores(df, b5.PRIMARY_QUALITY)
    assert s.tolist()[:3] == [0.5, 1.0, 1.0] and math.isnan(s.iloc[3]) and math.isnan(s.iloc[4])


def test_report_always_carries_the_standing_and_known_limitations():
    pre_ = {"owner_message": "cmsg_T", "manifest_sha256": "x", "n_trials": 100, "check4_complete": False}
    txt = run.report(pre_, {}, {})
    assert edge_rules.STANDING_LIMITATIONS in txt and run.KNOWN_INPUT_LIMITATIONS in txt
    assert "not proof of a deployable edge" in txt


def test_the_real_manifest_matches_the_files_it_names():
    m = json.loads(run.MANIFEST.read_text())
    for group in ("inputs", "code"):
        for path, h in m[group].items():
            p = Path(path) if Path(path).is_absolute() else REPO / path
            if p.exists():  # the shared research data is absent on some machines
                assert sha(p) == h, path


def test_the_manifest_covers_exactly_the_repository_code_the_run_imports():
    """Owner review 2026-10-19 item 3: every repository module the run path imports (including the loader's lazy
    imports) is hashed in the manifest, and nothing else; a new import fails this test until the manifest is rebuilt."""
    import subprocess
    code = ("import os, sys; sys.path.insert(0, '../equity'); import edge_b5_run, edge_b5_inputs, edge_split, stage2, "
            "xsection, edge_exec_prices; from equity import panel; r = os.path.abspath('..'); "
            "print('\\n'.join(sorted(os.path.relpath(m.__file__, r) for m in list(sys.modules.values()) "
            "if getattr(m, '__file__', None) and os.path.abspath(m.__file__).startswith(r + os.sep))))")
    out = subprocess.run([sys.executable, "-c", code], cwd=run.ROOT, capture_output=True, text=True, check=True)
    imported = set(out.stdout.split())
    import edge_b5_manifest as em
    m = json.loads(run.MANIFEST.read_text())
    assert set(m["code"]) == set(em.CODE) == imported
    assert list(m["inputs"]) == em.INPUTS and len(em.INPUTS) == 10


# ---------- ADDENDUM_3 (owner decision D20): point-in-time quality primary, full-window reverse veto ----------

def quality_frame():
    """Two groups, four names; name 3 fails the point-in-time rule only, name 4 the full-window rule only."""
    return pd.DataFrame({"cik": [1, 2, 3, 4], "month": pd.to_datetime(["2016-06-30"] * 4), "band": "large",
                         "group": ["a", "a", "a", "a"], "close_raw": 10.0, "financial": False,
                         "quality_ok_pit": [True, True, False, True], "quality_ok_window": [True, True, True, False],
                         "gross_profit": [100.0, 200.0, 300.0, 400.0], "gp_end": "2016-03-31", "gp_restated": False,
                         "revenue": np.nan, "cost_of_revenue": np.nan, "rev_end": None, "cor_end": None,
                         "rev_conflict": False, "cor_restated": False, "total_assets": 1000.0, "mcap": 1e4})


def test_the_primary_uses_the_point_in_time_rule_and_p9_the_full_window_rule(monkeypatch):
    df = quality_frame()
    monkeypatch.setattr(run.b5, "h1_score", lambda d: pd.Series([1.0, 2.0, 3.0, 4.0], index=d.index))
    p = run.score_panels(df)
    for t in run.TRIALS:
        assert list(p[t]["primary"]["quality_ok"]) == [True, True, False, True]
        assert list(p[t]["P9"]["quality_ok"]) == [True, True, True, False]
    # S2a's rank population follows the rule: name 3 is unranked in the primary, name 4 in P9
    prim, veto = p["S2A"]["primary"]["score"], p["S2A"]["P9"]["score"]
    assert math.isnan(prim.iloc[2]) and prim.iloc[3] == 1.0 and prim.iloc[1] == pytest.approx(2 / 3)
    assert math.isnan(veto.iloc[3]) and veto.iloc[2] == 1.0 and veto.iloc[1] == pytest.approx(2 / 3)


def test_a_bare_quality_column_is_refused_so_the_rule_is_never_implicit():
    with pytest.raises(ValueError, match="ambiguous"):
        run.score_panels(quality_frame().assign(quality_ok=True))
    with pytest.raises(TypeError):
        run.s2a_scores(quality_frame())  # the rule is a required argument


def test_both_rules_are_built_side_by_side_without_a_bare_column():
    months = pd.date_range("2015-01-31", periods=6, freq="ME")
    df = pd.DataFrame({"cik": 1, "month": months, "shares_out": [1e6, 1e6, 1e6, 5e7, 5e7, 5e7],
                       "shares_diluted": 1e6, "adjclose": 10.0, "close_raw": 10.0})
    q = run.st.with_quality_columns(df)
    assert "quality_ok" not in q
    import edge_split
    assert list(q["quality_ok_pit"]) == list(~edge_split.share_outliers_pit(df))
    assert list(q["quality_ok_window"]) == list(~edge_split.share_outliers(df))


def test_run_one_runs_p9_under_winq_from_the_full_window_panel_and_everything_else_from_the_primary(opened, monkeypatch):
    idx = pd.date_range("2015-02-02", periods=30, freq="MS")
    nav = pd.Series(np.linspace(1, 1.3, 30), index=idx)
    calls = []

    def fake(run_id, registry, panel, data, cfg, starts):
        calls.append((run_id, panel.attrs.get("name")))
        return {"results": [bt.Result(nav_usd=nav, nav_gbp=nav, contrib={1: 0.1})], "nav_gbp": nav, "nav_usd": nav}

    monkeypatch.setattr(run, "run_combined", fake)
    monkeypatch.setattr(run.st, "factor_alpha", lambda *a: {"alpha": 0.0, "alpha_t": 0.0})
    prim, veto = pd.DataFrame({"cik": [1], "score": [1.0]}), pd.DataFrame({"cik": [1], "score": [1.0]})
    prim.attrs["name"], veto.attrs["name"] = "primary", "window"
    monkeypatch.setattr(run.st, "without", lambda p, top: p)
    bench = pd.DataFrame({"VWRP": np.linspace(1, 1.2, 30), "VWRL": np.nan}, index=idx)
    data = {"bench": bench, "data_errors": frozenset(), "factors": pd.DataFrame(), "exec": None, "fx": None}
    run.run_one("H1", {"H1": {"primary": prim, "P9": veto}}, data, Path("unused"))
    by_id = {}
    for rid, name in calls:
        by_id.setdefault(rid, []).append(name)
    assert by_id["B5-H1-V2-ROB-WINQ"] == ["window"]
    assert "B5-H1-V2-ROB-PITQ" not in by_id
    assert all(n == "primary" for rid, ns in by_id.items() if rid != "B5-H1-V2-ROB-WINQ" for n in ns)


def good_inputs(**kw):
    r = {"trial": "H1", "t_nw": 3.5, "t_nonoverlap": None, "dsr": 0.9, "alpha": 0.01, "alpha_t": 2.5,
         "excess_2x": 0.01, "excess_vs_universe": 0.01, "excess_miss100": 0.01, "excess_nextmonth": 0.01,
         "excess_dataerr": 0.01, "excess_winq": 0.01, "excess_thirds": [0.01, -0.01, 0.02],
         "excess_without_top_contributor": 0.01}
    return {**r, **kw}


def test_the_full_window_rule_is_a_reverse_veto_that_can_never_rescue_the_primary():
    assert b5.verdict(good_inputs())["checks"]["P9"] is True
    assert b5.verdict(good_inputs(excess_winq=-0.01))["label"] == "fail"  # veto
    assert b5.verdict(good_inputs(excess_winq=None))["label"] == "fail"  # missing fails closed
    for bad in ({"t_nw": 1.0}, {"dsr": 0.5}, {"alpha_t": 1.0}, {"excess_2x": -0.01}):
        v = b5.verdict(good_inputs(excess_winq=0.5, **bad))  # a strong P9 changes nothing
        assert v["label"] in ("fail", "lead, not a pass") and v["label"] != b5.E2_BLOCKED_LABEL
    assert set(b5.verdict(good_inputs())) == {"checks", "label", "check4_complete"}  # no P9 statistic reported as a result


def test_retired_ids_can_never_run_or_be_recorded_even_with_the_run_open(opened):
    for rid in sorted(edge_registry.B5_RETIRED_IDS):
        with pytest.raises(ValueError, match="retired"):
            edge_registry.require(rid, opened["registry"])
        with pytest.raises(ValueError, match="retired"):
            bt.record(rid, {"sr_excess_monthly": 0.1, "excess_months": 94}, opened["registry"], "x")
    assert {"B5-H1-V2-ROB-PITQ", "B5-S2A-V2-ROB-PITQ", "B5-H1-FCFPS-ACCEL", "B5-S2A-GP-12M"} <= edge_registry.B5_RETIRED_IDS
    assert not edge_registry.B5_RETIRED_IDS & edge_registry.B5_RUN_IDS


@pytest.mark.parametrize("rid", ["B5-H1-V2-ROB-WINQ", "B5-S2A-V2-ROB-WINQ", "B5-V2-ADDENDUM-3"])
def test_preflight_refuses_when_an_addendum_3_record_is_missing(env, rid):
    lines = env["registry"].read_text().splitlines()
    env["registry"].write_text("\n".join(l for l in lines if f'"id": "{rid}"' not in l) + "\n")
    with pytest.raises((KeyError, ValueError)):
        pre(env)
    assert not env["lock"].exists()


def test_preflight_refuses_a_robustness_run_that_counts(env, monkeypatch, tmp_path):
    reg = tmp_path / "counted.jsonl"
    shutil.copy(edge_registry.PATH, reg)
    evs = edge_b5_addendum3.events(env["repo"])
    evs[1] = {**evs[1], "counts_for_dsr": True}  # B5-H1-V2-ROB-WINQ wrongly counted
    for e in evs:
        edge_registry.append(e, reg)
    edge_registry.append({"event": "register", "id": "B5-V2-RUN-MANIFEST", "kind": "diagnostic", "phase": "exploration",
                          "hypothesis": "none", "definition": "test", "universe": "x", "horizon_months": 0,
                          "window": {}, "counts_for_dsr": False, "touched_holdout": False,
                          "spec_sha256": sha(env["manifest"])}, reg)
    monkeypatch.setattr(run, "N_EXPECTED", 101)  # isolate the check from the N check
    with pytest.raises(ValueError, match="must not count"):
        run.preflight(reg, env["status"], env["manifest"], env["repo"], env["lock"])
    assert not env["lock"].exists()


def test_addendum_3_registration_adds_no_counted_trial_and_needs_the_owner(tmp_path):
    reg = tmp_path / "t.jsonl"
    shutil.copy(edge_registry.PATH, reg)
    before = edge_registry.n_trials(edge_registry.load(reg))
    with pytest.raises(PermissionError):
        edge_b5_addendum3.register("not-a-message", reg)
    out = edge_b5_addendum3.register("cmsg_X", reg)
    assert [e["id"] for e in out] == ["B5-V2-ADDENDUM-3", "B5-H1-V2-ROB-WINQ", "B5-S2A-V2-ROB-WINQ"]
    assert all(e["counts_for_dsr"] is False for e in out)
    assert edge_registry.n_trials(edge_registry.load(reg)) == before == 100
    with pytest.raises(ValueError, match="already registered"):
        edge_b5_addendum3.register("cmsg_X", reg)


def test_in_the_real_registry_addendum_3_and_winq_are_not_registered_yet():
    reg = edge_registry.registered(edge_registry.load())
    assert not {"B5-V2-ADDENDUM-3", "B5-H1-V2-ROB-WINQ", "B5-S2A-V2-ROB-WINQ", "B5-V2-RUN-MANIFEST"} & set(reg)
    assert {"B5-H1-V2-ROB-PITQ", "B5-S2A-V2-ROB-PITQ"} <= set(reg)  # history kept, never edited


def test_reports_carry_the_addendum_3_and_other_later_information_disclosures():
    for s in ("AVITA", "CoStar", "10-for-1", "P8", "SIC", "2026 snapshot", "General Dynamics", "Abbott"):
        assert s in run.KNOWN_INPUT_LIMITATIONS, s
