"""SEC 8-K filing events (mini fund Stage 2 §1, owner decisions D-D and U2 of 2026-10-23).

Builds `FilingEvent` records (docs/minifund/INTERFACES.md §1.2) from two inputs:

* the submissions JSON (`data.sec.gov/submissions/CIK##########.json`, the `filings.recent` arrays or a
  `filings.files[]` page): accession, form, filing date, item codes and `acceptanceDateTime`;
* the filing's SEC header (`<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS`, Eastern time).

Timestamp rule (owner review point 4). The header time is the **proposed** source of `available_at`. It stays
provisional (`available_at_status: "proposed_pending_crosscheck"`) until the 200-filing cross-check in
`filings_check.py` passes. The JSON `acceptanceDateTime` is stored as the exact string SEC returned and is never
parsed into `available_at`. One filing seen on 2026-10-23 differed by four hours; nothing here assumes any offset.

No guessed values (owner review point 5). A value that is missing, unparseable or ambiguous is `None` with a
`missing_reasons` entry. Nothing is filled from another field.

Header formats parsed: the tagged form (`<ACCEPTANCE-DATETIME>20260730163028`, `<ITEMS>2.02`) and the
"KEY:<tab>value" lines of a full-submission header. The fixtures are hand-written in those documented shapes
[not downloaded]. The parser must be checked against real headers before any bulk use (owner approval U3).

This module makes no network request. Fetching is `SecClient.get_raw`, which only the CLI in a later, separately
approved step would call.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SCHEMA = "FilingEvent"
SCHEMA_VERSION = "contracts-0.1"
METHOD_VERSION = "filings-0.1"
TAXONOMY_VERSION = "8k-items-1.0"
EIGHT_K_FORMS = {"8-K", "8-K/A"}
HEADER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}.hdr.sgml"
ITEM_RE = re.compile(r"^\d\.\d\d$")
LIMITATIONS = (
    "available_at is proposed (SEC header acceptance time, Eastern) until the 200-filing cross-check passes.",
    "The submissions JSON acceptanceDateTime is kept verbatim and not interpreted.",
    "8-K item codes before August 2004 use an older scheme and are not mapped.",
    "Event lists include delisted filers, but free price data does not (survivorship).",
    "SEC data is free to use; fair-access rules (User-Agent with contact, <= 10 requests/second) apply.",
)


class FilingError(ValueError):
    pass


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --- submissions JSON -------------------------------------------------------------------------------------------

def submission_rows(doc: dict) -> list[dict]:
    """Rows from a submissions document: either the full document (`filings.recent`) or a `filings.files[]` page,
    whose columnar arrays sit at the top level. Values are kept exactly as given."""
    cols = doc.get("filings", {}).get("recent") if "filings" in doc else doc
    if not isinstance(cols, dict) or "accessionNumber" not in cols:
        raise FilingError("no columnar filing arrays found")
    n = len(cols["accessionNumber"])
    bad = [k for k, v in cols.items() if isinstance(v, list) and len(v) != n]
    if bad:
        raise FilingError(f"columns of unequal length: {bad}")
    return [{k: v[i] for k, v in cols.items() if isinstance(v, list)} for i in range(n)]


def parse_items(raw) -> tuple[list[str] | None, str | None]:
    """'2.02,9.01' -> (['2.02', '9.01'], None). Empty, missing or malformed -> (None, reason)."""
    if raw is None:
        return None, "items_missing"
    if not isinstance(raw, str):
        return None, "items_unparseable"
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None, "items_missing"
    if not all(ITEM_RE.match(p) for p in parts):
        return None, "items_unparseable"
    return sorted(set(parts)), None


# --- SEC header -------------------------------------------------------------------------------------------------

_TAG = re.compile(r"^<([A-Z0-9-]+)>(.*)$")
_KV = re.compile(r"^\s*([A-Z][A-Z0-9 /&-]*?):\s*(.*?)\s*$")


def parse_header(text: str) -> dict:
    """Tagged values (`<ACCEPTANCE-DATETIME>...`, repeated `<ITEMS>...`) and 'KEY: value' lines. Unknown lines are
    ignored; nothing is inferred."""
    out = {"acceptance_datetime": None, "accession": None, "type": None, "filing_date": None, "period": None,
           "items": [], "item_descriptions": []}
    for line in text.splitlines():
        line = line.rstrip()
        m = _TAG.match(line.strip())
        if m:
            tag, val = m.group(1), m.group(2).strip()
            if not val:
                continue
            if tag == "ACCEPTANCE-DATETIME":
                out["acceptance_datetime"] = val
            elif tag == "ACCESSION-NUMBER":
                out["accession"] = val
            elif tag == "TYPE" and out["type"] is None:
                out["type"] = val
            elif tag == "FILING-DATE":
                out["filing_date"] = val
            elif tag == "PERIOD":
                out["period"] = val
            elif tag == "ITEMS":
                out["items"].append(val)
            continue
        m = _KV.match(line)
        if m:
            key, val = m.group(1).strip(), m.group(2)
            if not val:
                continue
            if key == "ACCESSION NUMBER" and out["accession"] is None:
                out["accession"] = val
            elif key == "CONFORMED SUBMISSION TYPE" and out["type"] is None:
                out["type"] = val
            elif key == "FILED AS OF DATE" and out["filing_date"] is None:
                out["filing_date"] = val
            elif key == "CONFORMED PERIOD OF REPORT" and out["period"] is None:
                out["period"] = val
            elif key == "ITEM INFORMATION":
                out["item_descriptions"].append(val)
    return out


def acceptance_to_utc(raw: str | None) -> tuple[str | None, str | None]:
    """'YYYYMMDDHHMMSS' in America/New_York -> (UTC ISO string, None), or (None, reason). Times that do not exist
    (spring-forward gap) or are ambiguous (fall-back hour) are not resolved by guessing."""
    if not raw:
        return None, "header_acceptance_missing"
    if not re.fullmatch(r"\d{14}", raw):
        return None, "header_acceptance_unparseable"
    try:
        naive = datetime.strptime(raw, "%Y%m%d%H%M%S")
    except ValueError:
        return None, "header_acceptance_unparseable"
    a, b = naive.replace(tzinfo=ET, fold=0), naive.replace(tzinfo=ET, fold=1)
    if a.astimezone(timezone.utc).astimezone(ET).replace(tzinfo=None) != naive:
        return None, "nonexistent_local_time"
    if a.utcoffset() != b.utcoffset():
        return None, "ambiguous_local_time"
    return a.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), None


def et_zone_name(available_at: str | None) -> str | None:
    if available_at is None:
        return None
    return datetime.fromisoformat(available_at.replace("Z", "+00:00")).astimezone(ET).tzname()


# --- FilingEvent ------------------------------------------------------------------------------------------------

def header_url(cik: int, accession: str) -> str:
    return HEADER_URL.format(cik=int(cik), acc_nodash=accession.replace("-", ""), acc=accession)


def filing_event(cik: int, row: dict, header: dict | None, *, header_sha256: str | None, header_url_: str | None,
                 header_retrieved_at: str | None, submissions_sha256: str, submissions_retrieved_at: str,
                 git_commit: str | None = None) -> dict:
    """One FilingEvent from a submissions row and (optionally) its parsed header."""
    reasons = []
    form = row.get("form")
    if form not in EIGHT_K_FORMS:
        raise FilingError(f"form {form!r} is not an 8-K")
    items, why = parse_items(row.get("items"))
    if why:
        reasons.append(why)
    if header is None:
        available_at, why = None, "header_missing"
        header_items = None
    else:
        available_at, why = acceptance_to_utc(header.get("acceptance_datetime"))
        header_items = sorted(set(header["items"])) or None
        if header.get("accession") and header["accession"] != row.get("accessionNumber"):
            raise FilingError(f"header accession {header['accession']} != {row.get('accessionNumber')}")
    if why:
        reasons.append(why)
    if items is not None and header_items is not None and items != header_items:
        reasons.append("items_differ_json_vs_header")
    body = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "cik": int(cik),
        "accession": row.get("accessionNumber"),
        "form": form,
        "is_amendment": form.endswith("/A"),
        "amends": None,  # the header does not reliably name the original; never guessed
        "items": items,
        "header_items": header_items,
        "taxonomy_version": TAXONOMY_VERSION,
        "filed_date": row.get("filingDate"),
        "period_of_report_date": row.get("reportDate") or None,
        "acceptance_time_source": None if header is None else header.get("acceptance_datetime"),
        "available_at": available_at,
        "available_at_basis": "sec_header_acceptance_et",
        "available_at_status": "proposed_pending_crosscheck" if available_at else "unavailable",
        "source_tz": "America/New_York",
        "submissions_json_acceptance": row.get("acceptanceDateTime"),
        "missing_reasons": sorted(set(reasons)),
        "source": {
            "submissions": {"sha256": submissions_sha256},
            "header": None if header is None else {"url": header_url_, "sha256": header_sha256},
        },
    }
    # record_id covers content and source hashes but not retrieval times, so re-reading identical bytes later
    # gives the same id and the store writes nothing
    body["record_id"] = sha256(canonical(body))
    body["source"]["submissions"]["retrieved_at"] = submissions_retrieved_at
    if header is not None:
        body["source"]["header"]["retrieved_at"] = header_retrieved_at
    body["writer"] = {"component": "equity.filings", "method_version": METHOD_VERSION, "git_commit": git_commit}
    return body


def events_from_submissions(cik: int, doc_bytes: bytes, retrieved_at: str, headers: dict[str, bytes],
                            header_retrieved_at: dict[str, str], git_commit: str | None = None) -> list[dict]:
    """FilingEvents for every 8-K and 8-K/A in a submissions document. `headers` maps accession -> raw header bytes
    for the filings whose header was fetched; others get `available_at: None` (`header_missing`)."""
    doc_sha = sha256(doc_bytes)
    out = []
    for row in submission_rows(json.loads(doc_bytes)):
        if row.get("form") not in EIGHT_K_FORMS:
            continue
        acc = row.get("accessionNumber")
        raw = headers.get(acc)
        hdr = None if raw is None else parse_header(raw.decode("latin-1"))
        out.append(filing_event(cik, row, hdr, header_sha256=None if raw is None else sha256(raw),
                                header_url_=None if raw is None else header_url(cik, acc),
                                header_retrieved_at=header_retrieved_at.get(acc), submissions_sha256=doc_sha,
                                submissions_retrieved_at=retrieved_at, git_commit=git_commit))
    return out


def business_days_after(d: date, n: int, holidays: set[date] = frozenset()) -> list[date]:
    """The next n weekdays after d that are not in `holidays`."""
    out, cur = [], d
    while len(out) < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5 and cur not in holidays:
            out.append(cur)
    return out
