"""O10 (2026-10-19): the stale 100% LQQ3 strategy is retired. Runs stay read-only and plan no orders."""
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import INSTRUMENTS, NOW, FakeQuotes, FakeT212, exchanges_for
from t212bot import monitor
from t212bot.config import CONFIG_PATH, SafetyError, StrategyConfig, load_strategy
from t212bot.decide import decide
from t212bot.executor import Bot
from test_monitor import RO, Quotes, loader

REPO = Path(__file__).resolve().parents[2]


def retired(cfg):
    return replace(cfg, name="retired", mode="retired", targets={}, signal=None)


def test_the_committed_strategy_is_retired_and_the_old_one_is_archived():
    cfg = load_strategy()
    assert cfg.mode == "retired" and cfg.targets == {} and cfg.signal is None
    assert "O10" in cfg.retired["owner_decision"]
    old = json.loads((CONFIG_PATH.parent / "archive" / "strategy_discretionary_intraday_v1_2026-10-19.json").read_text())
    assert old["name"] == "discretionary_intraday_v1" and old["targets"] == {"LQQ3l_EQ": 1.0}


def test_a_retired_config_cannot_carry_targets_or_a_signal(cfg):
    with pytest.raises(SafetyError):
        replace(cfg, mode="retired", targets={"LQQ3l_EQ": 1.0})


def test_retired_run_snapshots_and_halts_without_any_order(make_client, cfg, journal, tmp_path):
    fake = FakeT212()
    bot = Bot(make_client(fake), retired(cfg), journal, quotes=FakeQuotes(), now=lambda: NOW, sleep=lambda s: None,
              instruments=INSTRUMENTS, exchanges=exchanges_for(NOW), env={}, kill_file=tmp_path / "KILL")
    for force in (False, True):
        res = bot.run(execute=True, force=force)
        assert res == {"status": "halted", "reason": "strategy retired"}
    assert fake.posts == []
    assert journal.events("run_halted")[-1]["reason"].startswith("strategy retired")


def test_decide_refuses_under_a_retired_strategy(make_client, cfg, journal, tmp_path):
    bot = Bot(make_client(FakeT212()), retired(cfg), journal, quotes=FakeQuotes(), now=lambda: NOW,
              sleep=lambda s: None, instruments=INSTRUMENTS, exchanges=exchanges_for(NOW), env={},
              kill_file=tmp_path / "KILL")
    with pytest.raises(SafetyError, match="not 'discretionary'"):
        decide(bot, retired(cfg), journal, {"LQQ3l_EQ": 1.0}, "test", True, NOW, path=tmp_path / "d.json")


def test_monitor_reports_retired_and_raises_no_drift_alerts(cfg, journal, tmp_path):
    c = replace(retired(cfg), yahoo_symbols={"LQQ3l_EQ": "LQQ3.L"})
    journal.event("run_start", run_id="r1")
    res = monitor.check(c, journal, RO(lqq3=490.0), Quotes(), loader(), NOW, tmp_path / "KILL")
    assert res["exit"] == 0
    assert not any("vs target" in a["msg"] for a in res["alerts"])
    assert any("strategy retired" in a["msg"] for a in res["alerts"])


def test_no_code_writes_the_strategy_file():
    """Only a reviewed commit changes strategy.json: no module or script in the repository writes it."""
    pat = re.compile(r"strategy\.json|CONFIG_PATH")
    offenders = []
    for p in list(REPO.glob("**/*.py")) + list(REPO.glob("**/*.sh")):
        if "/tests/" in str(p) or "/archive/" in str(p):
            continue
        for line in p.read_text(errors="ignore").splitlines():
            if pat.search(line) and re.search(r"write_text|open\([^)]*['\"]w|json\.dump\(|>\s*\S*strategy\.json", line):
                offenders.append(f"{p.relative_to(REPO)}: {line.strip()}")
    assert offenders == []


def test_the_legacy_research_loop_is_retired():
    loop = (REPO / "research" / "LOOP.md").read_text()
    assert loop.startswith("# RETIRED")
    assert (REPO / "research" / "STOP").exists()
    assert (REPO / "research" / "archive" / "LOOP_retired_2026-10-19.md").exists()


# ---- review hardening (owner review of O10, 2026-10-19) ----
import hashlib
import os
import stat
import subprocess

ORIGINAL_STRATEGY_SHA256 = "a08ad34df6de53ec22d2083e480cd8886986cac6a3f3f57e49a26c37ab68ba02"  # master 90e9b3b
ORIGINAL_LOOP_SHA256 = "5af357f2e10d6edd2fe1d57b9ae78d16740ba5d9960a7dbecad6e1a1dbd747df"  # master 90e9b3b


def _bot(make_client, cfg, journal, tmp_path, fake):
    return Bot(make_client(fake), retired(cfg), journal, quotes=FakeQuotes(), now=lambda: NOW, sleep=lambda s: None,
               instruments=INSTRUMENTS, exchanges=exchanges_for(NOW), env={}, kill_file=tmp_path / "KILL")


