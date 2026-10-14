"""Milestone 2: IFRS filers, one reporting currency, industry templates, packed snapshots."""
from __future__ import annotations

import copy
import json
import sqlite3
from datetime import date

import pytest
from conftest import INSTRUMENTS, SEC_TICKERS, fy, make_facts
from test_foundation import _split_company

from equity import index, pipeline
from equity.fundamentals import analyse
from equity.industry import classify, supported
from equity.ingest import ingest_company, last_snapshot, pack_years, resolve, unpack_years, unpacked
from equity.sec import FACTS_URL, SUBMISSIONS_URL
from equity.universe import sync_security_master

TODAY = date(2026, 10, 14)


def make_ifrs(cur="EUR", n_years=6, form="20-F"):
    ends = [f"{2020 + i}-12-31" for i in range(n_years)]
    rev = {e: 5000 * (1.08 ** i) for i, e in enumerate(ends)}
    g = {}
    g["Revenue"] = fy({}, cur, rev, form=form)
    g["GrossProfit"] = fy({}, cur, {e: v * 0.5 for e, v in rev.items()}, form=form)
    g["ProfitLossFromOperatingActivities"] = fy({}, cur, {e: v * 0.2 for e, v in rev.items()}, form=form)
    g["ProfitLossBeforeTax"] = fy({}, cur, {e: v * 0.19 for e, v in rev.items()}, form=form)
    g["IncomeTaxExpenseContinuingOperations"] = fy({}, cur, {e: v * 0.19 * 0.25 for e, v in rev.items()}, form=form)
    g["ProfitLossAttributableToOwnersOfParent"] = fy({}, cur, {e: v * 0.1425 for e, v in rev.items()}, form=form)
    g["ProfitLoss"] = fy({}, cur, {e: v * 0.15 for e, v in rev.items()}, form=form)  # incl. minorities: not used
    g["CashFlowsFromUsedInOperatingActivities"] = fy({}, cur, {e: v * 0.25 for e, v in rev.items()}, form=form)
    g["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"] = \
        fy({}, cur, {e: v * 0.07 for e, v in rev.items()}, form=form)
    g["AdjustedWeightedAverageShares"] = fy({}, "shares", {e: 500.0 for e in ends}, form=form)
    g["DilutedEarningsLossPerShare"] = fy({}, f"{cur}/shares", {e: rev[e] * 0.1425 / 500 for e in ends}, form=form)
    g["CashAndCashEquivalents"] = fy({}, cur, {e: 800.0 for e in ends}, form=form, instant=True)
    g["Borrowings"] = fy({}, cur, {e: 1200.0 for e in ends}, form=form, instant=True)
    g["EquityAttributableToOwnersOfParent"] = fy({}, cur, {e: 4000.0 for e in ends}, form=form, instant=True)
    return {"cik": 999, "entityName": "Euro NV", "facts": {"ifrs-full": g, "dei": {}}}, ends, rev


# ---------------------------------------------------------------- IFRS and currency
def test_ifrs_filer_is_extracted_in_its_reporting_currency():
    facts, ends, rev = make_ifrs()
    a = analyse(facts, TODAY)
    assert a["taxonomy"] == "ifrs-full" and a["reporting_currency"] == "EUR"
    last = ends[-1]
    y = a["years"][last]
    assert y["revenue"]["c"] == "Revenue" and y["revenue"]["u"] == "EUR"
    assert y["net_income"]["c"] == "ProfitLossAttributableToOwnersOfParent"  # owners of parent, not ProfitLoss
    assert y["eps_diluted"]["u"] == "EUR/shares"
    s = a["summary"]
    assert s["fcf_per_share"] == pytest.approx(rev[last] * 0.18 / 500)
    assert s["roic"] == pytest.approx(rev[last] * 0.2 * 0.75 / (4000 + 1200 - 800))
    assert s["revenue_cagr_5y"] == pytest.approx(0.08)
    assert a["confidence"] == "high", a["flags"]


