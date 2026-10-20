"""O10 (2026-10-20): the weekday brief routine reads master with the prompt in docs/office/WEEKDAY_BRIEF_PROMPT.txt.

These tests run that prompt's exact read command, and the order paths it forbids, offline: no credentials from the
environment, every outbound call answered by the in-memory fake or refused. They show the command only reads, and
that the kill file the prompt creates stops a trading run in that clone even if one were started by mistake.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FakeT212
from t212bot.client import T212Client
from t212bot.config import Credentials, SafetyError
from t212bot.readonly import ReadOnlyClient

TRADING = Path(__file__).resolve().parents[1]
PROMPT = TRADING.parent / "docs" / "office" / "WEEKDAY_BRIEF_PROMPT.txt"
SECRET_PREFIXES = ("T212", "REPORT_EMAIL", "RESEND", "SMTP")

# Installed into the child interpreter: urlopen goes to FakeT212 (demo API) and is logged; anything else is refused.
SITECUSTOMIZE = r'''
import io, json, os, socket, sys, urllib.error, urllib.request
_saved = list(sys.path)
sys.path.insert(0, os.environ["BRIEF_TESTS_DIR"])
import time
import conftest
from conftest import FakeT212
# conftest put the source tree's trading/ on sys.path: undo that so the child imports t212bot from its own cwd
sys.path[:] = [os.getcwd()] + _saved
for _m in [m for m in sys.modules if m == "t212bot" or m.startswith("t212bot.")]:
    del sys.modules[_m]
conftest.INSTRUMENTS.append({"ticker": "LQQ3l_EQ", "currencyCode": "GBX", "workingScheduleId": 70, "type": "ETF",
                             "name": "WisdomTree NASDAQ 100 3x Daily Leveraged"})
_fake = FakeT212(cash=0.0, positions={"VWRPl_EQ": 2.0, "SGLNl_EQ": 3.0})
_fake.ccy["LQQ3l_EQ"], _fake.fill_px["LQQ3l_EQ"] = "GBX", 400.0

def _yahoo(url):
    sym = url.split("/chart/")[1].split("?")[0]
    meta = {"regularMarketPrice": 1.33 if sym.endswith("=X") else 100.0,
            "currency": "USD" if sym.endswith("=X") else "GBp", "regularMarketTime": int(time.time())}
    return json.dumps({"chart": {"result": [{"meta": meta}]}}).encode()
_log = open(os.environ["BRIEF_CALL_LOG"], "a")

class _R:
    def __init__(self, r): self.status, self.headers, self._b = r.status, r.headers, r.body
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False

def _urlopen(req, timeout=None, **k):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    method = req.get_method() if hasattr(req, "get_method") else "GET"
    _log.write(f"{method} {url}\n"); _log.flush()
    if url.startswith("https://query1.finance.yahoo.com/v8/finance/chart/") and method == "GET":
        class _Y: status, headers, body = 200, {}, _yahoo(url)
        return _R(_Y)
    if not url.startswith("https://demo.trading212.com/api/v0/"):
        raise OSError("network blocked in test: " + url)
    r = _fake(method, url, dict(req.header_items()), req.data, timeout)
    if r.status >= 400:
        raise urllib.error.HTTPError(url, r.status, "fake", r.headers, io.BytesIO(r.body))
    return _R(r)

def _blocked(*a, **k): raise OSError("network blocked in test")
urllib.request.urlopen = _urlopen
socket.create_connection = _blocked
socket.socket.connect = _blocked
'''


def _read_command() -> str:
    m = re.search(r"cd agent-skills/trading && python3 -c '([^']+)'", PROMPT.read_text())
    assert m, "the prompt's read command was not found"
    return m.group(1)


@pytest.fixture
def child(tmp_path):
    """Run python in a child process with fake demo credentials, the fake broker and no network."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(SITECUSTOMIZE)
    log = tmp_path / "calls.log"
    log.touch()
    env = {k: v for k, v in os.environ.items() if not k.startswith(SECRET_PREFIXES) and k != "PYTHONPATH"}
    env.update(T212_ENV="demo", T212_API_KEY="test-key", T212_API_SECRET="test-secret", PYTHONPATH=str(site),
               BRIEF_TESTS_DIR=str(TRADING / "tests"), BRIEF_CALL_LOG=str(log),
               HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9")

    def run(args, cwd):
        r = subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
        return r, log.read_text().splitlines()
    return run


def test_the_prompt_points_at_master_forbids_the_cli_and_sets_the_kill_switch_first():
    p = PROMPT.read_text()
    assert "(branch master)" in p and "r71zy3" not in p
    assert "touch agent-skills/trading/KILL" in p
    assert p.index("touch agent-skills/trading/KILL") < p.index("python3 -c")
    for forbidden in ("never place, amend or cancel orders", "never run the bot's command line",
                      "never edit anything under trading/config", "never commit or push",
                      "never change any routine, setting or permission"):
        assert forbidden in p
    cmd = _read_command()
    assert "ReadOnlyClient(T212Client(load_credentials()))" in cmd
    assert not re.search(r"execute|decide|place_|cancel|Bot\(|_request|\._c\b|\.run\(", cmd)


def test_the_read_command_only_reads_and_prints_the_account(child):
    r, calls = child(["-c", _read_command()], cwd=TRADING)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["summary"]["totalValue"] > 0 and out["pending_orders"] == []
    assert sorted(p["instrument"]["ticker"] for p in out["positions"]) == ["SGLNl_EQ", "VWRPl_EQ"]
    assert calls == ["GET https://demo.trading212.com/api/v0/equity/account/summary",
                     "GET https://demo.trading212.com/api/v0/equity/positions",
                     "GET https://demo.trading212.com/api/v0/equity/orders"]
    assert "test-key" not in r.stdout + r.stderr and "test-secret" not in r.stdout + r.stderr


def test_the_read_command_fails_closed_without_demo_credentials(child, tmp_path):
    r, calls = child(["-c", "import os; os.environ['T212_ENV'] = 'live'; " + _read_command()], cwd=TRADING)
    assert r.returncode != 0 and "T212_ENV must be 'demo'" in r.stderr and calls == []


def test_the_read_only_client_cannot_order_cancel_or_reach_the_full_client():
    fake = FakeT212()
    ro = ReadOnlyClient(T212Client(Credentials("k", "s"), transport=fake, sleep=lambda s: None))
    for name in ("place_market_order", "cancel_order", "_request", "calls", "_t"):
        with pytest.raises(SafetyError):
            getattr(ro, name)
    with pytest.raises(SafetyError):
        ro._c = None
    assert repr(ro) == "ReadOnlyClient(<redacted>)"
    assert fake.posts == [] and fake.get_calls == []


@pytest.mark.parametrize("argv", [
    ["run", "--execute", "--force"],
    ["decide", "--set", "LQQ3l_EQ=1.0", "--reason", "test", "--execute"],
    ["decide", "--cash", "--reason", "test", "--execute"],
])
def test_a_mistaken_trading_command_in_the_clone_sends_no_order(child, tmp_path, argv):
    """The prompt forbids the CLI. If a session ran a trading command anyway in its clone (kill file present), no
    order, cancel or other non-GET request leaves the process."""
    clone = tmp_path / "agent-skills" / "trading"
    shutil.copytree(TRADING, clone, ignore=shutil.ignore_patterns("tests", "__pycache__", "reports"))
    (clone / "KILL").touch()
    before = {p: p.read_bytes() for p in (TRADING / "config").iterdir()} | {
        p: p.read_bytes() for p in (TRADING / "journal").glob("*.*")}
    r, calls = child(["-m", "t212bot", *argv], cwd=clone)
    assert [c for c in calls if not c.startswith("GET ")] == [], calls
    assert "placed:" not in r.stdout, r.stdout
    assert all(p.read_bytes() == b for p, b in before.items())  # the child used the clone, not this checkout
    assert "run_start" in (clone / "journal" / "events.jsonl").read_text()


def test_the_kill_file_halts_a_trading_run_under_masters_strategy_before_any_order(tmp_path):
    """Isolates the kill switch from the other pre-trade checks: master's committed strategy (100% LQQ3), a fake
    account with cash to spend and every check otherwise passable. With the kill file the run halts with no POST;
    without it the same run would place the order."""
    from datetime import datetime, timezone
    from conftest import INSTRUMENTS, exchanges_for
    from t212bot.config import load_strategy
    from t212bot.executor import Bot
    from t212bot.journal import Journal
    from t212bot.market import Quote
    lqq3 = {"ticker": "LQQ3l_EQ", "currencyCode": "GBX", "workingScheduleId": 70, "type": "ETF", "name": "LQQ3"}
    now = datetime.now(timezone.utc)

    class Quotes:
        def quote(self, s): return Quote(s, 4.0, "GBP", now, "test")
        def gbpusd(self): return Quote("GBPUSD=X", 1.33, "USD", now, "test")

    def bot(kill_file):
        fake = FakeT212(cash=100.0)
        fake.ccy["LQQ3l_EQ"], fake.fill_px["LQQ3l_EQ"] = "GBX", 4.0
        c = T212Client(Credentials("k", "s"), transport=fake, sleep=lambda s: None)
        b = Bot(c, load_strategy(), Journal(tmp_path / ("j_" + kill_file.name)), quotes=Quotes(), now=lambda: now,
                sleep=lambda s: None, instruments=INSTRUMENTS + [lqq3], exchanges=exchanges_for(now), env={},
                kill_file=kill_file)
        return b, fake
    assert load_strategy().targets == {"LQQ3l_EQ": 1.0}  # master's file is not retired until PR #20 merges
    kill = tmp_path / "KILL"
    kill.touch()
    b, fake = bot(kill)
    res = b.run(execute=True, force=True)
    assert res["status"] == "halted" and "kill file present" in res["reason"] and fake.posts == []
    b, fake = bot(tmp_path / "NO_KILL")
    disc = tmp_path / "discretionary_targets.json"
    disc.write_text(json.dumps({"targets": {"LQQ3l_EQ": 1.0}, "reason": "test"}))
    for k, posts in ((kill, 0), (tmp_path / "NO_KILL", 1)):  # control: without the kill file the same run orders
        b, fake = bot(k)
        b._disc_path = disc
        res = b.run(execute=True, force=True)
        assert len(fake.posts) == posts, res
