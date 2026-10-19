import json
import multiprocessing as mp
import subprocess

import pytest

from office import events as ev
from office.store import GitStore, StoreUnavailable

from conftest import BRANCH


def test_chain_validates_and_detects_tampering():
    text = ev.extend("", [{"kind": "a"}, {"kind": "b", "x": 1}], "t", now="2026-10-19T00:00:00+00:00")
    assert ev.validate(text) == []
    lines = text.splitlines()
    tampered = "\n".join([lines[0].replace('"kind":"a"', '"kind":"z"'), lines[1]]) + "\n"
    assert "line 1: chain broken" in ev.validate(tampered)
    with pytest.raises(ev.CorruptLog):
        ev.extend(tampered, [{"kind": "c"}], "t")
    dropped = lines[1] + "\n"
    assert any("seq" in p for p in ev.validate(dropped))


def test_append_is_all_or_nothing_and_rejects_a_stale_base(make_store):
    a, b = make_store(), make_store()
    base_a, base_b = a.sync(), b.sync()
    assert a.append(base_a, [{"kind": "x"}], "x")
    assert b.append(base_b, [{"kind": "y"}], "y") is False  # lost the race: nothing of it is visible
    assert [e["kind"] for e in ev.parse(b.sync())] == ["x"]
    assert b.stats["rejected"] == 1


def _writer(remote, workdir, actor, n, q):
    s = GitStore(workdir, BRANCH, remote, actor=actor)
    for i in range(n):
        s.transact(lambda e: [{"kind": "w", "who": actor, "i": i}])
    q.put(s.stats)


def test_concurrent_writers_lose_nothing(remote, tmp_path):
    q, procs = mp.Queue(), []
    for k in range(6):
        p = mp.Process(target=_writer, args=(remote, tmp_path / f"p{k}", f"p{k}", 5, q))
        p.start()
        procs.append(p)
    for p in procs:
        p.join(120)
        assert p.exitcode == 0
    stats = [q.get() for _ in procs]
    text = GitStore(tmp_path / "check", BRANCH, remote).sync()
    got = [(e["who"], e["i"]) for e in ev.parse(text)]
    assert ev.validate(text) == [] and len(got) == 30 and len(set(got)) == 30
    assert sum(s["rejected"] for s in stats) > 0  # the race really happened


def test_push_with_unknown_outcome_is_resolved_by_looking_at_the_remote(make_store, monkeypatch):
    s = make_store()
    real = s._git

    def landed_but_error(*args, check=True):
        r = real(*args, check=check)
        if args[0] == "push":
            return subprocess.CompletedProcess(r.args, 128, "", "fatal: the remote end hung up unexpectedly")
        return r
    monkeypatch.setattr(s, "_git", landed_but_error)
    assert s.append(s.sync(), [{"kind": "x"}], "x") is True  # it did land
    assert s.stats["ambiguous_resolved"] == 1

    def lost_with_error(*args, check=True):
        if args[0] == "push":
            return subprocess.CompletedProcess(args, 128, "", "fatal: unable to access: Connection reset")
        return real(*args, check=check)
    monkeypatch.setattr(s, "_git", lost_with_error)
    assert s.append(s.sync(), [{"kind": "y"}], "y") is False  # it did not land
    monkeypatch.setattr(s, "_git", real)
    assert [e["kind"] for e in ev.parse(s.sync())] == ["x"]


def test_unreachable_remote_raises_instead_of_guessing(make_store, monkeypatch):
    s = make_store()
    base = s.sync()
    real = s._git

    def down(*args, check=True):
        if args[0] in ("push", "fetch"):
            return subprocess.CompletedProcess(args, 128, "", "fatal: unable to access: Could not resolve host")
        return real(*args, check=check)
    monkeypatch.setattr(s, "_git", down)
    monkeypatch.setattr("time.sleep", lambda x: None)
    with pytest.raises(StoreUnavailable):
        s.append(base, [{"kind": "x"}], "x")


def test_an_edited_remote_log_stops_every_writer_and_the_audit_finds_it(make_store, remote, tmp_path):
    s = make_store()
    s.transact(lambda e: [{"kind": "a"}])
    assert s.audit_history() == []
    w = tmp_path / "vandal"
    subprocess.run(["git", "clone", "-q", "-b", BRANCH, remote, str(w)], check=True)
    p = w / "events.jsonl"
    p.write_text(p.read_text().replace('"kind":"a"', '"kind":"b"'))
    for c in (["config", "user.email", "v@v"], ["config", "user.name", "v"], ["commit", "-qam", "edit"],
              ["push", "-q", "origin", BRANCH]):
        subprocess.run(["git", "-C", str(w), *c], check=True)
    # the edited line is the newest one, so the chain alone still validates; the prefix rule and the audit catch it
    assert ev.validate(p.read_text()) == []
    with pytest.raises(ev.CorruptLog, match="rewritten"):
        s.transact(lambda e: [{"kind": "c"}])
    fresh = GitStore(tmp_path / "auditor", BRANCH, remote)
    assert any("changed earlier log lines" in x for x in fresh.audit_history())
    assert json.loads(p.read_text().splitlines()[0])["kind"] == "b"
