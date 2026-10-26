"""Verdict annotations for registry results recorded without a verdict (owner decision D-A, 2026-10-23).

B5 run 2 recorded its two primary results in `research/edge/trials.jsonl` (lines 241-242) with the statistics the
deflated Sharpe needs but no `verdict` field; the fail verdicts are in the run's report. This module keeps those
verdicts in a separate append-only file, `research/edge/verdict_annotations.jsonl`, so the registry and
`edge_registry.py` stay byte-identical (both are pinned by the D33/D34 tests).

Each annotation is bound to the registry line it annotates by that line's number and sha256, and to its evidence by
the evidence file's sha256. Lines are hash-chained like the registry. An annotation adds no result: it changes
neither `n_trials` nor the Sharpe ratios the deflated Sharpe pools.

Annotations can only make a trial *less* usable (review finding P30-1): the allowed verdicts are `fail` and
`inconclusive`, and every annotation must match the pinned list `EXPECTED` of owner-decided annotations. A `pass`
can only ever come from a registry result line itself, never from this file.

If an evidence file changes, every annotation citing it stops validating, and `append` refuses to add anything
(P30-9). Recovery is a new owner-approved annotation set citing the new evidence sha256, in a new ledger version;
the old lines are never edited.

    python3 edge_verdicts.py            # validate both files and print every verdict
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import edge_registry

PATH = Path(__file__).resolve().parent / "edge" / "verdict_annotations.jsonl"
VERDICTS = {"fail", "inconclusive"}
REQUIRED = {"event", "id", "date", "verdict", "label", "annotates_line", "annotates_line_sha256", "evidence",
            "evidence_sha256", "owner_decision", "prev"}
REPO = Path(__file__).resolve().parent.parent
# The only annotations that may ever appear: trial id -> (verdict, owner decision). Owner decision D-A.
EXPECTED = {
    "B5-H1-FCFPS-ACCEL-V3": ("fail", "cmsg_01U4KMvkBYNknqm4HRVie8uv964VkQcqvQbBHhfQQbHd8Z"),
    "B5-S2A-GP-12M-V3": ("fail", "cmsg_01U4KMvkBYNknqm4HRVie8uv964VkQcqvQbBHhfQQbHd8Z"),
}


def _hex64(h) -> bool:
    return isinstance(h, str) and len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def load(path: Path = PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def validate(path: Path = PATH, registry: Path = edge_registry.PATH, repo: Path = REPO) -> list[str]:
    """Problems found (empty = valid): a broken chain, missing fields, an annotation of anything but a result line
    without a verdict, a line hash that no longer matches the registry, evidence whose sha256 differs, a second
    annotation for one trial, a verdict outside VERDICTS (so never `pass`), or an annotation not in EXPECTED."""
    problems = edge_registry.validate(registry)
    if problems:
        return [f"registry: {p}" for p in problems]
    if not path.exists():
        return []
    reg_lines = registry.read_text().splitlines()
    prev, seen = edge_registry.GENESIS, set()
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError as x:
            problems.append(f"line {n}: not JSON ({x})")
            prev = edge_registry.line_hash(raw)
            continue
        if e.get("prev") != prev:
            problems.append(f"line {n}: hash chain broken (a line was edited, removed or reordered)")
        prev = edge_registry.line_hash(raw)
        missing = REQUIRED - e.keys()
        if missing or e.get("event") != "verdict_annotation":
            problems.append(f"line {n}: not a complete verdict_annotation (missing {sorted(missing)})")
            continue
        tid, ln = e["id"], e["annotates_line"]
        target = reg_lines[ln - 1] if isinstance(ln, int) and 1 <= ln <= len(reg_lines) else None
        r = json.loads(target) if target else {}
        if target is None or r.get("event") != "result" or r.get("id") != tid:
            problems.append(f"line {n}: registry line {ln} is not {tid}'s result")
        elif edge_registry.line_hash(target) != e["annotates_line_sha256"]:
            problems.append(f"line {n}: registry line {ln} no longer has the annotated sha256")
        elif r.get("verdict") is not None:
            problems.append(f"line {n}: {tid}'s result already carries verdict {r['verdict']!r}")
        if tid in seen:
            problems.append(f"line {n}: second verdict annotation for {tid}")
        seen.add(tid)
        if e["verdict"] == "pass":
            problems.append(f"line {n}: verdict pass not allowed in annotations")
        elif e["verdict"] not in VERDICTS:
            problems.append(f"line {n}: verdict {e['verdict']!r} not in {sorted(VERDICTS)}")
        if not str(e["owner_decision"]).startswith("cmsg_"):
            problems.append(f"line {n}: no owner decision id (cmsg_...)")
        if EXPECTED.get(tid) != (e["verdict"], e["owner_decision"]):
            problems.append(f"line {n}: {tid} {e['verdict']!r} by {e['owner_decision']} is not a pinned owner decision")
        try:
            date.fromisoformat(str(e["date"]))
        except ValueError:
            problems.append(f"line {n}: date {e['date']!r} is not ISO")
        ev = repo / str(e["evidence"])
        if not _hex64(e["evidence_sha256"]) or not ev.is_file() \
                or hashlib.sha256(ev.read_bytes()).hexdigest() != e["evidence_sha256"]:
            problems.append(f"line {n}: evidence {e['evidence']} does not have the recorded sha256")
    return problems


def append(events: list[dict], *, on_date: str, path: Path = PATH, registry: Path = edge_registry.PATH,
           repo: Path = REPO) -> None:
    """Append `events`, chained and dated `on_date` (ISO; required, so the bytes never depend on the clock, P30-6),
    in one rename. Refuses, leaving the file untouched, unless the files are valid before and after and every
    earlier byte is unchanged."""
    date.fromisoformat(on_date)
    before = validate(path, registry, repo)
    if before:
        raise ValueError(f"invalid before append: {before}")
    old = path.read_bytes() if path.exists() else b""
    lines = [l for l in old.decode().splitlines() if l.strip()]
    prev = edge_registry.line_hash(lines[-1]) if lines else edge_registry.GENESIS
    for event in events:
        raw = json.dumps({"date": on_date, **event, "prev": prev}, sort_keys=True)
        lines.append(raw)
        prev = edge_registry.line_hash(raw)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    after = validate(tmp, registry, repo)
    if after or not tmp.read_bytes().startswith(old):
        tmp.unlink()
        raise ValueError(f"annotation rejected, file unchanged: {after or 'history changed'}")
    tmp.replace(path)


def verdicts(reg_events: list[dict], annotations: list[dict]) -> dict[str, str]:
    """Each resulted trial's verdict: the one on its result, else its annotation. Trials with neither are left out;
    a reader must treat a missing verdict as "not a pass"."""
    out = {e["id"]: e["verdict"] for e in reg_events if e.get("event") == "result" and e.get("verdict") is not None}
    for a in annotations:
        out.setdefault(a["id"], a["verdict"])
    return out


def allocation_eligible(trial_id: str, reg_events: list[dict], annotations: list[dict]) -> tuple[bool, str]:
    """Whether `trial_id` may be cited as allocation evidence, and why not. Only a registered `trial` counted for
    the deflated Sharpe whose **registry result line** says "pass" qualifies; annotations are read only to explain a
    refusal, never to grant eligibility. Necessary, not sufficient: the portfolio manager adds its own conditions
    (owner listing, confirmation, prospective evidence)."""
    reg = edge_registry.registered(reg_events).get(trial_id)
    if reg is None:
        return False, f"{trial_id} is not registered"
    if reg.get("kind") != "trial" or not reg.get("counts_for_dsr"):
        return False, f"{trial_id} is registered as {reg.get('kind')}, not a counted trial"
    on_result = {e["id"]: e["verdict"] for e in reg_events
                 if e.get("event") == "result" and e.get("verdict") is not None}
    if on_result.get(trial_id) == "pass":
        return True, "pass"
    v = verdicts(reg_events, annotations).get(trial_id)
    return False, f"{trial_id} verdict is {v or 'not recorded'}, not pass"


if __name__ == "__main__":
    probs = validate()
    for t, v in sorted(verdicts(edge_registry.load(), load()).items()):
        print(f"{t}: {v}")
    if probs:
        print("INVALID:\n  " + "\n  ".join(probs))
        sys.exit(1)
    print("valid")
