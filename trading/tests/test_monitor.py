"""Read-only monitor: alerts from fakes, never trades."""
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd

from conftest import NOW
from t212bot import monitor
from t212bot.market import Quote

SIG = {"type": "sma_trend", "symbol": "QQQ", "window": 100, "max_age_days": 5, "on_targets": {"LQQ3l_EQ": 1.0}, "off_targets": {}}


class RO:
    """Fake read-only account; any write attempt would raise AttributeError."""
    def __init__(self, value=500.0, lqq3=468.0, pending=(), fail=False):
        self.value, self.lqq3, self.pending, self.fail = value, lqq3, list(pending), fail

    def account_summary(self):
        if self.fail:
            raise RuntimeError("HTTP 503")
        return {"totalValue": self.value, "cash": {"availableToTrade": self.value - self.lqq3}}

    def positions(self):
        return [{"instrument": {"ticker": "LQQ3l_EQ"}, "walletImpact": {"currentValue": self.lqq3}}] if self.lqq3 else []

    def pending_orders(self):
        return self.pending


def loader(qqq_last=110.0, lqq3_prev_pence=35000.0):
    idx = pd.bdate_range(end=NOW.date() - timedelta(days=1), periods=150)
    q = np.full(len(idx), 100.0)
    q[-1] = qqq_last
    data = {"QQQ": pd.DataFrame({"close": q, "adjclose": q}, index=idx),
            "LQQ3.L": pd.DataFrame({"close": lqq3_prev_pence, "adjclose": lqq3_prev_pence}, index=idx)}
    return lambda s: data[s]


class Quotes:
    def __init__(self, qqq=110.0, lqq3=350.0):
        self.p = {"QQQ": (qqq, "USD"), "LQQ3.L": (lqq3, "GBP")}

    def quote(self, s):
        return Quote(s, self.p[s][0], self.p[s][1], NOW, "fake")


def _cfg(cfg):
    return replace(cfg, name="trend", targets={"LQQ3l_EQ": 1.0}, signal=SIG, cash_buffer_pct=0.015,
                   yahoo_symbols={"LQQ3l_EQ": "LQQ3.L"})


def _run(cfg, journal, tmp_path, ro=None, quotes=None, ld=None):
    journal.event("run_start", run_id="r1")
    return monitor.check(_cfg(cfg), journal, ro or RO(lqq3=490.0), quotes or Quotes(), ld or loader(), NOW, tmp_path / "KILL")


def test_healthy_account_no_alerts_and_journaled(cfg, journal, tmp_path):
    res = _run(cfg, journal, tmp_path)
    assert res["exit"] == 0, res["alerts"]
    assert res["intraday_moves"]["LQQ3l_EQ"] == 0.0          # pence close vs pounds quote handled
    assert journal.events("monitor")[-1]["total_value_gbp"] == 500.0


def test_account_failure_is_critical(cfg, journal, tmp_path):
    res = _run(cfg, journal, tmp_path, ro=RO(fail=True))
    assert res["exit"] == 2 and "account read failed" in res["alerts"][0]["msg"]


def test_intraday_cross_and_crash_warn(cfg, journal, tmp_path):
    res = _run(cfg, journal, tmp_path, quotes=Quotes(qqq=90.0, lqq3=300.0))
    msgs = " ".join(a["msg"] for a in res["alerts"])
    assert "crossed" in msgs and "out of" in msgs
    assert any(a["level"] == "CRITICAL" and "down -14.3%" in a["msg"] for a in res["alerts"])


def test_failed_run_kill_pending_and_mismatch(cfg, journal, tmp_path):
    (tmp_path / "KILL").write_text("")
    journal.event("run_start", run_id="r1")
    journal.event("run_failed", run_id="r1", error="stale quote")
    res = monitor.check(_cfg(cfg), journal, RO(lqq3=0.0, pending=[{"id": 1}]), Quotes(), loader(), NOW, tmp_path / "KILL")
    msgs = " ".join(a["msg"] for a in res["alerts"])
    assert res["exit"] == 2
    assert "run_failed stale quote" in msgs and "KILL" in msgs and "pending" in msgs and "LQQ3l_EQ is 0%" in msgs


def test_drawdown_from_peak(cfg, journal, tmp_path):
    journal.snapshot({"totalValue": 500.0, "cash": {"availableToTrade": 10}, "investments": {}}, [])
    res = _run(cfg, journal, tmp_path, ro=RO(value=400.0, lqq3=392.0))
    assert any(a["level"] == "WARN" and "-20.0% below its peak" in a["msg"] for a in res["alerts"])
