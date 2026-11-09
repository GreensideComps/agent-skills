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


def test_with_dropout_swaps_off_only_a_12_month_old_name_or_a_vacancy_trades(monkeypatch):
    sc = {**SC, "swap_on_dropout": False}
    rows = [row(9, 5), row(1, 3), row(3, 1), row(8, 0.9)]                  # B left the gated list
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-11-03", "C_US_EQ": "2026-11-03"})
    assert s.monthly_refresh(sc, rows, [], top_n=3)["action"] == "skip"
    held(monkeypatch, {"A_US_EQ": "2020-01-02", "B_US_EQ": "2026-11-03", "C_US_EQ": "2026-11-03"})
    r = s.monthly_refresh(sc, rows, [], top_n=3)
    assert r["sell"] == "A_US_EQ" and [b["cik"] for b in r["buy"]] == ["9"]
    assert s.monthly_refresh(sc, rows, [], top_n=3, swapped_this_month=True)["action"] == "skip"


def test_equal_weight_trims_and_top_ups(monkeypatch):
    trades = [{"ticker": t, "id": t.lower(), "ts": "2026-11-03T15:00:00Z", "signal": {"strategy": s.NAME}}
              for t in ("A_US_EQ", "B_US_EQ", "C_US_EQ")]
    monkeypatch.setattr(s.active, "open_trades", lambda records: trades)
    pos = {t: {"quantity": 1.0, "quantityAvailableForTrading": 1.0, "walletImpact": {"currentValue": v}}
           for t, v in (("A_US_EQ", 13.0), ("B_US_EQ", 10.0), ("C_US_EQ", 7.0))}
    q = {"A_US_EQ": {"price": 13.0}, "B_US_EQ": {"price": 10.0}, "C_US_EQ": {"price": 7.0}}
    sc = {"ew_rebalance": {"enabled": True, "from": "2026-12", "min_trade_gbp": 1.0}}
    dec = 1796126400.0                                                     # 2026-12-01
    args = (sc, [], pos, q.get, 1.0, dec, None)
    trims, tops, n = s.ew_orders(*args, {}, lambda t: True)
    assert [(o[0], o[1]) for o in trims] == [("A_US_EQ", -0.23)] and [(o[0], o[1]) for o in tops] == [("C_US_EQ", 0.428)]
    assert trims[0][6]["type"] == "active_trim" and tops[0][6]["entry_id"] == "c_us_eq"
    assert s.ew_orders(*args, {"ew_month": "2026-12"}, lambda t: True)[:2] == ([], [])
    assert s.ew_orders(*args, {"ew_done": {"2026-12": ["A_US_EQ", "C_US_EQ"]}}, lambda t: True)[:2] == ([], [])
    assert s.ew_orders(sc, [], pos, q.get, 1.0, dec - 86400 * 30, None, {}, lambda t: True)[:2] == ([], [])  # Nov
    assert s.ew_orders(*args, {}, lambda t: False)[2]                      # market shut: waits, month not done


def test_closed_result_counts_trims_and_top_ups():
    def rec(kind, net, fee=0.0):
        return {"signal": {"type": kind}, "broker": {"fill": {"walletImpact": {"netValue": net,
                                                                                "taxes": [{"quantity": -fee}]}}}}
    t = {"entry": rec("active_entry", 10.0), "exit": rec("active_exit", 11.0),
         "adj": [rec("active_trim", 2.0, 0.01), rec("active_topup", 1.0)]}
    r = s.active.closed_result(t)
    assert abs(r["pnl_gbp"] - (11 + 2 - 1 - 10 - 0.01)) < 1e-9 and abs(r["ret"] - r["pnl_gbp"] / 11) < 1e-9
