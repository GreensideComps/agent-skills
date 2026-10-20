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

PRE_V3_SHA256 = "0da0638e43b2cf7799cb46ef340b951a4fcd39ad94044a04ddbebb6cda1f85fd"  # registry before step 1 (D21)
V3_OWNER_MESSAGE = "cmsg_01U4KMvkBYNknqm4HRVie8uvCZeVB3ELHksWnNk6iBAk3Y"  # owner approval 2026-10-19 07:53Z
MANIFEST_OWNER_MESSAGE = "cmsg_01U4KMvkBYNknqm4HRVie8uvTgMxeHvcPJiF9NpWGKhNNC"  # owner approval 2026-10-19 08:29Z
MANIFEST_SHA256 = "0f02eda19ee528a3fb0b62ce9bf35c1864f8e9ad5b9d1581e5ec4a1abb4c7072"  # registered B5-V3-RUN-MANIFEST
MANIFEST_2_OWNER_MESSAGE = "cmsg_01U4KMvkBYNknqm4HRVie8uv1fMkFLASaWMXhFccwwfuzC"  # owner approval 2026-10-19 08:47Z
MANIFEST_2_SHA256 = "10190052cd13cb7f1735741069e07feb073d1ea8d4beff57f297859d4f799757"  # registered B5-V3-RUN-MANIFEST-2
MANIFEST_3_OWNER_MESSAGE = "cmsg_01U4KMvkBYNknqm4HRVie8uvHRo9DuV72QtY2Wr1T66tNP"  # owner approval 2026-10-19 13:15Z (D30)
MANIFEST_3_SHA256 = "f3f4fd71bae5ddf4932211c1983edac7dcb1d6d152d8d087c73550409a4b9671"  # registered B5-V3-RUN-MANIFEST-3
RUN_1_OWNER_MESSAGE = "cmsg_01U4KMvkBYNknqm4HRVie8uvUzn9qQCoyy3U7K3j4iY3kK"  # D26 authorisation, 2026-10-19 09:05Z


def pre_v3(dst):
    """Write the committed registry as it stood before version 3 was registered (every line before
    B5-V3-ADDENDUM-3), so registration tests can replay the 13-event step."""
    lines = edge_registry.PATH.read_text().splitlines(keepends=True)
    cut = next(i for i, l in enumerate(lines) if '"id": "B5-V3-ADDENDUM-3"' in l)
    dst.write_text("".join(lines[:cut]))
    return dst


REPO = Path(__file__).resolve().parents[2]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def make_env(tmp_path):
    """A copy of the repo's frozen specs and registry, with a manifest and an owner authorisation, in tmp."""
    docs = tmp_path / "docs" / "edge"
    docs.mkdir(parents=True)
    for f in ("B5_PREREGISTRATION.md", "B5_PREREGISTRATION_ADDENDUM_1.md", "B5_PREREGISTRATION_ADDENDUM_2.md",
              "B5_PREREGISTRATION_ADDENDUM_3.md"):
        shutil.copy(REPO / "docs" / "edge" / f, docs / f)
    (tmp_path / "in.csv").write_text("a,b\n1,2\n")
    (tmp_path / "code.py").write_text("x = 1\n")
    man = docs / run.MANIFEST.name
    man.write_text(json.dumps({"inputs": {"in.csv": sha(tmp_path / "in.csv")},
                               "code": {"code.py": sha(tmp_path / "code.py")}}))
    reg = tmp_path / "trials.jsonl"
    pre_v3(reg)
    have = edge_registry.registered(edge_registry.load(reg))
    base = {"event": "register", "kind": "diagnostic", "phase": "exploration", "hypothesis": "none",
            "universe": "as B5 v2", "horizon_months": 0, "window": {}, "counts_for_dsr": False,
            "touched_holdout": False}
    if "B5-V2-ADDENDUM-2" not in have:
        edge_registry.append({**base, "id": "B5-V2-ADDENDUM-2", "definition": "test",
                              "spec_sha256": sha(docs / "B5_PREREGISTRATION_ADDENDUM_2.md")}, reg)
    edge_b5_addendum3.register("cmsg_TEST_ADD3", reg, tmp_path)  # the prepared events, as the owner would approve
    edge_registry.append({**base, "id": run.MANIFEST_ID, "definition": "test", "spec_sha256": sha(man)}, reg)
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"ttm_check4_independent_source": {"complete": False},
                                  "b5_trial_run": {"authorised": True, "owner_message": "cmsg_TEST",
                                                   "manifest_id": run.MANIFEST_ID, "manifest_sha256": sha(man)}}))
    return {"registry": reg, "status": status, "manifest": man, "repo": tmp_path, "lock": tmp_path / "b5.lock"}


def pre(e):
    return run.preflight(e["registry"], e["status"], e["manifest"], e["repo"], e["lock"])


@pytest.fixture
def closed(env, monkeypatch, tmp_path):
    """The gate's fixed paths pointed at a closed state (no authorisation, no lock), whatever the real repository
    holds. Since run 1 (D26, B5_RUN_1_INCIDENT.md) the real status.json is authorised and the real lock exists, so
    tests of the closed gate can no longer use the real files."""
    shut = tmp_path / "closed_status.json"
    shut.write_text(json.dumps({"b5_trial_run": {"authorised": False}}))
    monkeypatch.setattr(edge_registry, "STATUS", shut)
    monkeypatch.setattr(edge_registry, "B5_LOCK", tmp_path / "no.lock")
    return env


@pytest.fixture
def opened(env, monkeypatch):
    """env with the run open: the gate's fixed paths pointed at env's authorised status and a lock preflight took.
    Only a test can repoint them; production code has no parameter for it."""
    pre(env)
    point_gate(monkeypatch, env)
    return env


def point_gate(mp, e):
    """Point every path the gate reads (status, lock, registry, manifest, repository root) at the env copy."""
    mp.setattr(edge_registry, "STATUS", e["status"])
    mp.setattr(edge_registry, "B5_LOCK", e["lock"])
    mp.setattr(edge_registry, "PATH", e["registry"])
    mp.setattr(edge_registry, "B5_MANIFEST", e["manifest"])
    mp.setattr(edge_registry, "B5_REPO", e["repo"])


def test_preflight_passes_once_and_the_lock_refuses_a_second_start(env):
    out = pre(env)
    assert out["owner_message"] == "cmsg_TEST" and out["n_trials"] == 102 and out["check4_complete"] is False
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


