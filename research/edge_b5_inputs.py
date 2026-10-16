"""Per-input SEC loader for the B5 trials: each TTM input with its own period end and the concepts behind it.

Owner, 2026-10-16 13:03Z: preparatory engineering only. This module turns SEC fact rows into the inputs
`edge_b5.h1_velocity` and `edge_b5.s2a_profitability` need. It reads no prices and computes no score, return or
ranking. Synthetic tests: research/tests/test_edge_b5_inputs.py.

Rules (B5_PREREGISTRATION.md v2 §1.1 and §2, plus ADDENDUM_1 §1-§2):

* Each input is `equity.panel.ttm` as known at the month-end (filed on or before it), with its own period end.
  Nothing is carried forward from an earlier month: a stale input is stale, it is not refreshed by an old value.
* H1: FCF needs operating cash flow and capex for the SAME TTM period end: the latest TTM of each, as known at
  the month-end. When those ends differ, `fcf_end` is None and H1 is unavailable for the row; no alignment to an
  older common end is attempted (v2 §2.1 as frozen; ADDENDUM_1 §2). The 183-day freshness rule is applied to the
  common end in `edge_b5.h1_velocity`.
* S2a: gross profit, revenue and cost of revenue each keep their own end; `edge_b5.s2a_profitability` applies
  freshness. ADDENDUM_1 §1 adds the revenue-concept rule: the revenue - cost of revenue fallback is unavailable
  when another listed revenue concept reports more than (1 + REV_CONFLICT) x the selected revenue for any
  period the TTM combined, or the selected revenue for such a period is not positive.
* Both trials: ADDENDUM_1 §3, a company-month whose latest balance sheet known at the month-end came from a
  foreign annual form (20-F, 40-F or their amendments) is unavailable (`foreign_form`): its share-count units
  (ordinary shares or ADS) and, for a re-used CIK, its identity cannot be reconciled with the price on free data.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "equity"))
from equity import panel  # noqa: E402

REV_CONFLICT = 0.10  # another listed revenue concept larger than the selected one by more than 10%: conflict
YEAR = (350, 380)
YTD = (80, 290)


def _parts(rows: list[dict], as_of: str, upto: str | None = None) -> tuple[dict | None, list[dict]]:
    """panel.ttm restricted to periods ending on or before `upto`, plus the fact rows it combined.

    The arithmetic is panel.ttm's own (the test asserts equality with panel.ttm when `upto` is None)."""
    if upto is not None:
        rows = [r for r in rows if r["end"] <= upto]
    t = panel.ttm(rows, as_of)
    if t is None:
        return None, []
    ks = [r for r in panel.known(rows, as_of) if r["start"]]
    years = [r for r in ks if YEAR[0] <= panel._days(r["start"], r["end"]) <= YEAR[1]]
    fy = max(years, key=lambda r: r["end"])
    if t["basis"] == "fy":
        return t, [fy]
    ytds = [r for r in ks if r["end"] > fy["end"] and YTD[0] <= panel._days(r["start"], r["end"]) <= YTD[1]
            and abs(panel._days(fy["end"], r["start"])) <= 10]
    cur = max(ytds, key=lambda r: r["end"])
    n = panel._days(cur["start"], cur["end"])
    prev = [r for r in ks if abs(panel._days(r["start"], r["end"]) - n) <= 10
            and abs(panel._days(r["end"], cur["end"]) - 365) <= 10]
    return t, [fy, cur, max(prev, key=lambda r: r["filed"])]


def ttm_input(rows: list[dict], as_of: str, upto: str | None = None) -> dict | None:
    """{val, end, filed, basis, concepts, periods}: one TTM input as known on `as_of`."""
    t, parts = _parts(rows, as_of, upto)
    if t is None:
        return None
    return {**t, "concepts": sorted({p["concept"] for p in parts}),
            "periods": [(p["start"], p["end"]) for p in parts]}


