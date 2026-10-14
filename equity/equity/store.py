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


class ShardedLedger(Ledger):
    """A ledger split across files in a directory, so no single file nears GitHub's 100 MB limit.

    `shard_of(record)` names the file a record goes to. Reads cover every shard plus the
    pre-sharding single file (`legacy`), if one is still there, de-duplicated on `rid` as usual.
    """

    def __init__(self, directory: Path, shard_of, legacy: Path | None = None):
        self.dir = Path(directory)
        self.shard_of = shard_of
        self.legacy = Path(legacy) if legacy else None
        self.path = self.dir  # for size reporting; reads and writes go through the shard files

    def _files(self) -> list[Path]:
        files = sorted(self.dir.glob("*.jsonl")) if self.dir.exists() else []
        return ([self.legacy] if self.legacy and self.legacy.exists() else []) + files

    def read(self) -> list[dict]:
        out, seen = [], set()
        for f in self._files():
            for rec in Ledger(f).read():
                rid = rec.get("rid")
                if rid is not None:
                    if rid in seen:
                        continue
                    seen.add(rid)
                out.append(rec)
        return out

    def append(self, records: list[dict] | dict) -> int:
        if isinstance(records, dict):
            records = [records]
        existing = self.rids()
        by_shard: dict[str, list[dict]] = {}
        for r in records:
            if "rid" not in r:
                raise ValueError("ledger records need a deterministic 'rid'")
            if r["rid"] in existing:
                continue
            existing.add(r["rid"])
            by_shard.setdefault(self.shard_of(r), []).append(r)
        for shard, recs in by_shard.items():
            Ledger(self.dir / f"{shard}.jsonl").append(recs)
        return sum(len(v) for v in by_shard.values())

    def migrate_legacy(self) -> int:
        """Move the pre-sharding file's records into shards (rids unchanged), then remove it."""
        if not self.legacy or not self.legacy.exists():
            return 0
        recs = Ledger(self.legacy).read()
        legacy, self.legacy = self.legacy, None
        n = self.append(recs)
        legacy.unlink()
        return n


def company_shard(rec: dict) -> str:
    return hashlib.sha256(str(rec.get("company_id")).encode()).hexdigest()[0]


def month_shard(rec: dict) -> str:
    return str(rec.get("ts_utc", "unknown"))[:7]


class Store:
    """The set of ledgers that make up the company database."""

    def __init__(self, root: Path = DATA_DIR):
        self.root = Path(root)
        self.securities = Ledger(self.root / "securities.jsonl")      # security master versions
        self.companies = Ledger(self.root / "companies.jsonl")        # discovery records
        self.transitions = Ledger(self.root / "transitions.jsonl")    # pipeline status changes
        # Sharded: these two grow with the universe and with every scheduled run.
        self.fundamentals = ShardedLedger(self.root / "fundamentals", company_shard,
                                          self.root / "fundamentals.jsonl")  # metric snapshots (only on change)
        self.scans = Ledger(self.root / "scans.jsonl")                # universe coverage per scan
        self.jobs = ShardedLedger(self.root / "jobs", month_shard, self.root / "jobs.jsonl")  # job runs, by month
        self.methods = Ledger(self.root / "methods.jsonl")            # metric formulas per method version
        self.prices = Ledger(self.root / "prices.jsonl")              # daily closes used for valuation
        self.screens = Ledger(self.root / "screens.jsonl")            # screener runs (scores, gates, ranks)
        self.valuations = Ledger(self.root / "valuations.jsonl")      # DCF scenarios, reverse DCF, multiples
        self.research = Ledger(self.root / "research.jsonl")          # theses and bear cases
        self.alerts = Ledger(self.root / "alerts.jsonl")              # changes between screen runs
        self.recommendations = Ledger(self.root / "recommendations.jsonl")  # paper picks, logged before outcomes
        self.paper = Ledger(self.root / "paper_trades.jsonl")          # simulated fills (portfolio + benchmark)
        self.paper_nav = Ledger(self.root / "paper_nav.jsonl")         # daily marks of both books
