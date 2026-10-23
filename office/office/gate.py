"""The 14-day unattended-operation gate, measured from the event log (criteria: docs/office/RELIABILITY_GATE.md for
G1, docs/office/RELIABILITY_GATE_G2.md for G2).

The gate starts with a `gate_started` event naming the owner's message, the heartbeat interval and the criteria
version; the criteria are fixed in this file before that event exists (`CRITERIA_VERSION` is what a new gate-start
records). A run is always scored under the version its own `gate_started` names, so G1 keeps its original rules.
Elapsed time is measured from event timestamps written by the store from the real clock. Every check is a pure
function of the log, so anyone can recompute the verdict from the branch history.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import health
from .handlers import HANDLERS
from .queue import tasks

CRITERIA_VERSION = "G2"
# Heartbeat check: the longest gap may be at most 2H plus this margin. G1 had none and failed on 21 Oct by 67 s after
# one missed run; G2 adds 15 minutes for session start lag, so exactly one missed run is tolerated, never two.
GAP_MARGIN_S = {"G1": 0.0, "G2": 900.0}
DAYS = 14
ALLOWED_KINDS = {"task_created", "task_refused", "task_claimed", "task_completed", "task_failed", "task_quarantined",
                 "worker_started", "worker_finished", "office_paused", "office_resumed", "gate_started"}
DAILY_REQUIRED = ("health", "digest")
NEVER_QUARANTINED = ("health", "digest")
MAX_UNFINISHED_SHARE = 0.05


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def evaluate(events: list[dict], now: float, history_problems: list[str], gate_seq: int | None = None) -> dict:
    """The verdict for the latest gate (or the one whose `gate_started` has `gate_seq`), under its own criteria.
    A gate's window ends where the next `gate_started` begins: an earlier gate is scored only on its own events and
    no later than that start. The history audit (`history_problems`) always covers the whole branch, which is stricter."""
    starts = [e for e in events if e["kind"] == "gate_started" and (gate_seq is None or e["seq"] == gate_seq)]
    if not starts:
        return {"verdict": "not started", "checks": []}
    g = starts[-1]
    nxt = next((e for e in events if e["kind"] == "gate_started" and e["seq"] > g["seq"]), None)
    if nxt is not None:
        events = [e for e in events if e["seq"] < nxt["seq"]]
        now = min(now, health.ts(nxt))
    version = g.get("criteria", "G1")
    if version not in GAP_MARGIN_S:
        return {"verdict": "unknown criteria", "criteria": version, "checks": []}
    g0, hb = health.ts(g), float(g["heartbeat_s"])
    limit = 2 * hb + GAP_MARGIN_S[version]
    win = [e for e in events if e["seq"] >= g["seq"]]
    checks: list[dict] = []

    def check(name: str, ok: bool, detail) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    elapsed = (now - g0) / 86400
    check("elapsed", elapsed >= DAYS, f"{elapsed:.2f} of {DAYS} days")
    check("history", not history_problems, history_problems[:3] or "every commit only appended")

    rs = [r for r in health.runs(events) if r["started"] >= g0]
    marks = [g0] + [r["started"] for r in rs] + [now]
    gaps = [b - a for a, b in zip(marks, marks[1:])]
    worst = max(gaps) if gaps else None
    if version == "G1":  # G1's detail text, unchanged
        detail = (f"{len(rs)} runs; longest gap {worst / 3600:.2f} h (limit {2 * hb / 3600:.2f} h)" if worst
                  else "no runs")
    else:
        i = gaps.index(worst)
        detail = (f"{len(rs)} runs; longest gap {worst:.0f} s from {health.utc_s(marks[i])} to "
                  f"{health.utc_s(marks[i + 1])} (limit {limit:.0f} s)")
    check("heartbeat", worst is not None and worst <= limit, detail)

    unfinished = [r for r in rs[:-1] if r["finished"] is None]
    share = len(unfinished) / max(1, len(rs) - 1)
    check("runs_finish", share <= MAX_UNFINISHED_SHARE, f"{len(unfinished)} of {max(0, len(rs) - 1)} closed runs "
          f"recorded no end ({share:.1%}, limit {MAX_UNFINISHED_SHARE:.0%})")

    done: dict[str, int] = {}
    last_claim: dict[str, int] = {}
    stale = 0
    for e in win:
        if e["kind"] == "task_claimed":
            last_claim[e["task"]] = e["seq"]
        elif e["kind"] == "task_completed":
            done[e["task"]] = done.get(e["task"], 0) + 1
            stale += e.get("fence") != last_claim.get(e["task"], e.get("fence"))
    dup = sorted(t for t, n in done.items() if n > 1)
    check("no_duplicates", not dup and not stale, f"{len(dup)} tasks completed twice; {stale} results from a stale "
          f"lease")

    st = tasks(events, now)
    orphans = [t for t, s in st.items() if s["status"] == "ready" and s["fence"] is not None and s["attempts"] and
               s["lease_until"] is not None and s["lease_until"] < now - 2 * hb]
    check("no_orphans", not orphans, f"{len(orphans)} expired leases not recovered within two heartbeats")

    day0, day_end = _day(g0 + 86400), _day(now - 86400)  # full UTC days inside the window
    days = sorted({e["inputs"]["day"] for e in win if e["kind"] == "task_created" and "day" in e.get("inputs", {})})
    full = [d for d in days if day0 <= d <= day_end]
    missing = []
    for d in full:
        for typ in DAILY_REQUIRED:
            if not any(s["type"] == typ and s["inputs"].get("day") == d and s["status"] == "done" for s in st.values()):
                missing.append(f"{typ} {d}")
    check("daily_outputs", full and not missing, f"{len(full)} full days; missing {missing[:5]}" if missing
          else f"{len(full)} full days, each with health and digest done")

    q_bad = [t for t, s in st.items() if s["status"] == "quarantined" and s["type"] in NEVER_QUARANTINED]
    check("core_never_quarantined", not q_bad, f"{len(q_bad)} health or digest tasks quarantined")

    bad_kinds = sorted({e["kind"] for e in win} - ALLOWED_KINDS)
    bad_types = sorted({e["type"] for e in win if e["kind"] == "task_created"} - set(HANDLERS))
    check("r0_only", not bad_kinds and not bad_types, f"unexpected kinds {bad_kinds}, task types {bad_types}"
          if bad_kinds or bad_types else "only R0 task types and office events")

    recovered = sum(1 for e in win if e["kind"] == "task_claimed" and e.get("recovered_fence") is not None)
    check("crash_recovered", recovered >= 1, f"{recovered} claims recovered an expired lease (at least one drill)")

    paused = health.paused(events)
    verdict = "pass" if all(c["pass"] for c in checks) and not paused else (
        "running" if elapsed < DAYS and all(c["pass"] for c in checks if c["check"] not in
                                            ("elapsed", "daily_outputs", "crash_recovered")) else "fail")
    return {"verdict": verdict, "criteria": version, "started": health.utc(g0), "owner_message":
            g.get("owner_message"), "heartbeat_h": hb / 3600, "paused": paused, "checks": checks}
