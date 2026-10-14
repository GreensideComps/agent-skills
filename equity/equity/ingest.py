"""Fetch SEC fundamentals for a company and store a snapshot only when it changed.

Storage format (method fund-2.0 onwards). A full-universe pass has to fit in git, so the
per-year values are packed: each filing (accession, date, form) is stored once in a
`filings` list and referenced by position, each metric's usual concept once in
`default_concept` (other concepts by position in `concepts`), units only when they
differ from the metric's default, and the first-filed value and accession only when
they differ from the latest. `unpack_years` restores exactly the in-memory format that
`fundamentals.analyse` produces, and readers always go through `last_snapshot`, which
unpacks. Formulas are stored once per method version in the `methods` ledger rather than
in every snapshot, and derived metrics are rounded to 6 significant figures with
not-computable ones omitted (reported values are never rounded). Snapshots written before fund-2.0 are stored unpacked and read as is.
"""
from __future__ import annotations

from datetime import date

from .fundamentals import CONCEPTS, METHOD_VERSION, METHODS, analyse
from .industry import classify, supported
from .sec import FACTS_URL, SUBMISSIONS_URL, SecClient
from .store import Store, content_hash, utc_now

_CORE = ("v", "c", "u", "a", "f", "form", "orig", "orig_a", "orig_f")


def _default_unit(metric: str, currency: str | None) -> str | None:
    kind = CONCEPTS[metric][1] if metric in CONCEPTS else None
    return {"money": currency, "shares": "shares", "per_share": f"{currency}/shares"}.get(kind)


def pack_years(years: dict[str, dict], currency: str | None) -> dict:
    """Compact, lossless form of `years` (see the module docstring); inverse: unpack_years."""
    filings: list[list] = []
    fidx: dict[str, int] = {}
    concepts: list[str] = []
    cidx: dict[str, int] = {}

    def filing(accn: str, filed: str, form: str | None) -> int:
        if accn not in fidx:
            fidx[accn] = len(filings)
            filings.append([accn, filed, form])
        elif form and filings[fidx[accn]][2] is None:
            filings[fidx[accn]][2] = form
        return fidx[accn]

    usage: dict[str, dict[str, int]] = {}
    for row in years.values():
        for metric, v in row.items():
            usage.setdefault(metric, {}).setdefault(v["c"], 0)
            usage[metric][v["c"]] += 1
    default_concept = {m: max(sorted(u), key=lambda c: u[c]) for m, u in usage.items()}
    rows: dict[str, dict] = {}
    for end, row in years.items():
        out = {}
        for metric, v in row.items():
            p = {"v": v["v"], "a": filing(v["a"], v["f"], v["form"])}
            if v["c"] != default_concept[metric]:
                if v["c"] not in cidx:
                    cidx[v["c"]] = len(concepts)
                    concepts.append(v["c"])
                p["c"] = cidx[v["c"]]
            if v["u"] != _default_unit(metric, currency):
                p["u"] = v["u"]
            if "orig_a" in v:
                if v["orig"] != v["v"]:
                    p["o"] = v["orig"]
                if v["orig_a"] != v["a"]:
                    p["oa"] = filing(v["orig_a"], v["orig_f"], None)
            p.update({k: x for k, x in v.items() if k not in _CORE})
            out[metric] = p
        rows[end] = out
    return {"filings": filings, "default_concept": default_concept, "concepts": concepts, "rows": rows}


def unpack_years(packed: dict, currency: str | None) -> dict[str, dict]:
    filings, concepts, default = packed["filings"], packed["concepts"], packed["default_concept"]
    years: dict[str, dict] = {}
    for end, row in packed["rows"].items():
        out = {}
        for metric, p in row.items():
            accn, f, form = filings[p["a"]]
            v = {"v": p["v"], "c": concepts[p["c"]] if "c" in p else default[metric],
                 "u": p.get("u", _default_unit(metric, currency)), "a": accn, "f": f, "form": form}
            if not p.get("calculated"):
                oa = filings[p.get("oa", p["a"])]
                v.update({"orig": p.get("o", p["v"]), "orig_a": oa[0], "orig_f": oa[1]})
            v.update({k: x for k, x in p.items() if k not in ("v", "c", "u", "a", "o", "oa")})
            out[metric] = v
        years[end] = out
    return years


