"""Remediation of review findings P33-1 to P33-8 (mini fund Stage 2 §2). Offline: committed synthetic fixtures and
in-memory variants only, and every test runs behind a guard that makes any network connection raise. The live
research-data folder is never read or written."""
import builtins
import hashlib
import json
import os
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

RESEARCH = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "prices"
CUT = "period1=1640995200&period2=1672531200"
URL = f"https://query1.finance.yahoo.com/v8/finance/chart/SYN?{CUT}&interval=1d&events=div%7Csplit"
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


def chart(name="chart_SYN_pull1.json"):
    return json.loads((FX / name).read_bytes())


def parse_doc(doc, url=URL, at=T0):
    return pp.parse_chart(json.dumps(doc).encode(), symbol="SYN", url=url, retrieved_at=at)


# P33-1: no inferred unadjusted price when the vendor reports no splits
def test_no_splits_reported_gives_no_unadjusted_price():
    doc = chart()
    doc["chart"]["result"][0].pop("events")
    out = parse_doc(doc)
    assert out["split_basis"] == "vendor_reported_none"
    for r in out["records"]:
        assert r["close_unadjusted"] is None and "split_history_unverified" in r["missing_reasons"]


def test_no_code_outside_price_provenance_uses_close_unadjusted_as_a_price():
    for p in RESEARCH.rglob("*.py"):
        if "tests" in p.parts or p.name in ("price_provenance.py", "daily_prices_to_2022.py"):
            continue
        assert "close_unadjusted" not in p.read_text(), p
    src = (RESEARCH / "daily_prices_to_2022.py").read_text()
    assert src.count("close_unadjusted") == 3  # the column name and the copy into the row; never priced


# P33-2: bar and split times outside session hours
def _shift_bar(doc, i, ts):
    doc["chart"]["result"][0]["timestamp"][i] = ts


def test_a_bar_at_midnight_utc_has_no_session_date():
    doc = chart()
    _shift_bar(doc, 4, 1672358400)  # 2022-12-30 00:00 UTC = 19:00 EST on the 29th
    out = parse_doc(doc)
    r = out["records"][4]
    assert r["session_date"] is None and "bar_time_outside_session" in r["missing_reasons"]
    assert r["close_unadjusted"] is None and r["available_at"] is None
    assert out["flags"] == ["bar_time_outside_session"]


def test_a_bar_at_the_open_is_unchanged():
    out = parse_doc(chart())
    assert out["flags"] == [] and out["records"][0]["session_date"] == "2022-12-23"
    assert out["records"][0]["bar_time"] == "2022-12-23T09:30:00-05:00"


def test_a_split_stamped_at_midnight_utc_blanks_the_prices_it_would_change():
    doc = chart()
    ev = doc["chart"]["result"][0]["events"]["splits"]
    sp = ev.pop("1672324200")
    sp["date"] = 1672358400  # 00:00 UTC on 30 Dec: 19:00 ET on the 29th, outside session hours
    ev["1672358400"] = sp
    out = parse_doc(doc)
    assert out["splits"][0]["time_verified"] is False
    recs = {r["session_date"]: r for r in out["records"]}
    for d in ("2022-12-23", "2022-12-27", "2022-12-28", "2022-12-29"):
        assert recs[d]["close_unadjusted"] is None and "split_date_unverified" in recs[d]["missing_reasons"]
    assert recs["2022-12-30"]["close_unadjusted"] == recs["2022-12-30"]["close"]


# P33-3: the cut-off is checked before storage and before parsing
@pytest.mark.parametrize("url", [
    "https://query1.finance.yahoo.com/v8/finance/chart/SYN?interval=1d",
    "https://query1.finance.yahoo.com/v8/finance/chart/SYN?period1=1640995200&period2=1675209600",
    "https://query1.finance.yahoo.com/v8/finance/chart/SYN?period2=soon",
])
def test_a_request_without_a_pre_2023_end_is_never_stored(tmp_path, url):
    with pytest.raises(edge_split.HoldoutViolation):
        pp.store_raw((FX / "chart_SYN_pull1.json").read_bytes(), tmp_path, url)
    assert not (tmp_path / "raw").exists()
    with pytest.raises(edge_split.HoldoutViolation):
        parse_doc(chart(), url=url)


def test_a_response_with_a_2023_bar_is_refused_at_parse_time():
    with pytest.raises(edge_split.HoldoutViolation):
        pp.parse_chart((FX / "chart_SYN_with_2023.json").read_bytes(), symbol="SYN", url=URL, retrieved_at=T0)


def test_a_valid_request_is_stored(tmp_path):
    body = (FX / "chart_SYN_pull1.json").read_bytes()
    assert pp.store_raw(body, tmp_path, URL).read_bytes() == body


# P33-4: only approved calendars
def test_no_calendar_is_approved_and_the_fixture_is_refused():
    assert pp.APPROVED_CALENDARS == frozenset()
    p = FX / "sessions_synthetic.csv"
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    for expected in (None, h, "0" * 64):
        with pytest.raises(pp.PriceError):
            pp.load_sessions(p, expected)


def test_an_approved_calendar_with_the_wrong_hash_is_refused(monkeypatch, tmp_path):
    p = tmp_path / "cal.csv"
    shutil.copy(FX / "sessions_synthetic.csv", p)
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setattr(pp, "APPROVED_CALENDARS", frozenset({h}))
    p.write_bytes(p.read_bytes() + b"2022-12-29,16:00,SYNTHETIC fixture,2026-10-23T00:00:00Z\n")
    with pytest.raises(pp.PriceError):
        pp.load_sessions(p, h)


