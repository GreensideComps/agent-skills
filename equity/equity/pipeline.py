"""Company pipeline: explicit, reversible statuses with an append-only audit trail.

Every transition needs a reason and at least one piece of evidence (a source URL,
an accession number, a fundamentals snapshot id, ...). Nothing is ever overwritten:
a company's current status is simply its latest transition, and the full history
stays in transitions.jsonl.

Gate hooks: moving a company to `candidate` requires a recorded bear case
(objections from the independent bear-case analyst) and a fundamentals snapshot
whose data confidence is not `low`, and an industry the screening method supports
(industry.py: banks, insurers, REITs and SPACs are not yet supported). The hooks are passed in, so the rule cannot be
bypassed by a caller that forgets to check.
"""
from __future__ import annotations

from .store import Store, content_hash, utc_now

STATUSES = ("discovered", "research_queue", "qualified", "watchlist", "candidate", "rejected", "thesis_broken")

ALLOWED = {
    None: {"discovered"},
    "discovered": {"research_queue", "rejected"},
    "research_queue": {"qualified", "rejected"},
    "qualified": {"watchlist", "research_queue", "rejected"},
    "watchlist": {"candidate", "research_queue", "rejected", "thesis_broken"},
    "candidate": {"watchlist", "rejected", "thesis_broken"},
    "rejected": {"research_queue"},          # reconsideration after a material change
    "thesis_broken": {"research_queue", "rejected"},
}


class TransitionError(ValueError):
    pass


def history(store: Store, company_id: str) -> list[dict]:
    return sorted((t for t in store.transitions.read() if t["company_id"] == company_id),
                  key=lambda t: (t["ts_utc"], t["seq"]))


def current_status(store: Store, company_id: str) -> str | None:
    h = history(store, company_id)
    return h[-1]["to"] if h else None


def all_statuses(store: Store) -> dict[str, str]:
    latest: dict[str, dict] = {}
    for t in store.transitions.read():
        cur = latest.get(t["company_id"])
        if cur is None or (t["ts_utc"], t["seq"]) > (cur["ts_utc"], cur["seq"]):
            latest[t["company_id"]] = t
    return {k: v["to"] for k, v in latest.items()}


def transition(store: Store, company_id: str, to: str, reason: str, evidence: list[str], actor: str,
               gate_checks: dict | None = None) -> dict:
    """Record a status change. `gate_checks` carries facts the gates need, e.g.
    {"bear_case_recorded": bool, "data_confidence": "high"|"medium"|"low", "industry_supported": bool}."""
    if to not in STATUSES:
        raise TransitionError(f"unknown status {to!r}")
    if not reason or not reason.strip():
        raise TransitionError("a transition needs a reason")
    evidence = [e for e in (evidence or []) if e and e.strip()]
    if not evidence:
        raise TransitionError("a transition needs at least one piece of evidence")
    hist = history(store, company_id)
    frm = hist[-1]["to"] if hist else None
    if to not in ALLOWED[frm]:
        raise TransitionError(f"{company_id}: {frm} -> {to} is not an allowed transition")
    if to == "candidate":
        g = gate_checks or {}
        if not g.get("bear_case_recorded"):
            raise TransitionError("candidate gate: an independent bear case must be recorded first")
        if g.get("data_confidence") not in ("high", "medium"):
            raise TransitionError("candidate gate: data confidence must be high or medium")
        if g.get("industry_supported") is not True:
            raise TransitionError("candidate gate: the industry must be classified and supported by the "
                                  "screening method (re-ingest snapshots older than fund-2.0)")
    seq = len(hist)
    rec = {"company_id": company_id, "from": frm, "to": to, "reason": reason.strip(), "evidence": evidence,
           "actor": actor, "seq": seq, "ts_utc": utc_now(), "gate_checks": gate_checks or {}}
    # rid = company + position in its history: a retried job cannot record the same step twice.
    rec["rid"] = f"{company_id}:{seq}:{content_hash([frm, to])}"
    if store.transitions.append(rec) == 0:
        raise TransitionError(f"{company_id}: transition #{seq} already recorded (duplicate or concurrent write)")
    return rec


def discover(store: Store, company_id: str, name: str, source: str, reason: str, evidence: list[str],
             actor: str, extra: dict | None = None) -> dict | None:
    """Record a discovery once per company. Returns the record, or None if already known."""
    if current_status(store, company_id) is not None:
        return None
    rec = {"rid": f"discovery:{company_id}", "company_id": company_id, "name": name, "source": source,
           "reason": reason, "evidence": evidence, "ts_utc": utc_now(), **(extra or {})}
    store.companies.append(rec)
    transition(store, company_id, "discovered", reason, evidence, actor)
    return rec
