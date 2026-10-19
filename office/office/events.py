"""Append-only, hash-chained event log: the only durable state of the research office.

Each line is one JSON event with `seq` (0, 1, 2, ...) and `prev` (sha256 of the previous line, or 64 zeros for the
first). Nothing is ever edited or removed; a correction is a new event. Current state is always derived from the
log, never stored beside it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

GENESIS = "0" * 64


class CorruptLog(Exception):
    """The log fails validation; nothing may be appended until a person has looked at it."""


def canonical(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def validate(text: str) -> list[str]:
    """Problems with the log (empty list when valid): bad JSON, a broken chain, a gap in seq, or a missing kind."""
    problems, prev = [], GENESIS
    for i, line in enumerate(l for l in text.splitlines() if l.strip()):
        try:
            e = json.loads(line)
        except ValueError:
            problems.append(f"line {i}: not JSON")
            break
        if e.get("seq") != i:
            problems.append(f"line {i}: seq {e.get('seq')!r}, expected {i}")
        if e.get("prev") != prev:
            problems.append(f"line {i}: chain broken")
        if not e.get("kind"):
            problems.append(f"line {i}: no kind")
        if canonical(e) != line:
            problems.append(f"line {i}: not in canonical form")
        prev = line_hash(line)
    return problems


def extend(text: str, new: list[dict], actor: str, now: str | None = None) -> str:
    """The log text with `new` appended, each given seq, prev, ts and actor. Raises CorruptLog on an invalid log."""
    problems = validate(text)
    if problems:
        raise CorruptLog(problems)
    lines = [l for l in text.splitlines() if l.strip()]
    prev = line_hash(lines[-1]) if lines else GENESIS
    out = list(lines)
    for e in new:
        e = {**e, "seq": len(out), "prev": prev, "ts": now or utcnow(), "actor": actor}
        line = canonical(e)
        out.append(line)
        prev = line_hash(line)
    return "\n".join(out) + "\n"
