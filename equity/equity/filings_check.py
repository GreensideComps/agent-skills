"""Header cross-check and sample selection for SEC 8-K events (mini fund Stage 2 §1; owner review point 4).

The cross-check decides whether the header acceptance time may become the confirmed source of `available_at`.
It needs at least 200 filings with >= 80 in Eastern Standard Time, >= 80 in Eastern Daylight Time and >= 10
distinct years. For each filing it checks the header time against SEC's filing-date rule (a filing accepted after
17:30 ET, or on a non-business day, is dated the next business day). It **reports** the difference between the
submissions JSON `acceptanceDateTime` and the header time as a distribution by time zone, and draws no conclusion
from it: one observed four-hour difference is not assumed to hold elsewhere.

Result: `insufficient_sample`, `fail`, `consistent_with_filing_dates` or `validated` (see `crosscheck`). There is no
`pass`: agreeing with the filing-date rule alone does not make a time usable (review finding P32-3).

    python3 -m equity.filings_check <filing_events.jsonl> [--holidays holidays.txt]

reads a local file only.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path

from .filings import BASIS, ET, LIMITATIONS, business_days_after, sha256

MIN_TOTAL, MIN_PER_ZONE, MIN_YEARS = 200, 80, 10
CUTOFF = time(17, 30)


def _json_utc(raw):
    """The JSON value read literally as written (a trailing Z as UTC). Returns None if not parseable."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def expected_filed_dates(local: datetime, holidays: set[date]) -> set[date]:
    d = local.date()
    business = d.weekday() < 5 and d not in holidays
    if business and local.time() <= CUTOFF:
        return {d}
    return {business_days_after(d, 1, holidays)[0]}


def _independent(e):
    """The event's independent acceptance time as UTC, or None. It must carry its source URL and sha256."""
    ind = e.get("independent_acceptance")
    if not isinstance(ind, dict) or not ind.get("source_url") or not ind.get("sha256"):
        return None
    return _json_utc(ind.get("time"))


