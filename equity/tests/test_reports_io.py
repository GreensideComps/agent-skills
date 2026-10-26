"""Write-once reports (WP-H, review finding P30-5). Offline: temporary folders only, and every test runs behind a
guard that makes any network connection raise. The real reports folder is only read, never written."""
import ast
import hashlib
import socket
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from equity import __main__ as cli
from equity import reports_io
from equity.store import Store

EQUITY = Path(__file__).resolve().parent.parent
REAL_REPORTS = EQUITY / "reports"


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


@pytest.fixture
def reports(tmp_path, monkeypatch):
    root = tmp_path / "reports"
    root.mkdir()
    monkeypatch.setattr(reports_io, "REPORTS_DIR", root)
    monkeypatch.setattr(reports_io, "PINNED", {})
    return root


def test_the_network_guard_blocks_connections():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443), timeout=1)


# 1. an existing different report is never replaced; reruns get numbered files
def test_a_rerun_never_replaces_the_existing_report(reports):
    p = reports / "screens" / "2026-10-14.md"
    assert reports_io.write_report_once(p, "first\n") == p
    assert reports_io.write_report_once(p, "second\n") == p.with_name("2026-10-14.rerun-1.md")
    assert reports_io.write_report_once(p, "third\n") == p.with_name("2026-10-14.rerun-2.md")
    assert p.read_text() == "first\n"
    assert p.with_name("2026-10-14.rerun-1.md").read_text() == "second\n"
    assert p.with_name("2026-10-14.rerun-2.md").read_text() == "third\n"


# 2. identical bytes write nothing
def test_an_identical_rerun_writes_nothing(reports):
    p = reports / "paper" / "2026-10-15.md"
    reports_io.write_report_once(p, "same\n")
    reports_io.write_report_once(p, "other\n")
    before = sorted(x.name for x in p.parent.iterdir())
    assert reports_io.write_report_once(p, "same\n") == p
    assert reports_io.write_report_once(p, "other\n") == p.with_name("2026-10-15.rerun-1.md")
    assert sorted(x.name for x in p.parent.iterdir()) == before


# 3. pinned historical reports: a changed or missing pinned file is an error, and nothing is written
def test_a_pinned_report_with_a_changed_hash_is_refused(reports, monkeypatch):
    p = reports / "screens" / "2026-10-14.md"
    p.parent.mkdir()
    p.write_text("historical\n")
    monkeypatch.setattr(reports_io, "PINNED", {"screens/2026-10-14.md": hashlib.sha256(b"other").hexdigest()})
    with pytest.raises(reports_io.ReportError):
        reports_io.write_report_once(p, "new\n")
    assert p.read_text() == "historical\n"
    assert sorted(x.name for x in p.parent.iterdir()) == ["2026-10-14.md"]


def test_a_missing_pinned_report_is_never_re_created(reports, monkeypatch):
    monkeypatch.setattr(reports_io, "PINNED", {"paper/2026-10-14.md": "0" * 64})
    p = reports / "paper" / "2026-10-14.md"
    with pytest.raises(reports_io.ReportError):
        reports_io.write_report_once(p, "recreated\n")
    assert not p.exists()


def test_an_intact_pinned_report_gets_a_rerun_file(reports, monkeypatch):
    p = reports / "screens" / "2026-10-23.md"
    p.parent.mkdir()
    p.write_bytes(b"pinned\n")
    monkeypatch.setattr(reports_io, "PINNED", {"screens/2026-10-23.md": hashlib.sha256(b"pinned\n").hexdigest()})
    assert reports_io.write_report_once(p, "rerun\n").name == "2026-10-23.rerun-1.md"
    assert p.read_bytes() == b"pinned\n"


def test_every_pinned_report_in_the_repository_is_intact():
    assert len(reports_io.PINNED) == 12
    assert reports_io.pinned_problems(REAL_REPORTS) == []


# 4. two writers racing for one name: one creates it, the other goes to a rerun file
def test_racing_writers_never_overwrite_each_other(reports):
    p = reports / "health" / "2026-10-24.md"
    texts = [f"writer {i}\n" for i in range(8)]
    start = threading.Barrier(len(texts))
    got = {}

    def run(t):
        start.wait()
        got[t] = reports_io.write_report_once(p, t)

    threads = [threading.Thread(target=run, args=(t,)) for t in texts]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    files = sorted(p.parent.iterdir())
    assert len(files) == len(texts) and len(set(got.values())) == len(texts)
    assert {f.read_text() for f in files} == set(texts)
    for t, f in got.items():
        assert f.read_text() == t


def test_a_failed_write_leaves_no_partial_file(reports, monkeypatch):
    p = reports / "screens" / "2026-10-26.md"

    def boom(fd):
        raise OSError("disk full")
    monkeypatch.setattr(reports_io.os, "fsync", boom)
    with pytest.raises(OSError):
        reports_io.write_report_once(p, "x\n")
    assert not p.exists()


