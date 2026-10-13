"""Trend-signal strategies: signal maths, config validation and end-to-end switching."""
from datetime import date, timedelta

import pandas as pd
import pytest

from conftest import INSTRUMENTS, NOW, FakeQuotes, FakeT212, exchanges_for
from t212bot.config import SafetyError, StrategyConfig
from t212bot.executor import Bot
from t212bot.planner import plan_rebalance
from t212bot.signals import sma_state

TODAY = NOW.date()


def closes(last_value, n=150, end=TODAY - timedelta(days=1), base=100.0):
    idx = pd.bdate_range(end=end, periods=n)
    s = pd.Series(base, index=idx, dtype=float)
    s.iloc[-1] = last_value
    return s


def sig_cfg(off=None):
    return StrategyConfig(
        name="trend-test", targets={"SGLNl_EQ": 1.0},
        yahoo_symbols={"VWRPl_EQ": "VWRP.L", "IWMOl_EQ": "IWMO.L", "SGLNl_EQ": "SGLN.L"},
        signal={"type": "sma_trend", "symbol": "QQQ", "window": 100,
                "on_targets": {"SGLNl_EQ": 1.0}, "off_targets": off or {}})


# ---------------------------------------------------------------- signal maths

def test_sma_on_and_off():
    assert sma_state(closes(120), 100, TODAY)["on"] is True
    assert sma_state(closes(80), 100, TODAY)["on"] is False


def test_todays_unfinished_bar_is_ignored():
    s = closes(80)                                   # yesterday: below trend
    s[pd.Timestamp(TODAY)] = 500.0                    # a live intraday print today must not flip it
    st = sma_state(s, 100, TODAY)
    assert st["on"] is False and st["as_of"] == (TODAY - timedelta(days=1)).isoformat()


def test_stale_or_short_data_refuses():
    with pytest.raises(SafetyError, match="old"):
        sma_state(closes(120, end=TODAY - timedelta(days=10)), 100, TODAY)
    with pytest.raises(SafetyError, match="need 100"):
        sma_state(closes(120, n=50), 100, TODAY)


# ---------------------------------------------------------------- config

def test_signal_config_allows_all_cash_but_static_does_not():
    assert sig_cfg().signal["off_targets"] == {}
    with pytest.raises(SafetyError):
        StrategyConfig(name="x", targets={}, yahoo_symbols={})
    with pytest.raises(SafetyError, match="unsupported"):
        StrategyConfig(name="x", targets={"SGLNl_EQ": 1.0}, yahoo_symbols={"SGLNl_EQ": "SGLN.L"},
                       signal={"type": "rsi", "symbol": "QQQ", "window": 100, "on_targets": {"SGLNl_EQ": 1.0}})
    with pytest.raises(SafetyError, match="shorting"):
        sig_cfg(off={"SGLNl_EQ": 0.5, "VWRPl_EQ": -0.2})


def test_planner_all_cash_target_with_only_cash_does_nothing():
    import dataclasses
    cfg = dataclasses.replace(sig_cfg(), targets={})
    plan = plan_rebalance(500.0, {}, {}, {}, cfg, date(2026, 10, 14))
    assert plan.needs_rebalance is False and plan.orders == []


# ---------------------------------------------------------------- end to end

@pytest.fixture
def make_sig_bot(make_client, journal, tmp_path):
    def _make(fake, loader, cfg=None):
        return Bot(make_client(fake), cfg or sig_cfg(), journal, quotes=FakeQuotes(), now=lambda: NOW,
                   sleep=lambda s: None, instruments=INSTRUMENTS, exchanges=exchanges_for(NOW),
                   env={}, kill_file=tmp_path / "KILL", daily_loader=loader)
    return _make


def loader_for(last):
    return lambda sym: pd.DataFrame({"adjclose": closes(last)})


def test_signal_on_buys_target(make_sig_bot, journal):
    fake = FakeT212()
    res = make_sig_bot(fake, loader_for(120)).run(execute=True)
    assert res["status"] == "executed"
    assert {p["ticker"] for p in fake.posts} == {"SGLNl_EQ"} and all(p["quantity"] > 0 for p in fake.posts)
    ev = journal.events("signal")[-1]
    assert ev["on"] is True and ev["targets"] == {"SGLNl_EQ": 1.0}


def test_signal_off_sells_everything_and_buys_nothing(make_sig_bot, journal):
    fake = FakeT212(cash=1.0, positions={"SGLNl_EQ": 5.0})
    res = make_sig_bot(fake, loader_for(80)).run(execute=True)
    assert res["status"] == "executed"
    assert fake.posts and all(p["quantity"] < 0 for p in fake.posts)
    assert fake.pos.get("SGLNl_EQ", 0) == 0
    # next day, still off and all cash: nothing to do
    n = len(fake.posts)
    assert make_sig_bot(fake, loader_for(80)).run(execute=True)["status"] == "no_action" and len(fake.posts) == n


def test_broken_signal_feed_never_trades(make_sig_bot, journal):
    def boom(sym):
        raise OSError("yahoo down")
    fake = FakeT212()
    with pytest.raises(SafetyError, match="signal unavailable"):
        make_sig_bot(fake, boom).run(execute=True)
    assert fake.posts == []
    assert journal.snapshots()                     # the account was still recorded
    assert journal.events("run_failed")[-1]["reason"].startswith("signal:")


def test_signal_flip_is_journalled(make_sig_bot, journal):
    fake = FakeT212()
    make_sig_bot(fake, loader_for(120)).run(execute=False)
    make_sig_bot(fake, loader_for(80)).run(execute=False)
    evs = journal.events("signal")
    assert [e["changed"] for e in evs] == [False, True]
