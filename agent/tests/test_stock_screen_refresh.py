from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import stock_screen as s

SC = {"picks": ["A_US_EQ", "B_US_EQ", "C_US_EQ"], "ciks": {"A_US_EQ": 1, "B_US_EQ": 2, "C_US_EQ": 3}}


def held(monkeypatch, dates):
    trades = [{"ticker": t, "ts": d + "T15:00:00Z", "signal": {"strategy": s.NAME}} for t, d in dates.items()]
    monkeypatch.setattr(s.active, "open_trades", lambda records: trades)


def row(cik, score, sic="3571"):
    return {"ticker": f"T{cik}", "cik": str(cik), "sic": sic, "score": str(score)}


def test_skip_when_every_held_name_is_still_in_the_top(monkeypatch):
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-11-03", "C_US_EQ": "2026-11-03"})
    r = s.monthly_refresh(SC, [row(1, 3), row(2, 2), row(3, 1), row(9, 0.5)], [], top_n=3)
    assert r["action"] == "skip"


def test_equal_dates_sell_the_lowest_score_or_a_dropped_name_and_buy_the_best_not_held(monkeypatch):
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-11-03", "C_US_EQ": "2026-11-03"})
    r = s.monthly_refresh(SC, [row(9, 5), row(1, 3), row(2, 2), row(3, 1)], [], top_n=3)
    assert r["sell"] == "C_US_EQ" and [b["cik"] for b in r["buy"]] == ["9"]
    r = s.monthly_refresh(SC, [row(9, 5), row(1, 3), row(3, 1), row(8, 0.9)], [], top_n=3)  # B left the gated list
    assert r["sell"] == "B_US_EQ" and [b["cik"] for b in r["buy"]] == ["9"]


def test_oldest_entry_goes_first_and_the_group_cap_holds(monkeypatch):
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-12-01", "C_US_EQ": "2026-12-01"})
    rows = [row(9, 5, "3571"), row(8, 4, "2800"), row(2, 3), row(3, 2), row(1, 0.1)]
    r = s.monthly_refresh(SC, rows, [], top_n=3, max_per_sic2=2)
    assert r["sell"] == "A_US_EQ" and [b["cik"] for b in r["buy"]] == ["8"]  # 9 would be a third in group 35


def test_a_hard_event_exit_is_refilled_without_a_sale(monkeypatch):
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-11-03"})
    sc = {**SC, "_state": {"exit": {"C_US_EQ": {"why": "8-K 1.03"}}}}
    r = s.monthly_refresh(sc, [row(3, 9), row(1, 3), row(2, 2), row(7, 1)], [], top_n=3)
    assert r["sell"] is None and r["vacant"] == ["C_US_EQ"] and [b["cik"] for b in r["buy"]] == ["7"]


def test_after_this_months_swap_later_weekly_runs_only_log(monkeypatch):
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-11-03", "C_US_EQ": "2026-11-03"})
    rows = [row(9, 5), row(1, 3), row(2, 2), row(3, 1)]
    r = s.monthly_refresh(SC, rows, [], top_n=3, swapped_this_month=True)
    assert r["action"] == "log_only" and r["sell"] is None and r["would_sell"] == "C_US_EQ" and r["buy"] == []


def test_a_name_gone_from_the_gated_list_is_an_extra_swap(monkeypatch):
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-12-01", "C_US_EQ": "2026-11-03"})
    rows = [row(9, 5), row(1, 3), row(3, 1), row(8, 0.9)]                  # B left the gated list
    r = s.monthly_refresh(SC, rows, [], top_n=3, swapped_this_month=True)
    assert r["action"] == "swap" and r["sell"] == "B_US_EQ" and [b["cik"] for b in r["buy"]] == ["9"]
    assert "extra swap" in r["notes"][0]