ARCHIVED_LOCK = REPO / "docs" / "edge" / "incidents" / "B5_RUN_1_LOCK.json"
ARCHIVED_LOCK_SHA256 = "c06eeaa3a6020adc896c9a18a39694bd5cf80f79fcb1d5eee594caea146f6e05"  # as committed in 4215a98
D29_OWNER_MESSAGE = "cmsg_01U4KMvkBYNknqm4HRVie8uv5MUSAy3Neyqof1pvHhyPuc"  # archival and reset, 2026-10-19 13:02Z
RUN_2_OWNER_MESSAGE = "cmsg_01U4KMvkBYNknqm4HRVie8uvNzjD1qcmHEXGwqYmiFikfZ"  # D31, run 2 authorised, 2026-10-19 13:25Z
PRE_RUN_2_SPENT = frozenset({RUN_1_OWNER_MESSAGE})  # the code's spent set when run 2 ran
# D34: the run-2 bytes of research/edge_registry.py (the file MANIFEST-3 hashed; commits bb9ea44 to 1eb0e96), kept
# as a committed fixture so no test depends on git history. Its sha256 is the MANIFEST-3 entry for that file.
RUN_2_EDGE_REGISTRY = Path(__file__).resolve().parent / "fixtures" / "b5_run2_edge_registry.py.orig"
MANIFEST_3_EDGE_REGISTRY_SHA256 = "e56f49aa862eaaf8048494272e1de1e3d363a0490282562b080f63dae5405c5c"
D32_OWNER_MESSAGE = "cmsg_01U4KMvkBYNknqm4HRVie8uvWW5mGZ7bsqjsGzRn39VcN1"  # run 2 closeout, 2026-10-19 13:55Z
RUN_2_LOCK = REPO / "docs" / "edge" / "incidents" / "B5_RUN_2_LOCK.json"
RUN_2_LOCK_SHA256 = "2041f109b37519e6a5b53a033b2ed82172cb1b5cd4bac6cec4e95a2834a60a61"  # as committed in e5d1dc1
PRE_RUN_2_LINES = 240  # registry before run 2: MANIFEST-3 registered (D30), no B5 result
PRE_RUN_2_SHA256 = "574d2e0bb98c0c7ba7f9347f8aa5565101c702259834262b49a8d8cafee4d497"
RUN_2_REGISTRY_SHA256 = "de03d38b18a2d80b5c4d20f647c8ff35f5471157aba71fa99da6b550fb1217e6"  # lines 1-252, commit a4a07d7
RUN_2_REPORT = REPO / "equity" / "reports" / "research" / "edge" / "b5_trials.md"
RUN_2_REPORT_SHA256 = "5dee03ea80bb3df568e624518543cef17cbd41ba53113301b6b53964288579bc"
RUN_2_RESULTS = {  # monthly excess Sharpe and months, as recorded by run 2 (registry lines 241-252)
    "B5-H1-FCFPS-ACCEL-V3": (0.15617751061474458, 94), "B5-S2A-GP-12M-V3": (0.19998574529911248, 94),
    "B5-H1-V3-ROB-2XCOST": (0.11350166081519096, 94), "B5-H1-V3-ROB-MISS100": (0.15617751061474458, 94),
    "B5-H1-V3-ROB-NEXTMONTH": (0.10117348632980143, 93), "B5-H1-V3-ROB-DATAERR": (0.15617751061474458, 94),
    "B5-H1-V3-ROB-WINQ": (0.15617751061474458, 94), "B5-S2A-V3-ROB-2XCOST": (0.19199438433545227, 94),
    "B5-S2A-V3-ROB-MISS100": (0.19998574529911248, 94), "B5-S2A-V3-ROB-NEXTMONTH": (0.19863073352096117, 93),
    "B5-S2A-V3-ROB-DATAERR": (0.19998574529911248, 94), "B5-S2A-V3-ROB-WINQ": (0.20350108467239858, 94),
}


@pytest.fixture
def pre_run_2(tmp_path, monkeypatch):
    """Isolated copy of the state just before run 2: the registry's first 240 lines (as committed at 45409e4), a
    status holding D31's authorisation exactly as the real history records it, and no lock. The gate's fixed paths
    point at these copies; the real registry, status and lock are never written."""
    reg = tmp_path / "trials.jsonl"
    reg.write_text("".join(edge_registry.PATH.read_text().splitlines(keepends=True)[:PRE_RUN_2_LINES]))
    assert sha(reg) == PRE_RUN_2_SHA256
    s = json.loads(b5.STATUS.read_text())
    h = s["b5_trial_run"]["history"][1]
    s["b5_trial_run"] = {k: h[k] for k in ("authorised", "owner_message", "manifest_id", "manifest_sha256")}
    status = tmp_path / "status.json"
    status.write_text(json.dumps(s))
    e = {"registry": reg, "status": status, "manifest": run.MANIFEST, "repo": manifest_3_repo(tmp_path),
         "lock": tmp_path / "b5.lock"}
    point_gate(monkeypatch, e)
    # O4 (D31 spent in code) came after run 2. Before run 2 only D26 was spent in code, so the copy restores that
    # set too; the real B5_SPENT_AUTHORISATIONS and the real edge_registry.py are untouched.
    monkeypatch.setattr(edge_registry, "B5_SPENT_AUTHORISATIONS", PRE_RUN_2_SPENT)
    return e


def manifest_3_repo(tmp_path):
    """A view of the repository as MANIFEST-3 hashed it: every entry links to the real one, except
    research/edge_registry.py, which is the exact bytes run 2 ran (the committed fixture, verified against the
    manifest hash). O4 changed the real file afterwards, so MANIFEST-3 no longer matches the real repository."""
    root = tmp_path / "repo"
    (root / "research").mkdir(parents=True)
    for c in REPO.iterdir():
        if c.name != "research":
            (root / c.name).symlink_to(c)
    for c in (REPO / "research").iterdir():
        if c.name != "edge_registry.py":
            (root / "research" / c.name).symlink_to(c)
    old = run_2_edge_registry_bytes()
    (root / "research" / "edge_registry.py").write_bytes(old)
    return root


def run_2_edge_registry_bytes() -> bytes:
    """The fixture's bytes, refused unless they hash to MANIFEST-3's recorded entry for research/edge_registry.py."""
    old = RUN_2_EDGE_REGISTRY.read_bytes()
    assert hashlib.sha256(old).hexdigest() == MANIFEST_3_EDGE_REGISTRY_SHA256
    assert json.loads(run.MANIFEST.read_text())["code"]["research/edge_registry.py"] == MANIFEST_3_EDGE_REGISTRY_SHA256
    return old


