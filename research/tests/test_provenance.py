"""Research-run provenance (mini fund Stage 2 §3). Offline: every test runs behind a guard that makes any network
connection raise, and uses only temporary files or committed fixtures."""
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import provenance as pv  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "provenance"


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise NetworkBlocked("network access attempted in an offline test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def fixed_versions():
    return {"numpy": {"version": "2.5.3"}, "pandas": {"version": "3.0.5"}}


def clean_git(repo):
    return {"commit": "a" * 40, "dirty": False, "dirty_paths": []}


def make(tmp_path, inputs, params, **kw):
    return pv.run_manifest(inputs, params, purpose="test", repo=tmp_path, versions=fixed_versions, git=clean_git, **kw)


def test_the_network_guard_blocks_connections():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443), timeout=1)
    with pytest.raises(NetworkBlocked):
        socket.socket().connect(("93.184.216.34", 443))


def test_same_inputs_and_params_give_the_same_manifest_apart_from_times(tmp_path):
    f = tmp_path / "a.csv"
    f.write_bytes(b"x,y\n1,2\n")
    m1 = make(tmp_path, [f], {"h": [1, 5, 20]}, started_at="2026-10-23T00:00:00+00:00")
    m2 = make(tmp_path, [f], {"h": [1, 5, 20]}, started_at="2026-10-24T09:00:00+00:00", finished_at="x")
    assert m1["content_sha256"] == m2["content_sha256"]
    strip = lambda m: {k: v for k, v in m.items() if k not in pv.TIME_FIELDS}
    assert strip(m1) == strip(m2)


def test_param_key_order_does_not_matter_but_values_do(tmp_path):
    a = make(tmp_path, [], {"a": 1, "b": 2})
    b = make(tmp_path, [], {"b": 2, "a": 1})
    c = make(tmp_path, [], {"a": 1, "b": 3})
    assert a["params_sha256"] == b["params_sha256"] != c["params_sha256"]


def test_one_changed_input_byte_changes_only_that_hash(tmp_path):
    f, g = tmp_path / "f.bin", tmp_path / "g.bin"
    f.write_bytes(b"\x00" * 100)
    g.write_bytes(b"\x01" * 100)
    before = {r["path"]: r["sha256"] for r in make(tmp_path, [f, g], {})["inputs"]}
    f.write_bytes(b"\x00" * 99 + b"\x02")
    after = {r["path"]: r["sha256"] for r in make(tmp_path, [f, g], {})["inputs"]}
    assert before["f.bin"] != after["f.bin"] and before["g.bin"] == after["g.bin"]


def test_known_bytes_have_their_known_hash(tmp_path):
    f = tmp_path / "abc"
    f.write_bytes(b"abc")
    assert pv.input_record(f, tmp_path)["sha256"] == \
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_a_missing_input_is_null_with_a_reason_not_a_guess(tmp_path):
    rec = make(tmp_path, [tmp_path / "absent.csv"], {})["inputs"][0]
    assert rec == {"path": "absent.csv", "bytes": None, "sha256": None, "missing_reason": "not_found"}


def test_a_missing_package_is_null_not_an_error():
    def version(name):
        if name == "statsmodels":
            raise pv.importlib.metadata.PackageNotFoundError(name)
        return "1.0"
    v = pv.package_versions(("numpy", "statsmodels"), version=version)
    assert v == {"numpy": {"version": "1.0"}, "statsmodels": {"version": None, "missing_reason": "not_installed"}}


def _git(repo, *args):
    # isolated from the user's git config (signing, hooks), so the test needs no credentials
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": os.environ["PATH"]}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def test_a_dirty_tree_is_recorded_not_hidden(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "x.py").write_text("1\n")
    _git(tmp_path, "add", "x.py")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c")
    clean = pv.git_state(tmp_path)
    assert len(clean["commit"]) == 40 and clean["dirty"] is False
    (tmp_path / "x.py").write_text("2\n")
    dirty = pv.git_state(tmp_path)
    assert dirty["dirty"] is True and dirty["dirty_paths"] == ["x.py"]


def test_outside_a_git_checkout_the_commit_is_null_with_a_reason(tmp_path):
    g = pv.git_state(tmp_path / "nowhere")
    assert g["commit"] is None and g["dirty"] is None and g["missing_reason"] == "not_a_git_checkout"


def test_every_manifest_carries_its_limitations(tmp_path):
    m = make(tmp_path, [], {})
    assert m["limitations"] == list(pv.LIMITATIONS) and m["schema_version"] == "provenance-0.1"


def test_a_manifest_is_written_once_and_never_overwritten(tmp_path):
    m = make(tmp_path, [], {})
    out = pv.write(m, tmp_path / "run")
    assert json.loads(out.read_text())["content_sha256"] == m["content_sha256"]
    with pytest.raises(FileExistsError):
        pv.write(make(tmp_path, [], {"other": True}), tmp_path / "run")
    assert json.loads(out.read_text())["content_sha256"] == m["content_sha256"]
    assert not list((tmp_path / "run").glob("*.tmp"))


def test_comparison_with_a_dataset_manifest_fixture(tmp_path):
    data_manifest = json.loads((FIXTURES / "data_manifest.json").read_text())
    good = FIXTURES / "prices_small.csv"
    run = make(tmp_path, [good, FIXTURES / "missing.csv.gz"], {})
    res = pv.compare_with_data_manifest(run, data_manifest)
    assert res["matched"] == ["prices_small.csv"]
    assert res["mismatched"] == [] and res["unreadable"] == ["missing.csv.gz"]
    assert res["only_in_data_manifest"] == ["fx_small.csv"]


def test_a_changed_dataset_file_is_reported_as_mismatched(tmp_path):
    data_manifest = json.loads((FIXTURES / "data_manifest.json").read_text())
    copy = tmp_path / "prices_small.csv"
    copy.write_bytes((FIXTURES / "prices_small.csv").read_bytes() + b"\n")
    res = pv.compare_with_data_manifest(make(tmp_path, [copy], {}), data_manifest)
    assert res["mismatched"] == ["prices_small.csv"] and res["matched"] == []


def test_cli_exit_code_reflects_the_comparison(tmp_path, capsys):
    assert pv.main(["--check-data-manifest", str(FIXTURES / "data_manifest.json")]) == 1  # missing.csv.gz is unreadable
    out = json.loads(capsys.readouterr().out)
    assert out["comparison"]["matched"] == ["prices_small.csv"]
