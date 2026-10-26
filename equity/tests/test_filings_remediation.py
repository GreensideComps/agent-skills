"""Remediation of review findings P32-1 to P32-9 (mini fund Stage 2 §1). Offline: committed synthetic fixtures and
in-memory data only, and every test runs behind a guard that makes any network connection raise."""
import ast
import json
import multiprocessing
import socket
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from equity import filings as fl
from equity import filings_check as fc
from equity.filings_store import FilingStore, StoreError
from equity.sec import SecClient

EQUITY = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "sec"
SUB = FX / "submissions_CIK0009999999.json"
CIK = 9999999
UA = "fixture-test test@example.invalid"


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
    return {p.name.split(".hdr")[0]: p.read_bytes() for p in FX.glob("0009999999-*.hdr.*")}


def build(doc=None, hdrs=None, at="2026-10-23T12:00:00+00:00", status=None):
    doc = SUB.read_bytes() if doc is None else doc
    hdrs = headers() if hdrs is None else hdrs
    return {e["accession"]: e for e in fl.events_from_submissions(
        CIK, doc, at, hdrs, {a: "2026-10-23T12:00:01+00:00" for a in hdrs}, header_status=status)}


def with_extra_10q(doc_bytes):
    d = json.loads(doc_bytes)
    rec = d["filings"]["recent"]
    for k, v in rec.items():
        if isinstance(v, list):
            v.append({"accessionNumber": "0009999999-26-000099", "form": "10-Q", "filingDate": "2026-10-20",
                      "items": "", "acceptanceDateTime": "2026-10-20T16:00:00.000Z"}.get(k, ""))
    return json.dumps(d).encode()


# P32-1: available_at is never set at ingest; the PIT gate releases nothing without an approved validated report
def test_every_stored_event_has_null_available_at_and_a_proposed_time():
    ev = build()
    assert all(e["available_at"] is None and "acceptance_unverified" in e["missing_reasons"] for e in ev.values())
    assert sum(e["proposed_available_at"] is not None for e in ev.values()) == 6


def test_the_pit_gate_returns_none_unless_the_report_is_validated_and_approved(monkeypatch):
    e = build()["0009999999-22-000001"]
    validated = {"status": "validated", "basis": fl.BASIS}
    for rep in (None, {"status": "fail", "basis": fl.BASIS},
                {"status": "consistent_with_filing_dates", "basis": fl.BASIS}, validated):
        assert fl.pit_available_at(e, rep) is None
    assert fl.APPROVED_CROSSCHECK_SHA256 == frozenset()
    monkeypatch.setattr(fl, "APPROVED_CROSSCHECK_SHA256", frozenset({fl.sha256(fl.canonical(validated))}))
    assert fl.pit_available_at(e, validated) == e["proposed_available_at"]
    assert fl.pit_available_at(e, dict(validated, basis="other")) is None


def test_only_the_gate_and_the_check_read_the_proposed_time():
    for p in (EQUITY / "equity").glob("*.py"):
        if p.name in ("filings.py", "filings_check.py"):
            continue
        assert "proposed_available_at" not in p.read_text(), p.name
    tree = ast.parse((EQUITY / "equity" / "filings.py").read_text())
    readers = [f.name for f in tree.body if isinstance(f, ast.FunctionDef)
               and any(isinstance(n, ast.Constant) and n.value == "proposed_available_at" for n in ast.walk(f))]
    assert sorted(readers) == ["filing_event", "pit_available_at"]


# P32-2: record_id ignores the submissions document hash; provenance goes to observations.jsonl
def test_an_unrelated_new_filing_in_submissions_changes_no_event(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "t")
    st.append(list(build().values()))
    assert len(st.observations()) == 7
    counts = st.append(list(build(with_extra_10q(SUB.read_bytes())).values()))
    assert counts == {"written": 0, "unchanged": 7, "revisions": 0}
    assert len(st.observations()) == 14 and st.validate() == []


