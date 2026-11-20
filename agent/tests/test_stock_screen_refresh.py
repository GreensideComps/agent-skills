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
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2020-01-02", "C_US_EQ": "2026-11-03"})
    r = s.monthly_refresh(sc, rows, [], top_n=3)
    assert r["sell"] == "B_US_EQ" and [b["cik"] for b in r["buy"]] == ["9"] and r["renew"] == []
    assert s.monthly_refresh(sc, rows, [], top_n=3, swapped_this_month=True)["action"] == "skip"


def test_a_name_still_in_the_top_list_after_12_months_is_renewed_not_sold(monkeypatch):
    sc = {**SC, "swap_on_dropout": False}
    rows = [row(9, 5), row(1, 3), row(3, 1), row(8, 0.9)]                  # top 3 = 9, A, C; B left the gated list
    held(monkeypatch, {"A_US_EQ": "2020-01-02", "B_US_EQ": "2026-11-03", "C_US_EQ": "2026-11-03"})
    r = s.monthly_refresh(sc, rows, [], top_n=3)
    assert r["action"] == "renew" and r["sell"] is None and r["buy"] == [] and r["renew"] == ["A_US_EQ"]
    assert "still in the top 3" in r["notes"][0]
    # once the renewal is recorded in config the clock restarts: nothing to do until 12 months after it
    today = s.time.strftime("%Y-%m-%d", s.time.gmtime())
    r = s.monthly_refresh({**sc, "renewed": {"A_US_EQ": today}}, rows, [], top_n=3)
    assert r["action"] == "skip" and r["renew"] == []
    # an old renewal ages like an entry: 12 months after it the name is reviewed again, and sold if it has dropped out
    r = s.monthly_refresh({**sc, "renewed": {"A_US_EQ": "2021-01-02"}}, [row(9, 5), row(3, 4), row(8, 3), row(1, 1)], [], top_n=3)
    assert r["sell"] == "A_US_EQ" and [b["cik"] for b in r["buy"]] == ["9"]
    # a renewal and a sale in the same run: the aged name outside the top list is sold, the one inside is renewed
    held(monkeypatch, {"A_US_EQ": "2020-01-02", "B_US_EQ": "2020-02-02", "C_US_EQ": "2026-11-03"})
    r = s.monthly_refresh(sc, rows, [], top_n=3)
    assert r["action"] == "swap" and r["sell"] == "B_US_EQ" and r["renew"] == ["A_US_EQ"]


def test_hold_since_is_the_later_of_entry_and_renewal():
    e = {"ticker": "A_US_EQ", "ts": "2026-11-03T15:00:00Z"}
    assert s.hold_since({}, e) == "2026-11-03"
    assert s.hold_since({"renewed": {"A_US_EQ": "2027-11-05"}}, e) == "2027-11-05"
    assert s.hold_since({"renewed": {"A_US_EQ": "2025-01-01"}}, e) == "2026-11-03"


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


def _entry(eid, ticker, strategy, stop, px=100.0):
    return {"id": eid, "t": 1.0, "status": "filled", "ticker": ticker,
            "signal": {"type": "active_entry", "strategy": strategy, "entry_px": px, "stop": stop}}


def test_disaster_stop_covers_strategies_without_their_own_stop():
    from market_agent import active
    recs = [_entry("a", "MU_US_EQ", "stock_screen", None), _entry("b", "IUMOl_EQ", "momentum_timing", 0.5, 20.0),
            _entry("c", "FIVN_US_EQ", "news_shock_vix_hi", None, 30.0), _entry("d", "X_US_EQ", "other", None)]
    pos = {t: {"quantity": 1.0, "currentPrice": 90.0} for t in ("MU_US_EQ", "IUMOl_EQ", "FIVN_US_EQ", "X_US_EQ")}
    dis = {"enabled": True, "pct": 0.3, "strategies": ["stock_screen", "news_shock"]}
    got = {n["ticker"]: n for n in active.stops_needed(recs, pos, {}, dis)}
    assert got["MU_US_EQ"]["stop_px"] == 70.0 and got["MU_US_EQ"]["disaster"]
    assert got["FIVN_US_EQ"]["stop_px"] == 21.0
    assert got["IUMOl_EQ"]["stop_px"] == 10.0 and not got["IUMOl_EQ"]["disaster"]  # its own rule stop wins
    assert "X_US_EQ" not in got  # a strategy not listed keeps no stop
    assert {n["ticker"] for n in active.stops_needed(recs, pos, {})} == {"IUMOl_EQ"}  # off: as before


