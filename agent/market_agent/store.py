"""Persistent state for the market agent: append-only JSONL events, an order-intent journal, a heartbeat file, a
single-instance lease and the control file (kill switch).

Everything lives under one state directory (default /mnt/project-files/market-agent/state), which outlives any
container. Records are appended, never edited; the heartbeat, lease and control files are replaced atomically.
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from pathlib import Path

LEASE_TTL_S = 180.0


def utc(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if ts is None else ts))


class LeaseHeld(RuntimeError):
    pass


class Store:
    def __init__(self, root: Path, clock=time.time, sleep=time.sleep):
        self.root = Path(root)
        self.clock, self.sleep = clock, sleep
        for d in ("events", "intents"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.instance = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------ append-only records
    def _append(self, path: Path, rec: dict) -> dict:
        line = json.dumps(rec, sort_keys=True, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return rec

    def event(self, kind: str, **data) -> dict:
        now = self.clock()
        rec = {"ts": utc(now), "t": round(now, 3), "kind": kind, "instance": self.instance, **data}
        return self._append(self.root / "events" / f"{utc(now)[:10]}.jsonl", rec)

    def events(self, day: str) -> list[dict]:
        p = self.root / "events" / f"{day}.jsonl"
        return _read_jsonl(p)

    def intent(self, **data) -> dict:
        now = self.clock()
        rec = {"ts": utc(now), "t": round(now, 3), "instance": self.instance, **data}
        return self._append(self.root / "intents" / "intents.jsonl", rec)

    def intents(self) -> list[dict]:
        return _read_jsonl(self.root / "intents" / "intents.jsonl")

    # ------------------------------------------------------------ replaced files
    def _replace(self, name: str, obj: dict) -> None:
        p = self.root / name
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str))
        os.replace(tmp, p)

    def read(self, name: str) -> dict | None:
        p = self.root / name
        try:
            return json.loads(p.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def heartbeat(self, info: dict) -> None:
        self._replace("heartbeat.json", {"ts": utc(self.clock()), "t": self.clock(), "instance": self.instance, **info})

    def control(self) -> dict:
        """The kill switch. A missing or unreadable control file means trading is OFF (fail closed)."""
        c = self.read("control.json")
        if not isinstance(c, dict) or c.get("trading_enabled") is not True:
            return {"trading_enabled": False, **(c if isinstance(c, dict) else {"reason": "control.json missing"})}
        return c

    def set_control(self, enabled: bool, reason: str, by: str) -> None:
        self._replace("control.json", {"trading_enabled": bool(enabled), "reason": reason, "by": by,
                                       "ts": utc(self.clock())})
        self.event("control", trading_enabled=bool(enabled), reason=reason, by=by)

    # ------------------------------------------------------------ single instance
    def acquire_lease(self) -> None:
        cur = self.read("lease.json")
        now = self.clock()
        if cur and cur.get("instance") != self.instance and now - float(cur.get("t", 0)) < LEASE_TTL_S:
            raise LeaseHeld(f"lease held by {cur.get('instance')} (renewed {now - float(cur['t']):.0f} s ago)")
        self._replace("lease.json", {"instance": self.instance, "t": now, "ts": utc(now)})
        self.sleep(2.0)  # let a racing writer on the shared mount land first, then check who holds it
        if (self.read("lease.json") or {}).get("instance") != self.instance:
            raise LeaseHeld("lost the lease race")
        self.event("lease_acquired", previous=cur)

    def renew_lease(self) -> None:
        cur = self.read("lease.json") or {}
        if cur.get("instance") not in (None, self.instance):
            raise LeaseHeld(f"lease taken over by {cur.get('instance')}")
        self._replace("lease.json", {"instance": self.instance, "t": self.clock(), "ts": utc(self.clock())})

    def release_lease(self) -> None:
        cur = self.read("lease.json") or {}
        if cur.get("instance") == self.instance:
            self._replace("lease.json", {"instance": None, "t": 0, "ts": utc(self.clock()), "released_by": self.instance})


def _read_jsonl(p: Path) -> list[dict]:
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for x in lines:
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            continue  # a torn last line from a crash is skipped, never repaired in place
    return out
