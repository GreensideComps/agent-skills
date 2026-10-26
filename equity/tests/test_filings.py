"""SEC 8-K filing events, store and header cross-check (mini fund Stage 2 §1). Offline: committed synthetic
fixtures only, and every test runs behind a guard that makes any network connection raise."""
import json
import socket
from datetime import date
from pathlib import Path

import pytest

from equity import filings as fl
from equity import filings_check as fc
from equity.filings_store import FilingStore, StoreError
from equity.sec import SecClient

FX = Path(__file__).resolve().parent / "fixtures" / "sec"
SUB = FX / "submissions_CIK0009999999.json"
CIK = 9999999
THANKSGIVING_2021 = {date(2021, 11, 25)}


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise NetworkBlocked("network access attempted in an offline test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def headers():
    out = {}
    for p in FX.glob("0009999999-*.hdr.*"):
        out[p.name.split(".hdr")[0]] = p.read_bytes()
    return out


def build(hdrs=None):
    hdrs = headers() if hdrs is None else hdrs
    return {e["accession"]: e for e in fl.events_from_submissions(
        CIK, SUB.read_bytes(), "2026-10-23T12:00:00+00:00", hdrs, {a: "2026-10-23T12:00:01+00:00" for a in hdrs})}


def test_the_network_guard_blocks_connections():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("www.sec.gov", 443), timeout=1)


# 1. header acceptance time -> UTC in both standard and daylight time, and on the change days
@pytest.mark.parametrize("raw,utc", [
    ("20220728163028", "2022-07-28T20:30:28Z"),   # EDT, UTC-4
    ("20210210090500", "2021-02-10T14:05:00Z"),   # EST, UTC-5
    ("20210314013000", "2021-03-14T06:30:00Z"),   # spring-forward day, before the change (EST)
    ("20210314030000", "2021-03-14T07:00:00Z"),   # spring-forward day, after the change (EDT)
    ("20211107003000", "2021-11-07T04:30:00Z"),   # fall-back day, before the repeated hour (EDT)
    ("20211107023000", "2021-11-07T07:30:00Z"),   # fall-back day, after it (EST)
])
def test_header_time_converts_to_utc(raw, utc):
    assert fl.acceptance_to_utc(raw) == (utc, None)


@pytest.mark.parametrize("raw,reason", [
    ("20210314023000", "nonexistent_local_time"),   # 02:30 does not exist on 14 Mar 2021
    ("20211107013000", "ambiguous_local_time"),     # 01:30 happens twice on 7 Nov 2021
    (None, "header_acceptance_missing"),
    ("2021-02-10 09:05", "header_acceptance_unparseable"),
    ("20211340090500", "header_acceptance_unparseable"),
])
def test_impossible_or_ambiguous_times_are_null_not_guessed(raw, reason):
    assert fl.acceptance_to_utc(raw) == (None, reason)


# 2. the JSON time is kept verbatim and never used for available_at
def test_json_acceptance_is_kept_verbatim_and_not_used():
    ev = build()
    raw = json.loads(SUB.read_text())["filings"]["recent"]
    for acc, js in zip(raw["accessionNumber"], raw["acceptanceDateTime"]):
        if acc in ev:
            assert ev[acc]["submissions_json_acceptance"] == js
    e = ev["0009999999-22-000003"]
    assert e["available_at"] is None
    assert e["proposed_available_at"] == "2022-07-29T20:30:28Z" != e["submissions_json_acceptance"]
    assert e["available_at_basis"] == "sec_header_acceptance_et"
    assert e["available_at_status"] == "proposed_pending_crosscheck"


# 3. items
@pytest.mark.parametrize("raw,out", [
    ("2.02,9.01", (["2.02", "9.01"], None)),
    ("9.01, 2.02", (["2.02", "9.01"], None)),
    ("", (None, "items_missing")),
    (None, (None, "items_missing")),
    ("Item 2.02", (None, "items_unparseable")),
])
def test_items_parse_or_are_null_with_a_reason(raw, out):
    assert fl.parse_items(raw) == out


def test_empty_items_are_never_filled_from_the_header():
    e = build()["0009999999-21-000006"]
    assert e["items"] is None and e["header_items"] is None and "items_missing" in e["missing_reasons"]


