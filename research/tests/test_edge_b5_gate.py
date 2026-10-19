"""B5 execution hardening after run 1 (owner, 2026-10-19 12:15Z): every protected entry point refuses unless a valid,
unspent owner authorisation names the registered manifest by id and sha256, the one-run lock names the same message
and manifest, and every file the manifest lists still has its hash.

Negative tests of each entry point (load_inputs, run_one, finish, and the per-trial bt.run_trial, bt.record and
edge_registry.require) under each failure, plus the positive control that the same calls pass the gate when nothing
is wrong. Synthetic only: no research data is read (the data loader is replaced by a sentinel that fails the test if
reached) and no trial is run."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_b5_run as run  # noqa: E402
import edge_backtest as bt  # noqa: E402
import edge_registry  # noqa: E402
from test_edge_b5_run import env, point_gate, sha  # noqa: E402,F401

D26 = "cmsg_01U4KMvkBYNknqm4HRVie8uvUzn9qQCoyy3U7K3j4iY3kK"  # run 1's authorisation, spent


class DataRead(Exception):
    """Raised by the sentinel loader: reaching it means the gate let the call through to the data."""


@pytest.fixture
def armed(env, monkeypatch):
    """env after a successful preflight, every gate path pointed at it, and the data loader replaced by a sentinel."""
    run.preflight(env["registry"], env["status"], env["manifest"], env["repo"], env["lock"])
    point_gate(monkeypatch, env)
    fake = type(sys)("xsection")

    def load(*a, **k):
        raise DataRead("xsection.load reached")
    fake.load = load
    monkeypatch.setitem(sys.modules, "xsection", fake)
    return env


def entry_points(e):
    """Each protected call, reduced to the cheapest arguments: the gate is their first statement."""
    tid = run.TRIALS["H1"]
    return {
        "load_inputs": lambda: run.load_inputs(),
        "run_one": lambda: run.run_one("H1", {}, {}, e["registry"]),
        "finish": lambda: run.finish({}, e["registry"], e["status"], "x", e["repo"] / "r.md", {}),
        "run_trial": lambda: bt.run_trial(tid, e["registry"], pd.DataFrame(), None, None, None),
        "record": lambda: bt.record(tid, {"sr_excess_monthly": 0.1, "excess_months": 94}, e["registry"], "x"),
        "require": lambda: edge_registry.require(tid, e["registry"]),
    }


def status_edit(field, value):
    def f(e):
        s = json.loads(e["status"].read_text())
        if value is DELETE:
            s["b5_trial_run"].pop(field, None)
        else:
            s["b5_trial_run"][field] = value
        e["status"].write_text(json.dumps(s))
    return f


def lock_edit(**kw):
    def f(e):
        lock = json.loads(e["lock"].read_text())
        lock.update(kw)
        e["lock"].write_text(json.dumps(lock))
    return f


DELETE = object()
OTHER_SHA = "f" * 64


def drop_status(e):
    s = json.loads(e["status"].read_text())
    s.pop("b5_trial_run")
    e["status"].write_text(json.dumps(s))


def no_status_file(e):
    e["status"].unlink()


def spent(e):
    """Run 1's D26 authorisation, otherwise complete and current, with a lock naming it: still refused."""
    status_edit("owner_message", D26)(e)
    lock_edit(owner_message=D26)(e)


def no_lock(e):
    e["lock"].unlink()


def bad_lock(e):
    e["lock"].write_text("not json")


def manifest_changed(e):
    e["manifest"].write_bytes(e["manifest"].read_bytes() + b" ")


def manifest_unregistered(e):
    """The registry without the manifest's register event (the last line in env)."""
    lines = e["registry"].read_text().splitlines(keepends=True)
    assert json.loads(lines[-1])["id"] == run.MANIFEST_ID
    e["registry"].write_text("".join(lines[:-1]))


def manifest_registered_elsewhere(e):
    """Status, lock and manifest file agree, but the registry registers the manifest id at another sha256 (the
    registered manifest is not the one authorised)."""
    lines = e["registry"].read_text().splitlines(keepends=True)
    last = json.loads(lines[-1])
    e["registry"].write_text("".join(lines[:-1]))
    edge_registry.append({k: v for k, v in last.items() if k not in ("prev", "date")} | {"spec_sha256": OTHER_SHA},
                         e["registry"])


def input_changed(e):
    (e["repo"] / "in.csv").write_text("a,b\n1,3\n")


def code_changed(e):
    (e["repo"] / "code.py").write_text("x = 2\n")


def input_missing(e):
    (e["repo"] / "in.csv").unlink()


