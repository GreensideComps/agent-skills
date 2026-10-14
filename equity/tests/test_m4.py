"""Milestone 4: DCF, reverse DCF, multiples, theses, bear cases, the candidate gate and alerts."""
from __future__ import annotations

import pytest
from test_m3 import CFG, TODAY, _scored

from equity import alerts, pipeline, research, screener, valuation
from equity.ingest import last_snapshot
from equity.prices import latest_prices


def test_dcf_matches_a_hand_computed_case():
    cfg = {**valuation.VALUATION_CONFIG, "explicit_years": 1, "fade_years": 1, "discount_rate": 0.10,
           "terminal_growth": 0.0}
    # year 1: 110 (g=10%); year 2: fade to 0% -> 110; tail 110/0.10 = 1100 at t=2
    expect = 110 / 1.1 + 110 / 1.21 + 1100 / 1.21
    assert valuation.dcf_ev(100, 0.10, cfg) == pytest.approx(expect)


def test_reverse_dcf_inverts_the_dcf():
    ev = valuation.dcf_ev(100, 0.12)
    assert valuation.implied_growth(100, ev) == pytest.approx(0.12, abs=1e-6)
    assert valuation.implied_growth(-5, ev) is None and valuation.implied_growth(100, 1e30) is None


def test_scenarios_are_mechanical_and_capped():
    assert valuation.scenario_growth(0.10) == pytest.approx({"bear": 0.02, "base": 0.07, "bull": 0.11})
    g = valuation.scenario_growth(0.60)
    assert g["base"] == 0.15 and g["bull"] == pytest.approx(0.19)
    assert valuation.scenario_growth(-0.2) == {"bear": -0.03, "base": 0.0, "bull": 0.04}
    assert valuation.scenario_growth(None) is None


def test_value_company_end_to_end(store, make_sec):
    r, snap, rev, ends = _scored(store, make_sec)
    v = valuation.value_company(snap, r)
    fcf3 = sum(rev[e] * 0.25 for e in ends[-3:]) / 3
    assert v["base_fcf"] == pytest.approx(fcf3)
    base = v["scenarios"]["base"]
    mcap, ev = r["valuation"]["market_cap"], r["valuation"]["enterprise_value"]
    assert base["value_per_share"] == pytest.approx((valuation.dcf_ev(fcf3, base["growth_5y"]) - (ev - mcap)) / 95)
    assert valuation.dcf_ev(fcf3, v["implied_growth_5y"]) == pytest.approx(ev, rel=1e-6)
    assert v["multiples"]["p_fcf"] == pytest.approx(mcap / (rev[ends[-1]] * 0.25))
    assert v["assumptions"]["discount_rate"] == 0.09


def test_no_dcf_without_market_value(store, make_sec):
    r, snap, *_ = _scored(store, make_sec, cur="GBp")
    assert valuation.value_company(snap, r)["notes"] == ["no market value (see screen valuation gate)"]


def test_no_dcf_without_positive_base_fcf(store, make_sec):
    r2, snap2, *_ = _scored(store, make_sec)
    neg = {**snap2, "derived": {e: {**d, "fcf": -1.0} for e, d in snap2["derived"].items()}}
    v = valuation.value_company(neg, r2)
    assert "scenarios" not in v and "not positive" in v["notes"][0]


GOOD = [{"objection": f"risk {i}", "evidence": [f"accn-{i}"], "watch": f"metric {i} falls"} for i in range(3)]


