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
    for f in ("B5_PREREGISTRATION.md", "B5_PREREGISTRATION_ADDENDUM_1.md", "B5_PREREGISTRATION_ADDENDUM_2.md"):
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
    edge_registry.append({**base, "id": "B5-V2-RUN-MANIFEST", "definition": "test", "spec_sha256": sha(man)}, reg)
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"ttm_check4_independent_source": {"complete": False},
                                  "b5_trial_run": {"authorised": True, "owner_message": "cmsg_TEST"}}))
    return {"registry": reg, "status": status, "manifest": man, "repo": tmp_path, "lock": tmp_path / "b5.lock"}


def pre(e):
    return run.preflight(e["registry"], e["status"], e["manifest"], e["repo"], e["lock"])


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
                                    "B5_PREREGISTRATION_ADDENDUM_2.md", "B5_RUN_MANIFEST.json"])
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


@pytest.mark.parametrize("rid", ["B5-H1-FCFPS-ACCEL-V2", "B5-S2A-GP-12M-V2", "B5-S2A-V2-ROB-PITQ", "B5-H1-V2-ROB-2XCOST"])
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


def test_finish_records_both_results_before_any_dsr(env, monkeypatch):
    seen = []
    real = bt.dsr

    def spy(m, registry):
        ev = edge_registry.load(registry)
        seen.append({e["id"] for e in ev if e.get("event") == "result"} >= set(run.TRIALS.values()))
        return real(m, registry)

    monkeypatch.setattr(bt, "dsr", spy)
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


def test_finish_refuses_one_trial_alone(env):
    with pytest.raises(RuntimeError, match="both trials"):
        run.finish({"H1": synthetic_run("H1", 0)}, env["registry"], env["status"], "test")
    assert not any(e.get("event") == "result" and e["id"].startswith("B5-H1-FCFPS")
                   for e in edge_registry.load(env["registry"]))


def test_a_missing_robustness_input_fails_its_gate_closed(env):
    runs = {t: synthetic_run(t, i) for i, t in enumerate(run.TRIALS)}
    del runs["H1"]["variants"]["P8"]
    out = run.finish(runs, env["registry"], env["status"], "test")
    assert out["H1"]["verdict"]["checks"]["P8"] is False and out["H1"]["verdict"]["label"] == "fail"


def test_run_one_refuses_when_a_variant_run_is_missing(monkeypatch):
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
                       "mcap": [1e4] * 5, "quality_ok": [True, True, True, False, True], "band": "large",
                       "close_raw": [10.0, 10.0, 10.0, 10.0, 0.5], "financial": False, "group": ["a", "a", "b", "a", "a"]})
    s = run.s2a_scores(df)
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
