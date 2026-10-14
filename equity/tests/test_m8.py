"""Milestone 8: point-in-time backtest helpers (no look-ahead, split handling, statistics)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from equity import backtest


def test_pit_facts_drops_values_filed_after_the_cutoff():
    facts = {"entityName": "X", "facts": {"us-gaap": {
        "Revenues": {"label": "R", "units": {"USD": [
            {"end": "2014-12-31", "val": 1, "filed": "2015-02-01"},
            {"end": "2014-12-31", "val": 2, "filed": "2016-02-01"},   # restatement, not yet known
            {"end": "2015-12-31", "val": 3, "filed": "2016-02-01"}]}},
        "Later": {"units": {"USD": [{"end": "2016-12-31", "val": 9, "filed": "2017-02-01"}]}}}}}
    out = backtest.pit_facts(facts, "2015-04-30")
    assert out["entityName"] == "X" and "Later" not in out["facts"]["us-gaap"]
    assert [x["val"] for x in out["facts"]["us-gaap"]["Revenues"]["units"]["USD"]] == [1]
    assert len(facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"]) == 3      # input untouched


def _ts(y, m):
    return int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())


def _chart(bars, splits=()):
    return json.dumps({"chart": {"result": [{
        "meta": {"currency": "USD"}, "timestamp": [_ts(y, m) for y, m, _, _ in bars],
        "indicators": {"quote": [{"close": [c for *_, c, _ in bars]}], "adjclose": [{"adjclose": [a for *_, a in bars]}]},
        "events": {"splits": {str(i): {"date": int(datetime(*d, tzinfo=timezone.utc).timestamp()),
                                       "numerator": n, "denominator": 1} for i, (d, n) in enumerate(splits)}}}]}}).encode()


def test_raw_close_undoes_later_splits_and_returns_use_adjusted_closes():
    s = backtest.parse_monthly(_chart([(2020, 4, 10.0, 9.0), (2021, 4, 12.0, 11.7), (2022, 4, 30.0, 30.0)],
                                      splits=[((2021, 7, 20), 4), ((2024, 6, 10), 10)]))
    assert backtest.raw_close(s, 2020, 4) == pytest.approx(10.0 * 40)   # both splits came later
    assert backtest.raw_close(s, 2022, 4) == pytest.approx(30.0 * 10)
    assert backtest.forward_return(s, 2020) == pytest.approx(11.7 / 9.0 - 1)
    assert backtest.forward_return(s, 2022) is None and backtest.raw_close(s, 2019, 4) is None


def test_spearman_handles_ties_and_small_samples():
    assert backtest.spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0)
    assert backtest.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    assert backtest.spearman([1, 1, 2, 2, 3], [1, 2, 3, 4, 5]) > 0.8
    assert backtest.spearman([1, 2], [1, 2]) is None


def test_evaluate_applies_the_preregistered_pass_rule():
    recs = []
    for i in range(30):   # score i predicts return i in every year, top half ranked
        rows = [{"year": y, "total": float(i), "eligible": i >= 15, "fwd_return": i / 100 + (y % 3) / 1000}
                for y in range(2012, 2018)]
        recs.append({"company_id": str(i), "rows": rows, "error": None})
    ev = backtest.evaluate(recs)
    assert ev["mean_ic"] > 0.99 and ev["ranked_win_rate"] == 1.0
    noisy = [{**r, "rows": [{**x, "fwd_return": ((int(r["company_id"]) * 7 + x["year"]) % 11) / 100}
                            for x in r["rows"]]} for r in recs]
    assert backtest.evaluate(noisy)["pass"] is False
    assert "Verdict" in backtest.report(ev)