def test_the_real_status_authorises_no_run_and_keeps_runs_1_and_2_as_spent_history():
    """D32: run 2 closed out; D31 is spent, as D26 was (D29). Both runs are kept as history with their outcome and
    archived lock, and nothing is authorised."""
    s = json.loads(b5.STATUS.read_text())["b5_trial_run"]
    assert s["authorised"] is False and "owner_message" not in s and D32_OWNER_MESSAGE in s["owner_decision"]
    h1, h2 = s["history"]
    assert h1["run"] == 1 and h1["owner_message"] == RUN_1_OWNER_MESSAGE and h1["spent"] is True
    assert h1["outcome"].startswith("D27") and h1["lock"] == "docs/edge/incidents/B5_RUN_1_LOCK.json"
    assert h1["lock_sha256"] == ARCHIVED_LOCK_SHA256 and RUN_1_OWNER_MESSAGE in edge_registry.B5_SPENT_AUTHORISATIONS
    assert h2["run"] == 2 and h2["owner_message"] == RUN_2_OWNER_MESSAGE and h2["spent"] is True
    assert h2["owner_decision"].startswith("D31") and h2["outcome"].startswith("D32")
    assert h2["manifest_id"] == run.MANIFEST_ID and h2["manifest_sha256"] == MANIFEST_3_SHA256
    assert h2["lock"] == "docs/edge/incidents/B5_RUN_2_LOCK.json" and h2["lock_sha256"] == RUN_2_LOCK_SHA256
    with pytest.raises(PermissionError, match="not authorised"):
        edge_registry.b5_authorisation()


def test_before_run_2_d31_authorised_manifest_3_and_the_gate_stayed_shut_until_preflight(pre_run_2):
    """Pre-run lifecycle on the isolated copy: D31's authorisation is valid and bound to MANIFEST-3, no B5 id has a
    result and no excess-over-VWRP Sharpe is recorded, the gate refuses with no lock, and preflight passes once and
    takes the lock (on the copy), after which the gate is open. No data is scored."""
    e = pre_run_2
    auth = edge_registry.b5_authorisation(e["status"])
    assert auth["owner_message"] == RUN_2_OWNER_MESSAGE and auth["manifest_sha256"] == MANIFEST_3_SHA256 == sha(run.MANIFEST)
    ev = edge_registry.load(e["registry"])
    assert edge_registry.n_trials(ev) == 102 and not edge_registry.validate(e["registry"])
    assert not {x["id"] for x in ev if x.get("event") == "result"} & (edge_registry.B5_RUN_IDS | edge_registry.B5_RETIRED_IDS)
    assert edge_registry.sharpe_list(ev, "portfolio_excess_vs_vwrp") == []
    with pytest.raises(PermissionError, match="not open"):
        edge_registry.b5_run_open(verify_files=True)
    pre(e)
    assert json.loads(e["lock"].read_text()) == {"owner_message": RUN_2_OWNER_MESSAGE, "manifest": MANIFEST_3_SHA256}
    assert e["lock"].read_bytes() == RUN_2_LOCK.read_bytes()  # the same lock run 2 took
    assert edge_registry.b5_run_open(verify_files=True) == RUN_2_OWNER_MESSAGE


@pytest.mark.parametrize("target", ["B5_PREREGISTRATION.md", "B5_PREREGISTRATION_ADDENDUM_1.md",
                                    "B5_PREREGISTRATION_ADDENDUM_2.md", "B5_PREREGISTRATION_ADDENDUM_3.md",
                                    run.MANIFEST.name])
def test_refused_when_a_spec_or_the_manifest_differs_from_its_registered_hash(env, target):
    p = env["repo"] / "docs" / "edge" / target
    p.write_bytes(p.read_bytes() + b" ")
    if target == run.MANIFEST.name:  # since the hardening, the authorisation names the manifest's sha256 too
        with pytest.raises(PermissionError, match="different manifest sha256"):
            pre(env)
    else:
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
    env["registry"].write_text("\n".join(l for l in lines if run.MANIFEST_ID not in l) + "\n")
    with pytest.raises(KeyError, match=f"{run.MANIFEST_ID} is not registered"):
        pre(env)


def test_refused_when_n_is_not_102(env):
    edge_registry.append({"event": "register", "id": "EXTRA", "kind": "trial", "phase": "exploration",
                          "hypothesis": "x", "definition": "x", "universe": "x", "horizon_months": 1, "window": {},
                          "counts_for_dsr": True, "touched_holdout": False}, env["registry"])
    with pytest.raises(ValueError, match="N is 103"):
        pre(env)


@pytest.mark.parametrize("rid", ["B5-H1-FCFPS-ACCEL-V3", "B5-S2A-GP-12M-V3", "B5-H1-V3-ROB-2XCOST", "B5-S2A-V3-ROB-WINQ",
                                 "B5-H1-FCFPS-ACCEL-V2", "B5-S2A-GP-12M-V2", "B5-S2A-V2-ROB-PITQ", "B5-H1-V2-ROB-2XCOST",
                                 "B5-S2A-GP-12M", "B5-H1-ROB-DATAERR"])
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


PRE = {"owner_message": "cmsg_TEST", "manifest_sha256": "x", "n_trials": 102, "check4_complete": False}


def fin(env, runs):
    return run.finish(runs, env["registry"], env["status"], "test", env["repo"] / "r.md", PRE)


def b5_results(registry):
    return [e for e in edge_registry.load(registry) if e.get("event") == "result" and e["id"] in edge_registry.B5_RUN_IDS]


def test_finish_computes_the_shared_dsr_from_both_staged_results_before_anything_is_recorded(opened, monkeypatch):
    env = opened
    before = env["registry"].read_bytes()
    seen = []
    real = bt.dsr

    def spy(m, registry):
        staged = {e["id"] for e in b5_results(registry)}
        seen.append((Path(registry) != env["registry"], staged >= set(run.TRIALS.values()),
                     env["registry"].read_bytes() == before, (env["repo"] / "r.md").exists()))
        return real(m, registry)

    monkeypatch.setattr(bt, "dsr", spy)
    runs = {t: synthetic_run(t, i) for i, t in enumerate(run.TRIALS)}
    out = fin(env, runs)
    assert seen == [(True, True, True, False)] * 2  # staged copy, both results, registry untouched, no report yet
    for t in run.TRIALS:
        assert out[t]["dsr"]["n_trials"] == 102 and out[t]["dsr"]["n_comparable"] == 2
        assert set(out[t]["verdict"]["checks"]) == set(run.GATES)
        assert out[t]["verdict"]["label"] != "E2 candidate"  # check 4 open
    after = env["registry"].read_bytes()
    assert after.startswith(before) and after.count(b"\n") == before.count(b"\n") + 12  # one step, history kept
    assert [e["id"] for e in b5_results(env["registry"])] == list(run.TRIALS.values()) + [
        run.rob_id(t, g) for t in run.TRIALS for g in run.ROB_IDS]
    assert not edge_registry.validate(env["registry"])
    assert (env["repo"] / "r.md").exists() and not list(env["repo"].glob("*.pending"))
    assert not list(env["registry"].parent.glob("*.staged"))
    with pytest.raises(ValueError):  # a second run of the same trial is refused by the registry
        fin(env, runs)


def _boom(*a, **k):
    raise RuntimeError("injected failure")