def compact_derived(derived: dict[str, dict]) -> dict[str, dict]:
    """Derived (calculated) metrics to 6 significant figures, with not-computable ones omitted.
    Reported values in `years` are never rounded."""
    return {end: {k: float(f"{x:.6g}") if isinstance(x, float) else x for k, x in row.items() if x is not None}
            for end, row in derived.items()}


def unpacked(snap: dict) -> dict:
    """A snapshot with `years` in the in-memory format, whichever format it was stored in."""
    if "years_packed" not in snap:
        return snap
    out = {k: v for k, v in snap.items() if k != "years_packed"}
    out["years"] = unpack_years(snap["years_packed"], snap.get("reporting_currency"))
    return out


def latest_securities(store: Store) -> dict[str, dict]:
    """t212_ticker -> latest version of each listing (absent ones included, flagged)."""
    latest: dict[str, dict] = {}
    for r in store.securities.read():
        latest[r["t212_ticker"]] = r
    return latest


def resolve(store: Store, symbol: str | None = None, company_id: str | None = None,
            isin: str | None = None) -> dict | None:
    """Find a present security by symbol, ISIN or company id (symbols are not unique
    across exchanges, so a US SEC-linked line is preferred for a bare symbol)."""
    secs = [s for s in latest_securities(store).values() if not s.get("absent")]
    if isin:
        hits = [s for s in secs if s["isin"] == isin]
    elif company_id:
        hits = [s for s in secs if s["company_id"] == company_id]
    else:
        hits = [s for s in secs if s["symbol"] == symbol.upper()]
    hits.sort(key=lambda s: (s.get("sec_match") != "high", s["t212_ticker"]))
    return hits[0] if hits else None


def last_snapshot(store: Store, company_id: str) -> dict | None:
    snaps = [s for s in store.fundamentals.read() if s["company_id"] == company_id]
    return unpacked(max(snaps, key=lambda s: s["retrieved_utc"])) if snaps else None


def record_methods(store: Store) -> None:
    store.methods.append({"rid": f"methods:{METHOD_VERSION}", "method_version": METHOD_VERSION,
                          "methods": METHODS, "recorded_utc": utc_now()})


def ingest_company(store: Store, sec: SecClient, security: dict, today: date | None = None,
                   max_age_s: float = 86400) -> tuple[dict, bool]:
    """Returns (snapshot, written). written=False when nothing changed since the last snapshot."""
    if security.get("sec_match") != "high" or not security.get("cik"):
        raise ValueError(f"{security['symbol']}: no verified SEC link (sec_match={security.get('sec_match')})")
    facts = sec.company_facts(security["cik"], max_age_s=max_age_s)
    profile = sec.submissions(security["cik"])
    sic = profile.get("sic") or None
    template = classify(sic)
    a = analyse(facts, today, template)
    # The snapshot identity is the filed data, the industry and the method version, not the
    # fetch time, so re-fetching unchanged filings writes nothing.
    input_hash = content_hash({"years": a["years"], "method": a["method_version"], "sic": sic})
    prev = last_snapshot(store, security["company_id"])
    if prev and prev["input_hash"] == input_hash:
        return prev, False
    record_methods(store)
    snap = {
        "rid": f"{security['company_id']}:{input_hash}",
        "company_id": security["company_id"], "cik": security["cik"], "entity_name": a["entity_name"],
        "source": f"SEC EDGAR XBRL companyfacts ({a['taxonomy']}, annual forms) + submissions (SIC)",
        "source_url": FACTS_URL.format(cik=int(security["cik"])),
        "profile_url": SUBMISSIONS_URL.format(cik=int(security["cik"])),
        "retrieved_utc": utc_now(), "input_hash": input_hash, "method_version": a["method_version"],
        "taxonomy": a["taxonomy"], "reporting_currency": a["reporting_currency"],
        "sic": sic, "sic_description": profile.get("sicDescription"), "industry_template": template,
        "screen_supported": supported(template),
        "value_types": {
            "years": "reported (XBRL as filed; 'o' = first filed value when it differs from 'v', the latest)",
            "derived": "calculated (formulas: methods ledger, by method_version)", "summary": "calculated"},
        "summary": a["summary"], "flags": a["flags"], "confidence": a["confidence"],
        "years_packed": pack_years(a["years"], a["reporting_currency"]),
        "derived": compact_derived(a["derived"]),
        "previous_snapshot": prev["rid"] if prev else None,
    }
    store.fundamentals.append(snap)
    return unpacked(snap), True