def test_both_header_formats_parse():
    tagged = fl.parse_header((FX / "0009999999-22-000001.hdr.sgml").read_text())
    colon = fl.parse_header((FX / "0009999999-21-000002.hdr.txt").read_text())
    assert tagged["acceptance_datetime"] == "20220728163028" and tagged["items"] == ["2.02", "9.01"]
    assert colon["acceptance_datetime"] == "20210210090500" and colon["accession"] == "0009999999-21-000002"
    assert colon["type"] == "8-K" and len(colon["item_descriptions"]) == 2 and colon["items"] == []


# 4. amendments
def test_amendment_is_flagged_and_the_original_is_not_guessed():
    e = build()["0009999999-21-000004"]
    assert e["form"] == "8-K/A" and e["is_amendment"] is True and e["amends"] is None


def test_only_8k_forms_become_events():
    ev = build()
    assert "0009999999-21-000008" not in ev and len(ev) == 7


# 6. missing header
def test_a_missing_header_gives_null_available_at():
    e = build()["0009999999-21-000007"]
    assert e["available_at"] is None and e["proposed_available_at"] is None
    assert e["available_at_status"] == "unavailable"
    assert e["missing_reasons"] == ["acceptance_unverified", "header_missing"] and e["source"]["header"] is None


def test_a_header_for_a_different_accession_is_labelled_and_the_batch_continues():
    h = headers()
    h["0009999999-22-000003"] = h["0009999999-22-000001"]
    ev = build(h)
    assert len(ev) == 7
    bad = [a for a, e in ev.items() if "header_accession_mismatch" in e["missing_reasons"]]
    assert bad == ["0009999999-22-000003"] and ev[bad[0]]["proposed_available_at"] is None


# 5. store: idempotent, revisions append, history never edited
def test_reingesting_identical_bytes_writes_nothing(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "2026-10-23T12:00:00+00:00")
    first = st.append(list(build().values()))
    again = fl.events_from_submissions(CIK, SUB.read_bytes(), "2026-11-01T00:00:00+00:00", headers(), {})
    second = st.append(again)
    assert first == {"written": 7, "unchanged": 0, "revisions": 0}
    assert second == {"written": 0, "unchanged": 7, "revisions": 0}
    assert st.validate() == []


def test_changed_bytes_for_an_accession_are_a_revision(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "t")
    st.append(list(build().values()))
    before = st.events_path.read_bytes()
    h = headers()
    h["0009999999-22-000001"] = h["0009999999-22-000001"].replace(b"163028", b"163029")
    counts = st.append([build(h)["0009999999-22-000001"]])
    assert counts == {"written": 1, "unchanged": 0, "revisions": 1}
    assert st.events_path.read_bytes().startswith(before)
    cur = st.current()["0009999999-22-000001"]
    assert cur["revision"] == 1 and cur["revision_reason"] == "content_changed"
    assert cur["supersedes"] == build()["0009999999-22-000001"]["record_id"]


def test_an_edited_line_breaks_the_chain(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "t")
    st.append(list(build().values()))
    lines = st.events_path.read_text().splitlines()
    lines[1] = lines[1].replace("1.01", "1.02")
    st.events_path.write_text("\n".join(lines) + "\n")
    assert st.validate()
    with pytest.raises(StoreError):
        st.append([])


def test_raw_bytes_are_stored_by_hash_and_checked(tmp_path):
    st = FilingStore(tmp_path)
    body = (FX / "0009999999-22-000001.hdr.sgml").read_bytes()
    h = st.put_raw(body)
    assert st.put_raw(body) == h and st.get_raw(h) == body
    (st.raw_dir / h).write_bytes(b"tampered")
    with pytest.raises(StoreError):
        st.get_raw(h)


# 7. pacing (fake clock and transport; nothing leaves the process)
def test_requests_are_paced_at_least_0_1_s_apart():
    now, sent = [0.0], []

    def clock():
        return now[0]

    def sleep(s):
        now[0] += s

    def transport(url, hdrs, timeout):
        sent.append(now[0])
        assert hdrs["User-Agent"] == "fixture-test test@example.invalid"
        return 200, b"<ACCEPTANCE-DATETIME>20220728163028\n"

    c = SecClient(ua="fixture-test test@example.invalid", transport=transport, sleep=sleep, clock=clock)
    for acc in ["0009999999-22-000001", "0009999999-22-000003", "0009999999-21-000004"]:
        r = c.get_raw(fl.header_url(CIK, acc))
        assert r["status"] == 200 and r["retrieved_at"]
    assert all(b - a >= 0.1 for a, b in zip(sent, sent[1:])) and c.min_interval >= 0.1


