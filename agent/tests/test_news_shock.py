from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import gap_rebound, news_shock as ns  # noqa: E402

from test_agent import make  # noqa: E402


def sessions(end="2026-11-09", n=40):
    d, out = date.fromisoformat(end), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


DAYS = sessions()


def chart(closes, vol=1e6):
    ts = [int(datetime.fromisoformat(f"{d}T20:00:00+00:00").timestamp()) for d in DAYS[-len(closes):]]
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"close": closes, "volume": [vol] * len(closes)}]}}]}}


def test_filings_drop_earnings_and_read_tickers():
    hits = [{"_source": {"form": "8-K", "items": ["5.02"], "file_date": "2026-11-05",
                         "display_names": ["Acme Corp  (ABC, ABCW)  (CIK 0000000001)"]}},
            {"_source": {"form": "8-K", "items": ["2.02", "9.01"], "file_date": "2026-11-05",
                         "display_names": ["Earn Inc  (ERN)  (CIK 0000000002)"]}},
            {"_source": {"form": "8-K", "items": ["8.01"], "display_names": ["Private Co  (CIK 0000000003)"]}}]
    assert [r["symbol"] for r in ns.filings(hits)] == ["ABC"]


def test_window_maps_weekend_filings_to_monday():
    assert ns.window(DAYS, "2026-11-09") == ("2026-11-07", "2026-11-09")
    assert ns.window(DAYS, "2026-11-05") == ("2026-11-05", "2026-11-05")


def test_move_is_two_days_vs_spy_with_prior_liquidity():
    sb = [(d, 100.0, 2e5) for d in DAYS]
    i = DAYS.index("2026-11-05")
    sb[i] = (DAYS[i], 95.0, 2e5)
    sb[i + 1] = (DAYS[i + 1], 90.0, 2e5)
    spy = [(d, 500.0, 0) for d in DAYS]
    m = ns.move(sb, spy, "2026-11-05")
    assert m["ear"] == -0.1 and m["median_dollar_vol"] == 2e7


def test_agent_scans_a_high_vix_day_and_buys_at_the_close_of_day_plus_2(tmp_path):
    ag, b, st, clock = make(tmp_path)
    ag.cfg["active"]["enabled"] = True
    ag.cfg["active"]["news_shock"]["enabled"] = True
    nc = ag._news_shock()
    clock.t = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc).timestamp()  # Mon 15:00 New York, in the buy window
    i = DAYS.index("2026-11-05")
    abc = [100.0] * len(DAYS)
    abc[i], abc[i + 1], abc[i + 2] = 95.0, 88.0, 89.0
    calm = [100.0] * len(DAYS)
    vix = [20.0] * len(DAYS)
    vix[i] = 28.0

    def get(url, params):
        sym = url.rsplit("/", 1)[-1]
        return chart({"SPY": [500.0] * len(DAYS), "^VIX": vix, "ABC": abc, "CALM": calm}[sym], 2e5)
    ag.get = get
    calls = []

    def sec(url, params):
        calls.append(params["startdt"])
        hits = [{"_source": {"form": "8-K", "items": ["5.02"], "display_names": [f"{s} Inc  ({s})  (CIK 1)"]}}
                for s in ("ABC", "CALM", "OTC")] if params["startdt"] == "2026-11-05" else []
        return {"hits": {"total": {"value": len(hits)}, "hits": hits}}
    ag.sec_get = sec
    ag.schedule_of = {"ABC_US_EQ": 71, "CALM_US_EQ": 71}
    ag.refresh_news_shock()
    s = st.read("news_shock.json")
    assert calls == ["2026-11-05"]                       # only the VIX >= 25 day is scanned
    assert list(s["signals"]) == ["ABC_US_EQ"] and s["signals"]["ABC_US_EQ"]["buy_day"] == "2026-11-09"
    assert s["signals"]["ABC_US_EQ"]["ear"] == -0.12
    orders, notes = ns.entry_orders(nc, ag.cfg, [], {}, lambda tk: {"price": 89.0}, 1.3, 1000.0, 500.0, clock.t,
                                    None, {}, s)
    assert [o[0] for o in orders] == ["ABC_US_EQ"]
    sig = orders[0][6]
    assert sig["strategy"] == ns.NAME and sig["exit_day"] == gap_rebound.exit_day("2026-11-09", 5)
    assert "VIX>=25" in sig["edge"]
