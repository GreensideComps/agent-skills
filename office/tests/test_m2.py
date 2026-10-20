"""M2: director, worker run, health alerts, handlers and the gate. Offline: a local bare remote, faked subprocesses."""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from office import director, gate, handlers, health, worker
from office import queue as q
from office.events import GENESIS, canonical, line_hash, parse
from office.handlers import Context
from office.store import GitStore

from conftest import BRANCH


@pytest.fixture
def store(remote, tmp_path, clock):
    n = [0]

    def make(actor="w"):
        n[0] += 1
        return GitStore(tmp_path / f"s{n[0]}", BRANCH, remote, actor=actor, clock=clock)
    return make


def ok_handlers(calls):
    def h(name):
        def f(ctx, inputs):
            calls.append((name, inputs["day"]))
            return {"ok": name}
        return f
    return {t: h(t) for t in ("health", "test_suites", "demo_snapshot", "digest")}


def ctx_for(s, clock, **kw):
    return Context(store=s, repo_url="unused", now=clock, env=kw.pop("env", {}), **kw)


def kinds(s):
    return [e["kind"] for e in parse(s.sync())]


def test_daily_plan_is_idempotent(store, clock):
    s = store()
    assert [r["status"] for r in director.plan(s, clock())] == ["created"] * 4
    assert [r["status"] for r in director.plan(store(), clock())] == ["exists"] * 4
    clock.t += 86400
    assert [r["status"] for r in director.plan(s, clock())] == ["created"] * 4  # a new UTC day


def test_a_run_records_its_heartbeat_does_the_day_and_reports_healthy(store, clock):
    s, calls = store(), []
    stats = worker.run(s, ctx_for(s, clock), worker="w", code="abc", clock=clock, handlers=ok_handlers(calls))
    assert stats["completed"] == 4 and stats["stopped"] == "idle" and stats["planned"] == 4
    assert [c[0] for c in calls] == ["health", "test_suites", "demo_snapshot", "digest"]  # priority order
    k = kinds(s)
    assert k[0] == "worker_started" and k[-1] == "worker_finished"
    rep = health.report(parse(s.sync()), clock(), 3600)
    assert rep["alerts"] == [] and rep["tasks"] == {"done": 4} and rep["runs"] == 1
    again = worker.run(s, ctx_for(s, clock), worker="w", code="abc", clock=clock, handlers=ok_handlers(calls))
    assert again["completed"] == 0 and again["planned"] == 0 and len(calls) == 4  # nothing is done twice


def test_a_run_that_dies_mid_task_is_recovered_by_the_next_run(store, clock):
    s, calls = store(), []

    def die(lease):
        raise SystemExit("killed")  # the session ends with the lease held and no worker_finished
    with pytest.raises(SystemExit):
        worker.run(s, ctx_for(s, clock), worker="a", code="x", clock=clock, handlers=ok_handlers(calls),
                   after_claim=die)
    assert calls == []
    clock.t += 3600  # next heartbeat: the health lease (600 s) has expired
    stats = worker.run(store(), ctx_for(s, clock), worker="b", code="x", clock=clock, handlers=ok_handlers(calls))
    assert stats["completed"] == 4
    ev = parse(s.sync())
    rec = [e for e in ev if e["kind"] == "task_claimed" and e["recovered_fence"] is not None]
    assert len(rec) == 1 and rec[0]["attempt"] == 2
    assert sum(e["kind"] == "task_completed" for e in ev) == 4  # exactly once each
    rep = health.report(ev, clock(), 3600)
    assert [a["code"] for a in rep["alerts"]] == ["run_did_not_finish"] and rep["recovered_claims"] == 1


def test_a_failing_handler_is_retried_with_backoff_then_quarantined_and_alerted(store, clock):
    s, calls = store(), []
    hs = ok_handlers(calls)

    def boom(ctx, inputs):
        raise RuntimeError("broker read failed")
    hs["demo_snapshot"] = boom
    st = worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock, handlers=hs)
    assert st["failed"] == 1 and st["completed"] == 3  # the digest still runs and reports it
    for wait in (300, 1200):
        clock.t += wait - 1
        assert worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock, handlers=hs)["failed"] == 0
        clock.t += 1
        assert worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock, handlers=hs)["failed"] == 1
    clock.t += 4000
    worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock, handlers=hs)
    ev = parse(s.sync())
    assert sum(e["kind"] == "task_quarantined" for e in ev) == 1
    rep = health.report(ev, clock(), 3600)
    assert any(a["code"] == "task_quarantined" and a["level"] == "critical" for a in rep["alerts"])
    md = handlers.render_digest(ev, clock(), director.day(clock()))
    assert "quarantined" in md and "broker read failed" in md


