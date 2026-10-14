"""Append-only JSONL ledgers: the durable source of truth for the company database.

Why text ledgers rather than a committed SQLite file:
* The cloud containers are ephemeral; durability comes from git commits.
* Several scheduled sessions push to the same branch. A binary database cannot be
  merged, while append-only JSONL merges cleanly with git's `union` driver
  (see the repository `.gitattributes`).
* History is never rewritten: a correction is a new record, so every past decision
  stays auditable.

Each record carries a deterministic `rid` (hash of its identifying content), so
re-running a job that appends the same record is a no-op: readers de-duplicate on
`rid`, and `append` skips records whose `rid` is already present.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def content_hash(obj) -> str:
    """Stable short hash of a JSON-serialisable object (key order independent)."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class Ledger:
    """One append-only JSONL file. Readers tolerate a torn final line."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out, seen = [], set()
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn write from a crashed run; the rest of the file is intact
            rid = rec.get("rid")
            if rid is not None:
                if rid in seen:
                    continue
                seen.add(rid)
            out.append(rec)
        return out

    def rids(self) -> set[str]:
        return {r["rid"] for r in self.read() if "rid" in r}

    def append(self, records: list[dict] | dict) -> int:
        """Append records that are not already present. Returns how many were written."""
        if isinstance(records, dict):
            records = [records]
        existing = self.rids()
        fresh = []
        for r in records:
            if "rid" not in r:
                raise ValueError("ledger records need a deterministic 'rid'")
            if r["rid"] in existing:
                continue
            existing.add(r["rid"])
            fresh.append(r)
        if fresh:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                for r in fresh:
                    f.write(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        return len(fresh)


class Store:
    """The set of ledgers that make up the company database."""

    def __init__(self, root: Path = DATA_DIR):
        self.root = Path(root)
        self.securities = Ledger(self.root / "securities.jsonl")      # security master versions
        self.companies = Ledger(self.root / "companies.jsonl")        # discovery records
        self.transitions = Ledger(self.root / "transitions.jsonl")    # pipeline status changes
        self.fundamentals = Ledger(self.root / "fundamentals.jsonl")  # metric snapshots (only on change)
        self.scans = Ledger(self.root / "scans.jsonl")                # universe coverage per scan
        self.jobs = Ledger(self.root / "jobs.jsonl")                  # job runs (start/finish events)
        self.methods = Ledger(self.root / "methods.jsonl")            # metric formulas per method version
