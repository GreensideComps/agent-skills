"""Task queue over the event log: idempotent creation, leased claims with fencing, bounded retries, quarantine.

Every function here is one store transaction. Task state is derived from the log by `tasks()`; nothing else is kept.

* Creation is idempotent: the task id is derived from its type and inputs, so a second create is a no-op.
* Dependencies must already exist when a task is created, so the graph can never contain a cycle.
* Growth limits (children per task, chain depth, open tasks, tasks created per day) refuse runaway task creation; a
  refusal is itself recorded, so it is visible.
* A claim is a lease with a fencing number (the seq of the claim event). Only the holder of the current, unexpired
  fence can complete or fail the task, so a worker that was paused or killed and later resumes cannot record a
  result over a newer attempt.
* An expired lease makes the task claimable again; the claim records which fence it recovered from.
* A failure schedules a retry with exponential backoff; after `max_attempts` claims the task is quarantined and needs
  a person (it is never retried again by the queue).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

from .store import GitStore

OPEN = {"ready", "leased", "waiting"}


@dataclass(frozen=True)
class Limits:
    max_children: int = 5
    max_depth: int = 4
    max_open: int = 200
    max_created_per_day: int = 500


@dataclass(frozen=True)
class Lease:
    task: str
    fence: int
    lease_until: float
    attempt: int
    inputs: dict = field(default_factory=dict)
    type: str = ""


def task_id(typ: str, inputs: dict) -> str:
    return "t-" + hashlib.sha256(json.dumps([typ, inputs], sort_keys=True).encode()).hexdigest()[:20]


def backoff(attempt: int, base: float = 300.0, cap: float = 3600.0) -> float:
    return min(cap, base * 4 ** max(0, attempt - 1))


def tasks(events: list[dict], now: float) -> dict[str, dict]:
    """Current state of every task, derived from the log."""
    out: dict[str, dict] = {}
    for e in events:
        k, t = e["kind"], e.get("task")
        if k == "task_created":
            out[t] = {"type": e["type"], "inputs": e["inputs"], "priority": e["priority"], "deps": e["deps"],
                      "parent": e.get("parent"), "depth": e["depth"], "max_attempts": e["max_attempts"],
                      "lease_s": e["lease_s"], "created_day": e["day"], "status": "ready", "attempts": 0,
                      "fence": None, "lease_until": None, "not_before": 0.0, "errors": [], "output": None}
        elif t not in out:
            continue
        elif k == "task_claimed":
            out[t].update(status="leased", fence=e["seq"], lease_until=e["lease_until"], worker=e["worker"])
            out[t]["attempts"] += 1
        elif k == "task_completed":
            out[t].update(status="done", output=e.get("output"), lease_until=None)
        elif k == "task_failed":
            out[t]["errors"].append(e["error"])
            out[t].update(status="ready", not_before=e["not_before"], lease_until=None)
        elif k == "task_quarantined":
            out[t].update(status="quarantined", reason=e["reason"], lease_until=None)
    for s in out.values():
        if s["status"] == "leased" and s["lease_until"] <= now:
            s["status"] = "ready"  # expired lease: the worker died or overran
        if s["status"] == "ready":
            dep = [out.get(d, {}).get("status") for d in s["deps"]]
            if any(d == "quarantined" for d in dep):
                s["status"] = "blocked"
            elif not all(d == "done" for d in dep) or s["not_before"] > now:
                s["status"] = "waiting"
    return out


def create(store: GitStore, typ: str, inputs: dict, *, priority: int = 50, deps: tuple[str, ...] = (),
           parent: str | None = None, max_attempts: int = 3, lease_s: float = 1800.0, limits: Limits = Limits(),
           clock=time.time) -> dict:
    """Create a task (or find the existing identical one). Returns {"task": id, "status": created|exists|refused}."""
    tid = task_id(typ, inputs)
    result: dict = {}

    def decide(events):
        now = clock()
        st = tasks(events, now)
        if tid in st:
            result.update(task=tid, status="exists")
            return None
        reason = None
        missing = [d for d in deps if d not in st]
        if missing:
            reason = f"unknown dependencies {missing}"
        depth = 0
        if parent is not None:
            if parent not in st:
                reason = reason or f"unknown parent {parent}"
            else:
                depth = st[parent]["depth"] + 1
                children = sum(1 for s in st.values() if s["parent"] == parent)
                if children >= limits.max_children:
                    reason = reason or f"parent already has {children} children"
                if depth > limits.max_depth:
                    reason = reason or f"chain depth {depth} over {limits.max_depth}"
        if sum(1 for s in st.values() if s["status"] in OPEN | {"blocked"}) >= limits.max_open:
            reason = reason or f"{limits.max_open} open tasks"
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        if sum(1 for s in st.values() if s["created_day"] == day) >= limits.max_created_per_day:
            reason = reason or f"{limits.max_created_per_day} tasks already created today"
        if reason:
            result.update(task=tid, status="refused", reason=reason)
            return [{"kind": "task_refused", "task": tid, "type": typ, "reason": reason}]
        result.update(task=tid, status="created")
        return [{"kind": "task_created", "task": tid, "type": typ, "inputs": inputs, "priority": priority,
                 "deps": list(deps), "parent": parent, "depth": depth, "max_attempts": max_attempts,
                 "lease_s": lease_s, "day": day}]

    store.transact(decide)
    return result


def claim(store: GitStore, worker: str, clock=time.time, types: set[str] | None = None) -> Lease | None:
    """Lease the highest-priority eligible task, quarantining any that has used all its attempts. None if idle."""
    got: list[Lease] = []

    def decide(events):
        now = clock()
        st = tasks(events, now)
        ready = sorted((t for t, s in st.items() if s["status"] == "ready" and (types is None or s["type"] in types)),
                       key=lambda t: (-st[t]["priority"], t))
        for t in ready:
            s = st[t]
            if s["attempts"] >= s["max_attempts"]:
                return [{"kind": "task_quarantined", "task": t,
                         "reason": f"{s['attempts']} attempts used; last errors {s['errors'][-2:]}"}]
            got[:] = [Lease(t, len(events), now + s["lease_s"], s["attempts"] + 1, s["inputs"], s["type"])]
            return [{"kind": "task_claimed", "task": t, "worker": worker, "lease_until": now + s["lease_s"],
                     "attempt": s["attempts"] + 1, "recovered_fence": s["fence"]}]
        return None

    while True:
        got.clear()
        out = store.transact(decide)
        if out is None:
            return None
        if out[0]["kind"] == "task_claimed":
            return got[0]
        # a quarantine was recorded; look for the next eligible task


def _holder(events, lease: Lease, now: float) -> str | None:
    s = tasks(events, now).get(lease.task)
    if s is None or s["fence"] != lease.fence:
        return "lease lost: the task was claimed again"
    if s["status"] != "leased":
        return f"lease not live (task is {s['status']})"
    return None


def complete(store: GitStore, lease: Lease, output: dict | None = None, clock=time.time) -> bool:
    """Record the result. False (nothing recorded) unless this lease is still the current, unexpired one."""
    ok = []

    def decide(events):
        if _holder(events, lease, clock()):
            return None
        ok.append(True)
        return [{"kind": "task_completed", "task": lease.task, "fence": lease.fence, "output": output}]

    store.transact(decide)
    return bool(ok)


def fail(store: GitStore, lease: Lease, error: str, clock=time.time) -> bool:
    """Record a failed attempt and schedule the retry. False if the lease is no longer held."""
    ok = []

    def decide(events):
        now = clock()
        if _holder(events, lease, now):
            return None
        ok.append(True)
        return [{"kind": "task_failed", "task": lease.task, "fence": lease.fence, "error": error[:500],
                 "not_before": now + backoff(lease.attempt)}]

    store.transact(decide)
    return bool(ok)
