from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import buyback_value as b

BC = {"entry_weight": 0.02, "max_open": 3, "max_per_sic2": 2, "hold_days": 182, "rule": "r", "edge": "e",
      "qty_decimals": 3}
CFG = {"core": {"buy_reserve": 0.01}}


def picks_file(d, month, rows):
    p = d / f"Q206_picks_{month}.csv"
    p.write_text("symbol,sic,rank,fcf_ev\n" + "".join(f"{s},{sic},{i + 1},0.1\n" for i, (s, sic) in enumerate(rows)))


def test_load_picks_takes_the_newest_month_and_refuses_stale_lists(tmp_path):
    picks_file(tmp_path, "2026-09", [("OLD", "3571")])
    picks_file(tmp_path, "2026-10", [("AAA", "3571")])
    now = time.mktime((2026, 11, 3, 12, 0, 0, 0, 0, 0))
    p = b.load_picks(str(tmp_path), now, 45)
    assert p["month"] == "2026-10" and p["rows"][0]["symbol"] == "AAA"
    assert b.load_picks(str(tmp_path), now + 60 * 86400, 45) is None


def test_wanted_respects_the_open_cap_the_group_cap_and_holdings(tmp_path):
    picks_file(tmp_path, "2026-10", [("A", "3571"), ("B", "3572"), ("C", "3573"), ("D", "2800"), ("E", "2800")])
    p = b.load_picks(str(tmp_path), time.mktime((2026, 11, 3, 0, 0, 0, 0, 0, 0)), 45)
    w = b.wanted(BC, p, [], {"D_US_EQ": {}}, lambda s: f"{s}_US_EQ", {})
    assert [x["ticker"] for x in w] == ["A_US_EQ", "B_US_EQ", "E_US_EQ"]  # C: group 35 full; D: already held
    assert b.wanted(BC, p, [], {}, lambda s: f"{s}_US_EQ", {"buyback_value": {}}) == []


def test_entry_orders_buy_with_a_six_month_time_stop_and_no_stop_loss(tmp_path):
    picks_file(tmp_path, "2026-10", [("A", "3571")])
    now = time.mktime((2026, 11, 3, 15, 0, 0, 0, 0, 0))
    p = b.load_picks(str(tmp_path), now, 45)
    o, _ = b.entry_orders(BC, CFG, [], {}, lambda tk: {"price": 50.0, "t": now}, 1.3, 1000, 100, now, 140, {}, p,
                          lambda s: f"{s}_US_EQ", lambda tk: True)
    sig = o[0][6]
    assert o[0][0] == "A_US_EQ" and sig["stop"] is None and sig["time_stop_s"] == 182 * 86400
    assert sig["picks_month"] == "2026-10" and sig["sic2"] == "35" and o[0][1] == 0.52
    o, n = b.entry_orders(BC, CFG, [], {}, lambda tk: {"price": 50.0, "t": now}, 1.3, 1000, 10, now, 140, {}, p,
                          lambda s: f"{s}_US_EQ", lambda tk: True)
    assert not o and "waits for cash" in n[0]
