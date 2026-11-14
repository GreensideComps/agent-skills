"""Q251-Q253 (sell-rule batch 8): the trade walker and the sleeve are checked on hand-built bars, so the exit order
and the slot accounting are known to do what the pre-registration says before any real price is read."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "always_on"))
import q251_trend_exits as q  # noqa: E402


def bars(rows, start="2020-01-01"):
    """rows = [(open, high, low, close)], one calendar day apart (weekends ignored: the walker only reads dates)."""
    d0 = date.fromisoformat(start)
    b = {k: [] for k in "dohlcv"}
    for i, (o, h, l, c) in enumerate(rows):
        b["d"].append((d0 + timedelta(days=i)).isoformat())
        b["o"].append(o); b["h"].append(h); b["l"].append(l); b["c"].append(c); b["v"].append(1e6)
    return b


FLAT = (100, 101, 99, 100)


def test_stop_fills_at_the_stop_and_a_gap_fills_at_the_open():
    b = bars([FLAT, (100, 101, 94, 96), FLAT])
    assert q.simulate(b, 0, 100, False, stop=95)[:3] == (1, q.INTRA, 95)
    b = bars([FLAT, (90, 91, 89, 90), FLAT])
    assert q.simulate(b, 0, 100, False, stop=95) == (1, q.OPEN, 90, "stop")


def test_stop_is_checked_before_the_target_on_the_same_day():
    b = bars([FLAT, (100, 112, 94, 100), FLAT])
    assert q.simulate(b, 0, 100, False, stop=95, target=110)[3] == "stop"
    b = bars([FLAT, (100, 112, 99, 100), FLAT])
    assert q.simulate(b, 0, 100, False, stop=95, target=110) == (1, q.INTRA, 110, "target")
    b = bars([FLAT, (111, 112, 110, 111), FLAT])
    assert q.simulate(b, 0, 100, False, stop=95, target=110) == (1, q.OPEN, 111, "target")


def test_time_limit_inclusive_and_strict():
    b = bars([FLAT] * 10)
    assert q.simulate(b, 0, 100, True, time_days=5)[:2] == (5, q.OPEN)                      # dated >= entry + 5
    assert q.simulate(b, 0, 100, False, time_days=5, time_strict=True)[:2] == (6, q.OPEN)   # dated > entry + 5


def test_entry_at_open_can_stop_out_the_same_session_but_not_at_its_open():
    b = bars([(100, 101, 90, 92), FLAT])
    assert q.simulate(b, 0, 100, True, stop=95) == (0, q.INTRA, 95, "stop")


def test_trailing_needs_arming_and_uses_the_prior_lows():
    up = [(100, 100, 100, 100)] + [(100 + i, 101 + i, 99 + i, 100 + i) for i in range(1, 13)]
    # never up 10% before the fall: an armed-only trail does nothing, the unarmed one sells at the prior 3-day low
    rows = up[:6] + [(104, 104, 90, 91), FLAT]
    b = bars(rows)
    assert q.simulate(b, 0, 100, True, trail_days=3, trail_arm=0.10)[3] == "end_of_data"
    t, m, px, why = q.simulate(b, 0, 100, True, trail_days=3)
    assert (t, why) == (6, "trailing") and px == min(b["l"][3:6])
    # once the high has been 10% above entry the armed trail sells too
    rows = up + [(111, 111, 90, 91), FLAT]
    b = bars(rows)
    t, m, px, why = q.simulate(b, 0, 100, True, trail_days=3, trail_arm=0.10)
    assert (t, why) == (13, "trailing") and px == min(b["l"][10:13])


def test_higher_of_stop_and_trailing_level_wins():
    rows = [(100, 100, 100, 100), (101, 102, 100, 101), (102, 103, 101, 102), (102, 102, 80, 81), FLAT]
    b = bars(rows)
    assert q.simulate(b, 0, 100, True, stop=90, trail_days=2)[2:] == (100, "trailing")      # trail 100 above stop 90
    assert q.simulate(b, 0, 100, True, stop=100.5, trail_days=2)[2:] == (100.5, "stop")


def test_cap_and_review_and_end_of_data():
    b = bars([FLAT] * 8)
    assert q.simulate(b, 0, 100, True, cap=3)[:2] == (3, q.OPEN)
    assert q.simulate(b, 0, 100, False, review_exit=lambda t: t == 4) == (4, q.CLOSE, 100, "review")
    assert q.simulate(b, 0, 100, False)[3] == "end_of_data"


def _tr(sym, b, i0, m0, i1, px=100.0, px1=100.0):
    return q._trade(sym, b, i0, m0, px, (i1, q.OPEN, px1, "time"))


def test_sleeve_slots_no_doubling_and_costs():
    b = bars([FLAT] * 12)
    book = {"A": b, "B": b, "C": b}
    sig = [{"sym": "A", "rank": 0.1}, {"sym": "B", "rank": 0.2}, {"sym": "C", "rank": 0.3}, {"sym": "A", "rank": 0.0}]
    cands = [_tr("A", b, 1, q.OPEN, 5), _tr("B", b, 1, q.OPEN, 5), _tr("C", b, 1, q.OPEN, 5), _tr("A", b, 3, q.OPEN, 6)]
    m, taken = q.sleeve(cands, sig, book, {}, {}, cost=0.001, slots=2)
    assert [t["sym"] for t in taken] == ["A", "B"]            # C finds no slot; the second A is already held
    assert m["2020-01"] == pytest.approx(-2 * 2 * 0.5 * 0.001)  # flat prices: only two sides of cost on two trades


def test_sleeve_frees_a_slot_the_session_after_an_exit_or_the_same_session_for_a_close_entry():
    b = bars([FLAT] * 12)
    book = {"A": b, "B": b}
    first = _tr("A", b, 1, q.OPEN, 5)
    sig = [{"sym": "A", "rank": 0}, {"sym": "B", "rank": 0}]
    assert len(q.sleeve([first, _tr("B", b, 5, q.OPEN, 8)], sig, book, {}, {}, slots=1)[1]) == 1
    assert len(q.sleeve([first, _tr("B", b, 6, q.OPEN, 8)], sig, book, {}, {}, slots=1)[1]) == 2
    assert len(q.sleeve([first, _tr("B", b, 5, q.CLOSE, 8)], sig, book, {}, {}, slots=1)[1]) == 2


def test_sleeve_return_is_trade_minus_benchmark_times_slot_weight():
    b = bars([FLAT, (100, 111, 100, 110), (110, 122, 110, 121), FLAT])
    tr = q._trade("A", b, 1, q.OPEN, 100.0, (2, q.CLOSE, 121.0, "review"))
    cc = {b["d"][2]: 0.02}
    oc = {b["d"][1]: 0.01}
    m, _ = q.sleeve([tr], [{"sym": "A", "rank": 0}], {"A": b}, cc, oc, cost=0.0, slots=10)
    assert m["2020-01"] == pytest.approx(0.1 * ((0.10 - 0.01) + (0.10 - 0.02)))


def test_a_close_entry_earns_nothing_on_its_entry_session():
    b = bars([FLAT, (100, 105, 100, 105), FLAT])
    tr = q._trade("A", b, 0, q.CLOSE, 100.0, (1, q.CLOSE, 105.0, "review"))
    assert q.trade_days(b, tr) == [(b["d"][1], pytest.approx(0.05), False)]


def test_bar_cleaning(tmp_path):
    p = tmp_path / "X.csv"
    rows = ["date,adj_open,adj_high,adj_low,adj_close,volume"] + [f"2020-01-{i % 28 + 1:02d},10,9,11,10,100" for i in range(301)]
    rows += ["2021-01-01,0,1,1,1,5", "2021-01-02,10,12,8,,5"]
    p.write_text("\n".join(rows) + "\n")
    b = q.load_bars(str(p))
    assert len(b["d"]) == 301 and b["h"][0] == 10 and b["l"][0] == 10      # high below and low above the close are fixed


def test_momentum_off_uses_ten_completed_month_ends_and_the_vix():
    spy = {"d": [], "c": []}
    for mth in range(1, 13):
        for day in (1, 15):
            spy["d"].append(f"2020-{mth:02d}-{day:02d}"); spy["c"].append(100.0 + mth)
    off = q.momentum_off_days(spy, {"2019-12-31": 12.0, "2020-12-10": 30.0})
    assert off["2020-10-15"] is True          # only nine completed months: missing history blocks
    assert off["2020-11-15"] is False         # above the 10-month mean, VIX calm
    assert off["2020-12-15"] is True          # VIX last closed at 30


def test_bench_rule_needs_all_three_discovery_views():
    ms = q.months(*q.DISCOVERY)
    up = {m: 0.01 + (0.001 if i % 2 else -0.001) for i, m in enumerate(ms)}
    down = {m: -0.01 for m in ms}
    assert q.bench_decision(up, up, up) is True
    assert q.bench_decision(up, down, up) is False and q.bench_decision(down, up, up) is False
