"""Validate the git-backed queue against the real GitHub remote, on a throwaway branch that is always deleted.

    python3 office/github_queue_test.py [--branch NAME] [--workers 6] [--report PATH]

Writes only to the throwaway branch (created fresh; refuses if it exists). The branch is deleted in a `finally`
block and on SIGTERM/SIGINT, and the deletion is verified with ls-remote; the report says whether cleanup succeeded.
Touches no other branch, no broker and no scheduled task.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from office import events as ev  # noqa: E402
from office import queue as q  # noqa: E402
from office.store import GitStore, StoreUnavailable  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def remote_url() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True,
                          check=True).stdout.strip()


class Offset:
    """Wall clock plus a manual offset, so backoff and lease expiry can be tested without waiting an hour."""

    def __init__(self):
        self.off = 0.0

    def __call__(self):
        return time.time() + self.off


def store(work: Path, name: str, branch: str, url: str) -> GitStore:
    return GitStore(work / name, branch, url, actor=name)


# ---------- worker processes ----------
def w_create(work, branch, url, name, out):
    s = store(work, name, branch, url)
    res = [q.create(s, "job", {"i": i})["status"] for i in range(20)]
    out.put((name, res, s.stats))


def w_drain(work, branch, url, name, out):
    s = store(work, name, branch, url)
    done = []
    while (lease := q.claim(s, name, types={"job"})) is not None:
        if q.complete(s, lease, {"by": name}):
            done.append(lease.task)
    out.put((name, done, s.stats))


def w_claim_then_die(work, branch, url, name):
    s = store(work, name, branch, url)
    q.claim(s, name, types={"crash"})
    os.kill(os.getpid(), signal.SIGKILL)  # killed mid-task: no complete, no fail


def w_append_forever(work, branch, url, name):
    s = store(work, name, branch, url)
    i = 0
    while True:
        s.transact(lambda e: [{"kind": "noise", "i": i}])
        i += 1


def run(branch: str, workers: int, work: Path, url: str) -> dict:
    rep: dict = {"branch": branch, "workers": workers, "results": {}}
    R = rep["results"]
    GitStore.create_branch(work / "seed", url, branch)
    main = store(work, "main", branch, url)
    ctx = mp.get_context("fork")

    def fan(target, n, *extra):
        out, ps = ctx.Queue(), []
        for k in range(n):
            p = ctx.Process(target=target, args=(work, branch, url, f"{target.__name__}{k}", out, *extra))
            p.start()
            ps.append(p)
        res = [out.get(timeout=900) for _ in ps]
        for p in ps:
            p.join(60)
        return res, [p.exitcode for p in ps]

    # S1 concurrent idempotent creation
    t0 = time.time()
    res, codes = fan(w_create, workers)
    evs = ev.parse(main.sync())
    created = [e for e in evs if e["kind"] == "task_created"]
    R["S1_concurrent_create"] = {"pass": len(created) == 20 and len({e["task"] for e in created}) == 20
                                 and all(c == 0 for c in codes),
                                 "created_events": len(created), "push_rejections": sum(r[2]["rejected"] for r in res),
                                 "seconds": round(time.time() - t0, 1)}
    # S2 concurrent drain: every task claimed and completed exactly once
    t0 = time.time()
    res, codes = fan(w_drain, workers)
    evs = ev.parse(main.sync())
    claims = [e["task"] for e in evs if e["kind"] == "task_claimed"]
    done = [t for r in res for t in r[1]]
    R["S2_concurrent_claim"] = {"pass": len(claims) == len(set(claims)) == 20 and sorted(done) == sorted(set(done))
                                and len(done) == 20 and all(c == 0 for c in codes),
                                "claims": len(claims), "double_claims": len(claims) - len(set(claims)),
                                "completed": len(done), "push_rejections": sum(r[2]["rejected"] for r in res),
                                "ambiguous_pushes_resolved": sum(r[2]["ambiguous_resolved"] for r in res),
                                "seconds": round(time.time() - t0, 1)}
    # S3 worker crash and lease expiry; S4 the dead worker's result is refused
    t = q.create(main, "crash", {}, lease_s=20)["task"]
    p = ctx.Process(target=w_claim_then_die, args=(work, branch, url, "victim"))
    p.start()
    p.join(120)
    blocked = q.claim(main, "rescuer", types={"crash"})
    time.sleep(21)
    lease = q.claim(main, "rescuer", types={"crash"})
    victim = [e for e in ev.parse(main.sync()) if e["kind"] == "task_claimed" and e["worker"] == "victim"][0]
    stale = q.Lease(t, victim["seq"], victim["lease_until"], 1)
    stale_ok = q.complete(store(work, "victim2", branch, url), stale, {"stale": True})
    fresh_ok = q.complete(main, lease, {"rescued": True}) if lease else False
    R["S3_crash_and_lease_expiry"] = {"pass": p.exitcode == -signal.SIGKILL and blocked is None and lease is not None
                                      and lease.task == t and lease.attempt == 2,
                                      "victim_exit": p.exitcode, "claim_during_live_lease": blocked is not None}
    R["S4_stale_result_refused"] = {"pass": stale_ok is False and fresh_ok is True}
    # S5 retries with backoff, then quarantine (clock offset stands in for waiting)
    clk = Offset()
    f = q.create(main, "flaky", {}, max_attempts=3, lease_s=60, clock=clk)["task"]
    attempts, between = [], []
    for _ in range(3):
        lease = q.claim(main, "w", clock=clk, types={"flaky"})
        attempts.append(lease.attempt if lease else None)
        q.fail(main, lease, "synthetic failure", clock=clk)
        between.append(q.claim(main, "w", clock=clk, types={"flaky"}) is None)
        clk.off += q.backoff(lease.attempt) + 1
    final = q.claim(main, "w", clock=clk, types={"flaky"})
    st = q.tasks(ev.parse(main.sync()), clk())[f]
    R["S5_retry_and_quarantine"] = {"pass": attempts == [1, 2, 3] and all(between) and final is None
                                    and st["status"] == "quarantined", "attempts": attempts}
    # S6 interrupted pushes: kill a busy writer at random moments; the remote must stay valid and append-only
    kills = []
    for k in range(8):
        p = ctx.Process(target=w_append_forever, args=(work, branch, url, f"noisy{k}"))
        p.start()
        time.sleep(random.uniform(0.5, 4.0))
        os.kill(p.pid, signal.SIGKILL)
        p.join(30)
        kills.append(p.exitcode)
        main.sync()  # raises CorruptLog if the kill left anything partial
    audit = store(work, "auditor", branch, url).audit_history()
    noise = [e for e in ev.parse(main.sync()) if e["kind"] == "noise"]
    R["S6_interrupted_pushes"] = {"pass": audit == [] and all(c == -signal.SIGKILL for c in kills),
                                  "kills": len(kills), "noise_events_landed": len(noise), "audit_problems": audit}
    # S7 remote unreachable: raises, records nothing
    bad = GitStore(work / "offline", branch, url, actor="offline")
    bad.sync()
    bad._git("remote", "set-url", "origin", "https://unreachable.invalid/x.git")
    n_before = len(ev.parse(main.sync()))
    try:
        bad.transact(lambda e: [{"kind": "should_not_land"}])
        raised = False
    except StoreUnavailable:
        raised = True
    R["S7_remote_unreachable"] = {"pass": raised and len(ev.parse(main.sync())) == n_before}
    R["final_audit"] = {"pass": main.audit_history() == [], "events": len(ev.parse(main.sync()))}
    return rep


def delete_branch(branch: str, url: str, work: Path) -> dict:
    tmp = work / "cleanup"
    tmp.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", str(tmp)], check=False)
    for i in range(4):
        subprocess.run(["git", "-C", str(tmp), "push", "-q", url, "--delete", branch], capture_output=True)
        left = subprocess.run(["git", "ls-remote", "--heads", url, branch], capture_output=True, text=True)
        if left.returncode == 0 and not left.stdout.strip():
            return {"deleted": True, "verified_by": "ls-remote shows no such branch"}
        time.sleep(2 ** i)
    return {"deleted": False, "ls_remote": left.stdout.strip()[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default=f"office-queue-test-{time.strftime('%Y%m%d%H%M%S', time.gmtime())}")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--report")
    a = ap.parse_args()
    url = remote_url()
    work = Path(tempfile.mkdtemp(prefix="office-gh-"))
    signal.signal(signal.SIGTERM, lambda *x: sys.exit(3))
    rep: dict = {"branch": a.branch, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        rep.update(run(a.branch, a.workers, work, url))
    except BaseException as e:  # noqa: BLE001 - report whatever failed, then clean up
        rep["error"] = f"{type(e).__name__}: {e}"[:1000]
    finally:
        rep["cleanup"] = delete_branch(a.branch, url, work)
        rep["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rep["all_pass"] = "error" not in rep and all(v.get("pass") for v in rep.get("results", {}).values()) \
        and rep["cleanup"]["deleted"]
    text = json.dumps(rep, indent=1)
    print(text)
    if a.report:
        Path(a.report).write_text(text + "\n")
    return 0 if rep["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
