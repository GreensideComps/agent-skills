"""The demo scoreboard and the go-live checks it computes (GO_LIVE_RULE.md, with Amendment 2)."""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "always_on"))

import scoreboard as sb  # noqa: E402
import stats  # noqa: E402

DAY = 86400.0
T0 = 1790000000.0  # Sept 2026


def trade(i, entry_t, excess, tag="gap_go"):
    return {"strategy": tag, "ticker": f"T{i}", "status": "closed", "entry_t": entry_t, "exit_t": entry_t + 5 * DAY,
            "excess": excess, "net_ret": excess + 0.01, "vwrp_ret": 0.01, "cost": 100.0, "pnl_gbp": 100 * (excess + 0.01),
            "exit_reason": "time"}


def row(summary, tag="gap_go"):
    return next(s for s in summary if s["strategy"] == tag)


def test_thirty_good_trades_spread_over_many_weeks_pass_every_check():
    r = random.Random(5)
    trades = [trade(i, T0 + i * 4 * DAY, 0.04 + r.gauss(0, 0.03)) for i in range(30)]
    s = row(sb.summarise(trades, T0 + 130 * DAY)[0])
    assert s["closed"] == 30 and s["entry_weeks"] >= 15
    assert s["t_stat"] >= s["t_needed"] and s["t_cluster"] >= s["t_cluster_needed"]
    assert s["go_live_eligible"] and all(s["go_live_checks"].values())
    assert s["t_needed"] == pytest.approx(stats.t_crit(29, 0.05 / len(sb.REGISTERED)))


def test_thirty_trades_opened_in_two_weeks_are_two_bets_not_thirty():
    """The error the audit found: a burst of trades that all rode one market move passed the plain t-test."""
    r = random.Random(5)
    trades = [trade(i, T0 + (0 if i < 15 else 7 * DAY) + (i % 15) * 3600, (0.05 if i < 15 else 0.03) + r.gauss(0, 0.004))
              for i in range(30)]
    s = row(sb.summarise(trades, T0 + 130 * DAY)[0])
    assert s["t_stat"] > s["t_needed"] * 3            # the plain test is fooled: a huge t
    assert s["entry_weeks"] == 2 and s["t_cluster_needed"] is None
    assert not s["go_live_checks"]["t>=crit"] and not s["go_live_eligible"]
    others = {k: v for k, v in s["go_live_checks"].items() if k != "t>=crit"}
    assert all(others.values())                       # only the corrected check stops it


def test_kill_rule_and_the_count_of_strategies_are_unchanged():
    trades = [trade(i, T0 + i * 4 * DAY, -0.01) for i in range(30)]
    summary, k = sb.summarise(trades, T0 + 130 * DAY)
    assert k == len(sb.REGISTERED) == 15
    assert row(summary)["kill_rule"].startswith("KILL") and not row(summary)["go_live_eligible"]
    # a tag the list does not know still counts towards the multiple-testing adjustment
    assert sb.summarise([{**t, "strategy": "new_idea"} for t in trades], T0 + 130 * DAY)[1] == 16


def _state(tmp_path):
    st = tmp_path / "state"
    (st / "intents").mkdir(parents=True)
    (st / "events").mkdir()
    def fill(i, tk, qty, net, when, sig):
        return [{"id": i, "status": "intended", "signal": sig},
                {"id": i, "status": "filled", "broker": {"order": {"ticker": tk},
                 "fill": {"filledAt": when, "quantity": qty, "walletImpact": {"netValue": net, "taxes": [{"quantity": -0.15}]}}}}]
    recs = fill("a", "X_US_EQ", 2.0, 100.0, "2026-11-02T15:00:00Z", {"type": "active_entry", "strategy": "gap_go", "vwrp_px": 100.0})
    recs += fill("b", "X_US_EQ", -2.0, 106.0, "2026-11-04T15:00:00Z", {"type": "active_exit", "strategy": "gap_go", "exit_reason": "take_profit"})
    recs += fill("c", "Y_US_EQ", 1.0, 50.0, "2026-11-04T16:00:00Z", {"type": "active_entry", "strategy": "stock_screen", "vwrp_px": 102.0})
    (st / "intents" / "intents.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    snaps = [{"kind": "snapshot", "t": sb.parse_ts("2026-11-04T15:00:00Z"), "rows": [{"ticker": sb.VWRP, "qty": 10, "value_gbp": 1020.0}]},
             {"kind": "snapshot", "t": sb.parse_ts("2026-11-05T15:00:00Z"), "rows": [{"ticker": sb.VWRP, "qty": 10, "value_gbp": 1030.0},
                                                                                     {"ticker": "Y_US_EQ", "qty": 1.0, "value_gbp": 55.0}]}]
    (st / "events" / "2026-11-04.jsonl").write_text("".join(json.dumps(s) + "\n" for s in snaps))
    return st


def test_trades_are_built_from_the_journal_net_of_costs_against_vwrp_over_the_same_days(tmp_path):
    st = _state(tmp_path)
    intents, fills, snaps = sb.load(str(st))
    trades, now = sb.build_trades(intents, fills, snaps, sb.vwrp_series(snaps))
    x, y = trades
    assert x["status"] == "closed" and x["net_ret"] == pytest.approx(0.06) and x["vwrp_ret"] == pytest.approx(0.02)
    assert x["excess"] == pytest.approx(0.04) and x["exit_reason"] == "take_profit"
    assert y["status"] == "open" and y["net_ret"] == pytest.approx(55.0 * (1 - sb.EXIT_FX_FEE) / 50.0 - 1)
    assert y["vwrp_ret"] == pytest.approx(103.0 / 102.0 - 1)


def test_the_script_runs_isolated_with_no_environment_and_writes_both_files(tmp_path):
    st, out = _state(tmp_path), tmp_path / "out"
    out.mkdir()
    r = subprocess.run([sys.executable, "-I", str(ROOT / "research" / "always_on" / "scoreboard.py"), "--state", str(st),
                        "--out", str(out)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "2 trades, 15 strategies, eligible: none" in r.stdout
    d = json.loads((out / "SCOREBOARD.json").read_text())
    assert {s["strategy"] for s in d["strategies"]} >= set(sb.REGISTERED)
    assert "counting trades opened in the same week as one bet" in (out / "SCOREBOARD.md").read_text()


def test_the_agent_config_points_at_this_script():
    cfg = json.loads((ROOT / "agent" / "market_agent" / "config.json").read_text())
    assert (ROOT / cfg["scoreboard"]["path"]).resolve() == (ROOT / "research" / "always_on" / "scoreboard.py").resolve()
    assert cfg["scoreboard"]["out"] == "state"