# 5. the commands themselves: a second run on the same as_of leaves the first file unchanged
def _screen_stubs(monkeypatch, md):
    from equity import alerts, screener, valuation
    monkeypatch.setattr(screener, "run", lambda store: {"rid": "r1", "as_of": "2026-10-14", "companies": 1,
                                                        "eligible": 1})
    monkeypatch.setattr(valuation, "run", lambda store, rec: [])
    monkeypatch.setattr(alerts, "run", lambda store, rec: {"alerts": [], "baseline": True})
    monkeypatch.setattr(screener, "report", lambda *a, **k: md)


def test_screen_rerun_keeps_the_first_report(reports, tmp_path, monkeypatch, capsys):
    store = Store(tmp_path / "data")
    _screen_stubs(monkeypatch, "screen v1\n")
    assert cli.cmd_screen(store, SimpleNamespace(top=25)) == 0
    _screen_stubs(monkeypatch, "screen v2\n")
    assert cli.cmd_screen(store, SimpleNamespace(top=25)) == 0
    d = reports / "screens"
    assert (d / "2026-10-14.md").read_text() == "screen v1\n"
    assert (d / "2026-10-14.rerun-1.md").read_text() == "screen v2\n"


def test_paper_rerun_keeps_the_first_report(reports, tmp_path, monkeypatch):
    from equity import paper, prices
    store = Store(tmp_path / "data")
    store.screens.append({"rid": "r1", "as_of": "2026-10-15", "ts_utc": "2026-10-15T21:00:00+00:00"})
    monkeypatch.setattr(prices, "latest_prices", lambda store: {})
    monkeypatch.setattr(paper, "rebalance", lambda *a, **k: {"rebalanced": False})
    monkeypatch.setattr(paper, "mark", lambda *a, **k: {"excess_return": 0.0})
    for md in ("paper v1\n", "paper v2\n"):
        monkeypatch.setattr(paper, "report", lambda store, md=md: md)
        assert cli.cmd_paper(store, SimpleNamespace(force=False)) == 0
    d = reports / "paper"
    assert (d / "2026-10-15.md").read_text() == "paper v1\n"
    assert (d / "2026-10-15.rerun-1.md").read_text() == "paper v2\n"


def test_reliability_rerun_keeps_the_first_report(reports, tmp_path, monkeypatch):
    from equity import reliability
    store = Store(tmp_path / "data")
    monkeypatch.setattr(reliability, "run", lambda store: {"as_of": "2026-10-16T22:00:00+00:00", "exit_code": 0})
    for md in ("health v1\n", "health v2\n"):
        monkeypatch.setattr(reliability, "report", lambda res, md=md: md)
        assert cli.cmd_reliability(store, SimpleNamespace()) == 0
    d = reports / "health"
    assert (d / "2026-10-16.md").read_text() == "health v1\n"
    assert (d / "2026-10-16.rerun-1.md").read_text() == "health v2\n"


def test_portfolio_rerun_keeps_the_first_report(reports, tmp_path, monkeypatch):
    from equity import portfolio
    store = Store(tmp_path / "data")
    monkeypatch.setattr(cli, "_t212_readonly", lambda: object())
    monkeypatch.setattr(portfolio, "snapshot", lambda client: {"rid": "p1", "as_of": "2026-10-19", "positions": []})
    monkeypatch.setattr(portfolio, "fetch_returns", lambda snap, store: ({}, {}, []))
    monkeypatch.setattr(portfolio, "analyse", lambda *a: {"flags": [], "total_value": 0})
    for md in ("portfolio v1\n", "portfolio v2\n"):
        monkeypatch.setattr(portfolio, "report", lambda an, failed, md=md: md)
        assert cli.cmd_portfolio(store, SimpleNamespace(ingest_missing=False)) == 0
    d = reports / "portfolio"
    assert (d / "2026-10-19.md").read_text() == "portfolio v1\n"
    assert (d / "2026-10-19.rerun-1.md").read_text() == "portfolio v2\n"


# 6. no other code path writes into reports/ directly
def test_no_command_writes_a_report_except_through_the_helper():
    src = (EQUITY / "equity" / "__main__.py").read_text()
    tree = ast.parse(src)
    report_funcs = []
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        body = ast.get_source_segment(src, fn)
        if "REPORTS_DIR" in body or '"reports"' in body:
            report_funcs.append(fn.name)
            assert "write_report_once" in body, fn.name
            for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
                f = call.func
                if isinstance(f, ast.Attribute) and f.attr in ("write_text", "write_bytes"):
                    target = ast.get_source_segment(src, f.value)
                    assert "REPORTS" not in target and "out" != target, (fn.name, target)
    assert sorted(report_funcs) == ["cmd_crosscheck", "cmd_paper", "cmd_portfolio", "cmd_reliability", "cmd_screen"]
    assert '"reports"' not in src
    for p in (EQUITY / "equity").glob("*.py"):
        if p.name != "reports_io.py":
            assert '"reports"' not in p.read_text(), p.name
