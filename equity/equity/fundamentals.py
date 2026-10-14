"""Annual fundamentals from SEC XBRL companyfacts, with provenance on every number.

Every extracted value records the XBRL concept, accession number, form and filing
date it came from. Two values exist for each period:
* `original` - the first value filed for that period (point-in-time: what an
  investor could know at the time), used for history and future backtests;
* `latest`   - the most recently filed value (includes restatements), used for
  current analysis. A difference > 1% is flagged as a restatement.

Derived metrics state their formula in METHODS. Nothing is estimated or filled in:
a missing input gives a missing output plus a flag.

Scope (milestone 2): annual 10-K / 20-F / 40-F data in either the us-gaap or the
ifrs-full taxonomy (one per company: the one with the most recent annual data). All
money values come from one reporting currency. Quarterly and segment data are not yet
handled. Industry templates (see industry.py) blank out metrics that do not mean
anything for banks, insurers, REITs and SPACs instead of reporting them.
"""
from __future__ import annotations

from datetime import date

from .industry import NOT_MEANINGFUL, NOT_REQUIRED

METHOD_VERSION = "fund-2.2"
ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"}
HISTORY_YEARS = 10

# metric -> (kind, unit kind, ordered fallback concepts). kind: flow (duration) | instant
CONCEPTS: dict[str, tuple[str, str, list[str]]] = {
    "revenue": ("flow", "money", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                  "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                                  "SalesRevenueGoodsNet", "SalesRevenueServicesNet"]),
    "cost_of_revenue": ("flow", "money", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
                                          "CostOfServices"]),
    "gross_profit": ("flow", "money", ["GrossProfit"]),
    "operating_income": ("flow", "money", ["OperatingIncomeLoss"]),
    "pretax_income": ("flow", "money", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"]),
    "income_tax": ("flow", "money", ["IncomeTaxExpenseBenefit"]),
    "net_income": ("flow", "money", ["NetIncomeLoss", "ProfitLoss"]),
    "eps_diluted": ("flow", "per_share", ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]),
    "eps_basic": ("flow", "per_share", ["EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"]),
    "shares_diluted": ("flow", "shares", ["WeightedAverageNumberOfDilutedSharesOutstanding"]),
    "ocf": ("flow", "money", ["NetCashProvidedByUsedInOperatingActivities",
                              "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
    "capex": ("flow", "money", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                                "PaymentsToAcquireMachineryAndEquipment",
                                "PaymentsToAcquireOilAndGasPropertyAndEquipment", "PaymentsToAcquireOilAndGasProperty",
                                "PaymentsForCapitalImprovements",
                                "PaymentsForProceedsFromProductiveAssets"]),  # last resort: net of disposals
    "d_and_a": ("flow", "money", ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                                  "DepreciationAndAmortization", "Depreciation"]),
    "sbc": ("flow", "money", ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"]),
    "interest_expense": ("flow", "money", ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"]),
    "dividends_paid": ("flow", "money", ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"]),
    "buybacks": ("flow", "money", ["PaymentsForRepurchaseOfCommonStock"]),
    "acquisitions": ("flow", "money", ["PaymentsToAcquireBusinessesNetOfCashAcquired"]),
    "cash": ("instant", "money", ["CashAndCashEquivalentsAtCarryingValue",
                                  "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    "short_investments": ("instant", "money", ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                                               "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]),
    "debt_total": ("instant", "money", ["LongTermDebt", "DebtLongtermAndShorttermCombinedAmount",
                                        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"]),
    "debt_noncurrent": ("instant", "money", ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"]),
    "debt_current": ("instant", "money", ["LongTermDebtCurrent", "DebtCurrent",
                                          "LongTermDebtAndCapitalLeaseObligationsCurrent"]),
    "short_borrowings": ("instant", "money", ["ShortTermBorrowings", "CommercialPaper"]),
    "equity": ("instant", "money", ["StockholdersEquity",
                                    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
    "total_assets": ("instant", "money", ["Assets"]),
    "goodwill": ("instant", "money", ["Goodwill"]),
    "receivables": ("instant", "money", ["AccountsReceivableNetCurrent"]),
    "inventory": ("instant", "money", ["InventoryNet"]),
}

# The same metrics in the IFRS taxonomy (20-F / 40-F filers such as TSMC, Novo Nordisk, Shell).
# Kind and unit kind are shared with CONCEPTS; only the concept names differ. IFRS has no standard
# short-term investments line, and its current-borrowings line already includes short-term debt,
# so those two fallbacks are empty or folded in rather than double counted.
IFRS_CONCEPTS: dict[str, list[str]] = {
    "revenue": ["Revenue", "RevenueFromContractsWithCustomers"],
    "cost_of_revenue": ["CostOfSales"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["ProfitLossFromOperatingActivities"],
    "pretax_income": ["ProfitLossBeforeTax"],
    "income_tax": ["IncomeTaxExpenseContinuingOperations"],
    "net_income": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
    "eps_diluted": ["DilutedEarningsLossPerShare", "DilutedEarningsLossPerShareFromContinuingOperations"],
    "eps_basic": ["BasicEarningsLossPerShare", "BasicEarningsLossPerShareFromContinuingOperations"],
    "shares_diluted": ["AdjustedWeightedAverageShares"],
    "ocf": ["CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
              "PurchaseOfPropertyPlantAndEquipment",
              "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"],
    "d_and_a": ["DepreciationAndAmortisationExpense", "AdjustmentsForDepreciationAndAmortisationExpense",
                "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"],
    "sbc": ["AdjustmentsForSharebasedPayments", "ExpenseFromSharebasedPaymentTransactionsWithEmployees"],
    "interest_expense": ["InterestExpense", "FinanceCosts"],
    "dividends_paid": ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"],
    "buybacks": ["PaymentsToAcquireOrRedeemEntitysShares"],
    "acquisitions": ["CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities"],
    "cash": ["CashAndCashEquivalents"],
    "short_investments": [],
    "debt_total": ["Borrowings"],
    "debt_noncurrent": ["NoncurrentPortionOfNoncurrentBorrowings", "LongtermBorrowings"],
    "debt_current": ["CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
                     "CurrentPortionOfNoncurrentBorrowings"],
    "short_borrowings": [],
    "equity": ["EquityAttributableToOwnersOfParent", "Equity"],
    "total_assets": ["Assets"],
    "goodwill": ["Goodwill"],
    "receivables": ["TradeAndOtherCurrentReceivables", "CurrentTradeReceivables"],
    "inventory": ["Inventories"],
}
assert set(IFRS_CONCEPTS) == set(CONCEPTS)
TAXONOMIES = ("us-gaap", "ifrs-full")


def concepts_for(taxonomy: str) -> dict[str, tuple[str, str, list[str]]]:
    if taxonomy == "us-gaap":
        return CONCEPTS
    return {m: (k, u, IFRS_CONCEPTS[m]) for m, (k, u, _) in CONCEPTS.items()}

METHODS = {
    "fcf": "ocf - capex (capex = cash paid for PP&E; leases and acquisitions not deducted)",
    "fcf_per_share": "fcf / weighted average diluted shares",
    "gross_margin": "gross_profit / revenue, or (revenue - cost_of_revenue) / revenue",
    "operating_margin": "operating_income / revenue",
    "net_margin": "net_income / revenue",
    "fcf_margin": "fcf / revenue",
    "ebitda": "operating_income + d_and_a (approximation; no adjustments)",
    "debt": "debt_total, else debt_noncurrent + debt_current; plus short_borrowings. Excludes lease liabilities.",
    "net_debt": "debt - cash - short_investments",
    "roic": "operating_income * (1 - tax rate) / average(equity + debt - cash); tax rate = income_tax / pretax "
            "clipped to [0, 0.35], 0.21 if unavailable. Not meaningful for banks/insurers.",
    "cash_conversion": "sum(ocf) / sum(net_income) over the last 5 years",
    "cagr": "(end / start) ** (1 / years) - 1, only when both ends are positive",
    "sbc_pct_revenue": "sbc / revenue",
    "share_change_cagr": "CAGR of diluted share count (negative = net buybacks)",
    "shares_outstanding": "cover-page dei:EntityCommonStockSharesOutstanding from the latest filing (summed over "
                          "classes), else the latest fiscal year's weighted diluted shares (proxy)",
    "taxonomy": "us-gaap or ifrs-full, whichever has the most recent annual revenue/OCF/net income; ties go "
                "to us-gaap. IFRS: net income = profit attributable to owners of the parent; debt = borrowings.",
    "reporting_currency": "the currency of the latest annual revenue/OCF/net income (ties: the one most annual "
                          "facts use); values in other currencies are ignored, never converted or mixed",
}


def _is_currency(u: str) -> bool:
    return len(u) == 3 and u.isalpha() and u.isupper()


def _unit_for(kind: str, units: dict, currency: str | None) -> str | None:
    if kind == "money":
        return currency if currency in units else None
    if kind == "shares":
        return "shares" if "shares" in units else None
    if kind == "per_share":
        want = f"{currency}/shares"
        return want if want in units else None
    return None


def reporting_currency(tax_facts: dict, concepts: dict) -> str | None:
    """The currency of the latest annual statements. Companies can change presentation
    currency (Diageo moved from GBP to USD in FY2024), so the latest annual revenue, OCF or
    net income decides. Some filers also tag a convenience translation of the same period
    (TSMC: USD next to TWD); among currencies at the latest period, the one used by most
    annual-form money facts overall wins. Values in other currencies are never mixed in."""
    counts: dict[str, int] = {}
    latest: dict[str, str] = {}
    core = {n for m in ("revenue", "ocf", "net_income") for n in concepts[m][2]}
    for _metric, (_kind, unit_kind, names) in concepts.items():
        if unit_kind != "money":
            continue
        for name in names:
            for u, entries in tax_facts.get(name, {}).get("units", {}).items():
                if not _is_currency(u):
                    continue
                annual = [e for e in entries if e.get("form") in ANNUAL_FORMS and "end" in e]
                counts[u] = counts.get(u, 0) + len(annual)
                if name in core and annual:
                    latest[u] = max(latest.get(u, ""), max(e["end"] for e in annual))
    if latest:
        newest = max(latest.values())
        cands = [u for u, end in latest.items() if end == newest]
    else:
        cands = [u for u, n in counts.items() if n]
    return max(sorted(cands), key=lambda u: counts.get(u, 0)) if cands else None


def choose_taxonomy(facts: dict) -> str:
    """The taxonomy with the most recent annual revenue, OCF or net income (companies can switch)."""
    best, best_end = "us-gaap", ""
    for tax in TAXONOMIES:
        tf = facts.get("facts", {}).get(tax, {})
        conc = concepts_for(tax)
        last = ""
        for metric in ("revenue", "ocf", "net_income"):
            for name in conc[metric][2]:
                for entries in tf.get(name, {}).get("units", {}).values():
                    for e in entries:
                        if e.get("form") in ANNUAL_FORMS and e.get("end", "") > last:
                            last = e["end"]
        if last > best_end:
            best, best_end = tax, last
    return best


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _annual_points(entries: list[dict], kind: str) -> dict[str, dict]:
    """period end -> {original: entry, latest: entry} for annual-form entries."""
    out: dict[str, dict] = {}
    for e in entries:
        if e.get("form") not in ANNUAL_FORMS or "end" not in e or e.get("val") is None:
            continue
        if kind == "flow":
            if "start" not in e or not 350 <= _days(e["start"], e["end"]) <= 380:
                continue
        elif "start" in e:
            continue
        slot = out.setdefault(e["end"], {"original": e, "latest": e})
        if e["filed"] < slot["original"]["filed"]:
            slot["original"] = e
        if e["filed"] >= slot["latest"]["filed"]:
            slot["latest"] = e
    return out


SPLIT_FACTORS = sorted({a * b for a in (1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 50, 100)
                        for b in (1, 2, 3, 4, 5, 10)})


def _split_factor(ratio: float) -> float:
    """Nearest split factor (or reverse-split reciprocal) within 3%, else 1 (an ordinary restatement)."""
    if ratio <= 0:
        return 1.0
    for f in SPLIT_FACTORS:
        for cand in (f, 1 / f):
            if abs(ratio / cand - 1) <= 0.03:
                return float(cand)
    return 1.0


def share_basis(entries: list[dict]) -> dict[str, float]:
    """accession -> multiplier converting that filing's share counts to the newest filing's basis.

    All values inside one filing share a basis, and each 10-K re-reports earlier years, so
    filings that report the same period are linked: the ratio of their values for that
    period is a split factor (or ~1). Walking the links from the newest filing gives every
    filing's cumulative multiplier, which handles several splits (e.g. 4:1 then 10:1).
    """
    by_end: dict[str, dict[str, float]] = {}
    filed: dict[str, str] = {}
    for e in entries:
        if e.get("form") in ANNUAL_FORMS and e.get("val") and "start" in e and \
                350 <= _days(e["start"], e["end"]) <= 380:
            by_end.setdefault(e["end"], {})[e["accn"]] = e["val"]
            filed[e["accn"]] = max(filed.get(e["accn"], ""), e["filed"])
    if not filed:
        return {}
    # links[a] = [(b, value_b / value_a)] for every filing b that reports a period a also reports
    links: dict[str, list[tuple[str, float]]] = {}
    for vals in by_end.values():
        for a in vals:
            for b in vals:
                if a != b:
                    links.setdefault(a, []).append((b, vals[b] / vals[a]))
    newest = max(filed, key=lambda a: (filed[a], a))
    mult = {newest: 1.0}
    queue = [newest]
    while queue:
        b = queue.pop(0)
        for a, a_over_b in links.get(b, []):
            if a not in mult:
                # value_a * mult_a == value_b * mult_b  =>  mult_a = mult_b * (value_b / value_a)
                mult[a] = mult[b] * _split_factor(1 / a_over_b)
                queue.append(a)
    return mult


def extract_annual(facts: dict) -> tuple[dict[str, dict], list[str], dict]:
    """Returns (years, flags, meta): years[fy_end][metric] = provenance-tagged value."""
    taxonomy = choose_taxonomy(facts)
    concept_map = concepts_for(taxonomy)
    gaap = facts.get("facts", {}).get(taxonomy, {})
    currency = reporting_currency(gaap, concept_map)
    flags: list[str] = []
    other_currencies = sorted({u for name in {n for _, _, ns in concept_map.values() for n in ns}
                               for u in gaap.get(name, {}).get("units", {})
                               if _is_currency(u) and u != currency})
    per_metric: dict[str, dict[str, dict]] = {}
    for metric, (kind, unit_kind, concepts) in concept_map.items():
        merged: dict[str, dict] = {}
        for concept in concepts:  # earlier concepts win for a given period
            node = gaap.get(concept)
            if not node:
                continue
            unit = _unit_for(unit_kind, node.get("units", {}), currency)
            if not unit:
                continue
            for end, pt in _annual_points(node["units"][unit], kind).items():
                if end not in merged:
                    merged[end] = {"pt": pt, "concept": concept, "unit": unit}
        per_metric[metric] = merged

    # Fiscal year ends come from the core flow statements, not from stray balance-sheet dates.
    fy_ends = sorted(set(per_metric["revenue"]) | set(per_metric["ocf"]) | set(per_metric["net_income"]))
    # Drop near-duplicate ends (52/53-week calendars can tag the same year a few days apart).
    dedup: list[str] = []
    for end in fy_ends:
        if dedup and _days(dedup[-1], end) < 300:
            dedup[-1] = end
        else:
            dedup.append(end)
    fy_ends = dedup[-HISTORY_YEARS:]

    shares_node = gaap.get(concept_map["shares_diluted"][2][0], {}).get("units", {})
    basis = share_basis(shares_node.get("shares", []))
    if all(m == 1.0 for m in basis.values()):
        basis = {}  # no split anywhere: every filing is already on the current basis
    per_share_scaled = {"shares_diluted": 1, "eps_diluted": -1, "eps_basic": -1}  # multiply / divide

    years: dict[str, dict] = {}
    for end in fy_ends:
        row = {}
        for metric, merged in per_metric.items():
            hit = merged.get(end)
            if hit is None:  # tolerate a few days' difference between statements
                near = [e for e in merged if abs(_days(e, end)) <= 7]
                hit = merged[near[0]] if near else None
            if hit is None:
                continue
            o, l_ = hit["pt"]["original"], hit["pt"]["latest"]
            lv, ov = l_["val"], o["val"]
            v = {"v": lv, "c": hit["concept"], "u": hit["unit"], "a": l_["accn"], "f": l_["filed"],
                 "form": l_["form"], "orig": ov, "orig_a": o["accn"], "orig_f": o["filed"]}
            if metric in per_share_scaled and basis:
                ml, mo = basis.get(l_["accn"]), basis.get(o["accn"])
                if ml is None or mo is None:
                    flags.append(f"split_basis_unlinked:{metric}:{end}")
                ml, mo = ml or 1.0, mo or 1.0
                power = per_share_scaled[metric]
                lv, ov = lv * ml ** power, ov * mo ** power
                if ml != 1.0:
                    v.update({"v": lv, "split_adj": ml ** power, "v_as_filed": l_["val"]})
            if ov and abs(lv - ov) / abs(ov) > 0.01:
                flags.append(f"restated:{metric}:{end}")
            row[metric] = v
        # Fallbacks, labelled as calculated rather than reported.
        if "shares_diluted" not in row and "net_income" in row and row.get("eps_diluted", {}).get("v"):
            row["shares_diluted"] = {"v": row["net_income"]["v"] / row["eps_diluted"]["v"],
                                     "c": "implied:net_income/eps_diluted", "u": "shares",
                                     "a": row["eps_diluted"]["a"], "f": row["eps_diluted"]["f"],
                                     "form": row["eps_diluted"]["form"], "calculated": True}
            flags.append("implied:shares_diluted")
        if "operating_income" not in row and "pretax_income" in row and "interest_expense" in row:
            row["operating_income"] = {"v": row["pretax_income"]["v"] + row["interest_expense"]["v"],
                                       "c": "proxy:pretax_income+interest_expense", "u": row["pretax_income"]["u"],
                                       "a": row["pretax_income"]["a"], "f": row["pretax_income"]["f"],
                                       "form": row["pretax_income"]["form"], "calculated": True}
            flags.append("proxy:operating_income")
        years[end] = row

    for metric in ("revenue", "capex", "ocf"):
        used = {years[e][metric]["c"] for e in years if metric in years[e]}
        if len(used) > 1:
            flags.append(f"concept_switch:{metric}")
    if basis:
        flags.append("share_split_adjusted")
    if other_currencies:
        flags.append("ignored_currencies:" + ",".join(other_currencies))
    return years, flags, {"reporting_currency": currency, "taxonomy": taxonomy}


def _g(row: dict, k: str):
    x = row.get(k)
    return None if x is None else x["v"]


def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def cagr(start, end, years: float):
    if start is None or end is None or years <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def derive(years: dict[str, dict]) -> dict[str, dict]:
    """Per-year derived metrics. Inputs missing -> output missing (never imputed)."""
    out: dict[str, dict] = {}
    ends = sorted(years)
    prev_ic = None
    for i, end in enumerate(ends):
        r = years[end]
        rev, ocf, capex = _g(r, "revenue"), _g(r, "ocf"), _g(r, "capex")
        fcf = ocf - capex if ocf is not None and capex is not None else None
        gp = _g(r, "gross_profit")
        if gp is None and rev is not None and _g(r, "cost_of_revenue") is not None:
            gp = rev - _g(r, "cost_of_revenue")
        debt = _g(r, "debt_total")
        if debt is None and _g(r, "debt_noncurrent") is not None:
            debt = _g(r, "debt_noncurrent") + (_g(r, "debt_current") or 0)
        if debt is not None:
            debt += _g(r, "short_borrowings") or 0
        cash = _g(r, "cash")
        liquid = None if cash is None else cash + (_g(r, "short_investments") or 0)
        op = _g(r, "operating_income")
        ebitda = op + _g(r, "d_and_a") if op is not None and _g(r, "d_and_a") is not None else None
        tax, pre = _g(r, "income_tax"), _g(r, "pretax_income")
        rate = min(max(tax / pre, 0.0), 0.35) if tax is not None and pre not in (None, 0) and pre > 0 else 0.21
        eq = _g(r, "equity")
        ic = eq + debt - cash if None not in (eq, debt, cash) else None
        avg_ic = (ic + prev_ic) / 2 if ic is not None and prev_ic is not None else ic
        roic = _div(op * (1 - rate), avg_ic) if op is not None and avg_ic and avg_ic > 0 else None
        prev_ic = ic
        sh = _g(r, "shares_diluted")
        d = {
            "fcf": fcf, "fcf_per_share": _div(fcf, sh), "gross_margin": _div(gp, rev),
            "operating_margin": _div(op, rev), "net_margin": _div(_g(r, "net_income"), rev),
            "fcf_margin": _div(fcf, rev), "ebitda": ebitda, "debt": debt,
            "net_debt": debt - liquid if debt is not None and liquid is not None else None,
            "roic": roic, "sbc_pct_revenue": _div(_g(r, "sbc"), rev),
            "interest_coverage": _div(op, _g(r, "interest_expense")),
        }
        if i > 0:
            p = years[ends[i - 1]]
            d["revenue_growth"] = _div(rev - _g(p, "revenue"), _g(p, "revenue")) if rev is not None and \
                _g(p, "revenue") else None
            pf = out[ends[i - 1]]["fcf_per_share"]
            d["fcf_per_share_growth"] = _div(d["fcf_per_share"] - pf, abs(pf)) if \
                d["fcf_per_share"] is not None and pf else None
            rec, prec = _g(r, "receivables"), _g(p, "receivables")
            d["receivables_growth"] = _div(rec - prec, prec) if rec is not None and prec else None
        out[end] = d
    return out


def summarise(years: dict[str, dict], derived: dict[str, dict], today: date | None = None) -> tuple[dict, list[str]]:
    """Headline metrics for the latest fiscal year, plus data-quality flags."""
    today = today or date.today()
    ends = sorted(years)
    flags: list[str] = []
    if not ends:
        return {}, ["no_annual_data"]
    last = ends[-1]
    L, D = years[last], derived[last]

    def series(key, src):
        return [(e, (src[e].get(key) if src is derived else _g(src[e], key))) for e in ends]

    def ncagr(key, src, n):
        if len(ends) <= n:
            return None
        return cagr(dict(series(key, src))[ends[-1 - n]], dict(series(key, src))[last], n)

    last5 = ends[-5:]
    ocf5 = [_g(years[e], "ocf") for e in last5]
    ni5 = [_g(years[e], "net_income") for e in last5]
    fcfs = [derived[e]["fcf"] for e in ends]
    s = {
        "latest_fy_end": last,
        "latest_filed": max((v["f"] for v in L.values()), default=None),
        "years_of_history": len(ends),
        "revenue": _g(L, "revenue"), "fcf": D["fcf"], "fcf_per_share": D["fcf_per_share"],
        "eps_diluted": _g(L, "eps_diluted"), "shares_diluted": _g(L, "shares_diluted"),
        "revenue_growth_yoy": D.get("revenue_growth"),
        "revenue_cagr_3y": ncagr("revenue", years, 3), "revenue_cagr_5y": ncagr("revenue", years, 5),
        "fcf_per_share_cagr_3y": ncagr("fcf_per_share", derived, 3),
        "fcf_per_share_cagr_5y": ncagr("fcf_per_share", derived, 5),
        "eps_cagr_5y": ncagr("eps_diluted", years, 5),
        "share_change_cagr_3y": ncagr("shares_diluted", years, 3),
        "gross_margin": D["gross_margin"], "operating_margin": D["operating_margin"],
        "net_margin": D["net_margin"], "fcf_margin": D["fcf_margin"],
        "roic": D["roic"],
        "roic_avg_5y": _avg([derived[e]["roic"] for e in last5]),
        "fcf_margin_avg_5y": _avg([derived[e]["fcf_margin"] for e in last5]),
        "fcf_positive_years": sum(1 for x in fcfs if x is not None and x > 0),
        "fcf_years_known": sum(1 for x in fcfs if x is not None),
        "cash_conversion_5y": (sum(ocf5) / sum(ni5)) if None not in ocf5 + ni5 and sum(ni5) > 0 else None,
        "net_debt": D["net_debt"],
        "net_debt_to_ebitda": _div(D["net_debt"], D["ebitda"]) if D["ebitda"] and D["ebitda"] > 0 else None,
        "interest_coverage": D["interest_coverage"],
        "sbc_pct_revenue": D["sbc_pct_revenue"],
        "goodwill_pct_assets": _div(_g(L, "goodwill"), _g(L, "total_assets")),
        "receivables_growth_yoy": D.get("receivables_growth"),
    }
    age = (today - date.fromisoformat(last)).days
    s["days_since_fy_end"] = age
    if age > 456:  # > 15 months: a newer annual report should exist
        flags.append("stale_annual_data")
    if len(ends) < 5:
        flags.append("short_history")
    for k in ("revenue", "ocf", "capex", "shares_diluted", "operating_income", "equity", "cash"):
        if k not in L:
            flags.append(f"missing:{k}")
    if D["debt"] is None:
        flags.append("missing:debt")
    return s, flags


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


CRITICAL_FLAGS = ("missing:revenue", "missing:ocf", "missing:capex", "missing:shares_diluted",
                  "stale_annual_data", "no_annual_data")
# Informational: they describe how a value was obtained, not a gap in the data.
INFO_FLAGS = ("restated", "concept_switch", "share_split_adjusted", "ignored_currencies", "not_meaningful")


def confidence(flags: list[str]) -> str:
    crit = [f for f in flags if f.startswith(CRITICAL_FLAGS)]
    if crit:
        return "low"
    soft = [f for f in flags if not f.startswith(INFO_FLAGS)]
    return "medium" if soft else "high"


def shares_outstanding(facts: dict, years: dict[str, dict]) -> dict | None:
    """Latest shares outstanding, for market capitalisation.

    Preferred: the cover-page count (dei:EntityCommonStockSharesOutstanding) from the most
    recent filing of any form, summed over share classes reported in that filing. It is
    dated weeks before the filing and is already on the current split basis. Fallback
    (e.g. Alphabet, which does not tag it): the latest fiscal year's weighted diluted
    shares, labelled as a proxy."""
    entries = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}) \
        .get("units", {}).get("shares", [])
    if entries:
        latest = max(entries, key=lambda e: (e["filed"], e["end"]))
        same = [e for e in entries if e["accn"] == latest["accn"] and e["end"] == latest["end"]]
        return {"v": float(sum(e["val"] for e in same)), "as_of": latest["end"], "a": latest["accn"],
                "f": latest["filed"], "form": latest["form"], "classes": len(same),
                "c": "dei:EntityCommonStockSharesOutstanding"}
    if years:
        last = years[max(years)].get("shares_diluted")
        if last:
            return {"v": last["v"], "as_of": max(years), "a": last["a"], "f": last["f"], "form": last["form"],
                    "c": "proxy:weighted_diluted_shares_latest_fy", "calculated": True}
    return None


def analyse(facts: dict, today: date | None = None, template: str = "industrial") -> dict:
    """`template` comes from industry.classify(SIC). Metrics a template marks as not
    meaningful are removed from the summary (and flagged) so no screen can rank on them;
    the reported inputs stay in `years`. Missing inputs that a template does not need
    (e.g. capex for a bank) do not lower confidence."""
    years, flags, meta = extract_annual(facts)
    derived = derive(years)
    summary, more = summarise(years, derived, today)
    not_needed = NOT_REQUIRED.get(template, ())
    more = [f for f in more if f not in {f"missing:{k}" for k in not_needed}]
    for k in NOT_MEANINGFUL.get(template, ()):
        if k in summary:
            summary[k] = None
            more.append(f"not_meaningful:{k}")
    flags = sorted(set(flags + more))
    return {"entity_name": facts.get("entityName"), "years": years, "derived": derived,
            "summary": summary, "flags": flags, "confidence": confidence(flags),
            "shares_outstanding": shares_outstanding(facts, years),
            "method_version": METHOD_VERSION, "industry_template": template, **meta}