def test_taxonomy_switch_uses_the_most_recent_one():
    """A company that moved from US GAAP to IFRS: the current statements are the IFRS ones."""
    old, _, _ = make_facts(n_years=4, end_md="12-31")          # us-gaap FY2020-2023
    new, ends, _ = make_ifrs(n_years=6)                         # ifrs-full FY2020-2025
    facts = {"entityName": "Switcher", "facts": {"us-gaap": old["facts"]["us-gaap"],
                                                  "ifrs-full": new["facts"]["ifrs-full"]}}
    assert analyse(facts, TODAY)["taxonomy"] == "ifrs-full"
    assert analyse(old, TODAY)["taxonomy"] == "us-gaap"


def test_convenience_translation_is_ignored_not_mixed():
    """20-F filers sometimes tag a USD convenience translation of the latest year next to TWD."""
    facts, ends, rev = make_ifrs(cur="TWD")
    g = facts["facts"]["ifrs-full"]
    g["Revenue"]["units"]["USD"] = [{"start": "2025-01-01", "end": ends[-1], "val": rev[ends[-1]] / 32,
                                     "accn": "x", "form": "20-F", "filed": "2026-04-15"}]
    a = analyse(facts, TODAY)
    assert a["reporting_currency"] == "TWD"
    assert a["years"][ends[-1]]["revenue"]["v"] == pytest.approx(rev[ends[-1]])
    assert "ignored_currencies:USD" in a["flags"] and a["confidence"] == "high"


def test_presentation_currency_change_follows_the_latest_statements():
    """Diageo-like: GBP for older years, then USD from FY2024 (older years have more facts)."""
    facts, ends, rev = make_ifrs(cur="GBP", n_years=6)
    g = facts["facts"]["ifrs-full"]
    for name, node in g.items():
        for u in list(node["units"]):
            if u in ("GBP", "GBP/shares"):
                usd = [dict(e) for e in node["units"][u] if e["end"] >= ends[-2]]
                node["units"][u] = [e for e in node["units"][u] if e["end"] < ends[-2]]
                node["units"][u.replace("GBP", "USD")] = usd
    a = analyse(facts, TODAY)
    assert a["reporting_currency"] == "USD"
    assert sorted(a["years"]) == ends[-2:] and "stale_annual_data" not in a["flags"]
    assert "ignored_currencies:GBP" in a["flags"]


def test_us_gaap_company_is_unchanged_by_m2():
    facts, ends, rev = make_facts()
    a = analyse(facts, TODAY)
    assert a["taxonomy"] == "us-gaap" and a["reporting_currency"] == "USD"
    assert a["confidence"] == "high" and a["flags"] == []


# ---------------------------------------------------------------- industry templates
@pytest.mark.parametrize("sic,template", [
    (6021, "bank"), ("6022", "bank"), (6035, "bank"), (6141, "bank"), (6311, "insurer"), (6411, "insurer"),
    (6211, "financial_other"), (6199, "financial_other"), (6726, "financial_other"), (6798, "reit"),
    (6770, "spac"), (3571, "industrial"), (4911, "industrial"), (None, "industrial"), ("", "industrial"),
])
def test_sic_classification(sic, template):
    assert classify(sic) == template
    assert supported(template) == (template == "industrial")


def test_bank_template_blanks_meaningless_metrics_without_penalising_confidence():
    facts, ends, _ = make_facts(capex=False)
    industrial = analyse(facts, TODAY)
    assert industrial["confidence"] == "low"  # missing capex matters for an industrial company
    bank = analyse(facts, TODAY, template="bank")
    s = bank["summary"]
    assert s["roic"] is None and s["fcf_per_share"] is None and s["net_debt_to_ebitda"] is None
    assert s["revenue"] is not None and s["eps_diluted"] is not None  # still meaningful
    assert "not_meaningful:roic" in bank["flags"] and "missing:capex" not in bank["flags"]
    assert bank["confidence"] == "high" and bank["industry_template"] == "bank"
    assert bank["years"][ends[-1]]["ocf"]["v"]  # reported inputs are kept