def fcf_inputs(ocf_rows: list[dict], capex_rows: list[dict], as_of: str, align: bool = False) -> dict:
    """OCF and capex for one common TTM period end, or fcf_end None (H1 unavailable).

    The registered rule (v2 §2.1, ADDENDUM_1 §2) is `align=False`: the latest TTM of each input as known at
    `as_of` must share one period end, otherwise there is no FCF. `align=True` is a diagnostic only (it counts
    how many rows an alignment step could have recovered); no trial uses it."""
    o, c = ttm_input(ocf_rows, as_of), ttm_input(capex_rows, as_of)
    none = {"ocf": None, "capex": None, "fcf_end": None, "aligned": False,
            "ocf_end": o and o["end"], "capex_end": c and c["end"]}
    if o is None or c is None:
        return none
    if o["end"] == c["end"]:
        return {**none, "ocf": o["val"], "capex": c["val"], "fcf_end": o["end"]}
    if not align:
        return none
    common = min(o["end"], c["end"])
    o2, c2 = ttm_input(ocf_rows, as_of, upto=common), ttm_input(capex_rows, as_of, upto=common)
    if o2 and c2 and o2["end"] == c2["end"] == common:
        return {**none, "ocf": o2["val"], "capex": c2["val"], "fcf_end": common, "aligned": True}
    return none


# Revenue concepts compared by the concept test (fundamentals.CONCEPTS / IFRS_CONCEPTS "revenue", any rank). Left
# out: RevenueFromContractWithCustomerIncludingAssessedTax, which by definition adds taxes collected for
# governments (excise, gross-receipts) and so legitimately exceeds the others.
CONCEPT_TEST_EXCLUDED = {"RevenueFromContractWithCustomerIncludingAssessedTax"}


def _chosen(rows: list[dict], as_of: str) -> dict:
    return {(r["start"], r["end"]): r for r in panel.known(rows, as_of)}


def _ratio(a: float, b: float) -> float:
    a, b = abs(a), abs(b)
    return float("inf") if min(a, b) == 0 else max(a, b) / min(a, b)


def restated_check(rows: list[dict], as_of: str, sel: dict | None) -> dict:
    """ADDENDUM_2 §2 (test T2): does a fy + ytd - prior_ytd TTM mix two accounting bases?

    The prior-year year-to-date period is taken from the latest filing, which may have recast it (a disposal,
    spin-off or restatement), while the fiscal year comes from the older annual report. The TTM is flagged when
    both hold, using filings on or before `as_of` only:

    1. the prior-year year-to-date value used differs by more than REV_CONFLICT (either direction) from another
       filing's value for exactly that period, under any listed concept of the metric (a recast often changes the
       concept, and the best-ranked concept may then be the stale, pre-recast one; CONCEPT_TEST_EXCLUDED left
       out) - the period was recast; and
    2. the annual report that supplied the fiscal year did NOT itself recast its prior-year comparative by more
       than REV_CONFLICT against that year's original value (so the fiscal year is still on the old basis).

    A TTM that is a single fiscal year (`basis` "fy") is never flagged. Returns {restated, worst_ratio}."""
    none = {"restated": False, "worst_ratio": None}
    if sel is None or sel["basis"] == "fy":
        return none
    best = _chosen(rows, as_of)
    fy, prev = best.get(sel["periods"][0]), best.get(sel["periods"][2])
    if fy is None or prev is None:
        return none
    known = [r for r in rows if r["filed"] <= as_of and r["start"] and r["concept"] not in CONCEPT_TEST_EXCLUDED]
    others = [r for r in known if (r["start"], r["end"]) == (prev["start"], prev["end"]) and r["accn"] != prev["accn"]]
    recast = max((_ratio(r["val"], prev["val"]) for r in others), default=1.0)
    if recast <= 1 + REV_CONFLICT:
        return {"restated": False, "worst_ratio": recast}
    # did the fiscal year's own annual report recast the year before it?
    same_filing_prior = [r for r in known if r["accn"] == fy["accn"] and r["end"] < fy["end"]
                         and 350 <= panel._days(r["start"], r["end"]) <= 380]
    fy_on_new_basis = False
    for c in same_filing_prior:
        orig = [r for r in known if (r["start"], r["end"]) == (c["start"], c["end"]) and r["filed"] < c["filed"]]
        if orig and _ratio(min(orig, key=lambda r: r["filed"])["val"], c["val"]) > 1 + REV_CONFLICT:
            fy_on_new_basis = True
    return {"restated": not fy_on_new_basis, "worst_ratio": recast}