def crosscheck(events: list[dict], holidays: set[date] = frozenset(), holidays_sha256: str | None = None) -> dict:
    """Check proposed header times. Status, strongest last:

    * `insufficient_sample`: the sample minimums are not met;
    * `fail`: a proposed time is missing, a filing date is unexplained, or an independent time disagrees;
    * `consistent_with_filing_dates`: the header times agree with SEC's filing-date rule. This alone never makes a
      time usable (review finding P32-3: a whole sample shifted by hours can still agree);
    * `validated`: additionally every filing has an independent acceptance time equal to the header time to the
      second, every JSON time parses, the JSON-minus-header offset is a single value per zone, and a holiday list
      with a recorded sha256 was used. The offsets still need separate owner acceptance."""
    eights = [e for e in events if e.get("form") in ("8-K", "8-K/A")]
    null_avail = [e["accession"] for e in eights if e.get("proposed_available_at") is None]
    zones, years = Counter(), set()
    offsets = defaultdict(Counter)
    json_unparseable, unexplained, independent_missing, mismatches = [], [], [], []
    for e in eights:
        if e.get("proposed_available_at") is None:
            continue
        utc = datetime.fromisoformat(e["proposed_available_at"].replace("Z", "+00:00"))
        local = utc.astimezone(ET)
        zone = local.tzname()
        zones[zone] += 1
        years.add(local.year)
        j = _json_utc(e.get("submissions_json_acceptance"))
        if j is None:
            json_unparseable.append(e["accession"])
        else:
            offsets[zone][int((j - utc).total_seconds())] += 1
        ind = _independent(e)
        if ind is None:
            independent_missing.append(e["accession"])
        elif ind != utc:
            mismatches.append({"accession": e["accession"], "header_utc": utc.isoformat(),
                               "independent_utc": ind.isoformat(), "seconds": int((ind - utc).total_seconds())})
        filed = e.get("filed_date")
        try:
            filed_d = date.fromisoformat(filed)
        except (TypeError, ValueError):
            unexplained.append({"accession": e["accession"], "reason": "filed_date_missing"})
            continue
        if filed_d not in expected_filed_dates(local, holidays):
            unexplained.append({"accession": e["accession"], "accepted_et": local.isoformat(),
                                "filed_date": filed, "reason": "filed_date_inconsistent_with_header_time"})
    checked = sum(zones.values())
    sample_ok = checked >= MIN_TOTAL and zones["EST"] >= MIN_PER_ZONE and zones["EDT"] >= MIN_PER_ZONE \
        and len(years) >= MIN_YEARS
    single_offsets = bool(offsets) and all(len(c) == 1 for c in offsets.values())
    blockers = []
    if independent_missing:
        blockers.append("independent_acceptance_missing")
    if json_unparseable:
        blockers.append("json_unparseable")
    if not single_offsets:
        blockers.append("json_offset_not_single_per_zone")
    if not holidays or not holidays_sha256:
        blockers.append("holidays_not_supplied")
    if not sample_ok:
        status = "insufficient_sample"
    elif null_avail or unexplained or mismatches:
        status = "fail"
    elif blockers:
        status = "consistent_with_filing_dates"
    else:
        status = "validated"
    return {
        "status": status,
        "basis": BASIS,
        "requirement": {"min_total": MIN_TOTAL, "min_per_zone": MIN_PER_ZONE, "min_distinct_years": MIN_YEARS},
        "events": len(eights),
        "checked": checked,
        "by_zone": dict(zones),
        "distinct_years": sorted(years),
        "available_at_null": null_avail,
        "unexplained_filed_dates": unexplained,
        "independent_missing": len(independent_missing),
        "independent_mismatches": mismatches,
        "validation_blockers": blockers,
        "json_minus_header_seconds_by_zone": {z: dict(sorted(c.items())) for z, c in sorted(offsets.items())},
        "json_offsets_need_owner_acceptance": True,
        "json_unparseable": json_unparseable,
        "holidays_supplied": len(holidays),
        "holidays_sha256": holidays_sha256,
        "note": "JSON offsets are reported, not interpreted; no offset is assumed for other filings.",
        "limitations": list(LIMITATIONS),
    }


def select_sample(rows: list[dict], n: int = 240, seed: int = 20261023) -> list[str]:
    """A deterministic sample of 8-K accessions spread across filing years and across the months that are mostly
    standard time (Nov-Mar) or daylight time (Apr-Oct). The month split only spreads the sample; each filing's
    real zone comes from its header later. Returns accessions."""
    strata = defaultdict(list)
    for r in rows:
        if r.get("form") not in ("8-K", "8-K/A") or not r.get("filingDate"):
            continue
        d = date.fromisoformat(r["filingDate"])
        strata[(d.year, "std" if d.month in (11, 12, 1, 2, 3) else "dst")].append(r["accessionNumber"])
    rng = random.Random(seed)
    keys = sorted(strata)
    for k in keys:
        strata[k] = sorted(strata[k])
        rng.shuffle(strata[k])
    out = []
    while len(out) < n and any(strata[k] for k in keys):
        for k in keys:
            if strata[k] and len(out) < n:
                out.append(strata[k].pop())
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cross-check SEC header times in a local filing_events.jsonl")
    ap.add_argument("events", type=Path)
    ap.add_argument("--holidays", type=Path, help="one ISO date per line (exchange/SEC holidays), optional")
    a = ap.parse_args(argv)
    events = [json.loads(ln) for ln in a.events.read_text().splitlines() if ln.strip()]
    hol, hol_sha = set(), None
    if a.holidays:
        raw = a.holidays.read_bytes()
        hol_sha = sha256(raw)
        hol = {date.fromisoformat(x.strip()) for x in raw.decode().splitlines() if x.strip()}
    rep = crosscheck(events, hol, hol_sha)
    print(json.dumps(rep, indent=1))
    return 0 if rep["status"] == "validated" else 1


if __name__ == "__main__":
    sys.exit(main())
