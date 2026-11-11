"""agent-1.23 self-check (invariants.py): each promise about the book, broken on purpose and caught."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import invariants  # noqa: E402
from market_agent.__main__ import health, main  # noqa: E402

NOW = 1_800_000_000.0
CFG = {"benchmark": {"t212": "VWRPl_EQ"}, "exits": {"tickers": ["INTC_US_EQ"]},
       "limits": {"max_name_weight": 0.05, "cap_exempt": ["VWRPl_EQ"]},
       "active": {"disaster_stop": {"enabled": True, "pct": 0.3, "strategies": ["stock_screen", "buyback_value"]}}}


def entry(eid, ticker, strategy, stop=None, time_stop_s=None, age_s=3600.0, px=100.0):
    return {"id": eid, "t": NOW - age_s, "status": "filled", "ticker": ticker,
            "signal": {"type": "active_entry", "strategy": strategy, "entry_px": px, "stop": stop,
                       "time_stop_s": time_stop_s}}


def pos(qty=1.0, value=20.0, pies=0.0):
    return {"quantity": qty, "quantityInPies": pies, "currentPrice": 90.0, "walletImpact": {"currentValue": value}}


def run(records, positions, stops=None, pending=None, seen=None, now=NOW, open_=True, priced=True, total=1000.0):
    return invariants.check(now=now, cfg=CFG, positions=positions, pending=pending or [], records=records,
                            stops=stops or {}, market_open=lambda t: open_, quote_ok=lambda t: priced, total=total,
                            seen=seen)


def codes(rep):
    return [(v["code"], v["ticker"], v["severity"]) for v in rep["violations"]]


def test_a_clean_book_passes():
    recs = [entry("a", "MU_US_EQ", "stock_screen"), entry("b", "JPM_US_EQ", "drop_rebound", stop=0.08, time_stop_s=864000)]
    positions = {"VWRPl_EQ": pos(5, 700.0), "MU_US_EQ": pos(), "JPM_US_EQ": pos()}
    stops = {"a": {"order_id": 1, "ticker": "MU_US_EQ", "qty": 1.0}, "b": {"order_id": 2, "ticker": "JPM_US_EQ", "qty": 1.0}}
    rep = run(recs, positions, stops, [{"id": 1, "ticker": "MU_US_EQ"}, {"id": 2, "ticker": "JPM_US_EQ"}])
    assert rep["ok"] and rep["violations"] == []
    assert rep["checked"] == {"positions": 3, "open_trades": 2, "need_stop": 2, "stops_resting": 2, "pending_orders": 2}
    assert invariants.verdict(rep, NOW)[0] == 0


def test_the_11_nov_gap_is_caught_a_holding_with_no_broker_stop():
    """The owner found SNDK, MU, BFAM, LEA, MTH and FIVN with no stop. The self-check finds the same thing itself."""
    recs = [entry("a", "MU_US_EQ", "stock_screen"), entry("b", "BFAM_US_EQ", "buyback_value", time_stop_s=273 * 86400)]
    positions = {"VWRPl_EQ": pos(5, 700.0), "MU_US_EQ": pos(), "BFAM_US_EQ": pos()}
    rep = run(recs, positions)
    assert codes(rep) == [("unprotected", "BFAM_US_EQ", "info"), ("unprotected", "MU_US_EQ", "info")]  # just seen
    assert "no stop was ever placed" in rep["violations"][0]["text"]
    seen, t = rep["seen"], NOW
    for _ in range(7):                                                # 35 minutes of open market later
        t += 300
        rep = run(recs, positions, seen=seen, now=t)
        seen = rep["seen"]
    assert codes(rep) == [("unprotected", "BFAM_US_EQ", "critical"), ("unprotected", "MU_US_EQ", "critical")]
    assert not rep["ok"] and invariants.verdict(rep, t)[0] == 2
    assert "0/2 holdings that need a stop have one resting" in invariants.verdict(rep, t)[1]


def test_the_broker_order_book_decides_not_the_agents_own_file():
    recs = [entry("a", "MU_US_EQ", "stock_screen")]
    positions = {"MU_US_EQ": pos(2.0)}
    said_live = {"a": {"order_id": 9, "ticker": "MU_US_EQ", "qty": 2.0}}
    assert codes(run(recs, positions, said_live, [])) == [("unprotected", "MU_US_EQ", "info")]       # broker has no 9
    half = {"a": {"order_id": 9, "ticker": "MU_US_EQ", "qty": 1.0}}
    rep = run(recs, positions, half, [{"id": 9, "ticker": "MU_US_EQ"}])
    assert codes(rep) == [("unprotected", "MU_US_EQ", "info")] and "covers 1 of 2" in rep["violations"][0]["text"]
    assert run(recs, positions, said_live, [{"id": 9, "ticker": "MU_US_EQ"}])["ok"]


def test_closed_market_time_is_not_counted_against_a_missing_stop():
    recs = [entry("a", "MU_US_EQ", "stock_screen")]
    positions = {"MU_US_EQ": pos()}
    rep = run(recs, positions, open_=False)
    seen, t = rep["seen"], NOW
    for _ in range(200):                                              # a whole weekend shut
        t += 900
        rep = run(recs, positions, seen=seen, now=t, open_=False)
        seen = rep["seen"]
    assert codes(rep) == [("unprotected", "MU_US_EQ", "info")]         # a stop cannot be placed while it is shut
    rep = run(recs, positions, seen=seen, now=t + 40 * 3600, open_=True)   # agent was down 40 h: adds 15 min at most
    assert codes(rep) == [("unprotected", "MU_US_EQ", "info")] and rep["violations"][0]["clock_s"] == 900.0


def test_orphans_ghosts_and_stray_orders():
    recs = [entry("g", "GONE_US_EQ", "drop_rebound", stop=0.08, time_stop_s=864000)]
    positions = {"VWRPl_EQ": pos(5, 700.0), "INTC_US_EQ": pos(), "WHO_US_EQ": pos(), "PIE_US_EQ": pos(1.0, 20.0, 1.0)}
    rep = run(recs, positions, pending=[{"id": 77, "ticker": "WHO_US_EQ"}])
    assert codes(rep) == [("ghost_trade", "GONE_US_EQ", "info"), ("orphan_position", "PIE_US_EQ", "info"),
                          ("orphan_position", "WHO_US_EQ", "info"), ("stray_order", "WHO_US_EQ", "info")]
    assert "inside a pie" in next(v["text"] for v in rep["violations"] if v["ticker"] == "PIE_US_EQ")
    rep = run(recs, positions, pending=[{"id": 77, "ticker": "WHO_US_EQ"}], seen=rep["seen"], now=NOW + 900)
    rep = run(recs, positions, pending=[{"id": 77, "ticker": "WHO_US_EQ"}], seen=rep["seen"], now=NOW + 1800)
    assert ("stray_order", "WHO_US_EQ", "warn") in codes(rep) and ("ghost_trade", "GONE_US_EQ", "warn") in codes(rep)
    assert ("orphan_position", "WHO_US_EQ", "info") in codes(rep)      # an hour of open market before it warns


def test_a_merger_position_gone_gets_two_days_before_it_is_a_ghost():
    recs = [entry("m", "DEAL_US_EQ", "merger_arb", stop=0.1, time_stop_s=400 * 86400)]
    rep = run(recs, {})
    seen, t = rep["seen"], NOW
    for _ in range(100):
        t += 900
        rep = run(recs, {}, seen=seen, now=t)
        seen = rep["seen"]
    assert codes(rep) == [("ghost_trade", "DEAL_US_EQ", "info")]       # 25 h: the deal cash-out is still being booked


def test_exit_rules_overdue_missing_and_the_12_month_screen_hold():
    day = 86400.0
    recs = [entry("t", "LATE_US_EQ", "news_shock_vix_hi", time_stop_s=5 * day, age_s=8 * day),
            entry("n", "PRAY_US_EQ", "mystery"),
            entry("s", "OLD_US_EQ", "stock_screen", age_s=400 * day),
            entry("k", "OK_US_EQ", "stock_screen", age_s=300 * day)]
    positions = {t: pos() for t in ("LATE_US_EQ", "PRAY_US_EQ", "OLD_US_EQ", "OK_US_EQ")}
    cfg_stops = {e["id"]: {"order_id": i + 1, "ticker": e["ticker"], "qty": 1.0} for i, e in enumerate(recs)}
    pend = [{"id": i + 1, "ticker": e["ticker"]} for i, e in enumerate(recs)]
    rep = run(recs, positions, cfg_stops, pend)
    assert codes(rep) == [("no_exit_rule", "PRAY_US_EQ", "warn"), ("overdue_refresh", "OLD_US_EQ", "warn"),
                          ("overdue_exit", "LATE_US_EQ", "info")]
    assert "nothing would ever sell it" in rep["violations"][0]["text"]
    assert "3.0 days past its time limit" in rep["violations"][2]["text"]


def test_weight_cap_and_unpriced_holdings():
    positions = {"VWRPl_EQ": pos(5, 700.0), "BIG_US_EQ": pos(1.0, 70.0), "FINE_US_EQ": pos(1.0, 60.0)}
    recs = [entry("a", "BIG_US_EQ", "drop_rebound", stop=0.08, time_stop_s=864000),
            entry("b", "FINE_US_EQ", "drop_rebound", stop=0.08, time_stop_s=864000)]
    stops = {"a": {"order_id": 1, "ticker": "BIG_US_EQ", "qty": 1.0}, "b": {"order_id": 2, "ticker": "FINE_US_EQ", "qty": 1.0}}
    pend = [{"id": 1, "ticker": "BIG_US_EQ"}, {"id": 2, "ticker": "FINE_US_EQ"}]
    rep = run(recs, positions, stops, pend, priced=False)
    assert codes(rep) == [("unpriced", "BIG_US_EQ", "info"), ("unpriced", "FINE_US_EQ", "info"),
                          ("unpriced", "VWRPl_EQ", "info"), ("weight_cap", "BIG_US_EQ", "info")]  # 7.0% > 6.25%; 6.0% is not


def test_any_breach_is_critical_after_a_day_and_clears_when_fixed():
    recs = [entry("n", "PRAY_US_EQ", "mystery")]
    positions = {"PRAY_US_EQ": pos()}
    rep = run(recs, positions)
    seen, t = rep["seen"], NOW
    for _ in range(97):
        t += 900
        rep = run(recs, positions, seen=seen, now=t)
        seen = rep["seen"]
    assert codes(rep) == [("no_exit_rule", "PRAY_US_EQ", "critical")]
    rep = run([], {}, seen=seen, now=t + 900)
    assert rep["ok"] and rep["seen"] == {}                             # fixed: the clock is forgotten


def test_audit_command_and_health_verdict(tmp_path, capsys):
    assert main(["--state", str(tmp_path), "audit"]) == 2             # never ran
    rep = run([entry("a", "MU_US_EQ", "stock_screen")], {"MU_US_EQ": pos()})
    (tmp_path / "invariants.json").write_text(json.dumps(rep))
    assert invariants.verdict(rep, NOW)[0] == 0                        # settling only
    assert invariants.verdict(rep, NOW + 3600)[0] == 2                 # stale report: the check is not running
    capsys.readouterr()
    main(["--state", str(tmp_path), "audit", "--max-age", "1e12"])
    out = json.loads(capsys.readouterr().out)
    assert out["report"]["violations"][0]["code"] == "unprotected" and "seen" not in out["report"]
    hb = {"t": NOW, "duty_age_s": {"prices": 5, "broker": 5}, "invariants": {"critical": 1, "warn": 0, "info": 0}}
    assert health(hb, NOW)[0] == 1 and "self-check critical 1" in health(hb, NOW)[1]
    assert health({**hb, "invariants": {"critical": 0}}, NOW)[0] == 0
