"""Thesis and bear-case records (milestone 4).

A company reaches `candidate` only with a recorded bear case (pipeline gate). To keep the
bear case independent and useful, a record is refused unless:
* it has at least MIN_OBJECTIONS objections, each with its own evidence (a filing
  accession, a URL, a snapshot or valuation id);
* each objection names what would confirm it (`watch`), so it can be checked later;
* its author is not the author of the company's latest thesis (the analyst who argued
  for the company cannot also write the case against it).
A bear case is "current" for the gate only while no annual filing newer than it has
arrived, so a new 10-K forces a fresh look.

Records are append-only; a revised thesis is a new record that names the one it replaces.
"""
from __future__ import annotations

from .store import Store, content_hash, utc_now

MIN_OBJECTIONS = 3


class ResearchError(ValueError):
    pass


def records(store: Store, company_id: str, kind: str | None = None) -> list[dict]:
    rs = [r for r in store.research.read() if r["company_id"] == company_id and (kind is None or r["kind"] == kind)]
    return sorted(rs, key=lambda r: r["ts_utc"])


def add_thesis(store: Store, company_id: str, actor: str, summary: str, points: list[dict]) -> dict:
    """points: [{"claim": str, "evidence": [str, ...]}]"""
    if not summary.strip():
        raise ResearchError("a thesis needs a summary")
    if not points or any(not p.get("claim", "").strip() or not [e for e in p.get("evidence", []) if e.strip()]
                         for p in points):
        raise ResearchError("every thesis point needs a claim and evidence")
    prev = records(store, company_id, "thesis")
    rec = {"kind": "thesis", "company_id": company_id, "actor": actor, "summary": summary.strip(), "points": points,
           "replaces": prev[-1]["rid"] if prev else None, "ts_utc": utc_now()}
    rec["rid"] = f"thesis:{company_id}:{content_hash([summary, points, actor])}"
    store.research.append(rec)
    return rec


def add_bear_case(store: Store, company_id: str, actor: str, objections: list[dict]) -> dict:
    """objections: [{"objection": str, "evidence": [str, ...], "watch": str}]"""
    if len(objections) < MIN_OBJECTIONS:
        raise ResearchError(f"a bear case needs at least {MIN_OBJECTIONS} objections")
    for o in objections:
        if not o.get("objection", "").strip():
            raise ResearchError("empty objection")
        if not [e for e in o.get("evidence", []) if e.strip()]:
            raise ResearchError(f"objection without evidence: {o['objection'][:60]}")
        if not o.get("watch", "").strip():
            raise ResearchError(f"objection without a 'watch' (what would confirm it): {o['objection'][:60]}")
    theses = records(store, company_id, "thesis")
    if theses and theses[-1]["actor"] == actor:
        raise ResearchError("the bear case must come from someone other than the thesis author "
                            f"({actor}); it is meant to be independent")
    rec = {"kind": "bear_case", "company_id": company_id, "actor": actor, "objections": objections,
           "ts_utc": utc_now()}
    rec["rid"] = f"bear:{company_id}:{content_hash([objections, actor])}"
    store.research.append(rec)
    return rec


def current_bear_case(store: Store, company_id: str, latest_snapshot: dict | None) -> dict | None:
    """The latest bear case, unless an annual filing newer than it has arrived since."""
    bears = records(store, company_id, "bear_case")
    if not bears:
        return None
    b = bears[-1]
    filed = (latest_snapshot or {}).get("summary", {}).get("latest_filed") or ""
    return None if filed > b["ts_utc"][:10] else b
