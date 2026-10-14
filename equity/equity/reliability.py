"""Reliability checks (milestone 7): did what should have run actually run, and is the data fresh?

Nothing here trusts a schedule. A run counts only when its evidence exists:
* a Claude routine counts when a commit with the expected subject prefix landed on its
  branch within `grace_minutes` of the scheduled time;
* an equity job counts when equity/data/jobs.jsonl has an ok finish for it in that window.
Expected times come from the cron expressions in config/schedule.json, read in their own
timezone (so a Europe/London 08:20 run is expected at 07:20 UTC in summer).

Findings carry a severity: `critical` (stuck job, failed latest run, stale prices or
screen), `warn` (missed run, ageing data, large ledger) or `info`. The command exits
0 / 1 / 2 for ok / warn / critical, so a scheduler can alert on it.

Limit: a run that did its work but committed nothing looks missed. The monitor and ops
scripts always commit their journal entry, so for them a missing commit is a real gap.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .jobs import job_health
from .store import Store

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "schedule.json"
SEVERITY = {"info": 0, "warn": 1, "critical": 2}


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = (int(x) for x in rng.split("-"))
        else:
            a = b = int(rng)
        out.update(range(a, b + 1, int(step) if step else 1))
    return out


def cron_times(cron: str, tz: str, start: datetime, end: datetime) -> list[datetime]:
    """Scheduled UTC datetimes in [start, end] for a 5-field cron read in `tz`."""
    mi, hr, dom, mon, dow = cron.split()
    mins, hrs = _field(mi, 0, 59), _field(hr, 0, 23)
    doms, mons = _field(dom, 1, 31), _field(mon, 1, 12)
    dows = {d % 7 for d in _field(dow, 0, 7)}
    z = ZoneInfo(tz)
    out = []
    d = start.astimezone(z).date() - timedelta(days=1)
    while d <= end.astimezone(z).date():
        if d.day in doms and d.month in mons and (d.isoweekday() % 7) in dows:
            for h in sorted(hrs):
                for m in sorted(mins):
                    t = datetime(d.year, d.month, d.day, h, m, tzinfo=z).astimezone(timezone.utc)
                    if start <= t <= end:
                        out.append(t)
        d += timedelta(days=1)
    return out


def git_commits(branch: str, since: datetime, repo: Path | None = None) -> list[tuple[datetime, str]]:
    """(commit time UTC, subject) on origin/<branch> since `since`. Fetches the branch first."""
    repo = repo or Path(__file__).resolve().parents[2]
    subprocess.run(["git", "fetch", "-q", "origin", branch], cwd=repo, check=False, capture_output=True)
    res = subprocess.run(["git", "log", f"origin/{branch}", f"--since={since.isoformat()}", "--format=%cI%x09%s"],
                         cwd=repo, capture_output=True, text=True, check=False)
    if res.returncode:
        raise RuntimeError(f"git log origin/{branch} failed: {res.stderr.strip()[:200]}")
    out = []
    for line in res.stdout.splitlines():
        ts, _, subj = line.partition("\t")
        out.append((datetime.fromisoformat(ts).astimezone(timezone.utc), subj))
    return out


def job_finishes(store: Store) -> dict[str, list[tuple[datetime, str]]]:
    """job name -> [(finish time, status)] from the job ledger."""
    starts = {e["run_id"]: e["job"] for e in store.jobs.read() if e["event"] == "start"}
    out: dict[str, list] = {}
    for e in store.jobs.read():
        if e["event"] == "finish":
            out.setdefault(e.get("job") or starts.get(e["run_id"], "?"), []).append(
                (datetime.fromisoformat(e["ts_utc"]), e["status"]))
    return out


def check_expectation(exp: dict, now: datetime, lookback: timedelta, evidence: list[tuple[datetime, str]]) -> dict:
    """Compare scheduled times with evidence. evidence: (time, label) already filtered to this expectation."""
    if not exp.get("active_from"):
        return {"name": exp["name"], "state": "not_scheduled", "expected": 0, "seen": 0, "missed": []}
    grace = timedelta(minutes=exp["grace_minutes"])
    start = max(now - lookback, datetime.fromisoformat(exp["active_from"].replace("Z", "+00:00")))
    due = cron_times(exp["cron"], exp["tz"], start, now - grace)
    missed = [t for t in due if not any(t <= ts <= t + grace for ts, _ in evidence)]
    upcoming = cron_times(exp["cron"], exp["tz"], now, now + timedelta(days=7))
    return {"name": exp["name"], "state": "missed" if missed else "ok", "expected": len(due),
            "seen": len(due) - len(missed), "missed": [t.isoformat() for t in missed],
            "last_evidence": max((ts for ts, _ in evidence), default=None),
            "next_expected": upcoming[0].isoformat() if upcoming else None}


def _days_old(d: str | None, today: date) -> int | None:
    return None if not d else (today - date.fromisoformat(d[:10])).days


def freshness(store: Store, today: date, limits: dict) -> list[dict]:
    """Age of the newest record in each ledger the daily pipeline should refresh."""
    prices = [p["date"] for p in store.prices.read() if not p["company_id"].startswith("BENCH:")]
    ingest = [e["ts_utc"] for e in store.jobs.read()
              if e["event"] == "finish" and e.get("job") == "ingest_fundamentals" and e["status"] == "ok"]
    newest = {"prices": max(prices, default=None),
              "screen": max((r["as_of"] for r in store.screens.read()), default=None),
              "paper_nav": max((r["as_of"] for r in store.paper_nav.read()), default=None),
              "fundamentals_check": max(ingest, default=None)}
    out = []
    for k, d in newest.items():
        age = _days_old(d, today)
        stale = age is None or age > limits[k]
        sev = ("critical" if k in ("prices", "screen") else "warn") if stale else "info"
        out.append({"check": f"freshness:{k}", "severity": sev, "newest": d, "age_days": age,
                    "limit_days": limits[k]})
    return out


def run(store: Store, now: datetime | None = None, cfg: dict | None = None, commits_for=git_commits) -> dict:
    """All checks. `commits_for(branch, since)` is injectable for tests."""
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    lookback = timedelta(days=cfg["lookback_days"])
    findings: list[dict] = []
    schedules = []
    commit_cache: dict[str, list] = {}
    finishes = job_finishes(store)
    for exp in cfg["expectations"]:
        ev = exp["evidence"]
        try:
            if ev["type"] == "commit":
                if ev["branch"] not in commit_cache:
                    commit_cache[ev["branch"]] = commits_for(ev["branch"], now - lookback - timedelta(days=1))
                evidence = [(t, s) for t, s in commit_cache[ev["branch"]] if s.startswith(ev["prefix"])]
            else:
                evidence = [(t, s) for t, s in finishes.get(ev["job"], []) if s == "ok"]
        except RuntimeError as e:
            findings.append({"check": f"schedule:{exp['name']}", "severity": "warn", "detail": f"no evidence source: {e}"})
            continue
        r = check_expectation(exp, now, lookback, evidence)
        schedules.append(r)
        if r["state"] == "missed":
            findings.append({"check": f"schedule:{exp['name']}", "severity": "warn",
                             "detail": f"{len(r['missed'])} of {r['expected']} runs in the last "
                                       f"{cfg['lookback_days']} days left no evidence", "missed": r["missed"]})
        elif r["state"] == "not_scheduled":
            findings.append({"check": f"schedule:{exp['name']}", "severity": "info", "detail": "not scheduled yet"})
        if ev["type"] == "job":
            runs = sorted(finishes.get(ev["job"], []))
            if runs and runs[-1][1] != "ok":
                findings.append({"check": f"job:{ev['job']}", "severity": "critical",
                                 "detail": f"latest run {runs[-1][1]} at {runs[-1][0].isoformat()}"})
    jh = job_health(store, now, timedelta(hours=cfg["stuck_after_hours"]))
    for s in jh["stuck"]:
        findings.append({"check": f"stuck:{s['job']}", "severity": "critical",
                         "detail": f"started {s['started']}, never finished", "run_id": s["run_id"]})
    findings += freshness(store, now.date(), cfg["freshness_days"])
    for p in sorted(store.root.glob("*.jsonl")):
        mb = p.stat().st_size / 1e6
        if mb > cfg["ledger_size_warn_mb"]:
            findings.append({"check": f"size:{p.name}", "severity": "warn",
                             "detail": f"{mb:.0f} MB (GitHub refuses files over 100 MB)"})
    worst = max((SEVERITY[f["severity"]] for f in findings), default=0)
    return {"as_of": now.replace(microsecond=0).isoformat(), "status": ["ok", "warn", "critical"][worst],
            "exit_code": worst, "schedules": schedules, "findings": findings}


def report(res: dict) -> str:
    def fmt(t):
        return "" if not t else (t if isinstance(t, str) else t.isoformat())[:16].replace("T", " ")
    lines = [f"# Reliability check, {fmt(res['as_of'])} UTC", "", f"Overall: **{res['status'].upper()}**", "",
             "## Scheduled runs (evidence, not schedules)", "",
             "| Run | State | Seen / expected | Last evidence | Next expected |", "|---|---|---|---|---|"]
    for s in res["schedules"]:
        lines.append(f"| {s['name']} | {s['state']} | {s['seen']} / {s['expected']} | "
                     f"{fmt(s.get('last_evidence'))} | {fmt(s.get('next_expected'))} |")
    lines += ["", "## Findings", ""]
    for f in sorted(res["findings"], key=lambda f: -SEVERITY[f["severity"]]):
        if f["severity"] == "info" and f["check"].startswith("freshness"):
            continue
        detail = f.get("detail") or f"newest {f.get('newest')}, {f.get('age_days')} days old (limit {f.get('limit_days')})"
        lines.append(f"- **{f['severity']}** {f['check']}: {detail}")
        if f.get("missed"):
            lines.append("  - missed (UTC): " + ", ".join(fmt(t) for t in f["missed"]))
    fresh = [f for f in res["findings"] if f["check"].startswith("freshness")]
    lines += ["", "## Data freshness", "", "| Ledger | Newest | Age (days) | Limit |", "|---|---|---|---|"]
    lines += [f"| {f['check'].split(':')[1]} | {f['newest']} | {f['age_days']} | {f['limit_days']} |" for f in fresh]
    return "\n".join(lines) + "\n"
