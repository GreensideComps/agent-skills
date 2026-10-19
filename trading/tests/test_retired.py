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