@pytest.mark.parametrize("where", ["verdict", "dsr_nan", "report", "commit_rename", "registry_changed"])
def test_a_failure_before_the_commit_records_nothing_and_leaves_no_report(opened, monkeypatch, where):
    """Owner review 2026-10-19, findings A and B: every failure up to the commit leaves the registry byte-identical,
    no report, no pending report and no staged copy; the lock stays."""
    import os
    env = opened
    runs = {t: synthetic_run(t, i) for i, t in enumerate(run.TRIALS)}
    if where == "verdict":
        monkeypatch.setattr(b5, "verdict", _boom)
    elif where == "dsr_nan":
        runs["S2A"]["metrics"] = {**runs["S2A"]["metrics"], "sr_excess_monthly": float("nan")}
    elif where == "report":
        monkeypatch.setattr(run, "report", _boom)
    elif where == "commit_rename":
        monkeypatch.setattr(os, "replace", lambda *a: _boom())
    elif where == "registry_changed":
        real = run.report

        def sneak(*a):
            edge_registry.append({"event": "register", "id": "LATE", "kind": "diagnostic", "phase": "exploration",
                                  "hypothesis": "x", "definition": "x", "universe": "x", "horizon_months": 0,
                                  "window": {}, "counts_for_dsr": False, "touched_holdout": False}, env["registry"])
            return real(*a)
        monkeypatch.setattr(run, "report", sneak)
    before = env["registry"].read_bytes()
    with pytest.raises((RuntimeError, ValueError)):
        fin(env, runs)
    after = env["registry"].read_bytes()
    assert after == before or (where == "registry_changed" and b5_results(env["registry"]) == [])
    assert b5_results(env["registry"]) == []
    assert not (env["repo"] / "r.md").exists() and not list(env["repo"].glob("*.pending"))
    assert not list(env["registry"].parent.glob("*.staged"))
    assert env["lock"].exists()


def test_only_the_final_report_rename_follows_the_commit(opened, monkeypatch):
    """If the last step fails, the results are recorded once and the full report is in the pending file."""
    import os
    env = opened
    real, calls = os.replace, []

    def second_fails(a, b):
        calls.append(b)
        if len(calls) == 2:
            raise OSError("injected")
        real(a, b)
    monkeypatch.setattr(os, "replace", second_fails)
    with pytest.raises(OSError):
        fin(env, {t: synthetic_run(t, i) for i, t in enumerate(run.TRIALS)})
    assert len(b5_results(env["registry"])) == 12 and not edge_registry.validate(env["registry"])
    pend = env["repo"] / "r.md.pending"
    assert pend.exists() and edge_rules.STANDING_LIMITATIONS in pend.read_text()


def test_finish_refuses_one_trial_alone(opened):
    env = opened
    with pytest.raises(RuntimeError, match="both trials"):
        fin(env, {"H1": synthetic_run("H1", 0)})
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
        fin(opened, runs)
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


def test_in_the_real_repo_both_run_locks_are_archived_unchanged_and_no_further_run_can_start():
    """D29 and D32: run 1's and run 2's locks are archived byte-identical as incident artefacts and no lock is in
    place. Run 2's 12 results are recorded, so with nothing authorised both preflight and the gate on the real files
    refuse before reading any data."""
    assert sha(ARCHIVED_LOCK) == ARCHIVED_LOCK_SHA256
    assert json.loads(ARCHIVED_LOCK.read_text()) == {"owner_message": RUN_1_OWNER_MESSAGE, "manifest": MANIFEST_2_SHA256}
    assert sha(RUN_2_LOCK) == RUN_2_LOCK_SHA256
    assert json.loads(RUN_2_LOCK.read_text()) == {"owner_message": RUN_2_OWNER_MESSAGE, "manifest": MANIFEST_3_SHA256}
    assert not edge_registry.B5_LOCK.exists()
    ev = edge_registry.load()
    done = {e["id"] for e in ev if e.get("event") == "result"}
    assert done & edge_registry.B5_RUN_IDS == set(RUN_2_RESULTS) and not done & edge_registry.B5_RETIRED_IDS
    with pytest.raises(PermissionError, match="not authorised"):
        run.preflight()
    with pytest.raises(PermissionError, match="not authorised"):
        edge_registry.b5_run_open(verify_files=True)
    assert not edge_registry.B5_LOCK.exists()  # preflight refused before taking a lock


def test_re_authorising_spent_d31_cannot_start_a_second_run(tmp_path, monkeypatch):
    """A status that re-authorises D31 for the same manifest, on a copy of the real post-run registry: preflight
    refuses at the authorisation (D31 is spent in code, O4), takes no lock, and the gate stays shut. With the code's
    pre-O4 spent set restored, preflight still refuses, at a later control, because run 2's results exist."""
    reg = tmp_path / "trials.jsonl"
    shutil.copy(edge_registry.PATH, reg)
    s = json.loads(b5.STATUS.read_text())
    h = s["b5_trial_run"]["history"][1]
    s["b5_trial_run"] = {k: h[k] for k in ("authorised", "owner_message", "manifest_id", "manifest_sha256")}
    status = tmp_path / "status.json"
    status.write_text(json.dumps(s))
    e = {"registry": reg, "status": status, "manifest": run.MANIFEST, "repo": REPO, "lock": tmp_path / "b5.lock"}
    with pytest.raises(PermissionError, match="spent"):
        pre(e)
    with monkeypatch.context() as m:
        m.setattr(edge_registry, "B5_SPENT_AUTHORISATIONS", PRE_RUN_2_SPENT)
        with pytest.raises(ValueError, match="already run"):
            pre(dict(e, repo=manifest_3_repo(tmp_path)))
    assert not e["lock"].exists() and reg.read_bytes() == edge_registry.PATH.read_bytes()
    point_gate(monkeypatch, e)
    with pytest.raises(PermissionError, match="spent"):
        edge_registry.b5_run_open(verify_files=True)


def test_run_2s_results_and_report_are_recorded_unchanged():
    """D32: the registry's first 240 lines are byte-identical to the pre-run registry, lines 241-252 are exactly run
    2's 12 results (one per B5 V3 id, with the recorded statistic, Sharpe and months), and the report is the one
    committed in a4a07d7, carrying both failed verdicts and every standing disclosure."""
    lines = edge_registry.PATH.read_text().splitlines(keepends=True)
    assert hashlib.sha256("".join(lines[:PRE_RUN_2_LINES]).encode()).hexdigest() == PRE_RUN_2_SHA256
    assert hashlib.sha256("".join(lines[:252]).encode()).hexdigest() == RUN_2_REGISTRY_SHA256
    assert not edge_registry.validate() and edge_registry.n_trials(edge_registry.load()) == 102
    got = [json.loads(line) for line in lines[PRE_RUN_2_LINES:252]]
    assert all(e["event"] == "result" and e["stat"] == "portfolio_excess_vs_vwrp" for e in got)
    assert {e["id"]: (e["sr_monthly"], e["n_months"]) for e in got} == RUN_2_RESULTS and len(got) == 12
    assert sha(RUN_2_REPORT) == RUN_2_REPORT_SHA256
    text = RUN_2_REPORT.read_text()
    assert text.count("Verdict: **fail**") == 2 and "E2 candidate" not in text
    assert RUN_2_OWNER_MESSAGE in text and MANIFEST_3_SHA256 in text and "N = 102" in text
    for s in ("Survivorship bias (material, unbounded)", "TTM check 4 complete: False", "94 valuation dates and 93 monthly",
              "95 valuation dates and 94 monthly"):
        assert s in text, s
    for tid in run.TRIALS.values():
        assert f"## {tid}\n\nVerdict: **fail**" in text
        sec = text.split(f"## {tid}")[1].split("\n## ")[0]
        assert "| P1 | False |" in sec and "| P2 | False |" in sec and "| P3 | False |" in sec
        assert all(f"| P{i} | True |" in sec for i in range(4, 12))


