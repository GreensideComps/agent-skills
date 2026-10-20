"""Sector classification for pm-1.0 (PM_SPEC.md §3). An approximation, not GICS: there is no free GICS source.

* Satellite holdings: SEC SIC code -> one of 11 top-level sectors, first matching range wins (specific ranges first).
* VWRP look-through: the provider publishes FTSE/ICB industries; `ICB` maps those names onto the same 11 sectors.
  The two systems differ (for example, SIC 7370 puts internet platforms in technology, where GICS has them in
  communication services), so every comparison between them carries a classification-mismatch flag.
"""
from __future__ import annotations

SECTORS = ("Energy", "Materials", "Industrials", "Consumer Discretionary", "Consumer Staples", "Health Care",
           "Financials", "Information Technology", "Communication Services", "Utilities", "Real Estate")

# (low, high inclusive, sector); the first match wins, so narrow ranges come before the wide ones they sit inside.
SIC_RANGES = (
    (2830, 2836, "Health Care"), (2840, 2844, "Consumer Staples"), (3570, 3579, "Information Technology"),
    (3630, 3639, "Consumer Discretionary"), (3710, 3716, "Consumer Discretionary"), (3840, 3851, "Health Care"),
    (5120, 5129, "Health Care"), (5140, 5149, "Consumer Staples"), (5400, 5499, "Consumer Staples"),
    (5912, 5912, "Consumer Staples"), (6798, 6798, "Real Estate"), (7370, 7379, "Information Technology"),
    (100, 999, "Consumer Staples"), (1000, 1099, "Materials"), (1200, 1399, "Energy"), (1400, 1499, "Materials"),
    (1500, 1799, "Industrials"), (2000, 2199, "Consumer Staples"), (2200, 2399, "Consumer Discretionary"),
    (2400, 2499, "Materials"), (2500, 2599, "Consumer Discretionary"), (2600, 2699, "Materials"),
    (2700, 2799, "Communication Services"), (2800, 2899, "Materials"), (2900, 2999, "Energy"),
    (3000, 3099, "Materials"), (3100, 3199, "Consumer Discretionary"), (3200, 3399, "Materials"),
    (3400, 3599, "Industrials"), (3600, 3699, "Information Technology"), (3700, 3799, "Industrials"),
    (3800, 3899, "Information Technology"), (3900, 3999, "Consumer Discretionary"), (4000, 4799, "Industrials"),
    (4800, 4899, "Communication Services"), (4900, 4999, "Utilities"), (5000, 5199, "Industrials"),
    (5200, 5999, "Consumer Discretionary"), (6000, 6499, "Financials"), (6500, 6599, "Real Estate"),
    (6700, 6799, "Financials"), (7000, 7099, "Consumer Discretionary"), (7200, 7299, "Consumer Discretionary"),
    (7300, 7399, "Industrials"), (7800, 7899, "Communication Services"), (7900, 7999, "Consumer Discretionary"),
    (8000, 8099, "Health Care"), (8100, 8999, "Industrials"), (9995, 9995, "Financials"),
)

ICB = {"Technology": "Information Technology", "Telecommunications": "Communication Services",
       "Basic Materials": "Materials", **{s: s for s in SECTORS}}


def from_sic(sic) -> str | None:
    """The sector for a SIC code, or None when the code is missing or outside every range (flag: unknown sector)."""
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return None
    for lo, hi, sector in SIC_RANGES:
        if lo <= code <= hi:
            return sector
    return None


def from_icb(name: str) -> str | None:
    return ICB.get(name)