def test_header_url_shape():
    assert fl.header_url(CIK, "0009999999-22-000001") == \
        "https://www.sec.gov/Archives/edgar/data/9999999/000999999922000001/0009999999-22-000001.hdr.sgml"


# cross-check
def test_crosscheck_reports_offsets_without_interpreting_them():
    rep = fc.crosscheck(list(build().values()), THANKSGIVING_2021)
    assert rep["status"] == "insufficient_sample" and rep["checked"] == 6
    # fixture offsets are invented: two equal, one +4 h, one -5 h (see fixtures/sec/README.md)
    assert rep["json_minus_header_seconds_by_zone"] == {"EDT": {0: 2, 14400: 1}, "EST": {-18000: 1, 0: 2}}
    assert rep["available_at_null"] == ["0009999999-21-000007"] and rep["basis"] == "sec_header_acceptance_et"
    assert rep["unexplained_filed_dates"] == []
    assert rep["limitations"] and "not interpreted" in rep["note"]


def test_a_late_filing_needs_the_holiday_list_to_be_explained():
    ev = list(build().values())
    without = fc.crosscheck(ev)
    assert [u["accession"] for u in without["unexplained_filed_dates"]] == ["0009999999-21-000005"]
    assert fc.crosscheck(ev, THANKSGIVING_2021)["unexplained_filed_dates"] == []


def _synthetic_events(n_est, n_edt, years, bad=0):
    """Many valid events in the FilingEvent shape, built in memory (no fixture files needed)."""
    out, k = [], 0
    for zone, n, month in (("EST", n_est, 1), ("EDT", n_edt, 7)):
        for i in range(n):
            y = years[i % len(years)]
            raw = f"{y}{month:02d}{10 + i % 15:02d}100000"
            avail, _ = fl.acceptance_to_utc(raw)
            filed = f"{y}-{month:02d}-{10 + i % 15:02d}"
            if k < bad:
                filed = f"{y}-{month:02d}-{11 + i % 15:02d}"
            out.append({"form": "8-K", "accession": f"x-{k}", "available_at": None, "proposed_available_at": avail,
                        "filed_date": filed, "submissions_json_acceptance": avail})
            k += 1
    return out


def test_the_check_passes_only_with_the_full_sample_and_no_problems():
    years = list(range(2010, 2021))
    weekdays_only = [e for e in _synthetic_events(150, 150, years)
                     if date.fromisoformat(e["filed_date"]).weekday() < 5]
    rep = fc.crosscheck(weekdays_only)
    assert rep["checked"] >= 200 and rep["status"] == "consistent_with_filing_dates", rep["unexplained_filed_dates"][:3]
    assert fc.crosscheck(weekdays_only[:150])["status"] == "insufficient_sample"
    broken = list(weekdays_only)
    broken[0] = dict(broken[0], filed_date="1999-01-01")
    assert fc.crosscheck(broken)["status"] == "fail"
    nulls = weekdays_only + [{"form": "8-K", "accession": "y", "proposed_available_at": None, "filed_date": "2015-01-05"}]
    assert fc.crosscheck(nulls)["status"] == "fail"


def test_sample_selection_is_deterministic_and_spread():
    rows = [{"form": "8-K", "accessionNumber": f"a-{y}-{m}-{i}", "filingDate": f"{y}-{m:02d}-1{i}"}
            for y in range(2008, 2023) for m in (1, 7) for i in range(5)]
    s1, s2 = fc.select_sample(rows, n=60), fc.select_sample(rows, n=60)
    assert s1 == s2 and len(set(s1)) == 60
    assert len({a.split("-")[1] for a in s1}) == 15


def test_events_carry_limitations_and_contract_version():
    e = build()["0009999999-22-000001"]
    assert e["schema"] == "FilingEvent" and e["schema_version"] == "contracts-0.1"
    assert e["items"] == ["2.02", "9.01"] and e["header_items"] == ["2.02", "9.01"]
    assert fl.LIMITATIONS and any("survivorship" in x for x in fl.LIMITATIONS)