# P33-5: float noise is not a revision
def _recs(close_by_day=None, adj_scale=None):
    out = parse_doc(chart())["records"]
    new = [dict(r) for r in out]
    for r in new:
        if close_by_day and r["session_date"] in close_by_day:
            r["close"] = close_by_day[r["session_date"]]
    return out, new


def test_float_noise_is_counted_not_reported():
    old, new = _recs()
    old[2] = dict(old[2], close=23.77)
    new[2] = dict(new[2], close=23.770000457763672)
    rep = pr.compare(old, new)
    assert rep["events"] == [] and rep["float_noise"] == 1


def test_a_real_change_is_unexplained():
    old, new = _recs()
    new[2] = dict(new[2], close=new[2]["close"] + 0.5)
    rep = pr.compare(old, new)
    assert rep["unexplained"] == 1 and rep["float_noise"] == 0


# P33-6 (accepted exception): two dividends between pulls give false alarms, never a hidden change
def test_two_dividends_between_pulls_are_flagged_unexplained():
    old = parse_doc(chart())["records"]
    new = [dict(r) for r in old]
    for i, f in ((0, 0.98), (1, 0.98), (2, 0.99)):
        new[i]["adjclose"] = old[i]["adjclose"] * f
    rep = pr.compare(old, new)
    assert rep["unexplained"] > 0
    assert {e["session_date"] for e in rep["events"]} == {old[i]["session_date"] for i in range(3)}


# P33-7 (accepted exception): compare() writes nothing
def test_compare_never_writes_files(monkeypatch):
    real_open = builtins.open

    def guarded(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            raise AssertionError(f"compare tried to write {file}")
        return real_open(file, mode, *a, **k)
    old = parse_doc(chart())["records"]
    new = parse_doc(chart("chart_SYN_pull2_dividend.json"), at=T1)["records"]
    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.setattr(Path, "write_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("write")))
    monkeypatch.setattr(Path, "write_bytes", lambda *a, **k: (_ for _ in ()).throw(AssertionError("write")))
    assert pr.compare(old, new)["counts"] == {"dividend_adjustment": 2}


# P33-8: manifest format and the live-folder refusal
def _setup(tmp_path):
    out = tmp_path / "edge"
    out.mkdir()
    shutil.copy(FX / "manifest_copy_2026-10-23.json", out / "manifest.json")
    index = tmp_path / "index.json"
    index.write_text(json.dumps([{"symbol": "SYN", "raw_path": str(FX / "chart_SYN_pull1.json"), "url": URL,
                                  "retrieved_at": T0}]))
    return out, index


def test_existing_manifest_lines_survive_except_one_comma(tmp_path):
    out, index = _setup(tmp_path)
    before = (out / "manifest.json").read_text()
    assert hashlib.sha256(before.encode()).hexdigest().startswith("bb0bf033de08ab5c")
    assert dp.main(["--raw-index", str(index), "--out-dir", str(out)]) == 0
    after = (out / "manifest.json").read_text()
    assert not after.endswith("\n")
    old_lines, new_lines = before.splitlines(), after.splitlines()
    kept = [ln for ln in old_lines if ln in new_lines]
    commas = [ln for ln in old_lines if ln not in new_lines]
    assert all(ln + "," in new_lines for ln in commas) and len(commas) <= 4
    assert len(kept) + len(commas) == len(old_lines)


def test_non_ascii_round_trips_unescaped(tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"files": {"a": {"rows": 1}}, "note": "Zürich £"}, indent=1, ensure_ascii=False))
    dp.add_to_manifest(m, "x.csv.gz", b"x", 1, "prov", clock=lambda: "t")
    assert "Zürich £" in m.read_text() and "\\u" not in m.read_text()


def test_the_live_folder_is_refused_before_it_is_read(tmp_path, monkeypatch):
    seen = []
    real_exists, real_read = Path.exists, Path.read_text

    def spy_exists(self, *a, **k):
        seen.append(str(self))
        return real_exists(self, *a, **k)

    def spy_read(self, *a, **k):
        seen.append(str(self))
        return real_read(self, *a, **k)
    monkeypatch.setattr(Path, "exists", spy_exists)
    monkeypatch.setattr(Path, "read_text", spy_read)
    monkeypatch.setattr(Path, "resolve", lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("resolved")))
    with pytest.raises(dp.ManifestError):
        dp.main(["--raw-index", str(tmp_path / "missing.json"), "--out-dir", "/mnt/project-files/research-data/edge"])
    with pytest.raises(dp.ManifestError):
        dp.check_out_dir("/mnt/project-files/research-data", None)
    assert not any("research-data" in p or "missing.json" in p for p in seen)


def test_a_symlink_into_the_protected_folder_is_refused(tmp_path, monkeypatch):
    protected = tmp_path / "research-data"
    (protected / "edge").mkdir(parents=True)
    os.symlink(protected / "edge", tmp_path / "link")
    monkeypatch.setattr(dp, "PROTECTED_ROOT", str(protected))
    with pytest.raises(dp.ManifestError):
        dp.check_out_dir(tmp_path / "link", None)
    dp.check_out_dir(tmp_path / "link", "cmsg_example")  # an approval id lets it through
    dp.check_out_dir(tmp_path / "elsewhere", None)