def test_pause_stops_work_until_an_owner_resume_and_resume_needs_a_message_id(store, clock):
    s, calls = store(), []
    worker.pause(s, "owner asked")
    st = worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock, handlers=ok_handlers(calls))
    assert st["stopped"] == "stop: owner asked" and calls == [] and st["planned"] == 0
    assert "worker_finished" in kinds(s)  # a paused run still records its heartbeat
    assert any(a["code"] == "paused" for a in health.report(parse(s.sync()), clock(), 3600)["alerts"])
    with pytest.raises(ValueError):
        worker.resume(s, "please go")
    worker.resume(s, "cmsg_01TEST")
    assert worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock,
                      handlers=ok_handlers(calls))["completed"] == 4


def test_stop_file_env_stop_and_task_budget(store, clock, tmp_path):
    s, calls = store(), []
    stop = tmp_path / "STOP"
    stop.touch()
    assert worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock, handlers=ok_handlers(calls),
                      stop_file=stop)["stopped"].startswith("stop: stop file")
    assert worker.run(s, ctx_for(s, clock, env={"OFFICE_STOP": "1"}), worker="w", code="x", clock=clock,
                      handlers=ok_handlers(calls))["stopped"] == "stop: OFFICE_STOP=1"
    assert calls == []
    st = worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock, handlers=ok_handlers(calls), max_tasks=1)
    assert st == {**st, "completed": 1, "stopped": "task budget"}


def test_an_overrunning_task_loses_its_lease_and_its_late_result_is_not_recorded(store, clock):
    s, other = store(), store("other")
    hs = ok_handlers([])

    def slow(ctx, inputs):
        clock.t += 601  # past the 600 s health lease; another worker takes the task meanwhile
        lb = q.claim(other, "other", clock=clock, types={"health"})
        assert lb is not None and q.complete(other, lb, {"by": "other"}, clock=clock)
        return {"by": "slow"}
    hs["health"] = slow
    st = worker.run(s, ctx_for(s, clock), worker="w", code="x", clock=clock, handlers=hs, max_tasks=1)
    assert st["lost"] == 1 and st["completed"] == 0
    out = [e["output"] for e in parse(s.sync()) if e["kind"] == "task_completed"]
    assert out == [{"by": "other"}]


class FakeRun:
    def __init__(self, results):
        self.results, self.calls = results, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[:2] == ["git", "clone"]:
            dest = cmd[-1]
            for sub in ("trading", "equity", "research", "office"):
                (__import__("pathlib").Path(dest) / sub).mkdir(parents=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["git", "-C"]:
            return SimpleNamespace(returncode=0, stdout="f" * 40 + "\n", stderr="")
        return self.results(cmd, kw)


SECRET_ENV = {"T212_ENV": "demo", "T212_API_KEY": "k", "T212_API_SECRET": "s", "RESEND_API_KEY": "r",
              "REPORT_EMAIL_TO": "x", "GH_TOKEN": "g", "PATH": "/usr/bin"}


def test_test_suites_strip_credentials_and_alert_on_failure(store, clock):
    def res(cmd, kw):
        name = kw["cwd"].rsplit("/", 1)[-1]
        assert not any(k.startswith(handlers.SECRET_PREFIXES) for k in kw["env"])
        assert set(kw["env"]) <= set(handlers.BASE_ENV) | {"HOME", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy",
                                                            "http_proxy", "NO_PROXY", "no_proxy", "GIT_TERMINAL_PROMPT"}
        assert kw["env"]["NO_PROXY"] == "" and kw["env"]["HOME"] != "/root"
        assert kw["env"]["HTTPS_PROXY"] == "http://127.0.0.1:9" and kw["env"]["PATH"] == "/usr/bin"
        if name == "equity":
            return SimpleNamespace(returncode=1, stdout="....\n2 failed, 116 passed in 3.1s\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="....\n139 passed in 9.0s\n", stderr="")
    fr = FakeRun(res)
    out = handlers.h_test_suites(ctx_for(store(), clock, env=SECRET_ENV, run=fr), {"day": "d"})
    assert out["suites"]["equity"] == {"exit": 1, "failed": 2, "passed": 116, "summary": "2 failed, 116 passed in 3.1s"}
    assert out["suites"]["office"]["passed"] == 139
    assert out["alert"]["code"] == "tests_failing" and "equity" in out["alert"]["text"]
    office_call = [c for c in fr.calls if c[1].get("cwd", "").endswith("office")][0]
    assert office_call[0][-1] == "tests"  # never the GitHub queue script


def test_demo_snapshot_skips_without_demo_credentials_and_reads_only_totals(store, clock, tmp_path):
    s = store()
    assert handlers.h_demo_snapshot(ctx_for(s, clock, env={"T212_ENV": "live", "T212_API_KEY": "k"}),
                                    {})["status"] == "skipped"
    seen = {}

    def res(cmd, kw):
        from pathlib import Path
        seen["kill"] = (Path(kw["cwd"]) / "KILL").exists()
        seen["env"] = set(kw["env"])
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
            "summary": {"totalValue": 1229.58, "cash": {"availableToTrade": 0}, "investments":
                        {"unrealizedProfitLoss": -68.4}}, "positions": [{"ticker": "A"}] * 22, "pending_orders": []}))
    out = handlers.h_demo_snapshot(ctx_for(s, clock, env=SECRET_ENV, run=FakeRun(res)), {})
    assert out == {"commit": "f" * 40, "total_value": 1229.58, "cash": 0, "positions": 22, "pending_orders": 0,
                   "unrealised_pl": -68.4}
    assert seen["kill"] and not seen["env"] & {"RESEND_API_KEY", "REPORT_EMAIL_TO", "GH_TOKEN"}
    assert seen["env"] <= set(handlers.BASE_ENV + handlers.NET_ENV + handlers.DEMO_ENV) | {"HOME"}
    assert "ReadOnlyClient" in seen["cmd"][-1] and "order" not in seen["cmd"][-1].replace("pending_orders", "")


