"""Cross-check SEC-derived figures against an independent provider (Yahoo fundamentals timeseries).

Purpose: detect extraction bugs and source conflicts. Neither source is assumed right; a
disagreement > TOLERANCE is reported as a conflict for review, never silently resolved.
Yahoo's endpoint is unofficial and unlicensed for redistribution, so it is used only as
a check, never as the system's source of record.
"""
from __future__ import annotations

import json
import time
import urllib.request

URL = ("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}"
       "?type={types}&period1=1420070400&period2={now}")
FIELDS = {  # our metric -> (yahoo type, sign)
    "revenue": ("annualTotalRevenue", 1),
    "ocf": ("annualOperatingCashFlow", 1),
    "capex": ("annualCapitalExpenditure", -1),
    "shares_diluted": ("annualDilutedAverageShares", 1),
}
TOLERANCE = 0.02


def fetch_yahoo(symbol: str, transport=None) -> dict[str, dict[str, float]]:
    """{yahoo_type: {as_of_date: value}}"""
    url = URL.format(sym=symbol.replace(".", "-"), types=",".join(t for t, _ in FIELDS.values()),
                     now=int(time.time()))
    if transport:
        body = transport(url)
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
    out: dict[str, dict[str, float]] = {}
    for res in json.loads(body)["timeseries"]["result"]:
        t = res["meta"]["type"][0]
        out[t] = {p["asOfDate"]: p["reportedValue"]["raw"] for p in res.get(t, []) if p}
    return out


def compare(snapshot: dict, yahoo: dict[str, dict[str, float]]) -> list[dict]:
    rows = []
    fy = snapshot["summary"].get("latest_fy_end")
    if not fy:
        return rows
    ours_row = snapshot["years"][fy]
    for metric, (ytype, sign) in FIELDS.items():
        ours = ours_row.get(metric, {}).get("v")
        series = yahoo.get(ytype, {})
        # Yahoo dates fiscal years by period end; allow a few days for 52/53-week calendars.
        theirs = next((v * sign for d, v in series.items() if abs(_days(d, fy)) <= 7), None)
        if ours is None or theirs is None:
            status = "missing_in_sec" if ours is None and theirs is not None else \
                "missing_in_yahoo" if theirs is None and ours is not None else "missing_both"
            diff = None
        else:
            diff = (ours - theirs) / abs(theirs) if theirs else None
            status = "agree" if diff is not None and abs(diff) <= TOLERANCE else "CONFLICT"
        rows.append({"metric": metric, "fy_end": fy, "sec": ours, "yahoo": theirs, "rel_diff": diff,
                     "status": status, "sec_concept": ours_row.get(metric, {}).get("c")})
    return rows


def _days(a: str, b: str) -> int:
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days
