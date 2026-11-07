"""agent-1.21 honest data sources: Tiingo, CBOE and broker prices in Yahoo's shapes; SEC results dates."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import datasrc, feeds, gap_rebound, news_shock, review, value_timing  # noqa: E402

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc).timestamp()  # Monday 10:00 New York


class Resp:
    def __init__(self, body, code=200):
        self.body, self.status_code = body, code

    def json(self):
        return self.body


def make(tmp_path, routes, clock=lambda: NOW, **kw):
    (tmp_path / "tiingo_token.txt").write_text("tok\n")
    calls = []

    def raw_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers))
        for k, v in routes.items():
            if url.endswith(k) or k in url:
                return Resp(v(params) if callable(v) else v)
        return Resp({}, 404)
    h = datasrc.Honest(tmp_path, lambda: {"VWRP.L": {"price": 110.5, "t": NOW - 60}}, clock=clock, raw_get=raw_get,
                       **kw)
    return h, calls


def test_spark_prices_us_from_iex_london_from_the_broker_and_fx_from_tiingo(tmp_path):
    h, calls = make(tmp_path, {
        "/iex/": [{"ticker": "SPY", "tngoLast": 600.5, "timestamp": "2026-11-09T14:59:58+00:00", "prevClose": 598.0}],
        "/tiingo/fx/top": [{"midPrice": 1.29, "quoteTimestamp": "2026-11-09T14:59:00+00:00"}]})
    d = h.get(feeds.SPARK, {"symbols": "SPY,VWRP.L,GBPUSD=X,VUSA.L", "range": "1d", "interval": "5m"})
    assert d["SPY"]["close"] == [600.5] and d["SPY"]["previousClose"] == 598.0
    assert d["VWRP.L"]["close"] == [110.5] and d["GBPUSD=X"]["close"] == [1.29]
    assert "VUSA.L" not in d  # a London line the broker does not hold has no honest price: UNVERIFIED
    assert all("Mozilla" not in (c[2] or {}).get("User-Agent", "") for c in calls)
    assert calls[0][2]["Authorization"] == "Token tok"
    h.get(feeds.SPARK, {"symbols": "SPY,GBPUSD=X"})
    assert len(calls) == 2  # the IEX batch (150 s) and FX (15 min) are cached
    q = feeds.fetch_quotes(["SPY"], get=h.get)["SPY"]
    assert q["price"] == 600.5 and q["prev_close"] == 598.0


def test_yahoo_search_is_empty_and_refusing_hosts_raise(tmp_path):
    h, _ = make(tmp_path, {})
    assert h.get(feeds.SEARCH, {"q": "JPM"}) == {"news": []}
    with pytest.raises(feeds.FeedError):
        h.get(gap_rebound.EARNINGS, {"date": "2026-11-09"})


def test_daily_bars_split_adjusted_like_yahoo_with_adjclose(tmp_path):
    rows = [{"date": f"2026-11-0{d}T00:00:00.000Z", "open": o, "high": o, "low": o, "close": o, "volume": 100,
             "adjClose": o * 0.99 if d < 6 else o, "splitFactor": sf}
            for d, o, sf in ((3, 200.0, 1.0), (4, 202.0, 1.0), (5, 204.0, 1.0), (6, 103.0, 2.0))]
    h, calls = make(tmp_path, {"/tiingo/daily/abc/prices": rows})
    b = gap_rebound.bars("ABC", h.get)
    assert [round(c, 2) for _, c, _ in b] == [100.0, 101.0, 102.0, 103.0]  # pre-split closes halved, volume doubled
    assert b[0][0] == "2026-11-03" and b[0][2] == 200
    adj = value_timing.adjusted("ABC", h.get)
    assert round(adj[0][1], 2) == 198.0
    gap_rebound.bars("ABC", h.get)
    assert len(calls) == 1  # cached on disk until the next 18:00 New York


def test_budget_refuses_above_the_hourly_cap(tmp_path):
    h, _ = make(tmp_path, {"/tiingo/daily/": []}, hour_cap=2)
    h.tiingo("/tiingo/daily/a/prices")
    h.tiingo("/tiingo/daily/b/prices")
    with pytest.raises(datasrc.BudgetError):
        h.tiingo("/tiingo/daily/c/prices")
    assert len(json.loads((tmp_path / "tiingo_usage.json").read_text())["t"]) == 2


def test_vix_history_takes_the_finished_session_from_the_quote(tmp_path):
    h, _ = make(tmp_path, {
        "quotes/_VIX.json": {"data": {"current_price": 25.64, "close": 25.64, "open": 26.4, "high": 26.6, "low": 23.5,
                                      "prev_day_close": 28.18, "last_trade_time": "2026-11-06T16:15:01"}},
        "historical/_VIX.json": {"data": [{"date": "2026-11-05", "open": "17.1", "high": "28.4", "low": "16.7",
                                           "close": "28.18"}]}})
    v = gap_rebound.bars("^VIX", h.get)
    assert [(d, c) for d, c, _ in v] == [("2026-11-05", 28.18), ("2026-11-06", 25.64)]
    px, t, prev = h.vix_quote()
    assert px == 25.64 and prev == 28.18 and t == datetime(2026, 11, 6, 21, 15, 1, tzinfo=timezone.utc).timestamp()


def test_results_date_from_sec_filings():
    f = [{"form": "8-K", "date": "2026-10-20", "items": "7.01"}, {"form": "8-K", "date": "2026-08-05", "items": "2.02,9.01"}]
    assert review.earnings_due(f, "2026-10-01", 3) is None                      # 57 days on: clear
    assert review.earnings_due(f, "2026-10-21", 3).startswith("expected about 2026-11-04")
    assert review.earnings_due(f, "2026-12-10", 3).startswith("UNVERIFIED")      # 127 days: stale
    assert review.earnings_due(f[:1], "2026-10-21", 3).startswith("UNVERIFIED")


def test_filings_split_results_from_other_8ks():
    hits = [{"_source": {"form": "8-K", "items": ["2.02", "9.01"], "display_names": ["Abc Inc  (ABC)  (CIK 0001)"]}},
            {"_source": {"form": "8-K", "items": ["8.01"], "display_names": ["Xyz Corp  (XYZ, XYZW)  (CIK 0002)"]}}]
    assert [r["symbol"] for r in news_shock.filings(hits, earnings=True)] == ["ABC"]
    assert [r["symbol"] for r in news_shock.filings(hits)] == ["XYZ"]
