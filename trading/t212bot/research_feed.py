"""Read the research side for the daily report: experiment registry, agenda, log.

The registry (research/experiments/*.json) is the source of truth for what was
tested and decided; the report summarises it rather than listing scripts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import ROOT

RESEARCH = ROOT.parent / "research"
REQUIRED = ["id", "title", "date", "hypothesis", "data", "methodology", "benchmark", "costs",
            "out_of_sample", "robustness", "limitations", "trials", "decision", "promoted", "evidence"]
DECISIONS = {"REJECTED", "PROMOTED", "SHADOW", "INSURANCE_ONLY", "MOMENTUM_SUPPORTED", "PENDING_RERUN",
             "AWAITING_EVIDENCE", "NO_CHANGE", "BLOCKED"}


def validate(rec: dict) -> list[str]:
    errs = [f"missing field '{k}'" for k in REQUIRED if k not in rec]
    if rec.get("decision") not in DECISIONS:
        errs.append(f"unknown decision {rec.get('decision')!r}")
    if rec.get("promoted") and rec.get("decision") != "PROMOTED":
        errs.append("promoted=true requires decision PROMOTED")
    if rec.get("decision") not in ("PENDING_RERUN", "BLOCKED") and not rec.get("evidence"):
        errs.append("a decided experiment must cite evidence files")
    return errs


def load_registry(root: Path = RESEARCH) -> tuple[list[dict], list[str]]:
    recs, problems = [], []
    for p in sorted((root / "experiments").glob("E*.json")):
        try:
            rec = json.loads(p.read_text())
        except Exception as e:
            problems.append(f"{p.name}: unreadable ({e})")
            continue
        for e in validate(rec):
            problems.append(f"{p.name}: {e}")
        recs.append(rec)
    return recs, problems


def agenda(root: Path = RESEARCH) -> list[dict]:
    p = root / "AGENDA.md"
    if not p.exists():
        return []
    items, cur = [], None
    for line in p.read_text().splitlines():
        m = re.match(r"^## (P\d+)[:\s—-]+(.*)$", line)
        if m:
            cur = {"id": m.group(1), "title": m.group(2).strip(), "status": ""}
            items.append(cur)
            continue
        m = re.match(r"^- \*\*Status:\*\*\s*(.*)$", line)
        if m and cur is not None and not cur["status"]:
            cur["status"] = m.group(1).strip()
    return items


def trial_counter(root: Path = RESEARCH) -> int | None:
    p = root / "AGENDA.md"
    if not p.exists():
        return None
    m = re.search(r"Trial counter[^:]*:\*\*\s*(\d+)", p.read_text())
    return int(m.group(1)) if m else None


def log_entries(root: Path = RESEARCH) -> list[dict]:
    p = root / "LOG.md"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        if line.startswith("| 20"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 6:
                rows.append({"date": cells[0], "item": cells[1], "what": cells[2], "result": cells[3], "decision": cells[4], "trials": cells[5]})
    return rows
