from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import gap_rebound as g

DAYS = [f"2026-09-{d:02d}" for d in range(1, 31)] + [f"2026-10-{d:02d}" for d in range(1, 6)]


def series(closes, vol=1e6):
    return [(d, c, vol) for d, c in zip(DAYS, closes)]


def test_event_move_measures_days_minus1_to_plus1_vs_spy_and_prior_liquidity():
    spy = series([100.0] * len(DAYS))
    st = [50.0] * 30 + [50.0, 40.0, 41.0, 42.0, 43.0]  # day0 = DAYS[31]: day -2 close 50, day +1 close 41
    m = g.event_move(series(st, vol=400_000), spy, DAYS[31])
    assert m["day_m2"] == DAYS[29] and m["day_p1"] == DAYS[32]
    assert m["ear"] == -0.18 and m["median_dollar_vol"] == 20_000_000
    assert g.event_move(series(st), spy, DAYS[3]) is None  # not enough history for the liquidity window


def fact(start, end, val, form="10-Q", filed="2026-08-01"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


def facts(rev, ocf, cap=None):
    g_ = {"Revenues": {"units": {"USD": rev}}, "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}}}
    if cap:
        g_["PaymentsToAcquirePropertyPlantAndEquipment"] = {"units": {"USD": cap}}
    return {"facts": {"us-gaap": g_}}


def test_health_builds_ttm_from_year_to_date_and_ignores_later_filings():
    rev = [fact("2024-01-01", "2024-12-31", 1000, "10-K", "2025-02-20"),
           fact("2025-01-01", "2025-12-31", 900, "10-K", "2026-02-20"),
           fact("2024-01-01", "2024-06-30", 500), fact("2025-01-01", "2025-06-30", 450),
           fact("2026-01-01", "2026-06-30", 400),
           fact("2026-01-01", "2026-09-30", 9e9, filed="2026-11-01")]  # filed after day 0: not seen
    ocf = [fact("2025-01-01", "2025-12-31", 100, "10-K", "2026-02-20"), fact("2025-01-01", "2025-06-30", 40),
           fact("2026-01-01", "2026-06-30", 60)]
    cap = [fact("2025-01-01", "2025-12-31", 50, "10-K", "2026-02-20"), fact("2025-01-01", "2025-06-30", 20),
           fact("2026-01-01", "2026-06-30", 30)]
    h = g.health(facts(rev, ocf, cap), "2026-10-28")
    assert h["rev"] == 850 and h["rev_prev"] == 950 and h["fcf"] == (100 + 60 - 40) - (50 + 30 - 20)
    assert h["weak"] is True  # revenue shrank
    h2 = g.health(facts(rev, ocf), "2026-10-28")
    assert h2["weak"] is True and "no capex" in h2["why"]  # shrinking revenue decides it without capex
    assert g.health(facts([], ocf), "2026-10-28")["weak"] is None  # missing data: UNVERIFIED, no trade


def test_exit_day_counts_trading_days_and_skips_holidays():
    assert g.exit_day("2026-11-24", 2) == "2026-11-27"  # Thanksgiving 26 Nov skipped
    assert g.exit_day("2026-11-05", 60) > "2027-01-28"


def test_entry_only_on_buy_day_inside_the_last_90_minutes():
    gc = {"entry_weight": 0.02, "max_open": 8, "buy_window_min": 90, "hold_days": 60, "rule": "r", "edge": "e"}
    cfg = {"core": {"buy_reserve": 0.01}}
    sig = {"eligible": True, "buy_day": "2026-11-05", "ear": -0.2, "day0": "2026-11-03", "health": {"why": "w"}}
    st = {"signals": {"X_US_EQ": sig}}
    q = lambda tk: {"price": 10.0, "t": 0}
    early = datetime.fromisoformat("2026-11-05T13:00:00-05:00").timestamp()
    late = datetime.fromisoformat("2026-11-05T15:00:00-05:00").timestamp()
    o, n = g.entry_orders(gc, cfg, [], {}, q, 1.3, 1000, 100, early, 140, {}, st)
    assert not o and "last 90 minutes" in n[0]
    o, _ = g.entry_orders(gc, cfg, [], {}, q, 1.3, 1000, 100, late, 140, {}, st)
    assert o[0][0] == "X_US_EQ" and o[0][6]["strategy"] == "gap_rebound" and o[0][6]["stop"] is None
    assert o[0][6]["exit_day"] == g.exit_day("2026-11-05", 60) and o[0][6]["time_stop_s"] > 80 * 86400
    o, _ = g.entry_orders(gc, cfg, [], {}, q, 1.3, 1000, 100, late, 140, {"gap_rebound": {}}, st)
    assert not o  # killed