def test_candidate_gate_refuses_unsupported_industry(store):
    cid = "SEC:7"
    pipeline.discover(store, cid, "Bank", "manual", "seed", ["url"], "t")
    for st in ("research_queue", "qualified", "watchlist"):
        pipeline.transition(store, cid, st, "ok", ["snap"], "t")
    with pytest.raises(pipeline.TransitionError, match="industry"):
        pipeline.transition(store, cid, "candidate", "cheap", ["snap"], "t",
                            {"bear_case_recorded": True, "data_confidence": "high", "industry_supported": False})


# ---------------------------------------------------------------- packed snapshots
@pytest.mark.parametrize("builder", ["plain", "restated", "split", "ifrs", "implied_shares"])
def test_pack_unpack_round_trip_is_exact(builder):
    if builder == "split":
        facts = _split_company()
    elif builder == "ifrs":
        facts = make_ifrs()[0]
    else:
        facts, ends, rev = make_facts()
        g = facts["facts"]["us-gaap"]
        if builder == "restated":
            g["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"].append(
                {"start": "2023-09-30", "end": ends[-2], "val": 1.0, "accn": "r", "form": "10-K/A",
                 "filed": "2026-09-01"})
        if builder == "implied_shares":
            del g["WeightedAverageNumberOfDilutedSharesOutstanding"]
    a = analyse(facts, TODAY)
    packed = pack_years(a["years"], a["reporting_currency"])
    assert unpack_years(json.loads(json.dumps(packed)), a["reporting_currency"]) == a["years"]
    if builder == "implied_shares":
        assert any(r["shares_diluted"].get("calculated") for r in a["years"].values())


def test_packed_snapshot_is_much_smaller(store, make_sec):
    facts, _, _ = make_facts(n_years=10)
    a = analyse(facts, TODAY)
    full = len(json.dumps(a["years"], separators=(",", ":")))
    packed = len(json.dumps(pack_years(a["years"], "USD"), separators=(",", ":")))
    assert packed < full * 0.6, (packed, full)


def test_ingest_stores_industry_and_reads_old_format(store, make_sec):
    facts, ends, _ = make_facts()
    sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    sec, _ = make_sec({FACTS_URL.format(cik=1234): [(200, facts)],
                       SUBMISSIONS_URL.format(cik=1234): [(200, {"sic": "6022", "sicDescription": "State Banks"})]})
    snap, wrote = ingest_company(store, sec, resolve(store, symbol="EXMP"), TODAY)
    assert wrote and snap["industry_template"] == "bank" and snap["screen_supported"] is False
    raw = store.fundamentals.read()[-1]
    assert "years" not in raw and "methods" not in raw and raw["years_packed"]["filings"]
    assert last_snapshot(store, "SEC:1234")["years"] == analyse(facts, TODAY, "bank")["years"]
    # A pre-M2 snapshot (unpacked, no template) is read as is.
    old = copy.deepcopy(raw)
    old.pop("years_packed")
    old["years"] = {"2020-09-30": {"revenue": {"v": 1}}}
    assert unpacked(old)["years"] == old["years"]
    # A SIC change alone is a new snapshot (the template, and so the summary, changed).
    sec2, _ = make_sec({FACTS_URL.format(cik=1234): [(200, facts)],
                        SUBMISSIONS_URL.format(cik=1234): [(200, {"sic": "3571"})]})
    sec2.cache_dir = sec2.cache_dir / "fresh"
    s2, w2 = ingest_company(store, sec2, resolve(store, symbol="EXMP"), TODAY)
    assert w2 and s2["industry_template"] == "industrial" and s2["previous_snapshot"] == snap["rid"]


def test_index_exposes_template_and_supported_filter(store, make_sec, tmp_path):
    facts, _, _ = make_facts()
    sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    sec, _ = make_sec({FACTS_URL.format(cik=1234): [(200, facts)],
                       SUBMISSIONS_URL.format(cik=1234): [(200, {"sic": "6798"})]})
    ingest_company(store, sec, resolve(store, symbol="EXMP"), TODAY)
    db = sqlite3.connect(index.build(store, tmp_path / "idx.sqlite"))
    assert db.execute("SELECT taxonomy, industry_template, screen_supported, roic FROM companies").fetchone() == \
        ("us-gaap", "reit", 0, None)