@pytest.mark.parametrize("rid", sorted(edge_registry.B5_RUN_IDS))
def test_no_b5_trial_or_robustness_id_can_run_or_be_recorded_while_closed(closed, rid):
    env = closed
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


def test_a_copied_registry_and_status_cannot_open_the_run(closed):
    """An alternate invocation that points preflight at copies passes preflight there, but the gate reads only the
    real status.json and lock (here held closed), so nothing can be run, scored from loaded data, or recorded."""
    env = closed
    pre(env)
    assert env["lock"].exists()
    runs = {t: synthetic_run(t, i) for i, t in enumerate(run.TRIALS)}
    for call in (lambda: run.load_inputs(), lambda: run.finish(runs, env["registry"], env["status"], "x",
                                                                  env["repo"] / "r.md", PRE),
                 lambda: run.run_one("H1", {}, {}, env["registry"]),
                 lambda: bt.run_trial(run.TRIALS["H1"], env["registry"], pd.DataFrame(), None, None, None)):
        with pytest.raises(PermissionError):
            call()
    assert results(env["registry"]) == []


@pytest.mark.parametrize("case", ["no_lock", "no_auth", "other_message", "not_true"])
def test_the_gate_needs_the_authorisation_and_a_lock_naming_the_same_message(env, monkeypatch, case):
    lock = env["lock"]
    status = json.loads(env["status"].read_text())
    good = {"owner_message": "cmsg_TEST", "manifest": sha(env["manifest"])}
    if case != "no_lock":
        lock.write_text(json.dumps({**good, "owner_message": "cmsg_OTHER" if case == "other_message" else "cmsg_TEST"}))
    if case == "no_auth":
        status.pop("b5_trial_run")
    if case == "not_true":
        status["b5_trial_run"]["authorised"] = "true"
    env["status"].write_text(json.dumps(status))
    point_gate(monkeypatch, env)
    with pytest.raises(PermissionError):
        edge_registry.b5_run_open()
    lock.write_text(json.dumps(good))
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
    assert run.P7_WINDOW_DISCLOSURE in txt  # D29: P7's shorter window is always stated
    for s in ("94 valuation dates and 93 monthly returns", "95 valuation dates and 94 monthly", "not directly comparable",
              "on its own dates"):
        assert s in run.P7_WINDOW_DISCLOSURE, s


def test_the_real_manifest_matches_the_files_it_names():
    """Every file MANIFEST-3 names still has its recorded hash, except research/edge_registry.py: O4 added D31 to
    the spent set after run 2 spent MANIFEST-3. That file's run-2 bytes are checked from the committed fixture
    instead, and the real file is checked to differ, so MANIFEST-3 can never pass the gate's file check again."""
    m = json.loads(run.MANIFEST.read_text())
    for group in ("inputs", "code"):
        for path, h in m[group].items():
            p = Path(path) if Path(path).is_absolute() else REPO / path
            if path == "research/edge_registry.py":
                assert h == MANIFEST_3_EDGE_REGISTRY_SHA256 and sha(p) != h
            elif p.exists():  # the shared research data is absent on some machines
                assert sha(p) == h, path
    run_2_edge_registry_bytes()


def test_since_run_2_edge_registry_changed_only_in_the_spent_set():
    """D33/D34: the only lines of research/edge_registry.py that differ from the run-2 fixture are the spent-set
    comment and definition, so the production change stays exactly what the owner approved."""
    import difflib
    old = run_2_edge_registry_bytes().decode().splitlines()
    new = Path(edge_registry.__file__).read_text().splitlines()
    changed = [l for l in difflib.unified_diff(old, new, lineterm="", n=0)
               if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    assert changed and all(l[1:].startswith(("#", "B5_SPENT_AUTHORISATIONS = ", " " * 37 + '"cmsg_')) for l in changed), changed


def test_every_spent_authorisation_in_the_history_is_spent_in_code_and_refused(tmp_path):
    """O4: each status.json history entry marked spent is in B5_SPENT_AUTHORISATIONS, and re-authorising it (for
    the manifest it named) is refused at the authorisation, before any lock, registry or file is read."""
    hist = json.loads(b5.STATUS.read_text())["b5_trial_run"]["history"]
    spent = [h for h in hist if h.get("spent") is True]
    assert {h["owner_message"] for h in spent} == {RUN_1_OWNER_MESSAGE, RUN_2_OWNER_MESSAGE}
    assert {h["owner_message"] for h in spent} <= edge_registry.B5_SPENT_AUTHORISATIONS
    status = tmp_path / "status.json"
    for h in spent:
        auth = {"authorised": True, "owner_message": h["owner_message"], "manifest_id": run.MANIFEST_ID,
                "manifest_sha256": h.get("manifest_sha256", MANIFEST_3_SHA256)}
        status.write_text(json.dumps({"b5_trial_run": auth}))
        with pytest.raises(PermissionError, match="spent"):
            edge_registry.b5_authorisation(status)


def test_the_real_gate_refuses_manifest_3_on_its_files_even_with_a_fresh_authorisation(tmp_path, monkeypatch):
    """Belt and braces: an unspent authorisation for MANIFEST-3 with a matching lock still cannot open the real
    gate, because research/edge_registry.py no longer matches MANIFEST-3."""
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"b5_trial_run": {"authorised": True, "owner_message": "cmsg_FRESH",
                                                   "manifest_id": run.MANIFEST_ID, "manifest_sha256": MANIFEST_3_SHA256}}))
    lock = tmp_path / "b5.lock"
    lock.write_text(json.dumps({"owner_message": "cmsg_FRESH", "manifest": MANIFEST_3_SHA256}))
    monkeypatch.setattr(edge_registry, "STATUS", status)
    monkeypatch.setattr(edge_registry, "B5_LOCK", lock)
    assert edge_registry.b5_run_open(verify_files=False) == "cmsg_FRESH"  # every other control passes
    with pytest.raises(PermissionError, match="edge_registry.py does not match"):
        edge_registry.b5_run_open(verify_files=True)