def test_a_cancelled_stop_on_a_held_position_is_placed_again():
    from market_agent import active
    recs = [_entry("b", "IUMOl_EQ", "momentum_timing", 0.5, 20.0)]
    pos = {"IUMOl_EQ": {"quantity": 1.0, "currentPrice": 19.0}}
    live = {"b": {"order_id": 7, "ticker": "IUMOl_EQ"}}
    assert active.stops_needed(recs, pos, live) == []
    lapsed = {"b": {"order_id": None, "ticker": "IUMOl_EQ", "cancelled": "2026-11-10T10:00:00Z"}}
    n = active.stops_needed(recs, pos, lapsed)
    assert len(n) == 1 and n[0]["replace"]
    filled = {"b": {"order_id": None, "ticker": "IUMOl_EQ", "cancelled": "x", "filled": "y"}}
    assert active.stops_needed(recs, pos, filled) == []
    assert active.stops_needed(recs, {}, lapsed) == []  # sold: nothing to protect


def test_renewal_uses_the_sic2_capped_top_list(monkeypatch):
    """agent-1.26.2 (improvement track S28): a held name at raw rank top_n+1 is inside the capped top list when a
    higher name is blocked by a full SIC2 group, so it renews instead of being sold and rebought."""
    sc = {**SC, "swap_on_dropout": False}
    rows = [row(7, 9, "7372"), row(8, 8, "7372"), row(1, 7, "7372"), row(9, 6, "7372"), row(3, 5, "2834"),
            row(2, 4, "3571")]  # 9 is SIC 73's fourth name: capped top 4 = 7, 8, A, C, so raw rank 5 (C) is in
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-11-03", "C_US_EQ": "2020-01-02"})
    assert s.capped_top(rows, 4, 3) == {7, 8, 1, 3}
    r = s.monthly_refresh(sc, rows, [], top_n=4, max_per_sic2=3)
    assert r["action"] == "renew" and r["renew"] == ["C_US_EQ"] and r["sell"] is None


# agent-1.27 (20 Nov 2026): a pick sold by its broker (safety) stop is not bought straight back
def _journal(ticker, exit_why, exit_ts, eid="e1"):
    entry = {"id": eid, "ticker": ticker, "status": "filled", "t": 1.0, "ts": "2026-11-06T15:00:00Z",
             "signal": {"type": "active_entry", "strategy": s.NAME}}
    out = {"id": eid + "x", "ticker": ticker, "status": "filled", "t": 2.0, "ts": exit_ts,
           "signal": {"type": "active_exit", "entry_id": eid, "strategy": s.NAME, "exit_reason": exit_why}}
    return [entry, out]


def test_a_safety_stopped_pick_is_not_refilled_until_the_next_refresh():
    sc = {**SC, "picks_month": "2026-11"}
    recs = _journal("A_US_EQ", "broker_stop", "2026-11-17T14:30:11Z")
    assert s.stopped(sc, recs) == {"A_US_EQ"}
    assert "A_US_EQ" not in s.missing(sc, recs, {}, set())
    # a stop-out before the current picks were set does not block (that refresh already saw the fall)
    assert "A_US_EQ" in s.missing({**sc, "picks_month": "2026-12"}, recs, {}, set())
    # other exits (rebalance, time) do not block either
    assert "A_US_EQ" in s.missing(sc, _journal("A_US_EQ", "rebalance", "2026-11-17T14:30:11Z"), {}, set())


def test_a_safety_stopped_pick_returns_only_if_fresh_scores_still_rank_it(monkeypatch):
    sc = {**SC, "picks_month": "2026-11"}
    recs = _journal("C_US_EQ", "broker_stop", "2026-11-17T14:30:11Z")
    monkeypatch.setattr(s.active, "trades", lambda records: [
        {"entry": recs[0], "exit": recs[1], "adj": []}])
    held(monkeypatch, {"A_US_EQ": "2026-11-03", "B_US_EQ": "2026-11-03"})
    r = s.monthly_refresh(sc, [row(3, 9), row(1, 3), row(2, 2), row(7, 1)], recs, top_n=3)
    assert r["vacant"] == ["C_US_EQ"] and [b["cik"] for b in r["buy"]] == ["3"]  # still ranked: may come back
    r = s.monthly_refresh(sc, [row(1, 3), row(2, 2), row(7, 1), row(3, 0.1)], recs, top_n=3)
    assert r["vacant"] == ["C_US_EQ"] and [b["cik"] for b in r["buy"]] == ["7"]  # fell out: refilled with the best
