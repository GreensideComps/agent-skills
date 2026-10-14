"""Milestone 6 (demo): read-only portfolio monitor - snapshot, exposure, concentration, co-movement, flags."""
from __future__ import annotations

import random

import pytest

from equity import portfolio


class FakeClient:
    """Exposes only the two GET methods the monitor may call."""

    def account_summary(self):
        return {"id": 123, "currency": "GBP", "totalValue": 100.0, "cash": {"availableToTrade": 0, "inPies": 0}}

    def positions(self):
        def pos(t, v, pie=True):
            return {"instrument": {"ticker": t, "name": t, "isin": "X", "currency": "USD"}, "quantity": 1.0,
                    "quantityInPies": 1.0 if pie else 0, "currentPrice": v, "walletImpact": {"currentValue": v,
                                                                                             "totalCost": v}}
        return [pos("AAA_US_EQ", 50.0), pos("BBB_US_EQ", 30.0), pos("IBTAl_EQ", 20.0, pie=False)]


CFG = {"thresholds": {"max_position_weight": 0.4, "max_sector_weight": 0.6, "max_avg_correlation": 0.5,
                      "max_vol_annual": 0.3, "move_5d": 0.1}}


def test_snapshot_reads_only_and_drops_the_account_id():
    snap = portfolio.snapshot(FakeClient())
    assert "id" not in snap and snap["total_value"] == 100.0 and len(snap["positions"]) == 3
    assert snap["positions"][2]["quantity_in_pies"] == 0 and snap["rid"].startswith("portfolio:")


def test_yahoo_symbols_and_broad_sectors():
    master = {"FB_US_EQ": {"symbol": "META"}, "BRK.B_US_EQ": {"symbol": "BRK.B"}}
    assert portfolio.yahoo_symbol("FB_US_EQ", master) == "META"
    assert portfolio.yahoo_symbol("BRK.B_US_EQ", master) == "BRK-B"
    assert portfolio.yahoo_symbol("IBTAl_EQ", master) == "IBTA.L"
    assert portfolio.broad_sector(3674) == "Technology" and portfolio.broad_sector("7372") == "Technology"
    assert portfolio.broad_sector(5961) == "Consumer discretionary" and portfolio.broad_sector(None) == "unknown"
    assert portfolio.broad_sector(6798) == "Real estate" and portfolio.broad_sector(4911) == "Utilities"


def _series(seed, beta=1.0, base=None, n=250):
    rnd = random.Random(seed)
    days = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    return {d: beta * (base[d] if base else 0) + rnd.gauss(0, 0.01) for d in days}


def test_risk_vol_correlation_and_beta():
    m = _series(1)
    a, b = _series(2, 1.0, m), _series(3, 1.0, m)
    rk = portfolio.risk({"A": 0.5, "B": 0.5}, {"A": a, "B": b}, m)
    assert 0.3 < rk["avg_correlation"] < 0.7          # half common factor, half noise
    assert rk["beta_qqq"] == pytest.approx(1.0, abs=0.25)
    assert rk["covered_weight"] == 1.0 and rk["vol_annual"] > 0
    short = portfolio.risk({"A": 0.5, "B": 0.5}, {"A": a, "B": {"2026-01-01": 0.0}}, m)
    assert short["vol_annual"] is None and short["with_history"] == 1


def test_analyse_flags_concentration_and_moves_and_reports(store):
    snap = portfolio.snapshot(FakeClient())
    rets = {"AAA_US_EQ": {**{f"2026-01-{i:02d}": 0.0 for i in range(1, 20)}, "2026-01-20": -0.15}}
    a = portfolio.analyse(snap, store, rets, None, CFG)
    w = {r["t212_ticker"]: r["weight"] for r in a["rows"]}
    assert w["AAA_US_EQ"] == pytest.approx(0.5) and a["concentration"]["effective_holdings"] == pytest.approx(1 / 0.38)
    assert any("AAA_US_EQ is 50.0%" in f for f in a["flags"])            # over the 40% position threshold
    assert any("moved -15.0% over 5" in f for f in a["flags"])
    assert any("broad sector 'ETF, fund or unmapped' is 100%" in f for f in a["flags"])   # nothing in the master here
    assert a["exposure"]["currency"] == {"USD": pytest.approx(1.0)}
    md = portfolio.report(a, ["X: no data"])
    assert "Portfolio monitor" in md and "Price history unavailable for: X: no data" in md
