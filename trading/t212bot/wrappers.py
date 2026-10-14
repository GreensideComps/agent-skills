"""Account-wrapper (ISA / GIA) rules, kept separate from investment maths.

The Trading 212 API does not report whether an account is an ISA, so the
wrapper comes from config/adviser.json -> account_type. These functions only
produce notes for the withdrawal adviser; they never change amounts.
"""
from __future__ import annotations


def withdrawal_notes(account_type: str, cfg: dict, amount: float, est_realised_gain: float) -> list[str]:
    at = (account_type or "").upper()
    notes: list[str] = []
    if amount <= 0:
        return notes
    if at == "ISA":
        isa = cfg.get("isa", {})
        notes.append("ISA: withdrawals and gains inside the ISA are free of UK income tax and CGT.")
        flex = isa.get("flexible_isa")
        if flex is True:
            notes.append("ISA: the account is configured as a flexible ISA, so money withdrawn can be replaced in the same tax year without using new allowance.")
        elif flex is False:
            notes.append("ISA: not a flexible ISA - money withdrawn cannot be paid back in without using this tax year's allowance "
                         f"(£{isa.get('annual_allowance_gbp', 20000):,.0f}).")
        else:
            notes.append("ISA: flexible-ISA status not configured - confirm with Trading 212 whether withdrawn money can be replaced without using allowance.")
    elif at == "GIA":
        aea = cfg.get("gia_tax", {}).get("annual_exempt_amount_gbp")
        if est_realised_gain > 0:
            notes.append(f"GIA: selling would realise an estimated £{est_realised_gain:.2f} of gains, reportable for UK Capital Gains Tax "
                         f"if your total gains for the tax year exceed the annual exempt amount (configured £{aea:,.0f}; check HMRC for the current figure).")
        else:
            notes.append("GIA: no net gain would be realised by the sales needed, so no Capital Gains Tax arises from this withdrawal.")
    else:
        notes.append(f"Unknown account type '{account_type}': tax treatment not assessed.")
    return notes