def test_archives_are_byte_identical_to_the_retired_originals():
    """The audit trail keeps the exact bytes master held before O10, not a re-serialisation."""
    arch = CONFIG_PATH.parent / "archive" / "strategy_discretionary_intraday_v1_2026-10-19.json"
    assert hashlib.sha256(arch.read_bytes()).hexdigest() == ORIGINAL_STRATEGY_SHA256
    loop = REPO / "research" / "archive" / "LOOP_retired_2026-10-19.md"
    assert hashlib.sha256(loop.read_bytes()).hexdigest() == ORIGINAL_LOOP_SHA256


def test_retired_run_keeps_the_read_only_snapshot_and_reconciliation(make_client, cfg, journal, tmp_path):
    """Every run path (status, run, run --execute, --force) snapshots and reconciles, then halts with no order."""
    fake = FakeT212()
    bot = _bot(make_client, cfg, journal, tmp_path, fake)
    calls = []
    real = bot.reconcile
    bot.reconcile = lambda: calls.append(1) or real()
    for execute, force in ((False, False), (True, False), (True, True)):
        assert bot.run(execute=execute, force=force) == {"status": "halted", "reason": "strategy retired"}
    assert len(journal.snapshots()) == 3 and len(calls) == 3
    assert fake.posts == []
    # halts before order planning: the pending-orders list (planning's first broker read) is never fetched
    assert not any(c.split("?")[0].rstrip("/").endswith("/equity/orders") for c in fake.get_calls), fake.get_calls


def test_order_submission_itself_refuses_under_a_retired_strategy(make_client, cfg, journal, tmp_path):
    """Defence in depth: even a caller that skips run() cannot send an order while the strategy is retired."""
    fake = FakeT212()
    bot = _bot(make_client, cfg, journal, tmp_path, fake)
    ref = {"price_gbp": 100.0, "currency": "GBP"}
    with pytest.raises(SafetyError, match="retired"):
        bot._place("VWRPl_EQ", 1.0, ref, "test", {})
    with pytest.raises(SafetyError, match="retired"):
        bot._retry_buy_with_fresh_cash("VWRPl_EQ", 1.0, 2, ref, "test", None, {})
    assert fake.posts == []


def test_report_and_daily_risk_have_no_live_strategy_shadow_when_retired(tmp_path, cfg):
    from t212bot import intel, report
    from t212bot.journal import Journal
    from test_shadow_report import book
    j = Journal(root=tmp_path)
    j.save_state({"inception": {"total_value_gbp": 100.0}})
    j.event("order_placed", ticker="VWRPl_EQ", quantity=0.3, order_id=1, reference={"price": 146.4})
    j.snapshot({"totalValue": 100.0, "cash": {"availableToTrade": 1.5}, "investments": {}}, [])
    c = replace(retired(cfg), shadow_portfolios={"A_benchmark_vwrp": {"type": "static", "targets": {"VWRPl_EQ": 1.0}}},
                yahoo_symbols={"VWRPl_EQ": "VWRP.L"})
    data = report.build(j, c, book=book())
    assert "A_benchmark_vwrp" in data["shadows"] and "B_live_rules_at_close" not in data["shadows"]
    out = intel.market_bundle(j, c, book=book())
    assert "market_error" not in out and "retired" in out["risk"]["note"]


def _fake_git(tmp_path, root):
    log = tmp_path / "git.log"
    g = tmp_path / "bin" / "git"
    g.parent.mkdir()
    g.write_text(f'#!/bin/sh\necho "$@" >> {log}\n[ "$1" = rev-parse ] && echo {root}\nexit 0\n')
    g.chmod(g.stat().st_mode | stat.S_IEXEC)
    return g.parent, log


@pytest.mark.parametrize("unreadable", [False, True])
def test_ops_run_refuses_before_any_sync_or_trade_when_retired(tmp_path, unreadable):
    """ops_run.sh would otherwise check out the bot branch (not retired) and run `t212bot run --execute` there.
    It must stop before fetch/checkout. An unreadable strategy file also stops it (fail closed)."""
    # The script runs against a scratch root holding only strategy.json (no bot code), with git faked and broker
    # credentials removed, so even a regressed guard could not reach the broker or the real journal.
    root = tmp_path / "repo"
    (root / "trading" / "config").mkdir(parents=True)
    if not unreadable:
        (root / "trading" / "config" / "strategy.json").write_bytes(CONFIG_PATH.read_bytes())
    bindir, log = _fake_git(tmp_path, root)
    env = {k: v for k, v in os.environ.items() if not k.startswith("T212")}
    env["PATH"] = f"{bindir}:{os.environ['PATH']}"
    r = subprocess.run(["bash", str(REPO / "trading" / "ops_run.sh")], env=env, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "no sync, no trading run" in r.stdout
    assert log.read_text().split("\n")[0].startswith("rev-parse") and "fetch" not in log.read_text()
