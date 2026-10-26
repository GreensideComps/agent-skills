"""Append-only store for SEC filing events and the raw bytes they came from (mini fund Stage 2 §1).

Layout under a root folder (for research, `/mnt/project-files/research-data/sec/`, never the git repo):

    raw/<sha256>          raw response bytes, written once, named by their hash
    filing_events.jsonl   one FilingEvent per line, hash-chained by `prev`
    observations.jsonl    one line per (event, submissions document, retrieval time), hash-chained by `prev`

Re-adding an identical event writes nothing. A changed event for the same accession is a new line with
`revision`, `supersedes` and `revision_reason`; the old line is never edited (INTERFACES §0.4).
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - not POSIX
    fcntl = None

GENESIS = "0" * 64


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()


class StoreError(RuntimeError):
    pass


class FilingStore:
    def __init__(self, root, clock=utc_now, single_writer: bool = False):
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.events_path = self.root / "filing_events.jsonl"
        self.obs_path = self.root / "observations.jsonl"
        self.clock = clock
        self.single_writer = single_writer

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
    def lines(self, path: Path | None = None) -> list[str]:
        path = self.events_path if path is None else path
        if not path.exists():
            return []
        return [ln for ln in path.read_text().splitlines() if ln.strip()]

    def events(self) -> list[dict]:
        return [json.loads(ln) for ln in self.lines()]

    def observations(self) -> list[dict]:
        return [json.loads(ln) for ln in self.lines(self.obs_path)]

    def validate(self) -> list[str]:
        """Both logs must be unbroken hash chains, and each accession's lines must form one revision chain:
        revision 0, 1, 2... with `supersedes` naming the previous line's record_id."""
        errs = []
        for name, path in (("events", self.events_path), ("observations", self.obs_path)):
            prev = GENESIS
            for i, ln in enumerate(self.lines(path), 1):
                if json.loads(ln).get("prev") != prev:
                    errs.append(f"{name} line {i}: chain broken")
                prev = line_hash(ln)
        last = {}
        for i, e in enumerate(self.events(), 1):
            before = last.get(e.get("accession"))
            want_rev = 0 if before is None else before["revision"] + 1
            want_sup = None if before is None else before["record_id"]
            if e.get("revision") != want_rev or e.get("supersedes") != want_sup:
                errs.append(f"events line {i}: revision chain broken for {e.get('accession')}")
            if before is not None and e.get("record_id") == before["record_id"]:
                errs.append(f"events line {i}: unchanged event written again")
            last[e.get("accession")] = e
        return errs

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        if fcntl is None:
            if not self.single_writer:
                raise StoreError("no fcntl on this platform: pass single_writer=True to append without a lock")
            yield
            return
        with open(self.root / "filing_events.lock", "a") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _extend(path: Path, new_lines: list[str]) -> None:
        old_bytes = path.read_bytes() if path.exists() else b""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(old_bytes + ("\n".join(new_lines) + "\n").encode())
        if not tmp.read_bytes().startswith(old_bytes):
            raise StoreError("append would change existing bytes")
        os.replace(tmp, path)

    def append(self, events: list[dict]) -> dict:
        """Append new or changed events. Returns {'written', 'unchanged', 'revisions'}.

        An event is unchanged when its record_id equals the **latest** line for its accession. Going back to an
        earlier version (A -> B -> A) is a new revision with `revision_reason: "reverted_to:<record_id>"` (P32-5).
        Each event's `observation` (submissions hash and retrieval time) goes to observations.jsonl, not into the
        event line, so re-reading a changed submissions document does not rewrite unchanged events (P32-2). The
        whole read-validate-replace runs under an exclusive lock (P32-9)."""
        with self._locked():
            errs = self.validate()
            if errs:
                raise StoreError("store invalid before append: " + "; ".join(errs))
            old_lines = self.lines()
            history, latest = defaultdict(set), {}
            for e in (json.loads(ln) for ln in old_lines):
                history[e["accession"]].add(e["record_id"])
                latest[e["accession"]] = e
            seen_obs = {(o["record_id"], o["submissions_sha256"], o["retrieved_at"]) for o in self.observations()}
            obs_old = self.lines(self.obs_path)
            prev = line_hash(old_lines[-1]) if old_lines else GENESIS
            obs_prev = line_hash(obs_old[-1]) if obs_old else GENESIS
            new_lines, obs_lines = [], []
            counts = {"written": 0, "unchanged": 0, "revisions": 0}
            now = self.clock()
            for ev in events:
                rec = dict(ev)
                obs = rec.pop("observation", None)
                acc = rec["accession"]
                before = latest.get(acc)
                if before is not None and before["record_id"] == rec["record_id"]:
                    counts["unchanged"] += 1
                else:
                    rec["revision"] = 0 if before is None else before["revision"] + 1
                    rec["supersedes"] = None if before is None else before["record_id"]
                    if before is None:
                        rec["revision_reason"] = None
                    elif rec["record_id"] in history[acc]:
                        rec["revision_reason"] = f"reverted_to:{rec['record_id']}"
                    else:
                        rec["revision_reason"] = "content_changed"
                    if before is not None:
                        counts["revisions"] += 1
                    rec["recorded_at"] = now
                    rec["prev"] = prev
                    line = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    new_lines.append(line)
                    prev = line_hash(line)
                    history[acc].add(rec["record_id"])
                    latest[acc] = rec
                    counts["written"] += 1
                if obs is not None:
                    key = (rec["record_id"], obs.get("submissions_sha256"), obs.get("retrieved_at"))
                    if key not in seen_obs:
                        seen_obs.add(key)
                        o = {"record_id": key[0], "accession": acc, "submissions_sha256": key[1],
                             "retrieved_at": key[2], "recorded_at": now, "prev": obs_prev}
                        line = json.dumps(o, sort_keys=True, separators=(",", ":"))
                        obs_lines.append(line)
                        obs_prev = line_hash(line)
            if new_lines:
                self._extend(self.events_path, new_lines)
            if obs_lines:
                self._extend(self.obs_path, obs_lines)
            return counts

    def current(self) -> dict[str, dict]:
        """Latest revision per accession."""
        out = {}
        for e in self.events():
            out[e["accession"]] = e
        return out
