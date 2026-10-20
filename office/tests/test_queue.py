import multiprocessing as mp

from office import events as ev
from office import queue as q
from office.store import GitStore

from conftest import BRANCH


def test_create_is_idempotent_and_dependencies_must_exist(make_store, clock):
    s = make_store()
    a = q.create(s, "audit", {"n": 1}, clock=clock)
    assert a["status"] == "created"
    assert q.create(make_store(), "audit", {"n": 1}, clock=clock) == {"task": a["task"], "status": "exists"}
    bad = q.create(s, "audit", {"n": 2}, deps=("t-nope",), clock=clock)
    assert bad["status"] == "refused" and "unknown dependencies" in bad["reason"]
    kinds = [e["kind"] for e in ev.parse(s.sync())]
    assert kinds == ["task_created", "task_refused"]  # the refusal is recorded, not silent


def test_growth_limits_refuse_runaway_creation(make_store, clock):
    s, lim = make_store(), q.Limits(max_children=2, max_depth=2, max_open=50, max_created_per_day=50)
    root = q.create(s, "root", {}, limits=lim, clock=clock)["task"]
    assert [q.create(s, "c", {"i": i}, parent=root, limits=lim, clock=clock)["status"] for i in range(3)] == \
        ["created", "created", "refused"]
    chain = root
    out = []
    for d in range(4):
        r = q.create(s, "deep", {"d": d}, parent=chain, limits=q.Limits(max_children=9, max_depth=2), clock=clock)
        out.append(r["status"])
        chain = r["task"]
    assert out == ["created", "created", "refused", "refused"]
    small = q.Limits(max_open=3)
    assert q.create(s, "x", {"k": 1}, limits=small, clock=clock)["status"] == "refused"


def test_priority_dependencies_and_idle(make_store, clock):
    s = make_store()
    low = q.create(s, "a", {"p": "low"}, priority=10, clock=clock)["task"]
    high = q.create(s, "a", {"p": "high"}, priority=90, clock=clock)["task"]
    after = q.create(s, "a", {"p": "after"}, priority=99, deps=(high,), clock=clock)["task"]
    l1 = q.claim(s, "w", clock=clock)
    assert l1.task == high  # `after` waits for its dependency despite higher priority
    assert q.complete(s, l1, {"ok": 1}, clock=clock)
    assert q.claim(s, "w", clock=clock).task == after
    assert q.claim(s, "w", clock=clock).task == low
    assert q.claim(s, "w", clock=clock) is None  # idle: nothing eligible, returns at once


def test_killed_worker_lease_expires_and_its_late_result_is_refused(make_store, clock):
    a, b = make_store("A"), make_store("B")
    t = q.create(a, "job", {}, lease_s=60, clock=clock)["task"]
    la = q.claim(a, "A", clock=clock)
    assert q.claim(b, "B", clock=clock) is None  # lease live
    clock.t += 61  # A was killed and never came back in time
    lb = q.claim(b, "B", clock=clock)
    assert lb.task == t and lb.fence != la.fence and lb.attempt == 2
    claim_ev = [e for e in ev.parse(b.sync()) if e["kind"] == "task_claimed"][-1]
    assert claim_ev["recovered_fence"] == la.fence
    assert q.complete(a, la, {"stale": True}, clock=clock) is False  # A resumes late: refused
    assert q.fail(a, la, "late", clock=clock) is False
    assert q.complete(b, lb, {"fresh": True}, clock=clock) is True
    st = q.tasks(ev.parse(b.sync()), clock())[t]
    assert st["status"] == "done" and st["output"] == {"fresh": True}


def test_completion_after_own_lease_expired_is_refused(make_store, clock):
    s = make_store()
    q.create(s, "job", {}, lease_s=10, clock=clock)
    lease = q.claim(s, "w", clock=clock)
    clock.t += 11
    assert q.complete(s, lease, {}, clock=clock) is False


def test_retry_with_backoff_then_quarantine_and_dependents_blocked(make_store, clock):
    s = make_store()
    t = q.create(s, "flaky", {}, max_attempts=3, lease_s=60, clock=clock)["task"]
    dep = q.create(s, "next", {}, deps=(t,), clock=clock)["task"]
    waits = []
    for attempt in (1, 2, 3):
        lease = q.claim(s, "w", clock=clock)
        assert lease.task == t and lease.attempt == attempt
        assert q.fail(s, lease, f"boom {attempt}", clock=clock)
        assert q.claim(s, "w", clock=clock) is None  # backing off
        waits.append(q.backoff(attempt))
        clock.t += q.backoff(attempt) + 1
    assert waits == [300, 1200, 3600]
    assert q.claim(s, "w", clock=clock) is None  # third failure: quarantined instead of a fourth attempt
    st = q.tasks(ev.parse(s.sync()), clock())
    assert st[t]["status"] == "quarantined" and "boom 3" in st[t]["reason"]
    assert st[dep]["status"] == "blocked"


def _drain(remote, workdir, actor, out):
    s = GitStore(workdir, BRANCH, remote, actor=actor)
    done = []
    while (lease := q.claim(s, actor)) is not None:
        if q.complete(s, lease, {"by": actor}):
            done.append(lease.task)
    out.put((actor, done, s.stats["rejected"]))


def test_concurrent_workers_claim_each_task_exactly_once(make_store, remote, tmp_path):
    s = make_store()
    ids = {q.create(s, "job", {"i": i})["task"] for i in range(24)}
    out, procs = mp.Queue(), []
    for k in range(6):
        p = mp.Process(target=_drain, args=(remote, tmp_path / f"d{k}", f"d{k}", out))
        p.start()
        procs.append(p)
    for p in procs:
        p.join(300)
        assert p.exitcode == 0
    res = [out.get() for _ in procs]
    done = [t for _, d, _ in res for t in d]
    assert sorted(done) == sorted(ids)  # every task once, none twice
    events = ev.parse(s.sync())
    claims = [e["task"] for e in events if e["kind"] == "task_claimed"]
    assert len(claims) == len(set(claims)) == 24
    assert sum(r for _, _, r in res) > 0
    assert s.audit_history() == []
