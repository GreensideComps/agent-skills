"""Milestone 7: reliability checks - cron expansion, missed runs from evidence, stuck jobs, freshness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from equity import reliability
from equity.jobs import job

UTC = timezone.utc


def _cfg(*exps):
    return {"expectations": list(exps), "lookback_days": 2, "stuck_after_hours": 3, "ledger_size_warn_mb": 60,
            "freshness_days": {"prices": 4, "screen": 4, "paper_nav": 4, "fundamentals_check": 10}}


MONITOR = {"name": "monitor", "cron": "57 7-9 * * 1-5", "tz": "Europe/London", "active_from": "2026-10-01T00:00:00Z",
           "grace_minutes": 45, "evidence": {"type": "commit", "branch": "bot", "prefix": "monitor:"}}


def test_cron_is_read_in_its_timezone_across_dst():
    # 08:20 London is 07:20 UTC in summer time and 08:20 UTC after the clocks go back (25 Oct 2026).
    ts = reliability.cron_times("20 8 * * 1-5", "Europe/London",
                                datetime(2026, 10, 23, tzinfo=UTC), datetime(2026, 10, 27, 23, tzinfo=UTC))
    assert [t.isoformat() for t in ts] == ["2026-10-23T07:20:00+00:00", "2026-10-26T08:20:00+00:00",
                                           "2026-10-27T08:20:00+00:00"]   # weekend skipped


def test_cron_fields_lists_ranges_steps_and_sunday_as_7():
    ts = reliability.cron_times("0,30 */12 * * 7", "UTC", datetime(2026, 10, 18, tzinfo=UTC),
                                datetime(2026, 10, 18, 23, 59, tzinfo=UTC))
    assert [t.strftime("%H:%M") for t in ts] == ["00:00", "00:30", "12:00", "12:30"]


def test_missed_runs_come_from_missing_evidence_not_the_schedule(store):
    now = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)   # Wednesday; fires at 06:57, 07:57, 08:57 UTC
    commits = [(datetime(2026, 10, 14, 6, 58, tzinfo=UTC), "monitor: ok"),
               (datetime(2026, 10, 14, 8, 30, tzinfo=UTC), "research: unrelated"),  # wrong prefix
               (datetime(2026, 10, 14, 9, 0, tzinfo=UTC), "monitor: late but in grace")]
    cfg = _cfg({**MONITOR, "active_from": "2026-10-14T00:00:00Z"})
    res = reliability.run(store, now, cfg, commits_for=lambda b, since: commits)
    s = res["schedules"][0]
    assert (s["expected"], s["seen"]) == (3, 2) and s["missed"] == ["2026-10-14T07:57:00+00:00"]
    assert res["status"] == "critical"   # empty store: prices and screen are missing too
    assert any(f["check"] == "schedule:monitor" and f["severity"] == "warn" for f in res["findings"])


def test_runs_before_active_from_and_inside_grace_are_not_missed(store):
    now = datetime(2026, 10, 14, 9, 20, tzinfo=UTC)   # the 08:57 run is still inside its 45 min grace
    cfg = _cfg({**MONITOR, "active_from": "2026-10-14T07:30:00Z"})
    res = reliability.run(store, now, cfg, commits_for=lambda b, since: [(datetime(2026, 10, 14, 7, 58, tzinfo=UTC),
                                                                         "monitor: x")])
    s = res["schedules"][0]
    assert (s["expected"], s["seen"], s["state"]) == (1, 1, "ok")
    assert s["next_expected"] == "2026-10-15T06:57:00+00:00"


def test_unscheduled_job_is_info_and_job_evidence_uses_the_ledger(store):
    exp = {"name": "screen", "cron": "30 22 * * 1-5", "tz": "Europe/London", "active_from": None,
           "grace_minutes": 180, "evidence": {"type": "job", "job": "screen"}}
    res = reliability.run(store, datetime(2026, 10, 14, 23, tzinfo=UTC), _cfg(exp), commits_for=None)
    assert res["schedules"][0]["state"] == "not_scheduled"
    with job(store, "screen", {}):
        pass
    now = datetime.now(UTC)
    exp2 = {**exp, "cron": f"{(now - timedelta(minutes=5)).minute} * * * *", "tz": "UTC",
            "active_from": (now - timedelta(hours=1)).isoformat(), "grace_minutes": 30}
    res = reliability.run(store, now + timedelta(minutes=40), _cfg(exp2), commits_for=None)
    assert res["schedules"][0]["seen"] >= 1


def test_failed_latest_job_and_stuck_job_are_critical(store):
    with pytest.raises(RuntimeError):
        with job(store, "paper_portfolio", {}):
            raise RuntimeError("boom")
    store.jobs.append({"rid": "old:start", "event": "start", "run_id": "old", "job": "screen",
                       "idempotency_key": None, "inputs": {}, "ts_utc": "2026-10-01T00:00:00+00:00"})
    exp = {"name": "paper", "cron": "30 22 * * 1-5", "tz": "Europe/London", "active_from": "2026-10-01T00:00:00Z",
           "grace_minutes": 180, "evidence": {"type": "job", "job": "paper_portfolio"}}
    res = reliability.run(store, datetime.now(UTC), _cfg(exp), commits_for=None)
    checks = {f["check"]: f["severity"] for f in res["findings"]}
    assert checks["job:paper_portfolio"] == "critical" and checks["stuck:screen"] == "critical"
    assert res["exit_code"] == 2
    md = reliability.report(res)
    assert "Overall: **CRITICAL**" in md and "stuck:screen" in md


def test_freshness_flags_old_prices_and_screen(store):
    store.prices.append({"rid": "p1", "company_id": "SEC:1", "date": "2026-10-01", "close": 1.0})
    store.prices.append({"rid": "p2", "company_id": "BENCH:SPY", "date": "2026-10-14", "close": 1.0})  # ignored
    store.screens.append({"rid": "s1", "as_of": "2026-10-13", "results": []})
    fr = {f["check"]: f for f in reliability.freshness(store, datetime(2026, 10, 14).date(),
                                                       _cfg()["freshness_days"])}
    assert fr["freshness:prices"]["severity"] == "critical" and fr["freshness:prices"]["age_days"] == 13
    assert fr["freshness:screen"]["severity"] == "info"
    assert fr["freshness:paper_nav"]["severity"] == "warn"   # never marked


def test_evidence_source_failure_is_reported_not_raised(store):
    def boom(branch, since):
        raise RuntimeError("no such branch")
    res = reliability.run(store, datetime(2026, 10, 14, 12, tzinfo=UTC), _cfg(MONITOR), commits_for=boom)
    assert any("no evidence source" in f.get("detail", "") for f in res["findings"])


def test_shipped_schedule_config_parses():
    cfg = reliability.load_config()
    now = datetime(2026, 10, 14, 12, tzinfo=UTC)
    for exp in cfg["expectations"]:
        reliability.cron_times(exp["cron"], exp["tz"], now - timedelta(days=1), now)
        assert exp["evidence"]["type"] in ("commit", "job")
