"""Task handlers (M2): the only work a worker can do. R0 only: health, tests, a read-only demo snapshot, the digest.

Each handler takes (ctx, inputs) and returns a small JSON-able output, or raises to fail the attempt. An output may
carry {"alert": {"level", "code", "text"}}, which `health.report` raises for 36 hours.

Side-effect boundaries (enforced here, not by prompt):
* No handler imports `trading/` into this process. The demo snapshot runs the read-only client in a child process of
  a fresh master clone, with the kill file set and only GET methods reachable (`ReadOnlyClient`).
* Test suites run in a fresh clone with every credential variable removed and the proxy pointed at a dead port, so
  a test cannot reach the broker, Yahoo or the email provider.
* The digest is written to files. Sending it by email happens only when `ctx.email` is set (owner-approved config);
  M2 ships with it off.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import health
from .events import parse

SECRET_PREFIXES = ("T212", "REPORT_EMAIL", "RESEND", "SMTP", "GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC")
SUITES = (("trading", "trading", ()), ("equity", "equity", ()), ("research", "research", ()),
          ("office", "office", ("tests",)))
READ_CMD = ('import json; from t212bot.config import load_credentials; from t212bot.client import T212Client; '
            'from t212bot.readonly import ReadOnlyClient; ro = ReadOnlyClient(T212Client(load_credentials())); '
            'print(json.dumps({"summary": ro.account_summary(), "positions": ro.positions(), '
            '"pending_orders": ro.pending_orders()}, default=str))')


@dataclass
class Context:
    store: object                      # GitStore
    repo_url: str                      # where to clone master from
    now: Callable[[], float]
    out_dir: Path | None = None        # where digests are written (e.g. the shared project folder)
    email: Callable[[str, str], str] | None = None   # (subject, markdown) -> provider id; None = do not send
    run: Callable = subprocess.run     # injectable for tests
    env: dict = field(default_factory=lambda: dict(os.environ))
    branch: str = "master"
    heartbeat_s: float = 3600.0


def clean_env(env: dict) -> dict:
    out = {k: v for k, v in env.items() if not k.startswith(SECRET_PREFIXES)}
    out.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9",
               http_proxy="http://127.0.0.1:9")
    return out


def clone(ctx: Context, dest: Path) -> str:
    r = ctx.run(["git", "clone", "-q", "--depth", "1", "--branch", ctx.branch, ctx.repo_url, str(dest)],
                capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(f"clone failed: {r.stderr.strip()[-300:]}")
    return ctx.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True,
                   timeout=60).stdout.strip()


def h_health(ctx: Context, inputs: dict) -> dict:
    events = parse(ctx.store.sync())
    rep = health.report(events, ctx.now(), ctx.heartbeat_s)
    out = {k: rep[k] for k in ("tasks", "runs", "hours_since_last_run", "recovered_claims", "events")}
    out["alerts"] = len(rep["alerts"])  # live alerts are recomputed from the log, never copied into an output
    problems = ctx.store.audit_history()
    out["history_audit"] = "clean" if not problems else problems[:5]
    if problems:
        out["alert"] = {"level": "critical", "code": "log_history", "text": f"event log history: {problems[0]}"}
    return out


def _counts(tail: str) -> dict:
    c = {k: int(n) for n, k in re.findall(r"(\d+) (passed|failed|errors?|skipped)", tail)}
    if "error" in c:
        c["errors"] = c.pop("error")
    return c


def h_test_suites(ctx: Context, inputs: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="office-tests-") as tmp:
        repo = Path(tmp) / "repo"
        sha = clone(ctx, repo)
        res, failed = {}, []
        for name, sub, args in SUITES:
            d = repo / sub
            if not d.is_dir():
                res[name] = {"status": "absent"}
                continue
            try:
                r = ctx.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=str(d),
                            env=clean_env(ctx.env), capture_output=True, text=True, timeout=1800)
                tail = (r.stdout.strip().splitlines() or [""])[-1]
                res[name] = {"exit": r.returncode, **_counts(tail), "summary": tail[-200:]}
                if r.returncode:
                    failed.append(name)
            except subprocess.TimeoutExpired:
                res[name] = {"status": "timeout"}
                failed.append(name)
    out = {"commit": sha, "suites": res}
    if failed:
        out["alert"] = {"level": "critical", "code": "tests_failing",
                        "text": f"tests failing on {ctx.branch} {sha[:10]}: {', '.join(failed)}"}
    return out


def h_demo_snapshot(ctx: Context, inputs: dict) -> dict:
    if ctx.env.get("T212_ENV") != "demo" or not ctx.env.get("T212_API_KEY"):
        return {"status": "skipped", "reason": "no demo credentials in this session"}
    with tempfile.TemporaryDirectory(prefix="office-demo-") as tmp:
        repo = Path(tmp) / "repo"
        sha = clone(ctx, repo)
        (repo / "trading" / "KILL").touch()  # the bot's kill switch, in this clone only
        env = {k: v for k, v in ctx.env.items() if not k.startswith(("REPORT_EMAIL", "RESEND", "SMTP"))}
        r = ctx.run(["python3", "-c", READ_CMD], cwd=str(repo / "trading"), env=env, capture_output=True, text=True,
                    timeout=300)
    if r.returncode:
        raise RuntimeError(f"read failed: {r.stderr.strip().splitlines()[-1][:300] if r.stderr.strip() else r.returncode}")
    d = json.loads(r.stdout)
    s, pos, pend = d["summary"], d["positions"] or [], d["pending_orders"] or []
    out = {"commit": sha, "total_value": s.get("totalValue"), "cash": (s.get("cash") or {}).get("availableToTrade"),
           "positions": len(pos), "pending_orders": len(pend),
           "unrealised_pl": (s.get("investments") or {}).get("unrealizedProfitLoss")}
    if pend:
        out["alert"] = {"level": "warn", "code": "demo_pending_orders",
                        "text": f"{len(pend)} pending order(s) on the demo account; the office places none"}
    return out


def latest_outputs(events: list[dict], day: str) -> dict[str, dict]:
    from .queue import task_id
    out = {}
    for typ in ("health", "test_suites", "demo_snapshot"):
        tid = task_id(typ, {"day": day})
        for e in events:
            if e["kind"] == "task_completed" and e["task"] == tid:
                out[typ] = e.get("output") or {}
    return out


def render_digest(events: list[dict], now: float, day: str, heartbeat_s: float = 3600.0) -> str:
    rep = health.report(events, now, heartbeat_s)
    o = latest_outputs(events, day)
    lines = [f"# Edge office digest {day}", "",
             f"Generated {health.utc(now)} from {rep['events']} logged events. Every figure below is read from the "
             f"log; anything not run is marked as such.", "", "## Alerts", ""]
    lines += [f"- **{a['level']}** {a['text']}" for a in rep["alerts"]] or ["- none"]
    lines += ["", "## Operation", "",
              f"- Worker runs recorded: {rep['runs']}; last started {health.utc(rep['last_run_started'])} "
              f"({rep['hours_since_last_run']} h ago)",
              f"- Tasks by state: {json.dumps(rep['tasks'], sort_keys=True)}",
              f"- Claims that recovered an expired lease: {rep['recovered_claims']}",
              f"- Runs that started but recorded no end: {len(rep['unfinished_runs'])}", "", "## Tests on master", ""]
    t = o.get("test_suites")
    if t is None:
        lines.append("- not run yet today")
    else:
        lines.append(f"Commit `{str(t.get('commit', 'unknown'))[:10]}`")
        for k, v in (t.get("suites") or {}).items():
            lines.append(f"- {k}: {v.get('summary') or v.get('status')}")
    lines += ["", "## Demo account (read-only)", ""]
    s = o.get("demo_snapshot")
    if s is None:
        lines.append("- not run yet today")
    elif s.get("status") == "skipped":
        lines.append(f"- skipped: {s.get('reason')}")
    else:
        lines.append(f"- value {s.get('total_value')}, cash {s.get('cash')}, {s.get('positions')} positions, "
                     f"{s.get('pending_orders')} pending orders, unrealised P/L {s.get('unrealised_pl')}")
    lines += ["", "No research run, holdout access, order or account change is possible from the office (R0 only).", ""]
    return "\n".join(lines)


def h_digest(ctx: Context, inputs: dict) -> dict:
    events = parse(ctx.store.sync())
    md = render_digest(events, ctx.now(), inputs["day"], ctx.heartbeat_s)
    out = {"chars": len(md), "written": None, "emailed": None}
    if ctx.out_dir is not None:
        p = Path(ctx.out_dir) / f"digest_{inputs['day']}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md)
        out["written"] = str(p)
    if ctx.email is not None:
        out["emailed"] = ctx.email(f"[Edge office] digest {inputs['day']}", md)
    out["markdown"] = md[:6000]
    return out


HANDLERS: dict[str, Callable[[Context, dict], dict]] = {
    "health": h_health, "test_suites": h_test_suites, "demo_snapshot": h_demo_snapshot, "digest": h_digest,
}