def revenue_check(rev_rows: list[dict], as_of: str, sel: dict | None) -> dict:
    """ADDENDUM_2 §1: is the selected TTM revenue usable for S2a's fallback? Three tests, input facts only:

    T0  the value used for any combined period is <= 0;
    T1  concept conflict: in the SAME filing (accession) that supplied the value used for a period, another listed
        revenue concept (CONCEPT_TEST_EXCLUDED left out) reports more than (1 + REV_CONFLICT) x that value for
        exactly the same period, in USD. This finds a partial line item ranked first;
    T2  restated period (`restated_check`).

    Any test failing sets `conflict`. The rule never picks a different concept; it only refuses an inconsistent
    one. `reasons` lists the tests that failed."""
    if sel is None:
        return {"conflict": False, "worst_ratio": None, "reasons": []}
    best = _chosen(rev_rows, as_of)
    reasons, worst = [], 1.0
    for per in sel["periods"]:
        ch = best.get(per)
        if ch is None:
            continue
        if ch["val"] <= 0:
            reasons.append("T0")
            worst = float("inf")
            continue
        same = [r["val"] for r in rev_rows if (r["start"], r["end"]) == per and r["accn"] == ch["accn"]
                and r["filed"] <= as_of and r["concept"] not in CONCEPT_TEST_EXCLUDED]
        if same:
            worst = max(worst, max(same) / ch["val"])
    if worst > 1 + REV_CONFLICT and "T0" not in reasons:
        reasons.append("T1")
    if restated_check(rev_rows, as_of, sel)["restated"]:
        reasons.append("T2")
    return {"conflict": bool(reasons), "worst_ratio": worst, "reasons": reasons}


FOREIGN_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A"}


def foreign_form(ta_rows: list[dict], as_of: str) -> bool | None:
    """ADDENDUM_1 §3: True when the latest balance sheet known on `as_of` was filed on a foreign annual form;
    None when no balance sheet is known."""
    t = panel.latest(ta_rows, as_of)
    return None if t is None else t["form"] in FOREIGN_FORMS


def company_month(fx: dict[str, list[dict]], as_of: str, align: bool = False) -> dict:
    """Every B5 TTM input for one company at one month-end, with period ends and provenance."""
    g = lambda m: fx.get(m, [])  # noqa: E731
    out = fcf_inputs(g("ocf"), g("capex"), as_of, align)
    out["foreign_form"] = foreign_form(g("total_assets"), as_of)
    for m, key in (("gross_profit", "gp"), ("revenue", "rev"), ("cost_of_revenue", "cor")):
        t = ttm_input(g(m), as_of)
        out[m] = t and t["val"]
        out[f"{key}_end"] = t and t["end"]
        out[f"{key}_concepts"] = t and t["concepts"]
        out[f"{key}_restated"] = restated_check(g(m), as_of, t)["restated"]
        if m == "revenue":
            rc = revenue_check(g("revenue"), as_of, t)
            out["rev_conflict"], out["rev_ratio"], out["rev_reasons"] = rc["conflict"], rc["worst_ratio"], rc["reasons"]
    for m in ("ocf", "capex"):  # reported for ADDENDUM_2 §2's open decision; not applied to H1
        out[f"{m}_restated"] = restated_check(g(m), as_of, ttm_input(g(m), as_of))["restated"]
    return out
