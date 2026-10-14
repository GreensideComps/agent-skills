"""Alerts from screen runs (milestone 4), de-duplicated by construction.

An alert fires on a *change* between a run and the previous run of the same screen method,
never on a state that merely persists, so a company that stays ranked does not alert every
day. The rid is company + kind + the run date, so re-running the same day writes nothing.
The first run of a method has nothing to compare with and records a baseline, not alerts.

Kinds:
* entered_ranked   - passed every gate for the first time (or again after dropping out)
* left_ranked      - was ranked, no longer is; names the gates that now fail
* score_move       - total moved by at least SCORE_MOVE points while ranked in both runs
* thesis_watch     - a company with a recorded bear case lost its ranking (the bear case
                     may be playing out)
"""
from __future__ import annotations

from .store import Store, utc_now

SCORE_MOVE = 10.0


def previous_run(store: Store, rec: dict) -> dict | None:
    prior = [r for r in store.screens.read() if r["method_version"] == rec["method_version"]
             and r["as_of"] < rec["as_of"]]
    return max(prior, key=lambda r: (r["as_of"], r["ts_utc"])) if prior else None


def diff(prev: dict, cur: dict, bear_case_ids: set[str] = frozenset()) -> list[dict]:
    p = {r["company_id"]: r for r in prev["results"]}
    out = []
    for r in cur["results"]:
        cid, old = r["company_id"], p.get(r["company_id"])
        was = bool(old and old.get("rank"))
        now = bool(r.get("rank"))

        def alert(kind, text, **extra):
            out.append({"rid": f"alert:{cid}:{kind}:{cur['as_of']}", "kind": kind, "company_id": cid,
                        "entity_name": r.get("entity_name"), "text": text, "as_of": cur["as_of"],
                        "screen_rid": cur["rid"], "previous_screen_rid": prev["rid"], **extra})
        if now and not was:
            alert("entered_ranked", f"passed every gate; rank {r['rank']}, total {r['total']:.0f}")
        elif was and not now:
            why = r["failed_gates"] + r["unknown_critical_gates"] or ["total score incomplete"]
            alert("left_ranked", "no longer ranked: " + ", ".join(why), gates=why)
            if cid in bear_case_ids:
                alert("thesis_watch", "has a recorded bear case and dropped out of the ranking: review it")
        elif now and was and abs(r["total"] - old["total"]) >= SCORE_MOVE:
            alert("score_move", f"total {old['total']:.0f} -> {r['total']:.0f}", delta=r["total"] - old["total"])
    return out


def run(store: Store, rec: dict) -> dict:
    prev = previous_run(store, rec)
    if prev is None:
        return {"baseline": True, "alerts": []}
    bears = {r["company_id"] for r in store.research.read() if r["kind"] == "bear_case"}
    alerts = diff(prev, rec, bears)
    now = utc_now()
    for a in alerts:
        a["ts_utc"] = now
    written = store.alerts.append(alerts)
    return {"baseline": False, "alerts": alerts, "written": written}