# D34: sha256 of each protected B5 artefact, each verified independently against the commit that wrote it and a
# second recorded copy (status.json history, the registry, DECISIONS or the report), so no test needs git history.
HISTORICAL_SHA256 = {
    "research/edge/trials.jsonl": RUN_2_REGISTRY_SHA256,  # a4a07d7 (run 2 results); D32 row
    "research/edge/status.json": "dfee716a559b092f471d8f36611727782465155fb1d672abfa170373e400086e",  # 1eb0e96 (D32)
    "docs/edge/incidents/B5_RUN_1_LOCK.json": ARCHIVED_LOCK_SHA256,  # 4215a98; status history run 1
    "docs/edge/incidents/B5_RUN_2_LOCK.json": RUN_2_LOCK_SHA256,  # e5d1dc1; status history run 2
    "equity/reports/research/edge/b5_trials.md": RUN_2_REPORT_SHA256,  # a4a07d7; status history run 2 outcome
    "docs/edge/B5_RUN_MANIFEST_3.json": MANIFEST_3_SHA256,  # bb9ea44; registry event B5-V3-RUN-MANIFEST-3 (D30)
}


def pinned_ok(p: Path, h: str) -> bool:
    return p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == h


def test_reusing_d31_is_refused_at_the_first_control_before_any_lock_or_research_file(tmp_path, monkeypatch):
    """D33: a status re-authorising D31 for MANIFEST-3 is refused by the authorisation check itself. The registry,
    manifest, repository and lock paths here do not exist, so any later control would fail differently; preflight
    and the gate both stop at "spent", and no lock is created."""
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"b5_trial_run": {"authorised": True, "owner_message": RUN_2_OWNER_MESSAGE,
                                                   "manifest_id": run.MANIFEST_ID, "manifest_sha256": MANIFEST_3_SHA256}}))
    gone = tmp_path / "absent"
    e = {"registry": gone / "trials.jsonl", "status": status, "manifest": gone / "manifest.json", "repo": gone,
         "lock": tmp_path / "b5.lock"}
    with pytest.raises(PermissionError, match="spent"):
        pre(e)
    assert not e["lock"].exists() and not gone.exists()
    point_gate(monkeypatch, e)
    with pytest.raises(PermissionError, match="spent"):
        edge_registry.b5_run_open(verify_files=True)
    assert RUN_2_OWNER_MESSAGE in edge_registry.B5_SPENT_AUTHORISATIONS
    assert RUN_1_OWNER_MESSAGE in edge_registry.B5_SPENT_AUTHORISATIONS


def test_preflight_refuses_manifest_3_on_its_files_even_with_a_fresh_authorisation(tmp_path):
    """D33: an unspent authorisation naming MANIFEST-3 passes the authorisation check, but preflight then refuses
    because research/edge_registry.py no longer matches MANIFEST-3, before the results check and before any lock.
    The manifest is not rewritten and the check is not bypassed."""
    reg = tmp_path / "trials.jsonl"
    shutil.copy(edge_registry.PATH, reg)
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"b5_trial_run": {"authorised": True, "owner_message": "cmsg_FRESH",
                                                   "manifest_id": run.MANIFEST_ID, "manifest_sha256": MANIFEST_3_SHA256}}))
    assert edge_registry.b5_authorisation(status)["owner_message"] == "cmsg_FRESH"
    e = {"registry": reg, "status": status, "manifest": run.MANIFEST, "repo": REPO, "lock": tmp_path / "b5.lock"}
    with pytest.raises(ValueError, match="research/edge_registry.py does not match the manifest"):
        pre(e)
    assert not e["lock"].exists() and reg.read_bytes() == edge_registry.PATH.read_bytes()
    assert sha(run.MANIFEST) == MANIFEST_3_SHA256


@pytest.mark.parametrize("path", sorted(HISTORICAL_SHA256))
def test_historical_evidence_is_byte_identical_to_its_pinned_hash(path):
    """D33/D34: the registry, status history, both archived locks, run 2's report and MANIFEST-3 keep the exact
    bytes recorded when they were written (pinned sha256, no git history needed)."""
    assert pinned_ok(REPO / path, HISTORICAL_SHA256[path])


@pytest.mark.parametrize("path", sorted(HISTORICAL_SHA256) + ["fixture"])
def test_the_pins_detect_an_altered_or_missing_copy(path, tmp_path):
    """Any one-byte change, truncation or deletion of a pinned artefact (or of the run-2 fixture) fails its pin."""
    src, h = (RUN_2_EDGE_REGISTRY, MANIFEST_3_EDGE_REGISTRY_SHA256) if path == "fixture" else (REPO / path,
                                                                                              HISTORICAL_SHA256[path])
    data = src.read_bytes()
    c = tmp_path / "copy"
    c.write_bytes(data)
    assert pinned_ok(c, h)
    for bad in (data[:-1] + bytes([data[-1] ^ 1]), data[:-1], data + b"\n"):
        c.write_bytes(bad)
        assert not pinned_ok(c, h)
    c.unlink()
    assert not pinned_ok(c, h)


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
    assert by_id["B5-H1-V3-ROB-WINQ"] == ["window"]
    assert "B5-H1-V2-ROB-PITQ" not in by_id
    assert all(n == "primary" for rid, ns in by_id.items() if rid != "B5-H1-V3-ROB-WINQ" for n in ns)


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


@pytest.mark.parametrize("rid", ["B5-H1-V3-ROB-WINQ", "B5-S2A-V3-ROB-WINQ", "B5-V3-ADDENDUM-3"])
def test_preflight_refuses_when_an_addendum_3_record_is_missing(env, rid):
    lines = env["registry"].read_text().splitlines()
    env["registry"].write_text("\n".join(l for l in lines if f'"id": "{rid}"' not in l) + "\n")
    with pytest.raises((KeyError, ValueError)):
        pre(env)
    assert not env["lock"].exists()


def test_preflight_refuses_a_robustness_run_that_counts(env, monkeypatch, tmp_path):
    reg = tmp_path / "counted.jsonl"
    pre_v3(reg)
    evs = edge_b5_addendum3.events(env["repo"])
    evs = [{**e, "counts_for_dsr": True} if e["id"] == "B5-H1-V3-ROB-WINQ" else e for e in evs]  # wrongly counted
    for e in evs:
        edge_registry.append(e, reg)
    edge_registry.append({"event": "register", "id": run.MANIFEST_ID, "kind": "diagnostic", "phase": "exploration",
                          "hypothesis": "none", "definition": "test", "universe": "x", "horizon_months": 0,
                          "window": {}, "counts_for_dsr": False, "touched_holdout": False,
                          "spec_sha256": sha(env["manifest"])}, reg)
    monkeypatch.setattr(run, "N_EXPECTED", 103)  # isolate the check from the N check
    with pytest.raises(ValueError, match="must not count"):
        run.preflight(reg, env["status"], env["manifest"], env["repo"], env["lock"])
    assert not env["lock"].exists()


