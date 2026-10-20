"""Command line: python3 -m office worker | status | digest | pause | resume | gate-start | gate-report.

State lives on the `claude/office-state` branch (the claude/ prefix is the one cloud sessions may push to) of the repository's own remote (override with --state-remote). Nothing
here places an order, reads a holdout or starts a research run; see handlers.py for everything a worker can do.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import gate, health, worker
from .events import parse
from .handlers import Context
from .store import GitStore

REPO = Path(__file__).resolve().parents[2]


def origin() -> str:
    return subprocess.run(["git", "-C", str(REPO), "remote", "get-url", "origin"], capture_output=True, text=True,
                          check=True).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="office")
    ap.add_argument("--state-remote", default=None)
    ap.add_argument("--branch", default="claude/office-state")
    ap.add_argument("--workdir", default=None, help="git workdir for the state branch (default: a temp dir)")
    ap.add_argument("--heartbeat-h", type=float, default=1.0)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worker")
    w.add_argument("--out-dir", default=None)
    w.add_argument("--max-tasks", type=int, default=8)
    w.add_argument("--max-seconds", type=float, default=2400.0)
    w.add_argument("--stop-file", default=str(REPO / "office" / "STOP"))
    w.add_argument("--drill-crash", action="store_true", help="exit right after the first claim (gate drill)")
    sub.add_parser("status")
    p = sub.add_parser("pause")
    p.add_argument("--reason", required=True)
    r = sub.add_parser("resume")
    r.add_argument("--owner-message", required=True)
    gs = sub.add_parser("gate-start")
    gs.add_argument("--owner-message", required=True)
    sub.add_parser("gate-report")
    dg = sub.add_parser("digest")
    dg.add_argument("--day", default=None)
    a = ap.parse_args(argv)

    remote = a.state_remote or origin()
    workdir = Path(a.workdir or tempfile.mkdtemp(prefix="office-state-"))
    store = GitStore(workdir, a.branch, remote, actor="worker" if a.cmd == "worker" else "cli")
    hb = a.heartbeat_h * 3600

    if a.cmd == "worker":
        ctx = Context(store=store, repo_url=origin(), now=time.time, out_dir=Path(a.out_dir) if a.out_dir else None,
                      heartbeat_s=hb)

        def crash(lease):
            print(json.dumps({"drill": "exiting after claim", "task": lease.task, "fence": lease.fence}))
            sys.stdout.flush()
            import os
            os._exit(3)
        stats = worker.run(store, ctx, worker=f"worker-{ctx.env.get('CLAUDE_CODE_REMOTE_SESSION_ID', 'local')[-12:]}",
                           code=worker.code_sha(REPO), max_tasks=a.max_tasks, max_seconds=a.max_seconds,
                           stop_file=Path(a.stop_file), after_claim=crash if a.drill_crash else None)
        print(json.dumps(stats, indent=1))
        return 0
    if a.cmd == "status":
        rep = health.report(parse(store.sync()), time.time(), hb)
        print(json.dumps(rep, indent=1, default=str))
        return 1 if any(x["level"] == "critical" for x in rep["alerts"]) else 0
    if a.cmd == "pause":
        worker.pause(store, a.reason)
    elif a.cmd == "resume":
        worker.resume(store, a.owner_message)
    elif a.cmd == "gate-start":
        if not a.owner_message.startswith("cmsg_"):
            raise SystemExit("gate-start needs the owner's message id (cmsg_...)")
        worker.record(store, "gate_started", owner_message=a.owner_message, heartbeat_s=hb,
                      criteria=gate.CRITERIA_VERSION)
    elif a.cmd == "digest":
        from . import director
        from .handlers import render_digest
        now = time.time()
        print(render_digest(parse(store.sync()), now, a.day or director.day(now), hb))
    elif a.cmd == "gate-report":
        problems = store.audit_history()
        print(json.dumps(gate.evaluate(parse(store.sync()), time.time(), problems), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
