"""The worker run (M2): one bounded pass over the queue, started by the heartbeat.

A run records `worker_started` (its heartbeat), plans the day's tasks, then claims and executes tasks until the
queue is idle or a budget is spent, and records `worker_finished` with its counts. A run that dies part way leaves
its lease to expire; the next run recovers the task (the claim records the fence it recovered from) and the health
report counts the run that never finished.

Stops, checked before every claim:
* `office_paused` in the log (durable; only an `office_resumed` naming the owner's message lifts it);
* the stop file, or OFFICE_STOP=1 in the environment (local emergency stop for this run).
"""
from __future__ import annotations

import secrets
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import director, health
from . import queue as q
from .events import parse
from .handlers import HANDLERS, Context, redact


def _stop_reason(store, stop_file: Path | None, env: dict) -> str | None:
    if env.get("OFFICE_STOP") == "1":
        return "OFFICE_STOP=1"
    if stop_file is not None and stop_file.exists():
        return f"stop file {stop_file}"
    return health.paused(parse(store.sync()))


def record(store, kind: str, **fields) -> None:
    store.transact(lambda events: [{"kind": kind, **fields}])


def run(store, ctx: Context, *, worker: str, code: str, clock: Callable[[], float] = time.time,
        max_tasks: int = 8, max_seconds: float = 2400.0, stop_file: Path | None = None,
        enabled: set[str] | None = None, handlers: dict | None = None,
        after_claim: Callable[[q.Lease], None] | None = None) -> dict:
    """One run. Returns its stats (also recorded in `worker_finished`). `after_claim` is a test and drill hook."""
    handlers = HANDLERS if handlers is None else handlers
    run_id = f"r-{int(clock())}-{secrets.token_hex(3)}"
    t0 = clock()
    record(store, "worker_started", run=run_id, worker=worker, code=code,
           session=ctx.env.get("CLAUDE_CODE_REMOTE_SESSION_ID"))
    stats = {"completed": 0, "failed": 0, "lost": 0, "planned": 0, "stopped": None}
    stop = _stop_reason(store, stop_file, ctx.env)
    if stop is None:
        stats["planned"] = sum(r["status"] == "created" for r in director.plan(store, clock(), enabled=enabled,
                                                                               clock=clock))
    while stop is None:
        if stats["completed"] + stats["failed"] + stats["lost"] >= max_tasks:
            stats["stopped"] = "task budget"
            break
        if clock() - t0 >= max_seconds:
            stats["stopped"] = "time budget"
            break
        lease = q.claim(store, worker, clock=clock, types=set(handlers))
        if lease is None:
            stats["stopped"] = "idle"
            break
        if after_claim is not None:
            after_claim(lease)
        try:
            out = handlers[lease.type](ctx, lease.inputs)
        except Exception as e:  # noqa: BLE001 - every failure is recorded and retried by the queue
            ok = q.fail(store, lease, redact(f"{type(e).__name__}: {e}", ctx.env), clock=clock)
            stats["failed" if ok else "lost"] += 1
        else:
            ok = q.complete(store, lease, out, clock=clock)
            stats["completed" if ok else "lost"] += 1
        stop = _stop_reason(store, stop_file, ctx.env)
    if stop is not None:
        stats["stopped"] = f"stop: {stop}"
    stats["seconds"] = round(clock() - t0, 1)
    record(store, "worker_finished", run=run_id, stats=stats)
    return stats


def pause(store, reason: str) -> None:
    record(store, "office_paused", reason=reason)


def resume(store, owner_message: str) -> None:
    if not owner_message.startswith("cmsg_"):
        raise ValueError("resume needs the owner's message id (cmsg_...)")
    record(store, "office_resumed", owner_message=owner_message)


def code_sha(repo: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
    return r.stdout.strip() or "unknown"
