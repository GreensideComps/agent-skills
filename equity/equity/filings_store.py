"""Append-only store for SEC filing events and the raw bytes they came from (mini fund Stage 2 §1).

Layout under a root folder (for research, `/mnt/project-files/research-data/sec/`, never the git repo):

    raw/<sha256>          raw response bytes, written once, named by their hash
    filing_events.jsonl   one FilingEvent per line, hash-chained by `prev`

Re-adding an identical event writes nothing. A changed event for the same accession is a new line with
`revision`, `supersedes` and `revision_reason`; the old line is never edited (INTERFACES §0.4).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()


class StoreError(RuntimeError):
    pass


class FilingStore:
    def __init__(self, root, clock=utc_now):
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.events_path = self.root / "filing_events.jsonl"
        self.clock = clock

    # raw bytes
    def put_raw(self, body: bytes) -> str:
        h = hashlib.sha256(body).hexdigest()
        p = self.raw_dir / h
        if p.exists():
            if hashlib.sha256(p.read_bytes()).hexdigest() != h:
                raise StoreError(f"raw file {h} is corrupt")
            return h
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(h + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, p)
        return h

    def get_raw(self, h: str) -> bytes:
        body = (self.raw_dir / h).read_bytes()
        if hashlib.sha256(body).hexdigest() != h:
            raise StoreError(f"raw file {h} is corrupt")
        return body

    # events
    def lines(self) -> list[str]:
        if not self.events_path.exists():
            return []
        return [ln for ln in self.events_path.read_text().splitlines() if ln.strip()]

    def events(self) -> list[dict]:
        return [json.loads(ln) for ln in self.lines()]

    def validate(self) -> list[str]:
        errs, prev, seen = [], GENESIS, set()
        for i, ln in enumerate(self.lines(), 1):
            e = json.loads(ln)
            if e.get("prev") != prev:
                errs.append(f"line {i}: chain broken")
            if e.get("record_id") in seen:
                errs.append(f"line {i}: duplicate record_id")
            seen.add(e.get("record_id"))
            prev = line_hash(ln)
        return errs

    def append(self, events: list[dict]) -> dict:
        """Append new or changed events. Returns {'written', 'unchanged', 'revisions'}."""
        errs = self.validate()
        if errs:
            raise StoreError("store invalid before append: " + "; ".join(errs))
        old_lines = self.lines()
        existing = [json.loads(ln) for ln in old_lines]
        ids = {e["record_id"] for e in existing}
        latest = {}
        for e in existing:
            latest[e["accession"]] = e
        prev = line_hash(old_lines[-1]) if old_lines else GENESIS
        new_lines, counts = [], {"written": 0, "unchanged": 0, "revisions": 0}
        for ev in events:
            if ev["record_id"] in ids:
                counts["unchanged"] += 1
                continue
            rec = dict(ev)
            before = latest.get(ev["accession"])
            rec["revision"] = 0 if before is None else before["revision"] + 1
            rec["supersedes"] = None if before is None else before["record_id"]
            rec["revision_reason"] = None if before is None else "content_changed"
            if before is not None:
                counts["revisions"] += 1
            rec["recorded_at"] = self.clock()
            rec["prev"] = prev
            line = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            new_lines.append(line)
            prev = line_hash(line)
            ids.add(rec["record_id"])
            latest[rec["accession"]] = rec
            counts["written"] += 1
        if new_lines:
            old_bytes = self.events_path.read_bytes() if self.events_path.exists() else b""
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.events_path.with_name(self.events_path.name + ".tmp")
            tmp.write_bytes(old_bytes + ("\n".join(new_lines) + "\n").encode())
            if not tmp.read_bytes().startswith(old_bytes):
                raise StoreError("append would change existing bytes")
            os.replace(tmp, self.events_path)
        return counts

    def current(self) -> dict[str, dict]:
        """Latest revision per accession."""
        out = {}
        for e in self.events():
            out[e["accession"]] = e
        return out