def test_digest_is_written_from_the_log_and_not_emailed_by_default(store, clock, tmp_path):
    s, calls = store(), []
    hs = ok_handlers(calls)
    hs["digest"] = handlers.h_digest
    worker.run(s, ctx_for(s, clock, out_dir=tmp_path / "digests"), worker="w", code="x", clock=clock, handlers=hs)
    d = director.day(clock())
    out = [e["output"] for e in parse(s.sync()) if e["kind"] == "task_completed" and e["output"].get("chars")][0]
    assert out["emailed"] is None and out["written"].endswith(f"digest_{d}.md")
    md = (tmp_path / "digests" / f"digest_{d}.md").read_text()
    assert md.startswith(f"# Edge office digest {d}") and "R0 only" in md


def test_health_raises_a_critical_alert_when_a_commit_edited_earlier_log_lines(store, clock, remote, tmp_path):
    s = store()
    worker.record(s, "office_paused", reason="first")
    worker.record(s, "office_resumed", owner_message="cmsg_1")
    assert handlers.h_health(ctx_for(s, clock), {})["history_audit"] == "clean"
    w = tmp_path / "evil"  # an ordinary (non-force) commit that rewrites the log with a valid new chain
    subprocess.run(["git", "clone", "-q", "-b", BRANCH, remote, str(w)], check=True)
    events = parse((w / "events.jsonl").read_text())
    lines, prev = [], GENESIS
    for e in events:
        e = {**e, "prev": prev, "reason": "edited"} if e["kind"] == "office_paused" else {**e, "prev": prev}
        lines.append(canonical(e))
        prev = line_hash(lines[-1])
    (w / "events.jsonl").write_text("\n".join(lines) + "\n")
    for cmd in (["-c", "user.email=e@x", "-c", "user.name=e", "commit", "-qam", "edit"], ["push", "-q", "origin", BRANCH]):
        subprocess.run(["git", "-C", str(w), *cmd], check=True)
    fresh = store()  # a worker that never saw the old text: the chain validates, only the history audit catches it
    out = handlers.h_health(ctx_for(fresh, clock), {})
    assert out["alert"]["code"] == "log_history" and "changed earlier log lines" in out["alert"]["text"]
    with pytest.raises(Exception, match="history was rewritten"):
        s.sync()  # the worker that saw the original refuses to go on


# Gate: synthetic logs (pure function of events), so 14 days can be checked without 14 days of commits.