def test_a_changed_8k_in_submissions_is_exactly_one_revision(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "t")
    st.append(list(build().values()))
    d = json.loads(SUB.read_bytes())
    i = d["filings"]["recent"]["accessionNumber"].index("0009999999-22-000001")
    d["filings"]["recent"]["items"][i] = "2.02"
    assert st.append(list(build(json.dumps(d).encode()).values())) == {"written": 1, "unchanged": 6, "revisions": 1}


def test_same_bytes_later_add_observations_only(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "t")
    st.append(list(build().values()))
    before = st.events_path.read_bytes()
    st.append(list(build(at="2026-11-01T00:00:00+00:00").values()))
    assert st.events_path.read_bytes() == before and len(st.observations()) == 14
    st.append(list(build(at="2026-11-01T00:00:00+00:00").values()))
    assert len(st.observations()) == 14
    assert all("observation" not in e and "submissions" not in e["source"] for e in st.events())


# P32-3: the cross-check statuses
def _events(n_est=120, n_edt=120, shift_h=0, json_ok=True, independent=None, years=range(2010, 2021)):
    """Weekday 10:00 ET filings across years and both zones. `shift_h` moves the proposed time; `independent` is
    None (absent), 'equal' or an hour offset from the unshifted header time."""
    out, years, k = [], list(years), 0
    for month, n in ((1, n_est), (7, n_edt)):
        i = 0
        while i < n:
            y, day = years[k % len(years)], 5 + k % 20
            k += 1
            local = datetime(y, month, day, 10, 0, 0, tzinfo=fl.ET)
            if local.weekday() >= 5:
                continue
            i += 1
            true = local.astimezone(timezone.utc)
            prop = true + timedelta(hours=shift_h)
            e = {"form": "8-K", "accession": f"x-{k}", "available_at": None, "filed_date": local.date().isoformat(),
                 "proposed_available_at": prop.isoformat().replace("+00:00", "Z"),
                 "submissions_json_acceptance": prop.isoformat() if json_ok else None}
            if independent is not None:
                t = true if independent == "equal" else true + timedelta(hours=independent)
                e["independent_acceptance"] = {"time": t.isoformat(), "source_url": "https://example.invalid/i",
                                               "sha256": "0" * 64}
            out.append(e)
    return out


HOL = {datetime(2015, 12, 25).date()}


def test_a_4h_shift_without_json_is_only_consistent_not_validated():
    rep = fc.crosscheck(_events(shift_h=4, json_ok=False), HOL, "a" * 64)
    assert rep["status"] == "consistent_with_filing_dates" and rep["checked"] >= 200
    assert "json_unparseable" in rep["validation_blockers"]


def test_a_4h_shift_against_independent_times_fails_with_the_mismatches():
    rep = fc.crosscheck(_events(shift_h=4, independent="equal"), HOL, "a" * 64)
    assert rep["status"] == "fail" and len(rep["independent_mismatches"]) == rep["checked"]
    assert {m["seconds"] for m in rep["independent_mismatches"]} == {-14400}


def test_fully_consistent_synthetic_data_is_validated():
    rep = fc.crosscheck(_events(independent="equal"), HOL, "a" * 64)
    assert rep["status"] == "validated" and rep["validation_blockers"] == []
    assert rep["json_minus_header_seconds_by_zone"] == {"EDT": {0: 120}, "EST": {0: 120}}
    assert rep["json_offsets_need_owner_acceptance"] is True


def test_no_holidays_is_never_validated():
    ev = _events(independent="equal")
    assert fc.crosscheck(ev)["status"] == "consistent_with_filing_dates"
    assert fc.crosscheck(ev, HOL)["status"] == "consistent_with_filing_dates"  # no sha256 recorded


def test_one_unparseable_json_value_blocks_validation():
    ev = _events(independent="equal")
    ev[3] = dict(ev[3], submissions_json_acceptance="garbage")
    rep = fc.crosscheck(ev, HOL, "a" * 64)
    assert rep["status"] == "consistent_with_filing_dates" and rep["json_unparseable"] == [ev[3]["accession"]]