CASES = {
    "authorised false": status_edit("authorised", False),
    "authorised not True": status_edit("authorised", "true"),
    "authorisation missing": drop_status,
    "status file missing": no_status_file,
    "owner message missing": status_edit("owner_message", DELETE),
    "owner message not a cmsg id": status_edit("owner_message", "approved"),
    "stale: run 1's spent D26 authorisation": spent,
    "stale: authorisation for MANIFEST-2": status_edit("manifest_id", "B5-V3-RUN-MANIFEST-2"),
    "manifest id missing": status_edit("manifest_id", DELETE),
    "manifest sha missing": status_edit("manifest_sha256", DELETE),
    "manifest sha malformed": status_edit("manifest_sha256", "abc"),
    "lock absent": no_lock,
    "lock unreadable": bad_lock,
    "lock names another message": lock_edit(owner_message="cmsg_OTHER"),
    "lock names another manifest": lock_edit(manifest=OTHER_SHA),
    "manifest file changed": manifest_changed,
    "manifest not registered": manifest_unregistered,
    "manifest registered at another sha": manifest_registered_elsewhere,
}
FILE_CASES = {"input file changed": input_changed, "code file changed": code_changed,
              "input file missing": input_missing}
ENTRY = ["load_inputs", "run_one", "finish", "run_trial", "record", "require"]
HEAVY = ["load_inputs", "run_one", "finish"]  # these also re-hash every file the manifest lists


@pytest.mark.parametrize("entry", ENTRY)
@pytest.mark.parametrize("case", sorted(CASES))
def test_every_entry_point_refuses_when_the_authorisation_lock_or_manifest_is_wrong(armed, case, entry):
    CASES[case](armed)
    before = armed["registry"].read_bytes()
    with pytest.raises(PermissionError):
        entry_points(armed)[entry]()
    assert armed["registry"].read_bytes() == before
    assert not (armed["repo"] / "r.md").exists()


@pytest.mark.parametrize("entry", HEAVY)
@pytest.mark.parametrize("case", sorted(FILE_CASES))
def test_the_data_and_result_entry_points_refuse_when_a_listed_file_no_longer_matches(armed, case, entry):
    FILE_CASES[case](armed)
    with pytest.raises(PermissionError, match="does not match the run manifest"):
        entry_points(armed)[entry]()


def test_positive_control_each_entry_point_passes_the_gate_when_nothing_is_wrong(armed):
    """The same calls get past the gate and fail only at their next step, so the refusals above come from the gate."""
    calls = entry_points(armed)
    assert edge_registry.b5_run_open(verify_files=True) == "cmsg_TEST"
    with pytest.raises(DataRead):
        calls["load_inputs"]()
    with pytest.raises(KeyError):  # an empty panels dict: past the gate, at the first lookup
        calls["run_one"]()
    with pytest.raises(RuntimeError, match="both trials"):
        calls["finish"]()
    assert calls["require"]()["id"] == run.TRIALS["H1"]


def test_run_1s_authorisation_can_never_open_another_run_even_with_a_fresh_lock_and_manifest(env, monkeypatch):
    """D26 with everything else valid: preflight refuses before taking a lock, and a lock written by hand naming it
    does not open the gate either."""
    s = json.loads(env["status"].read_text())
    s["b5_trial_run"]["owner_message"] = D26
    env["status"].write_text(json.dumps(s))
    with pytest.raises(PermissionError, match="spent"):
        run.preflight(env["registry"], env["status"], env["manifest"], env["repo"], env["lock"])
    assert not env["lock"].exists()
    env["lock"].write_text(json.dumps({"owner_message": D26, "manifest": sha(env["manifest"])}))
    point_gate(monkeypatch, env)
    with pytest.raises(PermissionError, match="spent"):
        edge_registry.b5_run_open()
    assert D26 in edge_registry.B5_SPENT_AUTHORISATIONS


@pytest.mark.parametrize("edit", ["manifest_id", "manifest_sha256", "manifest_file"])
def test_preflight_refuses_an_authorisation_for_another_manifest_before_taking_the_lock(env, edit):
    if edit == "manifest_file":
        manifest_changed(env)
    else:
        status_edit(edit, "B5-V3-RUN-MANIFEST-2" if edit == "manifest_id" else OTHER_SHA)(env)
    with pytest.raises(PermissionError):
        run.preflight(env["registry"], env["status"], env["manifest"], env["repo"], env["lock"])
    assert not env["lock"].exists()


def test_the_run_and_the_gate_name_the_same_manifest():
    assert run.MANIFEST == edge_registry.B5_MANIFEST and run.MANIFEST_ID == edge_registry.B5_MANIFEST_ID
    assert run.SPECS[run.MANIFEST_ID] == "docs/edge/" + run.MANIFEST.name


def test_in_the_real_repo_the_gate_is_closed_until_preflight_takes_the_lock():
    """D31: the real status.json authorises run 2 on MANIFEST-3 (run 1's D26 is history, and spent in code too); with
    no lock the gate stops before the registry or any listed file is read."""
    with pytest.raises(PermissionError, match="not open"):
        edge_registry.b5_run_open(verify_files=True)
