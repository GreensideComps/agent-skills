"""Discretionary `decide`: limits enforced in code; orders still go through Bot.run with all checks."""
import json
from dataclasses import replace

import pytest

from conftest import INSTRUMENTS, NOW, FakeQuotes, FakeT212, exchanges_for
from t212bot import decide
from t212bot.config import SafetyError, StrategyConfig, validate_targets
from t212bot.executor import Bot

LIMITS = {"universe": ["VWRPl_EQ", "IWMOl_EQ"], "max_decisions_per_day": 2, "daily_loss_stop": 0.10}


@pytest.fixture
def dcfg(cfg):
    return replace(cfg, mode="discretionary", decision_limits=LIMITS)


@pytest.fixture
def bot(make_client, dcfg, journal, tmp_path):
    def _make(fake):
        return Bot(make_client(fake), dcfg, journal, quotes=FakeQuotes(), now=lambda: NOW, sleep=lambda s: None,
                   instruments=INSTRUMENTS, exchanges=exchanges_for(NOW), env={}, kill_file=tmp_path / "KILL")
    return _make


def test_validate_rejects_shorts_borrowing_and_outside_universe(dcfg):
    with pytest.raises(SafetyError, match="shorting"):
        validate_targets({"VWRPl_EQ": -0.5}, dcfg)
    with pytest.raises(SafetyError, match="no borrowing"):
        validate_targets({"VWRPl_EQ": 0.7, "IWMOl_EQ": 0.5}, dcfg)
    with pytest.raises(SafetyError, match="universe"):
        validate_targets({"SGLNl_EQ": 1.0}, dcfg)
    assert validate_targets({}, dcfg) == {}


def test_all_cash_target_is_a_valid_config(cfg):
    StrategyConfig(name="d", targets={}, yahoo_symbols=cfg.yahoo_symbols, mode="discretionary")
    with pytest.raises(SafetyError):
        StrategyConfig(name="s", targets={}, yahoo_symbols=cfg.yahoo_symbols)


def test_decide_executes_through_bot_and_journals_reason(bot, dcfg, journal, tmp_path):
    fake = FakeT212()
    path = tmp_path / "disc.json"
    res = decide.decide(bot(fake), dcfg, journal, {"VWRPl_EQ": 1.0}, "test buy", True, NOW, path=path)
    assert res["status"] == "executed" and {p["ticker"] for p in fake.posts} == {"VWRPl_EQ"}
    assert json.loads(path.read_text())["targets"] == {"VWRPl_EQ": 1.0}
    assert journal.events("decision")[-1]["reason"] == "test buy"


def test_dry_run_places_nothing_and_leaves_no_file(bot, dcfg, journal, tmp_path):
    fake = FakeT212()
    path = tmp_path / "disc.json"
    res = decide.decide(bot(fake), dcfg, journal, {"VWRPl_EQ": 1.0}, "look", False, NOW, path=path)
    assert res["status"] == "dry_run" and fake.posts == [] and not path.exists()
    assert not list(tmp_path.glob("*.dryrun.json"))


def test_kill_switch_still_stops_decisions(bot, dcfg, journal, tmp_path):
    (tmp_path / "KILL").write_text("")
    fake = FakeT212()
    res = decide.decide(bot(fake), dcfg, journal, {"VWRPl_EQ": 1.0}, "x", True, NOW, path=tmp_path / "d.json")
    assert res["status"] == "halted" and fake.posts == []


def test_daily_decision_limit(bot, dcfg, journal, tmp_path):
    for _ in range(2):
        journal.event("decision", execute=True, targets={}, reason="r")
    with pytest.raises(SafetyError, match="decision limit"):
        decide.decide(bot(FakeT212()), dcfg, journal, {}, "third", True, NOW, path=tmp_path / "d.json")


def test_daily_loss_stop_allows_only_cash(dcfg, journal):
    journal.snapshot({"totalValue": 100.0, "cash": {"availableToTrade": 1}, "investments": {}}, [])
    with pytest.raises(SafetyError, match="daily loss stop"):
        decide.check_limits(dcfg, journal, {"VWRPl_EQ": 1.0}, 89.0, NOW)
    assert decide.check_limits(dcfg, journal, {}, 89.0, NOW)["day_return"] == pytest.approx(-0.11)


def test_rules_mode_refuses_decide(bot, cfg, journal, tmp_path):
    with pytest.raises(SafetyError, match="not 'discretionary'"):
        decide.decide(bot(FakeT212()), cfg, journal, {}, "x", True, NOW, path=tmp_path / "d.json")
