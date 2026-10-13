"""Daily report orchestration: collect -> compute -> store -> (optionally) email.

Read-only towards Trading 212: only a ReadOnlyClient is created here.

Exit codes (for schedulers):
  0  report generated (and delivered, if --send)
  1  unexpected error
  2  report generated but CRITICAL data problems were found (still delivered if --send)
  3  email delivery failed or was not configured when --send was requested
  4  not due yet / already delivered today (with --respect-schedule)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import emailer, intel
from .client import T212Client
from .config import ROOT, load_credentials, load_strategy
from .journal import Journal
from .readonly import ReadOnlyClient

CONFIG = ROOT / "config"


def load_json(p: Path) -> dict:
    return json.loads(p.read_text())


def build_email(M: dict, md: str, html: str, ecfg: emailer.EmailConfig, rcfg: dict, kind: str = "daily") -> emailer.Email:
    A = M.get("account") or {}
    crit = any(a["level"] == "CRITICAL" for a in M["alerts"])
    warn = any(a["level"] == "WARN" for a in M["alerts"])
    status = "ACTION NEEDED" if crit else ("warnings" if warn else "OK")
    val = f"£{A['total_value']:.2f}" if A.get("total_value") is not None else "value unavailable"
    gain = M["performance"].get("investment_gain")
    gtxt = f", gain £{gain:+.2f}" if gain is not None else ""
    pre = rcfg.get("subject_prefix", "[T212 demo]")
    if M["meta"].get("example"):
        pre += " [EXAMPLE DATA]"
    if kind == "adviser":
        subject = f"{pre} Withdrawal adviser: {M['adviser']['headline'][:120]}"
    else:
        subject = f"{pre} Daily report {M['meta']['report_date']} - {val}{gtxt} - {status}"
    atts = [(f"daily-report-{M['meta']['report_date']}.md", md.encode(), "text/markdown")] if rcfg.get("attach_markdown") and kind == "daily" else []
    return emailer.Email(subject, md, html, ecfg.to or "", ecfg.sender or "", atts)


def run(send: bool = False, force: bool = False, respect_schedule: bool = False, now: datetime | None = None,
        ro=None, env: dict | None = None, reports_root: Path = intel.REPORTS, journal: Journal | None = None,
        market: dict | None = None, research: dict | None = None, http=None, sleep=None) -> dict:
    now = now or datetime.now(timezone.utc)
    rcfg = load_json(CONFIG / "reporting.json")
    acfg = load_json(CONFIG / "adviser.json")
    scfg = load_strategy()
    ecfg = emailer.load_config(env)
    is_due, local_date = emailer.due(now, rcfg["report_time_local"], rcfg["timezone"])
    rdate = local_date.isoformat()
    if respect_schedule:
        if not is_due:
            return {"exit": 4, "status": "not_due", "detail": f"local time before {rcfg['report_time_local']} {rcfg['timezone']}"}
        key = emailer.idempotency_key(rdate, "daily", ecfg.to)
        if not force and emailer.already_sent(key, reports_root):
            return {"exit": 4, "status": "already_sent", "detail": f"report for {rdate} already delivered"}

    journal = journal or Journal()
    if ro is None:
        try:
            ro = ReadOnlyClient(T212Client(load_credentials(env)))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"

            class _Dead:
                def __getattr__(self, n):
                    def f(*a, **k):
                        raise RuntimeError(f"credentials unavailable ({err})")
                    return f
            ro = _Dead()
    acct = intel.collect_account(ro, lambda: datetime.now(timezone.utc))
    if acct["summary"].ok and acct["positions"].ok:
        journal.snapshot(acct["summary"].data, acct["positions"].data)   # verified reading, kept for TWR
    research = research if research is not None else intel.research_bundle()
    market = market if market is not None else intel.market_bundle(journal, scfg)
    prev = intel.previous_metrics(rdate, reports_root)
    state = intel.load_state(reports_root)
    M, new_state = intel.compute(acct, journal.snapshots(), journal.events(), scfg.name, acfg, state, research, market, prev,
                                 emailer.last_delivery(reports_root), now, kill=intel.kill_status(),
                                 research_stop=intel.research_stopped())
    paths = intel.store(M, reports_root)
    intel.save_state(new_state, reports_root)
    crit = any(a["level"] == "CRITICAL" for a in M["alerts"])
    out = {"exit": 2 if crit else 0, "status": "generated", "paths": {k: str(v) for k, v in paths.items()},
           "alerts": M["alerts"], "adviser": M["adviser"]["headline"]}
    if send:
        md, html = paths["md"].read_text(), paths["html"].read_text()
        kw = {"root": reports_root, "force": force, "http": http}
        if sleep:
            kw["sleep"] = sleep
        res = emailer.deliver(build_email(M, md, html, ecfg, rcfg), ecfg, rdate, "daily", **kw)
        out["delivery"] = res.__dict__
        if res.status == "sent":
            ckw = {"root": reports_root, "http": http}
            if sleep:
                ckw["sleep"] = sleep
            conf = emailer.confirm_delivery(res, ecfg, rdate, "daily", **ckw)
            out["delivery_confirmation"] = conf
            if conf["status"] == "confirmed_failed":
                out["exit"] = 3
        if M["adviser"].get("notify"):
            r2 = emailer.deliver(build_email(M, md, html, ecfg, rcfg, kind="adviser"), ecfg,
                                 f"{rdate}:{M['adviser']['reason_code']}:{M['adviser']['amount_gbp']}", "adviser", **kw)
            out["adviser_delivery"] = r2.__dict__
            if r2.status in ("sent", "skipped_duplicate"):
                from types import SimpleNamespace
                from . import adviser as adv
                si = M["adviser"]["_state_inputs"]
                rec = SimpleNamespace(amount_gbp=M["adviser"]["amount_gbp"], reason_code=M["adviser"]["reason_code"])
                intel.save_state(adv.update_state(new_state, rec, si["gain"], si["drawdown"], si["net"], True, local_date), reports_root)
        M["delivery"] = out["delivery"]
        M["delivery_confirmation"] = out.get("delivery_confirmation")
        paths["json"].write_text(json.dumps(M, indent=1, default=str))   # record the outcome with the report
        if res.status not in ("sent", "skipped_duplicate"):
            out["exit"] = 3
    return out
