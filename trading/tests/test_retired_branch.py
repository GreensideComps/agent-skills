"""Owner decision O10 (2026-10-20): this branch's bot is retired and kept for audit only.
These tests run with the retirement in force (marker `retired_guard`) and use only the
in-memory fake broker or a scratch directory: no network, no credentials."""
import hashlib
import os
import shutil
import stat
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import INSTRUMENTS, NOW, FakeQuotes, FakeT212, exchanges_for
from t212bot import __main__ as cli
from t212bot import decide, retired
from t212bot.config import SafetyError
from t212bot.executor import Bot

pytestmark = pytest.mark.retired_guard
TRADING = Path(__file__).resolve().parent.parent
LIMITS = {"universe": ["VWRPl_EQ", "IWMOl_EQ"], "max_decisions_per_day": 2, "daily_loss_stop": 0.10}


@pytest.fixture(autouse=True)
def _no_network_no_secrets(monkeypatch):
    """If a guard regresses, the code under test must still not reach the broker, Yahoo or the
    email provider: strip every credential and block outbound connections for this module."""
    import socket
    import urllib.request
    for k in list(os.environ):
        if k.startswith(("T212", "REPORT_EMAIL", "RESEND", "SMTP")):
            monkeypatch.delenv(k)

    def blocked(*a, **k):
        raise AssertionError("network access attempted in a retirement test")
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def bot(make_client, cfg, journal, tmp_path):
    def _make(fake, mode="rules"):
        c = replace(cfg, mode="discretionary", decision_limits=LIMITS) if mode == "discretionary" else cfg
        return Bot(make_client(fake), c, journal, quotes=FakeQuotes(), now=lambda: NOW, sleep=lambda s: None,
                   instruments=INSTRUMENTS, exchanges=exchanges_for(NOW), env={}, kill_file=tmp_path / "KILL")
    return _make


def test_the_flag_is_a_code_constant_and_on():
    assert retired.BRANCH_RETIRED is True
    src = (TRADING / "t212bot" / "retired.py").read_text()
    assert "\nBRANCH_RETIRED = True\n" in src


@pytest.mark.parametrize("argv", [
    ["status"], ["run"], ["run", "--execute"], ["run", "--execute", "--force"], ["reconcile"], ["report"],
    ["monitor"], ["advise"], ["daily-report", "--send", "--force"], ["email-check"],
    ["decide", "--set", "LQQ3l_EQ=1.0", "--reason", "x", "--execute"], ["decide", "--cash", "--reason", "x", "--execute"],
])
def test_every_cli_command_refuses_before_touching_credentials_or_the_broker(argv, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("the retired CLI must not get this far")
    monkeypatch.setattr(cli, "load_credentials", boom)
    monkeypatch.setattr(cli, "T212Client", boom)
    monkeypatch.setattr(cli, "load_strategy", boom)
    assert cli.main(argv) == 5
    assert "retired" in capsys.readouterr().err


@pytest.mark.parametrize("execute,force", [(False, False), (True, False), (True, True)])
def test_bot_run_refuses_before_any_broker_call(bot, execute, force):
    fake = FakeT212(cash=100.0)
    b = bot(fake)
    with pytest.raises(SafetyError, match="retired"):
        b.run(execute=execute, force=force)
    assert b.c.calls == [] and fake.posts == []


def test_decide_refuses_before_any_broker_call(bot, tmp_path):
    fake = FakeT212(cash=100.0)
    b = bot(fake, mode="discretionary")
    with pytest.raises(SafetyError, match="retired"):
        decide.decide(b, b.cfg, b.j, {"VWRPl_EQ": 1.0}, "x", execute=True, now=NOW,
                      path=tmp_path / "t.json", scratch=tmp_path)
    assert b.c.calls == [] and fake.posts == [] and not (tmp_path / "t.json").exists()


def test_order_methods_refuse_and_send_nothing(bot):
    fake = FakeT212(cash=100.0)
    b = bot(fake)
    with pytest.raises(SafetyError, match="retired"):
        b._place("VWRPl_EQ", 0.1, {}, "x", {})
    with pytest.raises(SafetyError, match="retired"):
        b._retry_buy_with_fresh_cash("VWRPl_EQ", 0.1, 4, {}, "x", RuntimeError("x"), {})
    with pytest.raises(SafetyError, match="retired"):
        b.c.place_market_order("VWRPl_EQ", 0.1)
    with pytest.raises(SafetyError, match="retired"):
        b.c.cancel_order(1)
    for method in ("POST", "DELETE", "PUT", "PATCH"):
        with pytest.raises(SafetyError, match="retired"):
            b.c._request(method, "/api/v0/equity/orders/market", "order_market", {"ticker": "VWRPl_EQ", "quantity": 1})
    assert b.c.calls == [] and fake.posts == []


@pytest.mark.parametrize("script", ["ops_run.sh", "monitor_run.sh"])
def test_scripts_exit_before_any_git_python_or_pip_call(script, tmp_path):
    shutil.copy(TRADING / script, tmp_path / script)
    log = tmp_path / "calls.log"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("git", "python3", "pip3"):
        f = bindir / tool
        f.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\nexit 0\n')
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ)  # credentials already stripped by the autouse fixture
    env["PATH"] = f"{bindir}:/usr/bin:/bin"
    r = subprocess.run(["bash", str(tmp_path / script)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 5
    assert "retired" in r.stdout
    assert not log.exists()


def test_old_strategy_kept_byte_for_byte_for_audit():
    sha = hashlib.sha256((TRADING / "config" / "strategy.json").read_bytes()).hexdigest()
    assert sha == "a08ad34df6de53ec22d2083e480cd8886986cac6a3f3f57e49a26c37ab68ba02"
