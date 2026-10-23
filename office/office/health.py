"""System health and alert conditions, derived from the event log only (M2).

Nothing here is stored beside the log: every number is recomputed from events, so a report can always be checked
against the history it came from.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .queue import tasks

MISSED_MARGIN_S = 900.0  # start lag after the scheduled fire was 93-189 s on 20-21 Oct; 15 min is well clear of it
TASK_ALERT_S = 36 * 3600


def ts(e: dict) -> float:
    return datetime.fromisoformat(e["ts"]).timestamp()


def runs(events: list[dict]) -> list[dict]:
    """One record per worker run: start time, end time (None if it never finished), outcome counts."""
    out: dict[str, dict] = {}
    for e in events:
        if e["kind"] == "worker_started":
            out[e["run"]] = {"run": e["run"], "worker": e["actor"], "started": ts(e), "finished": None,
                             "code": e.get("code"), "stats": None}
        elif e["kind"] == "worker_finished" and e.get("run") in out:
            out[e["run"]].update(finished=ts(e), stats=e.get("stats"))
    return sorted(out.values(), key=lambda r: r["started"])


def report(events: list[dict], now: float, heartbeat_s: float = 3600.0) -> dict:
    """The current health of the office, and the alerts it raises. `heartbeat_s` is the scheduled interval."""
    st = tasks(events, now)
    rs = runs(events)
    by_status: dict[str, int] = {}
    for s in st.values():
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    last = rs[-1] if rs else None
    since_last = None if last is None else now - last["started"]
    unfinished = [r["run"] for r in rs[:-1] if r["finished"] is None]  # the newest run may still be going
    expired = [t for e in events if e["kind"] == "task_claimed" and e.get("recovered_fence") is not None
               for t in [e["task"]]]
    alerts = []
    if last is None:
        alerts.append({"level": "critical", "code": "no_worker_run", "text": "no worker run has ever started"})
    elif since_last > 2 * heartbeat_s:
        alerts.append({"level": "critical", "code": "worker_silent",
                       "text": f"no worker run for {since_last / 3600:.1f} h (more than two heartbeats)"})
    elif since_last > heartbeat_s + MISSED_MARGIN_S:
        alerts.append({"level": "warn", "code": "heartbeat_overdue",
                       "text": f"no worker run has started for {since_last / 3600:.2f} h: a scheduled run may have "
                               f"been missed, refused or delayed"})
    for a, b in zip(rs, rs[1:]):  # a missed or late run, already followed by another run: raised for a day
        gap = b["started"] - a["started"]
        if gap > heartbeat_s + MISSED_MARGIN_S and now - b["started"] < 86400:
            alerts.append({"level": "warn", "code": "heartbeat_missed",
                           "text": f"no run started between {utc(a['started'])} and {utc(b['started'])} "
                                   f"({gap / 3600:.2f} h): a scheduled run was missed or started late"})
    recent = {time.strftime("%Y-%m-%d", time.gmtime(now - d * 86400)) for d in range(3)}
    old_q = 0
    for t, s in sorted(st.items()):
        if s["status"] == "quarantined" and s["created_day"] not in recent:
            old_q += 1  # reported once below, so a past day's failure does not alert for ever
        elif s["status"] == "quarantined":
            alerts.append({"level": "critical", "code": "task_quarantined",
                           "text": f"{s['type']} {t} quarantined: {s.get('reason', '')[:200]}"})
        elif s["status"] == "blocked":
            alerts.append({"level": "warn", "code": "task_blocked", "text": f"{s['type']} {t} blocked by a dependency"})
    if old_q:
        alerts.append({"level": "warn", "code": "old_quarantined", "text": f"{old_q} quarantined task(s) from "
                       f"earlier days still need a person"})
    if unfinished:
        alerts.append({"level": "warn", "code": "run_did_not_finish",
                       "text": f"{len(unfinished)} worker run(s) started but never recorded an end"})
    # A task's alert stays live for 36 h, unless a later completion of the same task type came back without one:
    # that clears it from the live list. The event that raised it is never touched; `cleared_alerts` names both.
    # A completion that checked nothing (output status "skipped", e.g. a demo snapshot without credentials) clears
    # nothing.
    latest: dict[str, dict] = {}
    raised: list[tuple[str, dict]] = []
    for e in events:
        if e["kind"] != "task_completed" or e.get("task") not in st:
            continue
        typ = st[e["task"]]["type"]
        out = e.get("output") or {}
        if out.get("status") == "skipped" and not out.get("alert"):
            continue
        latest[typ] = e
        if (e.get("output") or {}).get("alert") and now - ts(e) < TASK_ALERT_S:
            raised.append((typ, e))
    cleared = []
    for typ, e in raised:
        a = e["output"]["alert"]
        later = latest[typ]
        if later is not e and not (later.get("output") or {}).get("alert"):
            cleared.append({"code": a.get("code", "task_alert"), "raised_seq": e["seq"], "raised": e["ts"],
                            "cleared_by_seq": later["seq"], "cleared": later["ts"], "type": typ})
            continue
        alerts.append({"level": a.get("level", "warn"), "code": a.get("code", "task_alert"), "text": a["text"]})
    if paused(events):
        alerts.append({"level": "warn", "code": "paused", "text": f"office paused: {paused(events)}"})
    return {"tasks": by_status, "runs": len(rs), "last_run_started": last and last["started"],
            "hours_since_last_run": None if since_last is None else round(since_last / 3600, 2),
            "unfinished_runs": unfinished, "recovered_claims": len(expired), "alerts": alerts,
            "cleared_alerts": cleared,
            "events": len(events)}


def paused(events: list[dict]) -> str | None:
    """The reason the office is paused, or None. Only an owner resume (with the owner's message id) lifts it."""
    reason = None
    for e in events:
        if e["kind"] == "office_paused":
            reason = e.get("reason", "paused")
        elif e["kind"] == "office_resumed" and e.get("owner_message"):
            reason = None
    return reason


def utc(t: float | None) -> str:
    return "never" if t is None else datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes")


def utc_s(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")
