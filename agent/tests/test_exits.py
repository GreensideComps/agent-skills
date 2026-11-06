from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import exits  # noqa: E402

from test_agent import make  # noqa: E402


def facts(rows):
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": e, "filed": f, "val": v, "form": "10-Q"} for e, f, v in rows]}}}}}


def test_profit_lock_arms_at_25pct_and_sells_at_half_the_best_gain():
    assert not exits.profit_lock(0.10, 0.20)          # never armed
    assert not exits.profit_lock(0.20, 0.30)          # armed, still above 15%
    assert exits.profit_lock(0.15, 0.30)              # gave back half
    assert exits.profit_lock(-0.05, 0.40)


def test_shares_thesis_breaks_on_a_rising_count_filed_after_entry():
    f = facts([("2025-09-30", "2025-10-30", 100e6), ("2026-09-30", "2026-11-05", 102e6)])
    assert exits.shares_thesis(f, "2026-11-01")["broken"] is True
    f = facts([("2025-09-30", "2025-10-30", 100e6), ("2026-09-30", "2026-11-05", 97e6)])
    assert exits.shares_thesis(f, "2026-11-01")["broken"] is False


def test_shares_thesis_is_unverified_without_a_new_filing_or_a_year_ago_count():
    f = facts([("2025-09-30", "2025-10-30", 100e6), ("2026-06-30", "2026-08-01", 120e6)])
    assert exits.shares_thesis(f, "2026-11-06")["broken"] is None    # nothing filed since entry
    f = facts([("2026-09-30", "2026-11-10", 120e6)])
    assert exits.shares_thesis(f, "2026-11-06")["broken"] is None    # no year-ago count
    assert exits.shares_thesis({}, "2026-11-06")["broken"] is None


def test_plan_names_why_held_and_what_sells():
    e = {"id": "x", "ticker": "DXC_US_EQ", "t": 0, "ts": "2026-11-06T14:34:00Z",
         "signal": {"strategy": "buyback_value", "stop": None, "take_profit": None, "time_stop_s": 182 * 86400}}
    r = exits.plan(e, 0.30, 0.32, 0, "held 6 months", None, "buyback intact", None, {"arm": 0.25, "keep": 0.5})
    assert r["verdict"] == "hold" and "held 6 months" in r["held_because"]
    assert any("time exit" in x for x in r["sells_if"]) and any("armed" in x for x in r["sells_if"])
    assert exits.plan(e, 0.1, 0.32, 0, None, "profit_lock")["verdict"] == "sell: profit_lock"


def test_agent_exit_rules_sell_on_profit_lock_thesis_and_hard_event_only_where_configured(tmp_path):
    ag, b, st, clock = make(tmp_path)
    ag.cfg["active"]["enabled"] = True
    xc = ag.cfg["active"]["exit_review"]
    xc.update(enabled=True, hard_events_for=["buyback_value", "gap_rebound"])
    xc["thesis"]["enabled"] = xc["profit_lock"]["enabled"] = True  # both OFF in config after Q221; mechanics tested
    px = {"DXC_US_EQ": 11.0, "SPB_US_EQ": 50.0, "TTD_US_EQ": 13.0}
    ag._quote = lambda tk: {"price": px[tk]} if tk in px else None
    st._replace("exit_review.json", {
        "peak": {"DXC_US_EQ": {"entry_id": "a", "entry_px": 10.0, "peak": 0.30},
                 "SPB_US_EQ": {"entry_id": "b", "entry_px": 40.0, "peak": 0.40}},
        "thesis": {"TTD_US_EQ": {"broken": True, "why": "thesis broken"}}})
    assert ag._exit_rules_why("DXC_US_EQ", "buyback_value") == "profit_lock"   # +10% after a +30% best
    assert ag._exit_rules_why("SPB_US_EQ", "stock_screen") is None             # screener: no profit lock
    assert ag._exit_rules_why("TTD_US_EQ", "buyback_value") == "thesis_broken"
    st._replace("stock_screen.json", {"exit": {"OPY_US_EQ": {"why": "sec_delisting"}}})
    assert ag._exit_rules_why("OPY_US_EQ", "gap_rebound") == "sec_delisting"
    ag.cfg["active"]["exit_review"]["profit_lock"]["enabled"] = False
    assert ag._exit_rules_why("DXC_US_EQ", "buyback_value") is None
