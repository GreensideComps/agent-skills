"""G2 start acceptance (H3): one full UTC day of clean scheduled heartbeat slots, scored from the log only.

Read-only: a pure function of events. It never starts, retries or records a run. The office log cannot see a session
that was refused before the worker ran (no event is written), so such a slot shows as `missing`; refusals seen in the
session records are passed in by the reviewer and any one of them fails acceptance.

Each slot is a scheduled fire time (`minute` past every third hour, UTC). The slot's window runs from its fire time to
the next slot's. The first `worker_started` in the window is the slot's run; any other run in the window is `extra`.

* `clean`: started within `tolerance_s` of the fire time, recorded `worker_finished` with `stopped == "idle"`, and ran
  the expected commit.
* `delayed`: started inside the window but later than `tolerance_s` (for example held by a usage limit).
* `missing`: no run started in the window (never fired, refused, or failed before the worker ran).
* `incomplete`: started but never finished, or stopped for any reason other than an empty queue (a budget, a pause,
  a stop file, a refused drill).
* `wrong_code`: finished cleanly but ran a commit other than the one under review.

Acceptance passes only when the day is over, all slots are clean, there are no extra runs and no refusals were
reported. Anything else fails; there is no partial credit and no retry inside the day.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import health

SLOT_HOURS = 3
CLEAN_STOP = "idle"


def slots(day: str, minute: int = 12) -> list[float]:
    d0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    return [d0 + h * 3600 + minute * 60 for h in range(0, 24, SLOT_HOURS)]


def evaluate(events: list[dict], day: str, now: float, *, code: str, minute: int = 12, tolerance_s: float = 900.0,
             refusals: list[str] = ()) -> dict:
    fires = slots(day, minute)
    end = fires[-1] + SLOT_HOURS * 3600
    rs = health.runs(events)
    out, extra = [], []
    for i, t in enumerate(fires):
        hi = fires[i + 1] if i + 1 < len(fires) else end
        mine = [r for r in rs if t <= r["started"] < hi]
        extra += [r["run"] for r in mine[1:]]
        row = {"slot": health.utc_s(t), "run": None, "lag_s": None, "status": "missing"}
        if mine:
            r = mine[0]
            stopped = (r["stats"] or {}).get("stopped")
            row.update(run=r["run"], lag_s=round(r["started"] - t, 1), stopped=stopped, code=r["code"])
            if r["started"] - t > tolerance_s:
                row["status"] = "delayed"
            elif r["finished"] is None or stopped != CLEAN_STOP:
                row["status"] = "incomplete"
            elif r["code"] != code:
                row["status"] = "wrong_code"
            else:
                row["status"] = "clean"
        out.append(row)
    counts: dict[str, int] = {}
    for row in out:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    if now < end:
        verdict = "pending"
    elif counts.get("clean", 0) == len(fires) and not extra and not refusals:
        verdict = "pass"
    else:
        verdict = "fail"
    return {"verdict": verdict, "day": day, "code": code, "minute": minute, "tolerance_s": tolerance_s,
            "counts": counts, "slots": out, "extra_runs": extra, "refusals": list(refusals),
            "note": "a session refused before the worker ran writes no event and shows here as missing"}