def test_bear_case_rules():
    from equity.store import Store
    import tempfile, pathlib  # noqa: E401
    st = Store(pathlib.Path(tempfile.mkdtemp()))
    with pytest.raises(research.ResearchError, match="at least 3"):
        research.add_bear_case(st, "SEC:1", "bear", GOOD[:2])
    with pytest.raises(research.ResearchError, match="evidence"):
        research.add_bear_case(st, "SEC:1", "bear", GOOD[:2] + [{"objection": "x", "evidence": [" "], "watch": "y"}])
    with pytest.raises(research.ResearchError, match="watch"):
        research.add_bear_case(st, "SEC:1", "bear", GOOD[:2] + [{"objection": "x", "evidence": ["e"], "watch": ""}])
    research.add_thesis(st, "SEC:1", "analyst", "cheap compounder", [{"claim": "ROIC 30%", "evidence": ["snap"]}])
    with pytest.raises(research.ResearchError, match="other than the thesis author"):
        research.add_bear_case(st, "SEC:1", "analyst", GOOD)
    b = research.add_bear_case(st, "SEC:1", "bear", GOOD)
    assert research.current_bear_case(st, "SEC:1", {"summary": {"latest_filed": "2000-01-01"}}) == b
    # A newer annual filing makes the bear case stale for the gate.
    assert research.current_bear_case(st, "SEC:1", {"summary": {"latest_filed": "2999-01-01"}}) is None
    t2 = research.add_thesis(st, "SEC:1", "analyst", "revised", [{"claim": "c", "evidence": ["e"]}])
    assert t2["replaces"].startswith("thesis:SEC:1:")


def test_candidate_needs_current_bear_case_end_to_end(store, make_sec):
    _, snap, *_ = _scored(store, make_sec)
    cid = "SEC:1234"
    pipeline.discover(store, cid, "Example", "screen", "ranked", ["screen rid"], "t")
    for st in ("research_queue", "qualified", "watchlist"):
        pipeline.transition(store, cid, st, "ok", ["e"], "t")
    gates = {"data_confidence": snap["confidence"], "industry_supported": snap["screen_supported"]}
    with pytest.raises(pipeline.TransitionError, match="bear case"):
        pipeline.transition(store, cid, "candidate", "r", ["e"], "t",
                            {**gates, "bear_case_recorded": research.current_bear_case(store, cid, snap) is not None})
    research.add_bear_case(store, cid, "bear-analyst", GOOD)
    pipeline.transition(store, cid, "candidate", "r", ["e"], "t",
                        {**gates, "bear_case_recorded": research.current_bear_case(store, cid, snap) is not None})
    assert pipeline.current_status(store, cid) == "candidate"


def _run(store, as_of, total=None, ranked=True):
    rec = {"rid": f"screen:x:{as_of}", "method_version": "screen-1.0", "as_of": as_of, "ts_utc": as_of + "T12:00:00",
           "results": [{"company_id": "SEC:1", "entity_name": "One", "total": total or 70.0,
                        "rank": 1 if ranked else None, "failed_gates": [] if ranked else ["leverage"],
                        "unknown_critical_gates": []}]}
    store.screens.append(rec)
    return rec


def test_alerts_fire_on_changes_only_and_dedupe(store):
    assert alerts.run(store, _run(store, "2026-10-01"))["baseline"] is True
    assert alerts.run(store, _run(store, "2026-10-02"))["alerts"] == []          # persisting state: silent
    out = alerts.run(store, _run(store, "2026-10-03", total=85.0))
    assert [a["kind"] for a in out["alerts"]] == ["score_move"]
    research.add_bear_case(store, "SEC:1", "bear", GOOD)
    rec = _run(store, "2026-10-04", ranked=False)
    out = alerts.run(store, rec)
    assert {a["kind"] for a in out["alerts"]} == {"left_ranked", "thesis_watch"}
    assert "leverage" in out["alerts"][0]["text"]
    assert alerts.run(store, rec)["written"] == 0                                 # same day again: no repeat
    out = alerts.run(store, _run(store, "2026-10-05"))
    assert [a["kind"] for a in out["alerts"]] == ["entered_ranked"]


def test_screen_report_shows_valuation_and_alert_sections(store, make_sec):
    _scored(store, make_sec)
    rec = screener.run(store, CFG, TODAY)
    vals = {v["company_id"]: v for v in valuation.run(store, rec)}
    md = screener.report(rec, valuations=vals, alerts=alerts.run(store, rec))
    assert "Price implies" in md and "/yr" in md and "baseline recorded" in md
    assert store.valuations.read()[0]["assumptions"]["terminal_growth"] == 0.025
    assert latest_prices(store) and last_snapshot(store, "SEC:1234")
