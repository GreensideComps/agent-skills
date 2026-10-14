"""Offline fixtures: synthetic SEC companyfacts and Trading 212 instruments."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from equity.sec import SecClient  # noqa: E402
from equity.store import Store  # noqa: E402


def fy(concept_vals: dict, unit: str, years: dict, form="10-K", instant=False, filed_lag_days=60):
    """Build us-gaap entries: years = {fy_end: value}. Each 10-K also re-reports the prior year."""
    out = []
    ends = sorted(years)
    for i, end in enumerate(ends):
        y = int(end[:4])
        filed = f"{y}-{int(end[5:7]) % 12 + 1:02d}-15" if int(end[5:7]) < 11 else f"{y + 1}-01-15"
        entry = {"end": end, "val": years[end], "accn": f"0000000000-{y % 100:02d}-000001", "fy": y,
                 "fp": "FY", "form": form, "filed": filed}
        if not instant:
            entry["start"] = f"{y - 1}{end[4:]}" if end[5:] != "12-31" else f"{y}-01-01"
        out.append(entry)
    concept_vals.setdefault("units", {}).setdefault(unit, []).extend(out)
    return concept_vals


def make_facts(n_years=6, capex=True, revenue_concept="Revenues", end_md="09-30"):
    ends = [f"{2020 + i}-{end_md}" for i in range(n_years)]
    rev = {e: 1000 * (1.1 ** i) for i, e in enumerate(ends)}
    g = {}
    g[revenue_concept] = fy({}, "USD", rev)
    g["GrossProfit"] = fy({}, "USD", {e: v * 0.6 for e, v in rev.items()})
    g["OperatingIncomeLoss"] = fy({}, "USD", {e: v * 0.25 for e, v in rev.items()})
    g["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = \
        fy({}, "USD", {e: v * 0.24 for e, v in rev.items()})
    g["IncomeTaxExpenseBenefit"] = fy({}, "USD", {e: v * 0.24 * 0.2 for e, v in rev.items()})
    g["NetIncomeLoss"] = fy({}, "USD", {e: v * 0.192 for e, v in rev.items()})
    g["NetCashProvidedByUsedInOperatingActivities"] = fy({}, "USD", {e: v * 0.3 for e, v in rev.items()})
    if capex:
        g["PaymentsToAcquirePropertyPlantAndEquipment"] = fy({}, "USD", {e: v * 0.05 for e, v in rev.items()})
    g["WeightedAverageNumberOfDilutedSharesOutstanding"] = fy({}, "shares", {e: 100 - i for i, e in enumerate(ends)})
    g["EarningsPerShareDiluted"] = fy({}, "USD/shares", {e: rev[e] * 0.192 / (100 - i) for i, e in enumerate(ends)})
    g["CashAndCashEquivalentsAtCarryingValue"] = fy({}, "USD", {e: 200.0 for e in ends}, instant=True)
    g["LongTermDebt"] = fy({}, "USD", {e: 300.0 for e in ends}, instant=True)
    g["StockholdersEquity"] = fy({}, "USD", {e: 900.0 for e in ends}, instant=True)
    g["ShareBasedCompensation"] = fy({}, "USD", {e: v * 0.02 for e, v in rev.items()})
    # Noise that must be ignored: a quarterly 10-Q value and a 3-month duration inside a 10-K.
    g[revenue_concept]["units"]["USD"].append({"start": "2025-07-01", "end": "2025-09-30", "val": 1,
                                               "accn": "q", "form": "10-Q", "filed": "2025-11-01"})
    g[revenue_concept]["units"]["USD"].append({"start": "2025-07-01", "end": "2025-09-30", "val": 2,
                                               "accn": "q4", "form": "10-K", "filed": "2025-11-15"})
    return {"cik": 1234, "entityName": "Example Corp", "facts": {"us-gaap": g}}, ends, rev


INSTRUMENTS = [
    {"ticker": "EXMP_US_EQ", "type": "STOCK", "isin": "US0000000001", "currencyCode": "USD",
     "shortName": "EXMP", "name": "Example"},
    {"ticker": "OLDT_US_EQ", "type": "STOCK", "isin": "US0000000002", "currencyCode": "USD",
     "shortName": "NEWT", "name": "Newt Holdings"},                      # renamed: T212 ticker is stale
    {"ticker": "BRK_B_US_EQ", "type": "STOCK", "isin": "US0846707026", "currencyCode": "USD",
     "shortName": "BRK.B", "name": "Berkshire Hathaway (Class B)"},
    {"ticker": "MISM_US_EQ", "type": "STOCK", "isin": "US0000000003", "currencyCode": "USD",
     "shortName": "MISM", "name": "Totally Different Name"},              # symbol matches, name does not
    {"ticker": "RMVl_EQ", "type": "STOCK", "isin": "GB00BGDT3G23", "currencyCode": "GBX",
     "shortName": "RMV", "name": "Rightmove"},
    {"ticker": "VWRPl_EQ", "type": "ETF", "isin": "IE00BK5BQT80", "currencyCode": "GBP",
     "shortName": "VWRP", "name": "Vanguard FTSE All-World"},
]
SEC_TICKERS = [
    {"cik": 1234, "name": "Example Corp", "ticker": "EXMP", "exchange": "NYSE"},
    {"cik": 2222, "name": "NEWT HOLDINGS INC", "ticker": "NEWT", "exchange": "Nasdaq"},
    {"cik": 1067983, "name": "BERKSHIRE HATHAWAY INC", "ticker": "BRK-B", "exchange": "NYSE"},
    {"cik": 3333, "name": "Mismatch Biotech Inc", "ticker": "MISM", "exchange": "Nasdaq"},
]


class FakeTransport:
    def __init__(self, routes: dict):
        self.routes = routes   # url -> list of (status, obj) consumed in order (last one repeats)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers))
        if url not in self.routes and "/submissions/" in url:  # default registrant profile: an industrial
            return 200, json.dumps({"sic": "3571", "sicDescription": "Electronic Computers"}).encode()
        seq = self.routes[url]
        status, obj = seq.pop(0) if len(seq) > 1 else seq[0]
        return status, json.dumps(obj).encode() if not isinstance(obj, bytes) else obj


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


@pytest.fixture
def make_sec(tmp_path):
    def _make(routes):
        t = FakeTransport(routes)
        sleeps = []
        c = SecClient(ua="test-app test@example.com", transport=t, cache_dir=tmp_path / "cache",
                      sleep=sleeps.append, clock=lambda: 0.0)
        c.sleeps = sleeps
        return c, t
    return _make
