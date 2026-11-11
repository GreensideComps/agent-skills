"""The plain-English rules page: complete, honest about every exit, and never out of date."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import (active, buyback_value, gap_rebound, invariants, merger, news_shock, rules, social,  # noqa: E402
                          stock_screen, swing, value_timing)
from market_agent.agent import load_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "agent" / "RULES.md"


def test_the_saved_page_matches_the_live_config():
    assert PAGE.read_text() == rules.render(load_config()), \
        "docs/agent/RULES.md is out of date: run python3 -m market_agent rules --write docs/agent/RULES.md"


def test_every_strategy_the_agent_can_trade_is_described():
    cfg = load_config()
    code = {buyback_value.NAME, gap_rebound.NAME, merger.NAME, news_shock.NAME, social.NAME, stock_screen.NAME,
            swing.SQUEEZE, swing.GAP, *value_timing.NAMES, *cfg["active"]["strategies"]}
    assert {r["name"] for r in rules.strategies(cfg)} == code


def test_every_strategy_states_how_it_buys_and_at_least_one_exit_besides_the_kill_rule():
    for r in rules.strategies(load_config()):
        assert [b for b in r["buys"] if b], r["name"]
        real = [s for s in r["sells"] if not s.startswith("kill rule")]
        assert real, f"{r['name']} has no rule that would ever sell a trade"
        assert any(s.startswith("kill rule") for s in r["sells"]), r["name"]


def test_strategies_without_their_own_stop_state_the_safety_net_and_the_self_check_agrees():
    cfg = load_config()
    d = cfg["active"]["disaster_stop"]
    by = {r["name"]: r for r in rules.strategies(cfg)}
    for key in d["strategies"]:
        name = next(n for n in by if n.startswith(key))
        assert any("safety-net stop" in s for s in by[name]["sells"]), name
        level, is_disaster = active.stop_level({"strategy": name, "stop": None, "entry_px": 100.0}, d)
        assert is_disaster and level == d["pct"]
    # a strategy with neither a stop, a time limit nor a rule exit would be flagged by the self-check
    assert set(invariants.RULE_EXIT) <= set(by)


def test_the_page_follows_the_config_and_shows_what_is_switched_off():
    cfg = load_config()
    cfg["active"]["stock_screen"]["swap_on_dropout"] = True
    assert "replaced early" in rules.render(cfg)
    cfg["active"]["stock_screen"]["swap_on_dropout"] = False
    text = rules.render(cfg, {"gap_go": {"why": "trails VWRP after 30 trades"}})
    assert "NOT sold early" in text and "switched off by the system (trails VWRP after 30 trades)" in text
    cfg["active"]["disaster_stop"]["pct"] = 0.2
    assert "20% below the buy price" in rules.render(cfg)


def test_config_prose_does_not_contradict_the_switches():
    ss = load_config()["active"]["stock_screen"]
    if ss.get("swap_on_dropout") is False:
        assert "except an extra swap" not in ss["rebalance"]