def synth(days=15, hb=3600.0, skip=(), extra=()):
    from datetime import datetime, timezone
    t0, out = 1_800_000_000.0, []

    def add(t, **e):
        e.update(seq=len(out), ts=datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds"))
        out.append(e)
    add(t0, kind="gate_started", heartbeat_s=hb, owner_message="cmsg_X", criteria="G1")
    n = int(days * 86400 / hb)
    for i in range(1, n + 1):
        t = t0 + i * hb - 60
        if i in skip:
            continue
        add(t, kind="worker_started", run=f"r{i}", actor="w")
        d = director.day(t)
        for typ in ("health", "digest"):
            tid = q.task_id(typ, {"day": d})
            if not any(e.get("task") == tid for e in out):
                add(t, kind="task_created", task=tid, type=typ, inputs={"day": d}, priority=50, deps=[], parent=None,
                    depth=0, max_attempts=3, lease_s=600.0, day=d)
                c = len(out)
                add(t, kind="task_claimed", task=tid, worker="w", lease_until=t + 600, attempt=1,
                    recovered_fence=None)
                add(t, kind="task_completed", task=tid, fence=c, output={})
        add(t + 30, kind="worker_finished", run=f"r{i}", stats={})
    for e in extra:
        add(t0 + 3 * 86400, **e)
    return out, t0 + days * 86400


def drill(out):
    """Mark one claim as a recovery, as a real crash drill would."""
    for e in out:
        if e["kind"] == "task_claimed":
            e["recovered_fence"] = 1
            return out


def test_gate_passes_a_clean_fifteen_days_and_reports_each_check():
    ev, now = synth()
    r = gate.evaluate(drill(ev), now, [])
    assert r["verdict"] == "pass", [c for c in r["checks"] if not c["pass"]]
    assert {c["check"] for c in r["checks"]} == {"elapsed", "history", "heartbeat", "runs_finish", "no_duplicates",
                                                  "no_orphans", "daily_outputs", "core_never_quarantined", "r0_only",
                                                  "crash_recovered"}


def test_gate_is_running_before_fourteen_days_and_fails_on_each_breach():
    ev, now = synth(days=5)
    assert gate.evaluate(drill(ev), now, [])["verdict"] == "running"
    gap, now = synth(skip=(100, 101))  # three hours without a run
    r = gate.evaluate(drill(gap), now, [])
    assert r["verdict"] == "fail" and not [c for c in r["checks"] if c["check"] == "heartbeat"][0]["pass"]
    ev, now = synth(extra=[{"kind": "order_submitted"}])
    assert gate.evaluate(drill(ev), now, [])["verdict"] == "fail"
    ev, now = synth()
    dup = dict([e for e in ev if e["kind"] == "task_completed"][5])
    ev, now = synth(extra=[{k: v for k, v in dup.items() if k not in ("seq", "ts")}])
    assert not [c for c in gate.evaluate(drill(ev), now, [])["checks"] if c["check"] == "no_duplicates"][0]["pass"]
    ev, now = synth()
    assert gate.evaluate(ev, now, [])["verdict"] == "fail"  # no crash drill recovered
    assert gate.evaluate(drill(ev), now, ["commit abc changed earlier log lines"])["verdict"] == "fail"
    assert gate.evaluate([], now, [])["verdict"] == "not started"


def test_failure_text_is_redacted_before_it_reaches_the_log(store, clock):
    s = store()
    env = {"T212_API_KEY": "sekrit-demo-key-123", "PATH": "/usr/bin"}
    hs = ok_handlers([])

    def leak(ctx, inputs):
        raise RuntimeError("fatal: https://user:tok3n@github.com/x.git said no; key sekrit-demo-key-123")
    hs["health"] = leak
    worker.run(s, ctx_for(s, clock, env=env), worker="w", code="x", clock=clock, handlers=hs, max_tasks=1)
    text = s.sync()
    assert "tok3n" not in text and "sekrit-demo-key-123" not in text and "***@github.com" in text


def test_history_audit_detects_a_replaced_root_commit(remote, tmp_path, clock):
    first = GitStore(tmp_path / "a", BRANCH, remote, clock=clock)
    first.sync()
    root = first._git("rev-list", "--max-parents=0", f"origin/{BRANCH}").stdout.strip()
    assert GitStore(tmp_path / "b", BRANCH, remote, clock=clock, root=root).audit_history() == []
    other = GitStore(tmp_path / "c", BRANCH, remote, clock=clock, root="0" * 40)
    assert "branch history was replaced" in other.audit_history()[0]


def test_github_queue_script_refuses_any_branch_but_a_throwaway_one():
    import sys as _s
    r = subprocess.run([_s.executable, "github_queue_test.py", "--branch", "claude/office-state"],
                       cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]), capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "HTTPS_PROXY": "http://127.0.0.1:9"}, timeout=60)
    assert r.returncode != 0 and "office-queue-test-" in r.stderr
