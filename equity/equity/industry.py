"""Industry templates from the SEC's SIC code.

The industrial template (FCF = OCF - capex, ROIC on equity + debt - cash, net debt / EBITDA)
is wrong for some businesses, and reporting a number anyway is worse than reporting none:
* banks and lenders: deposits and loans are the business, so OCF, "debt" and invested
  capital do not mean what they mean for an industrial company;
* insurers: float and investment flows dominate cash flow;
* other financials (brokers, asset managers, closed-end funds, holding offices): same issue;
* REITs: property purchases are not tagged as PP&E capex, and FFO/AFFO is the relevant measure;
* SPACs (blank checks): no operating business at all.

For these templates the metrics in NOT_MEANINGFUL are blanked out of the summary and
flagged, and the company is `supported = False` for screening. Proper bank, insurer and
REIT metrics (ROE, combined ratio, FFO) are later work; until then excluding them is the
honest answer. SIC comes from SEC's submissions API, so it is only known for SEC filers.
"""
from __future__ import annotations

SUPPORTED = ("industrial",)

_FINANCIAL_MEANINGLESS = ("fcf", "fcf_per_share", "fcf_per_share_cagr_3y", "fcf_per_share_cagr_5y", "fcf_margin",
                          "fcf_margin_avg_5y", "fcf_positive_years", "cash_conversion_5y", "roic", "roic_avg_5y",
                          "net_debt", "net_debt_to_ebitda", "interest_coverage", "gross_margin",
                          "operating_margin")
NOT_MEANINGFUL: dict[str, tuple[str, ...]] = {
    "bank": _FINANCIAL_MEANINGLESS,
    "insurer": _FINANCIAL_MEANINGLESS,
    "financial_other": _FINANCIAL_MEANINGLESS,
    "reit": ("fcf", "fcf_per_share", "fcf_per_share_cagr_3y", "fcf_per_share_cagr_5y", "fcf_margin",
             "fcf_margin_avg_5y", "fcf_positive_years", "roic", "roic_avg_5y", "gross_margin"),
    "spac": _FINANCIAL_MEANINGLESS + ("revenue_growth_yoy", "revenue_cagr_3y", "revenue_cagr_5y"),
}
# Inputs whose absence is expected under a template, so it does not lower data confidence.
NOT_REQUIRED: dict[str, tuple[str, ...]] = {
    "bank": ("capex", "operating_income", "debt", "revenue"),
    "insurer": ("capex", "operating_income", "debt"),
    "financial_other": ("capex", "operating_income", "debt"),
    "reit": ("capex",),
    "spac": ("capex", "revenue", "operating_income", "debt"),
}


def classify(sic: int | str | None) -> str:
    """SIC code -> template name. Unknown SIC -> industrial (the default method)."""
    try:
        n = int(sic)
    except (TypeError, ValueError):
        return "industrial"
    if n == 6770:
        return "spac"
    if n == 6798:
        return "reit"
    if 6020 <= n <= 6039 or 6110 <= n <= 6169:
        return "bank"            # commercial banks, savings institutions, credit institutions, lenders
    if 6300 <= n <= 6411:
        return "insurer"         # insurance carriers, agents and brokers
    if 6000 <= n <= 6799:
        return "financial_other"  # brokers, asset managers, funds, holding and investment offices
    return "industrial"


def supported(template: str) -> bool:
    return template in SUPPORTED
