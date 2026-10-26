"""Daily-price provenance and revision detection (mini fund Stage 2 §2). Offline: committed synthetic fixtures only,
and every test runs behind a guard that makes any network connection raise."""
import gzip
import hashlib
import json
import shutil
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import daily_prices_to_2022 as dp  # noqa: E402
import edge_split  # noqa: E402
import price_provenance as pp  # noqa: E402
import price_revisions as pr  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures" / "prices"
CUT = "period1=1640995200&period2=1672531200"
URL_SPLITS = f"https://query1.finance.yahoo.com/v8/finance/chart/SYN?{CUT}&interval=1d&events=div%7Csplit"
URL_PLAIN = f"https://query1.finance.yahoo.com/v8/finance/chart/SYN?{CUT}&interval=1d"
T0, T1 = "2026-10-23T12:00:00+00:00", "2026-10-30T12:00:00+00:00"


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


def parse(name, url=URL_SPLITS, retrieved_at=T0, sessions=None):
    return pp.parse_chart((FX / name).read_bytes(), symbol="SYN", url=url, retrieved_at=retrieved_at,
                          sessions=sessions)


def test_the_network_guard_blocks_connections():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("query1.finance.yahoo.com", 443), timeout=1)


# 1. raw hash and retrieved_at recorded; parsing twice is identical
def test_raw_body_hash_and_retrieval_time_are_recorded():
    body = (FX / "chart_SYN_pull1.json").read_bytes()
    out = parse("chart_SYN_pull1.json")
    assert out["raw"] == {"url": URL_SPLITS, "sha256": hashlib.sha256(body).hexdigest(), "retrieved_at": T0,
                          "symbol": "SYN", "source": pp.SOURCE}
    assert all(r["source"]["raw_sha256"] == out["raw"]["sha256"] for r in out["records"])
    assert parse("chart_SYN_pull1.json") == out


def test_record_ids_ignore_the_retrieval_time():
    a = [r["record_id"] for r in parse("chart_SYN_pull1.json")["records"]]
    b = [r["record_id"] for r in parse("chart_SYN_pull1.json", retrieved_at=T1)["records"]]
    assert a == b


def test_session_dates_come_from_the_exchange_time_zone():
    assert [r["session_date"] for r in parse("chart_SYN_pull1.json")["records"]] == \
        ["2022-12-23", "2022-12-27", "2022-12-28", "2022-12-29", "2022-12-30"]
    with pytest.raises(pp.PriceError):
        parse("chart_SYN_no_tz.json")


# decision-time versus adjusted prices (P33-1: replaces the earlier test that treated the inference as verified)
def test_decision_time_price_undoes_the_later_reverse_split_but_is_flagged_unverified():
    recs = {r["session_date"]: r for r in parse("chart_SYN_pull1.json")["records"]}
    assert recs["2022-12-23"]["close"] == 10.0
    assert recs["2022-12-23"]["close_unadjusted"] == pytest.approx(1.0)
    assert recs["2022-12-28"]["close_unadjusted"] == pytest.approx(1.2)
    assert recs["2022-12-29"]["close_unadjusted"] == 13.0  # on and after the split day nothing changes
    for r in recs.values():
        assert r["price_kinds"]["close_unadjusted"] == "decision_unadjusted_unverified"
        assert r["split_basis"] == "vendor_reported_unverified"
        assert "split_history_unverified" in r["missing_reasons"]


def test_without_split_history_the_decision_price_is_null_not_the_adjusted_close():
    for r in parse("chart_SYN_pull1.json", url=URL_PLAIN)["records"]:
        assert r["close_unadjusted"] is None and "split_history_missing" in r["missing_reasons"]
        assert r["split_basis"] == "not_requested"


# close times
def test_without_a_sourced_calendar_available_at_is_null():
    for r in parse("chart_SYN_pull1.json")["records"]:
        assert r["available_at"] is None and "close_time_unverified" in r["missing_reasons"]


def test_close_times_come_from_the_calendar_including_early_closes(monkeypatch):
    h = hashlib.sha256((FX / "sessions_synthetic.csv").read_bytes()).hexdigest()
    monkeypatch.setattr(pp, "APPROVED_CALENDARS", frozenset({h}))  # exercises the maths only; nothing is approved
    cal = pp.load_sessions(FX / "sessions_synthetic.csv", h)
    recs = {r["session_date"]: r for r in parse("chart_SYN_pull1.json", sessions=cal)["records"]}
    assert {r["calendar_sha256"] for r in recs.values()} == {h}
    assert recs["2022-12-23"]["available_at"] == "2022-12-23T18:00:00Z"   # 13:00 EST (synthetic early close)
    assert recs["2022-12-27"]["available_at"] == "2022-12-27T21:00:00Z"   # 16:00 EST
    assert recs["2022-12-30"]["available_at"] is None                      # not in the calendar


def test_a_calendar_row_without_a_source_is_refused(tmp_path, monkeypatch):
    p = tmp_path / "cal.csv"
    p.write_text("date,close_et,source,source_retrieved_at\n2022-12-27,16:00,,\n")
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setattr(pp, "APPROVED_CALENDARS", frozenset({h}))
    with pytest.raises(pp.PriceError):
        pp.load_sessions(p, h)


# 2-3. revision classes
def test_a_dividend_rescaling_is_classified_not_unexplained():
    rep = pr.compare(parse("chart_SYN_pull1.json")["records"],
                     parse("chart_SYN_pull2_dividend.json", retrieved_at=T1)["records"])
    assert rep["counts"] == {"dividend_adjustment": 2} and rep["unexplained"] == 0
    assert {e["factor"] for e in rep["events"]} == {0.99}


