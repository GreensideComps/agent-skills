"""The method audit's own arithmetic, on small hand-made inputs."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "always_on"))

import method_audit  # noqa: E402
import stats  # noqa: E402
import survivorship_coverage  # noqa: E402


def test_t_values_use_only_results_with_a_sharpe_and_a_length():
    ev = [{"event": "register", "id": "A", "hypothesis": "idea A"},
          {"event": "result", "id": "A", "sr_monthly": 0.2, "n_months": 100, "verdict": "fail"},
          {"event": "result", "id": "B", "sr_monthly": 0.5},                # no length: cannot be judged
          {"event": "result", "id": "C", "n_months": 96}]                   # no Sharpe
    tv = method_audit.t_values(ev)
    assert [r["id"] for r in tv] == ["A"] and tv[0]["t"] == pytest.approx(2.0) and tv[0]["what"] == "idea A"
    assert tv[0]["p"] == pytest.approx(stats.t_sf(2.0, 99))


def test_tails_count_both_sides_against_luck():
    rows = method_audit.tails([-3.1, -2.2, 0.1, 1.7, 2.6])
    r2 = next(r for r in rows if r["t"] == 2.0)
    assert (r2["above"], r2["below"]) == (1, 2) and r2["by_luck"] == pytest.approx(5 * 0.02275, abs=1e-4)


def test_power_table_matches_the_formula():
    rows = method_audit.power_table(486)
    r = next(x for x in rows if x["ann"] == 0.03 and x["years"] == 8)
    assert r["expected_t"] == pytest.approx(0.3 * math.sqrt(8)) and r["p_bar"] < 0.001 and r["years_for_80"] > 300


def test_the_audit_runs_on_the_live_registry_and_reports_the_bar():
    ev = method_audit.load()
    assert len(method_audit.t_values(ev)) >= 100
    assert 4.6 < stats.dsr_bar_t(486) < 4.8


def test_survivorship_coverage_counts_priced_and_vanished_companies():
    rows = []
    def co(cik, months, revenue, priced):
        for m in months:
            rows.append({"cik": cik, "month": f"{m}-28", "ttm_revenue": revenue, "close_raw": 10.0 if priced else None})
    span = [f"{y}-{m:02d}" for y in range(2013, 2023) for m in (1, 7)]
    co(1, span, 2e9, True)                       # large, priced, survives
    co(2, [s for s in span if s < "2015-01"], 3e9, False)   # large, stops filing in 2014, never priced
    co(3, span, 5e8, True)                       # too small to count
    got = survivorship_coverage.coverage(df=pd.DataFrame(rows))
    y13 = next(r for r in got if r["year"] == 2013)
    assert (y13["companies"], y13["priced"], y13["gone_in_3y"], y13["gone_priced"]) == (2, 1, 1, 0)
    y16 = next(r for r in got if r["year"] == 2016)
    assert (y16["companies"], y16["priced"], y16["gone_in_3y"]) == (1, 1, 0)
    assert next(r for r in got if r["year"] == 2021)["gone_in_3y"] is None    # three years on is past the data