def test_the_cli_exits_zero_only_when_validated(tmp_path, capsys):
    p, hol = tmp_path / "ev.jsonl", tmp_path / "hol.txt"
    hol.write_text("2015-12-25\n")
    p.write_text("\n".join(json.dumps(e) for e in _events(independent="equal")))
    assert fc.main([str(p), "--holidays", str(hol)]) == 0
    assert json.loads(capsys.readouterr().out)["holidays_sha256"] == fl.sha256(b"2015-12-25\n")
    p.write_text("\n".join(json.dumps(e) for e in _events()))
    assert fc.main([str(p), "--holidays", str(hol)]) == 1


# P32-5: revert handling and the per-accession revision chain
def _one(items):
    d = json.loads(SUB.read_bytes())
    i = d["filings"]["recent"]["accessionNumber"].index("0009999999-22-000001")
    d["filings"]["recent"]["items"][i] = items
    return build(json.dumps(d).encode())["0009999999-22-000001"]


def test_a_then_b_then_a_writes_three_lines_and_a_revert(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "t")
    a, b = _one("2.02,9.01"), _one("2.02")
    for ev in (a, b, a):
        st.append([ev])
    lines = st.events()
    assert len(lines) == 3 and st.validate() == []
    cur = st.current()["0009999999-22-000001"]
    assert cur["revision"] == 2 and cur["items"] == ["2.02", "9.01"]
    assert cur["revision_reason"] == f"reverted_to:{a['record_id']}"


def test_a_then_a_writes_one_line(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "t")
    a = _one("2.02,9.01")
    assert st.append([a]) == {"written": 1, "unchanged": 0, "revisions": 0}
    assert st.append([a]) == {"written": 0, "unchanged": 1, "revisions": 0}


