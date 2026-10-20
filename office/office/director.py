"""Director rules (M2): which tasks exist each day. Fixed code, no judgement.

Every task id is derived from its type and inputs (`queue.task_id`), and the inputs carry the UTC date, so running
the plan any number of times in a day creates each task once. Only R0 work is planned here: maintenance,
monitoring, read-only checks and reporting. Nothing here can start a research experiment, read a holdout or place an
order; those task types do not exist in `handlers.HANDLERS`.
"""
from __future__ import annotations

import time

from . import queue as q

DAILY = (  # (type, priority, lease seconds, max attempts)
    ("health", 90, 600.0, 3),
    ("test_suites", 70, 3600.0, 2),
    ("demo_snapshot", 60, 900.0, 3),
)


def day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def plan(store, now: float, *, enabled: set[str] | None = None, clock=None) -> list[dict]:
    """Create today's tasks (idempotent). `enabled` limits the daily types (default: all). Returns the results."""
    d = day(now)
    clk = clock or (lambda: now)
    made = []
    for typ, pri, lease, attempts in DAILY:
        if enabled is not None and typ not in enabled:
            continue
        r = q.create(store, typ, {"day": d}, priority=pri, lease_s=lease, max_attempts=attempts, clock=clk)
        made.append(r)
    # The digest has the lowest priority, so a run does the day's checks first, but it does not depend on them: a
    # check that is failing, waiting for a retry or quarantined is reported in the digest instead of silencing it.
    made.append(q.create(store, "digest", {"day": d}, priority=40, lease_s=600.0, max_attempts=3, clock=clk))
    return made
