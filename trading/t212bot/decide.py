"""Discretionary decisions (owner override 2026-10-14): set target holdings, then run the normal executor.

`python -m t212bot decide --set LQQ3l_EQ=1.0 --reason "..." [--execute]`
`python -m t212bot decide --cash --reason "..." [--execute]`

Orders still go only through Bot.run, so every existing safety check applies (demo lock, KILL, pending
orders, market hours, fresh and consistent quotes, cash cap, ambiguous-order handling, max orders per run).
Extra limits from strategy.json `decision_limits`, enforced here rather than left to judgement:
  max_decisions_per_day   executed decisions per London calendar day
  daily_loss_stop         once the account is this far below the day's first value, only all-cash is allowed
  universe                the only tickers that may be held
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DISCRETIONARY_PATH, SafetyError, StrategyConfig, validate_targets

LONDON = ZoneInfo("Europe/London")


def parse_targets(items: list[str]) -> dict[str, float]:
    out = {}
    for it in items:
        k, _, v = it.partition("=")
        if not k or not v:
            raise SafetyError(f"bad target {it!r}; use TICKER=weight")
        out[k.strip()] = float(v)
    return out


def _london_day(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone(LONDON).date().isoformat()


def check_limits(cfg: StrategyConfig, journal, targets: dict, value_now: float, now: datetime) -> dict:
    lim = cfg.decision_limits
    today = now.astimezone(LONDON).date().isoformat()
    done = [e for e in journal.events("decision") if e.get("execute") and _london_day(e["ts_utc"]) == today]
    maxd = int(lim.get("max_decisions_per_day", 8))
    if len(done) >= maxd:
        raise SafetyError(f"decision limit reached: {len(done)} executed today (max {maxd})")
    day_vals = [float(s["total_value_gbp"]) for s in journal.snapshots() if _london_day(s["ts_utc"]) == today]
    day_start = day_vals[0] if day_vals else value_now
    day_ret = value_now / day_start - 1 if day_start > 0 else 0.0
    stop = float(lim.get("daily_loss_stop", 0.10))
    if day_ret <= -stop and targets:
        raise SafetyError(f"daily loss stop: account {day_ret:.1%} today (limit -{stop:.0%}); only --cash is allowed until tomorrow")
    return {"decisions_today": len(done), "day_start_gbp": day_start, "day_return": day_ret}


def decide(bot, cfg: StrategyConfig, journal, targets: dict, reason: str, execute: bool, now: datetime,
           path: Path = DISCRETIONARY_PATH, scratch: Path | None = None) -> dict:
    if cfg.mode != "discretionary":
        raise SafetyError("strategy.json mode is not 'discretionary'")
    if not reason.strip():
        raise SafetyError("a decision needs a reason")
    targets = validate_targets(targets, cfg)
    value = float(bot.c.account_summary()["totalValue"])
    lim = check_limits(cfg, journal, targets, value, now)
    rec = {"targets": targets, "reason": reason.strip(), "set_utc": now.isoformat(timespec="seconds")}
    journal.event("decision", execute=execute, **rec, **lim)
    target_file = path if execute else (scratch or path.with_suffix(".dryrun.json"))
    target_file.write_text(json.dumps(rec, indent=1) + "\n")
    bot._disc_path = target_file
    try:
        return bot.run(execute=execute, force=True)
    finally:
        if not execute:
            target_file.unlink(missing_ok=True)