def test_version_3_registration_adds_exactly_the_two_v3_trials_and_preserves_every_earlier_line(tmp_path):
    """D21: registering version 3 takes N from 100 to 102, counting only the two V3 trials; every existing registry
    line (version 1, version 2, addenda 1-2) stays byte-identical; it needs the owner's message id and runs once."""
    reg = tmp_path / "t.jsonl"
    pre_v3(reg)
    before_lines = reg.read_text().splitlines()
    assert edge_registry.n_trials(edge_registry.load(reg)) == 100
    with pytest.raises(PermissionError):
        edge_b5_addendum3.register("not-a-message", reg)
    assert reg.read_text().splitlines() == before_lines
    out = edge_b5_addendum3.register("cmsg_X", reg)
    ids = [e["id"] for e in out]
    assert ids[0] == "B5-V3-ADDENDUM-3" and len(ids) == 13 and len(set(ids)) == 13
    assert {e["id"] for e in out if e["counts_for_dsr"]} == set(run.TRIALS.values())
    assert {e["id"] for e in out if not e["counts_for_dsr"]} == {"B5-V3-ADDENDUM-3"} | {
        run.rob_id(t, g) for t in run.TRIALS for g in run.ROB_IDS}
    ev = edge_registry.load(reg)
    assert edge_registry.n_trials(ev) == 102 == run.N_EXPECTED and not edge_registry.validate(reg)
    after = reg.read_text().splitlines()
    assert after[:len(before_lines)] == before_lines  # history byte-identical
    regd = edge_registry.registered(ev)
    for old in ("B5-H1-FCFPS-ACCEL-V2", "B5-S2A-GP-12M-V2", "B5-H1-FCFPS-ACCEL", "B5-S2A-GP-12M"):
        assert regd[old]["counts_for_dsr"] is True and old in edge_registry.B5_RETIRED_IDS
    a3 = sha(REPO / "docs" / "edge" / "B5_PREREGISTRATION_ADDENDUM_3.md")
    assert all(e["spec_sha256"] == a3 for e in out)
    assert regd["B5-H1-FCFPS-ACCEL-V3"]["supersedes"] == "B5-H1-FCFPS-ACCEL-V2"
    with pytest.raises(ValueError, match="already registered"):
        edge_b5_addendum3.register("cmsg_X", reg)


def test_version_3_registration_is_all_or_nothing(tmp_path, monkeypatch):
    """Owner approval 07:53Z: the 13-event transition is atomic. A bad 13th line, a proposal mismatch, a partial
    clash, an invalid registry or a failed rename each leave the registry byte-identical."""
    import json
    import os
    reg = tmp_path / "t.jsonl"
    pre_v3(reg)
    before = reg.read_bytes()
    evs = edge_b5_addendum3.events()
    assert evs == json.loads(edge_b5_addendum3.PROPOSAL.read_text())  # code and reviewed file agree
    bad = evs[:-1] + [{**evs[-1], "kind": "bogus"}]  # 12 good events, the 13th invalid
    prop = tmp_path / "bad.json"
    prop.write_text(json.dumps(bad))
    monkeypatch.setattr(edge_b5_addendum3, "events", lambda repo=None: bad)
    with pytest.raises(ValueError, match="rejected"):
        edge_b5_addendum3.register("cmsg_X", reg, proposal=prop)
    assert reg.read_bytes() == before
    monkeypatch.undo()
    with pytest.raises(ValueError, match="differ from the reviewed proposal"):
        edge_b5_addendum3.register("cmsg_X", reg, proposal=prop)
    assert reg.read_bytes() == before
    one = tmp_path / "one.jsonl"  # only the last id already present: nothing else may be added
    pre_v3(one)
    edge_registry.append(evs[-1], one)
    one_before = one.read_bytes()
    with pytest.raises(ValueError, match="already registered"):
        edge_b5_addendum3.register("cmsg_X", one)
    assert one.read_bytes() == one_before
    broken = tmp_path / "broken.jsonl"
    broken.write_bytes(before.replace(b'"prev": "', b'"prev": "x', 1))
    with pytest.raises(ValueError, match="invalid before"):
        edge_b5_addendum3.register("cmsg_X", broken)

    def fail(*a):
        raise OSError("disk")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        edge_b5_addendum3.register("cmsg_X", reg)
    assert reg.read_bytes() == before and not list(tmp_path.glob("*.tmp"))


def test_preflight_refuses_at_n_100_before_version_3_is_registered(env, tmp_path):
    """The version-2-only registry (as it is today) cannot start the run: the V3 records are missing."""
    reg = tmp_path / "v2only.jsonl"
    pre_v3(reg)
    with pytest.raises((KeyError, ValueError)):
        run.preflight(reg, env["status"], env["manifest"], env["repo"], env["lock"])
    assert not env["lock"].exists()


def test_version_2_ids_are_retired_and_version_3_ids_are_the_only_runnable_b5_ids():
    v2 = {"B5-H1-FCFPS-ACCEL-V2", "B5-S2A-GP-12M-V2"} | {f"B5-{t}-V2-ROB-{g}" for t in ("H1", "S2A")
                                                         for g in ("2XCOST", "MISS100", "NEXTMONTH", "DATAERR", "PITQ")}
    assert v2 <= edge_registry.B5_RETIRED_IDS
    assert all("-V3" in i for i in edge_registry.B5_RUN_IDS) and len(edge_registry.B5_RUN_IDS) == 12
    for rid in v2:
        with pytest.raises(ValueError, match="retired"):
            edge_registry.require(rid)