def test_a_lone_changed_close_is_unexplained_and_reported():
    rep = pr.compare(parse("chart_SYN_pull1.json")["records"],
                     parse("chart_SYN_pull3_unexplained.json", retrieved_at=T1)["records"])
    assert rep["counts"] == {"unexplained": 1} and rep["events"][0]["session_date"] == "2022-12-28"
    assert rep["events"][0]["old"]["close"] == 12.0 and rep["events"][0]["new"]["close"] == 12.5


def test_a_split_rescaling_of_close_and_adjclose_is_classified():
    old = parse("chart_SYN_pull1.json")["records"]
    new = [dict(r) for r in old]
    for r in new[:2]:
        r["close"], r["adjclose"] = r["close"] / 2, r["adjclose"] / 2
    rep = pr.compare(old, new)
    assert rep["counts"] == {"split_adjustment": 2} and rep["unexplained"] == 0


def test_new_and_dropped_rows_are_reported():
    old = parse("chart_SYN_pull1.json")["records"]
    rep = pr.compare(old[:3], old[1:])
    assert rep["counts"] == {"new_row": 2, "dropped_row": 1}


def test_identical_pulls_have_no_revisions():
    assert pr.compare(parse("chart_SYN_pull1.json")["records"],
                      parse("chart_SYN_pull1.json", retrieved_at=T1)["records"])["events"] == []


# 4. cut-off
def test_nothing_after_2022_can_enter_the_daily_file(tmp_path):
    index = [{"symbol": "SYN", "raw_path": str(FX / "chart_SYN_with_2023.json"), "url": URL_SPLITS,
              "retrieved_at": T0}]
    with pytest.raises(edge_split.HoldoutViolation):
        dp.build_rows(index)


# 5. manifest entries preserved
def _setup(tmp_path):
    out = tmp_path / "edge"
    out.mkdir()
    shutil.copy(FX / "manifest_copy_2026-10-23.json", out / "manifest.json")
    index = tmp_path / "index.json"
    index.write_text(json.dumps([{"symbol": "SYN", "raw_path": str(FX / "chart_SYN_pull1.json"),
                                  "url": URL_SPLITS, "retrieved_at": T0}]))
    return out, index


def test_adding_the_daily_file_keeps_every_existing_manifest_entry(tmp_path):
    out, index = _setup(tmp_path)
    before = json.loads((out / "manifest.json").read_text())
    assert dp.main(["--raw-index", str(index), "--out-dir", str(out)]) == 0
    after = json.loads((out / "manifest.json").read_text())
    for name, entry in before["files"].items():
        assert after["files"][name] == entry
    assert after["provenance"].items() >= before["provenance"].items()
    assert after["history"][:len(before["history"])] == before["history"]
    assert {k: v for k, v in after.items() if k not in ("files", "provenance", "history", "limitations")} == \
        {k: v for k, v in before.items() if k not in ("files", "provenance", "history")}
    blob = (out / dp.OUT_NAME).read_bytes()
    assert after["files"][dp.OUT_NAME]["sha256"] == hashlib.sha256(blob).hexdigest()
    assert after["files"][dp.OUT_NAME]["rows"] == 5
    assert after["limitations"][dp.OUT_NAME] == list(pp.LIMITATIONS)
    lines = gzip.decompress(blob).decode().splitlines()
    assert lines[0].split(",") == dp.COLUMNS and len(lines) == 6


def test_the_daily_file_and_its_entry_are_never_replaced(tmp_path):
    out, index = _setup(tmp_path)
    dp.main(["--raw-index", str(index), "--out-dir", str(out)])
    snapshot = (out / "manifest.json").read_bytes(), (out / dp.OUT_NAME).read_bytes()
    with pytest.raises(dp.ManifestError):
        dp.main(["--raw-index", str(index), "--out-dir", str(out)])
    (out / dp.OUT_NAME).unlink()
    with pytest.raises(dp.ManifestError):  # the manifest entry still exists, so it is not replaced either
        dp.main(["--raw-index", str(index), "--out-dir", str(out)])
    assert (out / "manifest.json").read_bytes() == snapshot[0]
    assert not (out / dp.OUT_NAME).exists()


def test_same_rows_give_the_same_file_bytes():
    rows = dp.build_rows([{"symbol": "SYN", "raw_path": str(FX / "chart_SYN_pull1.json"), "url": URL_SPLITS,
                           "retrieved_at": T0}])
    assert dp.encode(rows) == dp.encode(rows)


def test_raw_responses_are_stored_once_by_hash(tmp_path):
    body = (FX / "chart_SYN_pull1.json").read_bytes()
    p = pp.store_raw(body, tmp_path, URL_SPLITS)
    assert p.name == hashlib.sha256(body).hexdigest() and pp.store_raw(body, tmp_path, URL_SPLITS) == p
    p.write_bytes(b"tampered")
    with pytest.raises(pp.PriceError):
        pp.store_raw(body, tmp_path, URL_SPLITS)


def test_limitations_cover_survivorship_revisions_and_licence():
    text = " ".join(pp.LIMITATIONS).lower()
    assert "survivorship" in text and "revision" in text and "licen" in text
    assert parse("chart_SYN_pull1.json")["limitations"] == list(pp.LIMITATIONS)
