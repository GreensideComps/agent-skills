"""Remediation of review findings P31-1 to P31-6 (mini fund Stage 2 §3). Offline: temporary folders and temporary
git repositories with no user configuration, and every test runs behind a guard that makes any network connection
raise."""
import errno
import json
import math
import os
import socket
import subprocess
import sys
import threading
from datetime import date
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


def _git(repo, *args):
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": os.environ["PATH"]}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    _git(tmp_path, "init", "-q")
    (tmp_path / "x.py").write_text("1\n")
    _git(tmp_path, "add", "x.py")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c")
    return tmp_path


def manifest(**kw):
    return pv.run_manifest([], {"p": 1}, purpose="t", git=lambda r: {"commit": "c", "dirty": False},
                           versions=lambda: {}, started_at="2026-10-23T00:00:00+00:00", **kw)


# P31-1: exclusive create, no hard links, no partial files
def test_write_works_where_hard_links_are_unsupported(tmp_path, monkeypatch):
    def no_link(*a, **k):
        raise OSError(errno.EOPNOTSUPP, "Operation not supported")
    monkeypatch.setattr(os, "link", no_link)
    out = pv.write(manifest(), tmp_path)
    assert json.loads(out.read_text())["purpose"] == "t" and sorted(os.listdir(tmp_path)) == ["run_manifest.json"]


def test_an_existing_manifest_is_left_byte_identical(tmp_path):
    (tmp_path / "run_manifest.json").write_bytes(b"original")
    with pytest.raises(FileExistsError):
        pv.write(manifest(), tmp_path)
    assert (tmp_path / "run_manifest.json").read_bytes() == b"original"


def test_a_failed_fsync_leaves_no_file(tmp_path, monkeypatch):
    def boom(fd):
        raise OSError("disk full")
    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        pv.write(manifest(), tmp_path)
    assert os.listdir(tmp_path) == []


def test_racing_writers_exactly_one_wins(tmp_path):
    start, results = threading.Barrier(8), []

    def run():
        start.wait()
        try:
            pv.write(manifest(), tmp_path)
            results.append("ok")
        except FileExistsError:
            results.append("exists")
    ts = [threading.Thread(target=run) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count("ok") == 1 and results.count("exists") == 7


# P31-2 and P31-4: dirty trees are told apart, renames and odd names recorded exactly
def test_two_different_dirty_edits_give_different_diff_hashes(repo):
    (repo / "x.py").write_text("2\n")
    a = pv.git_state(repo)
    (repo / "x.py").write_text("3\n")
    b = pv.git_state(repo)
    assert a["dirty"] and b["dirty"] and a["diff_sha256"] != b["diff_sha256"]


def test_a_clean_tree_has_no_diff_hash(repo):
    g = pv.git_state(repo)
    assert g["dirty"] is False and g["diff_sha256"] is None and g["diff_reason"] == "clean" and g["untracked"] == []


def test_require_clean_refuses_a_dirty_tree(repo):
    (repo / "x.py").write_text("2\n")
    with pytest.raises(ValueError):
        pv.run_manifest([], {}, purpose="t", repo=repo, require_clean=True, versions=lambda: {})
    with pytest.raises(ValueError):
        pv.run_manifest([], {}, purpose="t", repo=repo / "nowhere", require_clean=True, versions=lambda: {})


def test_untracked_files_are_hashed(repo):
    (repo / "new.txt").write_bytes(b"abc")
    g = pv.git_state(repo)
    assert g["untracked"] == [{"path": "new.txt", "sha256":
                               "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}]


def test_renames_spaces_and_non_ascii_names_are_exact(repo):
    _git(repo, "mv", "x.py", "renamed file.py")
    (repo / "café ü.txt").write_text("1\n")
    g = pv.git_state(repo)
    assert {"from": "x.py", "to": "renamed file.py"} in g["dirty_paths"]
    assert "café ü.txt" in g["dirty_paths"]
    assert [u["path"] for u in g["untracked"]] == ["café ü.txt"]


# P31-3: canonical JSON refuses what it cannot represent faithfully
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nan_and_infinity_are_refused(bad):
    with pytest.raises(ValueError):
        pv.canonical({"x": bad})


@pytest.mark.parametrize("bad", [date(2026, 1, 1), Path("/tmp"), {1, 2}, (1, 2)])
def test_non_json_types_are_refused_with_the_key_path(bad):
    with pytest.raises(TypeError, match=r"\$\.a\.b"):
        pv.canonical({"a": {"b": bad}})


def test_int_and_float_hash_differently_by_design():
    assert pv.canonical({"x": 1}) != pv.canonical({"x": 1.0})


# P31-5: matching by relative path, refusing duplicate names, saying what a match means
def test_duplicate_basenames_are_refused(tmp_path):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "prices.csv").write_text(d)
    m = pv.run_manifest([tmp_path / "a" / "prices.csv", tmp_path / "b" / "prices.csv"], {}, purpose="t",
                        git=lambda r: {}, versions=lambda: {})
    with pytest.raises(ValueError):
        pv.compare_with_data_manifest(m, {"files": {"prices.csv": {"sha256": "0"}}})


def test_the_comparison_says_what_a_match_means(capsys):
    pv.main(["--check-data-manifest", str(FIXTURES / "data_manifest.json")])
    out = json.loads(capsys.readouterr().out)
    assert out["comparison"]["meaning"] == "byte match only; not correctness, PIT safety or licence"
    assert out["comparison"]["matched"] == ["prices_small.csv"]


# P31-6: environment detail and UTC times
def test_a_metadata_error_is_recorded_not_raised():
    def version(name):
        raise RuntimeError("corrupt metadata")
    assert pv.package_versions(("numpy",), version=version, modules={}) == \
        {"numpy": {"version": None, "missing_reason": "metadata_error:RuntimeError"}}


def test_an_imported_module_records_its_version_and_file():
    fake = type(sys)("fakepkg")
    fake.__version__, fake.__file__ = "9.9", "/somewhere/fakepkg/__init__.py"
    v = pv.package_versions(("fakepkg",), version=lambda n: "1.0", modules={"fakepkg": fake})
    assert v["fakepkg"] == {"version": "1.0", "module_version": "9.9", "module_file": "/somewhere/fakepkg/__init__.py"}


@pytest.mark.parametrize("field", ["started_at", "finished_at"])
def test_non_utc_times_are_refused(field):
    kw = {"started_at": "2026-10-23T00:00:00+00:00", field: "2026-10-23T12:00:00+01:00"}
    with pytest.raises(ValueError):
        pv.run_manifest([], {}, purpose="t", git=lambda r: {}, versions=lambda: {}, **kw)


def test_the_manifest_records_the_interpreter():
    assert manifest()["python"]["executable"] == sys.executable