def test_in_the_real_registry_version_3_and_its_manifests_are_registered_and_nothing_else(tmp_path):
    """Step 1 (owner approval 07:53Z, card 08:22Z): the 13 version-3 events were appended atomically after an
    unchanged history. Step 2 (owner approval 08:29Z): one more line, B5-V3-RUN-MANIFEST at the reviewed manifest
    hash, uncounted. Then MANIFEST-2 (08:47Z, D25) and MANIFEST-3 (13:15Z, D30), each superseding the one before.
    These assertions read the registry as it stood before run 2 (its first 240 lines); run 2's results are checked
    in test_run_2s_results_and_report_are_recorded_unchanged. N = 102."""
    ev = edge_registry.load()[:PRE_RUN_2_LINES]
    reg = edge_registry.registered(ev)
    v3 = edge_b5_addendum3.events()
    assert hashlib.sha256(pre_v3(tmp_path / "pre.jsonl").read_bytes()).hexdigest() == PRE_V3_SHA256  # history intact
    assert [e["id"] for e in ev[-16:-3]] == [e["id"] for e in v3]
    for got, want in zip(ev[-16:-3], v3):
        assert {k: got[k] for k in want} == want and got["owner_message"] == V3_OWNER_MESSAGE
    m = ev[-3]
    assert m["id"] == "B5-V3-RUN-MANIFEST" and m["counts_for_dsr"] is False and m["owner_message"] == MANIFEST_OWNER_MESSAGE
    assert m["spec_sha256"] == MANIFEST_SHA256 == sha(REPO / "docs" / "edge" / "B5_RUN_MANIFEST.json")  # kept as registered
    assert edge_registry.n_trials(ev) == 102 == run.N_EXPECTED and not edge_registry.validate()
    done = {e["id"] for e in ev if e.get("event") == "result"}
    assert not done & (set(edge_registry.B5_RUN_IDS) | set(edge_registry.B5_RETIRED_IDS))
    assert {"B5-H1-FCFPS-ACCEL-V2", "B5-S2A-GP-12M-V2", "B5-H1-V2-ROB-PITQ", "B5-S2A-V2-ROB-PITQ"} <= set(reg)
    m2 = ev[-2]  # step 2 repeated after run fix 1 (owner approval 08:47Z)
    assert m2["id"] == "B5-V3-RUN-MANIFEST-2" and m2["counts_for_dsr"] is False and m2["supersedes"] == m["id"]
    assert m2["spec_sha256"] == MANIFEST_2_SHA256 == sha(REPO / "docs" / "edge" / "B5_RUN_MANIFEST_2.json")
    assert m2["owner_message"] == MANIFEST_2_OWNER_MESSAGE
    m3 = ev[-1]  # after run fix 2, the hardening and D29 (owner approval 13:15Z, D30)
    proposed = json.loads((REPO / "docs" / "edge" / "B5_V3_PROPOSED_MANIFEST_3_EVENT.json").read_text())
    assert m3["id"] == run.MANIFEST_ID and m3["counts_for_dsr"] is False and m3["supersedes"] == m2["id"]
    assert m3["spec_sha256"] == MANIFEST_3_SHA256 == sha(run.MANIFEST) and m3["owner_message"] == MANIFEST_3_OWNER_MESSAGE
    assert {k: m3[k] for k in proposed if k != "owner_message"} == {k: v for k, v in proposed.items() if k != "owner_message"}
    assert json.loads(edge_registry.STATUS.read_text())["b5_trial_run"]["history"][0]["owner_message"] == \
        "cmsg_01U4KMvkBYNknqm4HRVie8uvUzn9qQCoyy3U7K3j4iY3kK"  # D26 authorisation, spent by run 1 (D29 history)


def test_reports_carry_the_addendum_3_and_other_later_information_disclosures():
    for s in ("AVITA", "CoStar", "10-for-1", "P8", "SIC", "2026 snapshot", "General Dynamics", "Abbott"):
        assert s in run.KNOWN_INPUT_LIMITATIONS, s


def test_stage_never_touches_the_registry_and_refuses_bad_input(tmp_path):
    """edge_registry.stage/commit (B5_RUN_FIX_1): staging leaves the registry byte-identical; an invalid event, a
    confirmation batch or an invalid registry is refused with no staged copy left; commit refuses a registry that
    changed after staging."""
    reg = tmp_path / "t.jsonl"
    shutil.copy(edge_registry.PATH, reg)
    before = reg.read_bytes()
    ok = {"event": "register", "id": "S1", "kind": "diagnostic", "phase": "exploration", "hypothesis": "x",
          "definition": "x", "universe": "x", "horizon_months": 0, "window": {}, "counts_for_dsr": False,
          "touched_holdout": False}
    for bad in ([ok, {**ok, "id": "S2", "kind": "bogus"}], [ok, ok], [{"event": "batch", "batch": "b"}]):
        with pytest.raises(ValueError):
            edge_registry.stage(bad, reg)
        assert reg.read_bytes() == before and not list(tmp_path.glob("*.staged"))
    staged, old = edge_registry.stage([ok, {**ok, "id": "S2"}], reg)
    assert reg.read_bytes() == before and staged.read_bytes().startswith(before)
    edge_registry.append({**ok, "id": "S3"}, reg)  # someone else writes in between
    with pytest.raises(ValueError, match="changed since staging"):
        edge_registry.commit(staged, old, reg)
    staged.unlink()
    broken = tmp_path / "b.jsonl"
    broken.write_bytes(before.replace(b'"prev": "', b'"prev": "x', 1))
    with pytest.raises(ValueError, match="invalid before"):
        edge_registry.stage([ok], broken)


def test_the_fixed_run_uses_only_the_new_manifest_and_the_old_records_are_kept():
    """B5_RUN_FIX_2: the run looks up B5-V3-RUN-MANIFEST-3 for B5_RUN_MANIFEST_3.json (registered on the owner's
    approval 13:15Z, D30); the registered B5-V3-RUN-MANIFEST and B5-V3-RUN-MANIFEST-2 records and their files are
    kept unchanged and never used."""
    assert run.MANIFEST_ID == "B5-V3-RUN-MANIFEST-3" and run.MANIFEST.name == "B5_RUN_MANIFEST_3.json"
    assert not {"B5-V3-RUN-MANIFEST", "B5-V3-RUN-MANIFEST-2"} & set(run.SPECS)
    reg = edge_registry.registered(edge_registry.load())
    assert reg[run.MANIFEST_ID]["spec_sha256"] == sha(run.MANIFEST) == MANIFEST_3_SHA256
    assert reg["B5-V3-RUN-MANIFEST"]["spec_sha256"] == sha(REPO / "docs" / "edge" / "B5_RUN_MANIFEST.json")
    assert reg["B5-V3-RUN-MANIFEST-2"]["spec_sha256"] == sha(REPO / "docs" / "edge" / "B5_RUN_MANIFEST_2.json")


def test_the_proposed_manifest_2_event_matches_the_files_it_names():
    ev = json.loads((REPO / "docs" / "edge" / "B5_V3_PROPOSED_MANIFEST_2_EVENT.json").read_text())
    assert ev["id"] == "B5-V3-RUN-MANIFEST-2" and ev["counts_for_dsr"] is False and ev["supersedes"] == "B5-V3-RUN-MANIFEST"
    assert ev["spec_sha256"] == sha(REPO / "docs" / "edge" / "B5_RUN_MANIFEST_2.json")
    assert sha(REPO / "docs" / "edge" / "B5_RUN_FIX_1.md") in ev["definition"]


def test_the_proposed_manifest_3_event_matches_the_files_it_names():
    """B5_RUN_FIX_2: the proposed event for MANIFEST-3, superseding MANIFEST-2 (the file keeps its placeholder; the
    registered copy carries the owner's D30 message id)."""
    ev = json.loads((REPO / "docs" / "edge" / "B5_V3_PROPOSED_MANIFEST_3_EVENT.json").read_text())
    assert ev["id"] == run.MANIFEST_ID and ev["counts_for_dsr"] is False and ev["supersedes"] == "B5-V3-RUN-MANIFEST-2"
    assert ev["spec_sha256"] == sha(run.MANIFEST)
    assert sha(REPO / "docs" / "edge" / "B5_RUN_FIX_2.md") in ev["definition"]
    assert ev["owner_message"].startswith("<")  # a placeholder: nothing is approved