def test_a_wrong_supersedes_is_a_validate_error(tmp_path):
    st = FilingStore(tmp_path, clock=lambda: "t")
    st.append([_one("2.02,9.01")])
    st.append([_one("2.02")])
    lines = st.events_path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["supersedes"] = "f" * 64
    rec["prev"] = json.loads(lines[1])["prev"]
    st.events_path.write_text(lines[0] + "\n" + json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
    assert any("revision chain broken" in x for x in st.validate())
    with pytest.raises(StoreError):
        st.append([])


# P32-4 and P32-8: accession normalisation and per-filing mismatches
def test_an_undashed_header_accession_is_the_same_filing():
    h = headers()
    h["0009999999-22-000001"] = h["0009999999-22-000001"].replace(
        b"<ACCESSION-NUMBER>0009999999-22-000001", b"<ACCESSION-NUMBER>000999999922000001")
    plain, undashed = build()["0009999999-22-000001"], build(hdrs=h)["0009999999-22-000001"]
    assert "header_accession_mismatch" not in undashed["missing_reasons"]
    assert undashed["proposed_available_at"] == plain["proposed_available_at"]
    assert undashed["accession_raw"]["header"] == "000999999922000001"


@pytest.mark.parametrize("raw", ["00099999992200000", "0009999999-22-00000A", None, ""])
def test_malformed_accessions_are_refused(raw):
    assert fl.normalise_accession(raw) == (None, "accession_unparseable")


def test_a_different_header_accession_is_a_mismatch():
    h = headers()
    h["0009999999-22-000001"] = h["0009999999-22-000001"].replace(b"22-000001", b"22-000077")
    e = build(hdrs=h)["0009999999-22-000001"]
    assert "header_accession_mismatch" in e["missing_reasons"] and e["proposed_available_at"] is None


# P32-6: fetch failures are labelled, never parsed
def _client(transport, now):
    def clock():
        return now[0]

    def sleep(s):
        now[0] += s
    return SecClient(ua=UA, transport=transport, sleep=sleep, clock=clock)


def test_a_429_header_is_labelled_and_kept_raw(tmp_path):
    now, sent = [0.0], []

    def transport(url, hdrs, timeout):
        sent.append(now[0])
        return 429, b"<html>Too Many Requests</html>"
    st = FilingStore(tmp_path)
    accs = ["0009999999-22-000001", "0009999999-22-000003"]
    bodies, status, times = fl.fetch_headers(_client(transport, now), st, CIK, accs)
    ev = build(hdrs=bodies, status=status)
    e = ev["0009999999-22-000001"]
    assert "header_fetch_failed:429" in e["missing_reasons"] and e["proposed_available_at"] is None
    assert e["source"]["header"]["http_status"] == 429
    assert st.get_raw(e["source"]["header"]["sha256"]) == b"<html>Too Many Requests</html>"
    assert all(b - a >= 0.1 for a, b in zip(sent, sent[1:]))


def test_a_connection_error_is_labelled(tmp_path):
    def transport(url, hdrs, timeout):
        raise urllib.error.URLError("unreachable")
    bodies, status, _ = fl.fetch_headers(_client(transport, [0.0]), FilingStore(tmp_path), CIK,
                                         ["0009999999-22-000001"])
    assert bodies == {} and status == {"0009999999-22-000001": "error:URLError"}
    e = build(hdrs=bodies, status=status)["0009999999-22-000001"]
    assert "header_fetch_error:URLError" in e["missing_reasons"] and e["proposed_available_at"] is None


def test_existing_sec_client_methods_are_unchanged():
    import subprocess
    try:
        old = subprocess.run(["git", "show", "origin/master:equity/equity/sec.py"], cwd=EQUITY, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("master's sec.py is not available in this checkout")

    def methods(src):
        tree = ast.parse(src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SecClient")
        return {f.name: ast.dump(f) for f in cls.body if isinstance(f, ast.FunctionDef)}
    before, after = methods(old), methods((EQUITY / "equity" / "sec.py").read_text())
    for name, dump in before.items():
        if name != "get_raw":
            assert after[name] == dump, name


# P32-7: header vs JSON disagreements
def test_type_and_filed_date_disagreements_are_reasons():
    h = headers()
    h["0009999999-22-000001"] = h["0009999999-22-000001"].replace(b"<TYPE>8-K", b"<TYPE>10-K").replace(
        b"<FILING-DATE>20220728", b"<FILING-DATE>19990101")
    e = build(hdrs=h)["0009999999-22-000001"]
    assert {"type_differs_json_vs_header", "filed_date_differs_json_vs_header"} <= set(e["missing_reasons"])
    assert e["items_rule"] == "json_items; conflicts excluded"
    assert "filed_date_differs_json_vs_header" not in build()["0009999999-22-000001"]["missing_reasons"]


def test_an_items_conflict_is_flagged():
    e = _one("2.02")
    assert e["items_conflict"] is True and "items_differ_json_vs_header" in e["missing_reasons"]
    assert build()["0009999999-22-000001"]["items_conflict"] is False


# P32-9: two processes appending at once lose nothing
def _writer(root, tag, q):
    try:
        st = FilingStore(root, clock=lambda: "t")
        for i in range(50):
            st.append([{"accession": f"{tag}-{i}", "record_id": f"{tag}-{i}"}])
        q.put("ok")
    except Exception as e:  # pragma: no cover - reported to the parent
        q.put(repr(e))


def test_two_processes_appending_keep_every_line(tmp_path):
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()
    ps = [ctx.Process(target=_writer, args=(tmp_path, t, q)) for t in ("a", "b")]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    assert [q.get(timeout=5) for _ in ps] == ["ok", "ok"]
    st = FilingStore(tmp_path)
    assert len(st.events()) == 100 and st.validate() == []


def test_no_fcntl_needs_single_writer(tmp_path, monkeypatch):
    from equity import filings_store
    monkeypatch.setattr(filings_store, "fcntl", None)
    with pytest.raises(StoreError):
        FilingStore(tmp_path).append([])
    assert FilingStore(tmp_path, single_writer=True).append([]) == {"written": 0, "unchanged": 0, "revisions": 0}
