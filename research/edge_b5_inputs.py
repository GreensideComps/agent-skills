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


def revenue_check(rev_rows: list[dict], as_of: str, sel: dict | None) -> dict:
    """ADDENDUM_1 §1: is the selected TTM revenue the largest listed concept for each of its periods?

    For every period the TTM combined, the largest value any listed revenue concept reported for exactly that
    (start, end), as known on `as_of`, is compared with the selected concept's value. A gap above REV_CONFLICT
    marks the revenue as conflicting. Reads facts only; never chooses a different concept."""
    if sel is None:
        return {"conflict": False, "worst_ratio": None}
    known = [r for r in rev_rows if r["filed"] <= as_of and r["start"]]
    worst = 1.0
    best = {(r["start"], r["end"]): r for r in panel.known(rev_rows, as_of)}
    for per in sel["periods"]:
        chosen = best.get(per)
        vals = [r["val"] for r in known if (r["start"], r["end"]) == per]
        if chosen is None or not vals:
            continue
        if chosen["val"] <= 0:
            return {"conflict": True, "worst_ratio": float("inf")}
        worst = max(worst, max(vals) / chosen["val"])
    return {"conflict": worst > 1 + REV_CONFLICT, "worst_ratio": worst}


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
        if m == "revenue":
            rc = revenue_check(g("revenue"), as_of, t)
            out["rev_conflict"], out["rev_ratio"] = rc["conflict"], rc["worst_ratio"]
    return out
