from datetime import date

import pytest

from t212bot.config import SafetyError
from t212bot.planner import Holding, plan_rebalance, round_down

FX = 1.3237
PX = {"VWRPl_EQ": 146.40, "IWMOl_EQ": 116.95 / FX}
CCY = {"VWRPl_EQ": "GBP", "IWMOl_EQ": "USD", "SGLNl_EQ": "GBP"}
D = date(2026, 10, 13)


def test_round_down_is_exact():
    assert round_down(0.1 + 0.2, 4) == 0.3
    assert round_down(1.99999, 2) == 1.99
    assert round_down(0.33333333, 4) == 0.3333
    assert round_down(-1, 3) == 0.0


def test_initial_deploy_from_cash(cfg):
    p = plan_rebalance(100.0, {}, PX, CCY, cfg, D)
    assert p.needs_rebalance and any("uninvested cash" in r for r in p.reasons)
    assert [o.side for o in p.orders] == ["BUY", "BUY"]
    by = {o.ticker: o for o in p.orders}
    # each leg ≈ 50% of 98.5% investable, IWMO leg budgets the 0.15% FX fee
    assert 48.5 < by["VWRPl_EQ"].est_value_gbp <= 49.25
    assert 48.5 < by["IWMOl_EQ"].est_value_gbp <= 49.25 / 1.0015
    assert by["VWRPl_EQ"].quantity == round_down(49.25 / 146.40, 4)
    assert 0.0 <= p.projected_cash_gbp <= 3.0


def test_no_action_inside_band(cfg):
    h = {"VWRPl_EQ": Holding("VWRPl_EQ", 0.336, 0.336, 146.40), "IWMOl_EQ": Holding("IWMOl_EQ", 0.555, 0.555, PX["IWMOl_EQ"])}
    p = plan_rebalance(1.5, h, PX, CCY, cfg, D, last_rebalance_month="2026-10")
    assert not p.needs_rebalance and p.orders == []


def test_drift_triggers_sell_then_buy(cfg):
    px = dict(PX, VWRPl_EQ=146.40 * 1.4)  # VWRP rallied 40%
    h = {"VWRPl_EQ": Holding("VWRPl_EQ", 0.336, 0.336, px["VWRPl_EQ"]), "IWMOl_EQ": Holding("IWMOl_EQ", 0.555, 0.555, PX["IWMOl_EQ"])}
    p = plan_rebalance(1.0, h, px, CCY, cfg, D)
    assert any("drift" in r for r in p.reasons)
    assert [o.side for o in p.orders] == ["SELL", "BUY"]
    sell = p.orders[0]
    assert sell.ticker == "VWRPl_EQ" and sell.quantity < 0 and -sell.quantity <= 0.336


def test_sell_never_exceeds_available(cfg):
    px = dict(PX, VWRPl_EQ=146.40 * 2)
    h = {"VWRPl_EQ": Holding("VWRPl_EQ", 0.6, 0.05, px["VWRPl_EQ"]), "IWMOl_EQ": Holding("IWMOl_EQ", 0.1, 0.1, PX["IWMOl_EQ"])}
    p = plan_rebalance(0.0, h, px, CCY, cfg, D)
    sells = [o for o in p.orders if o.side == "SELL"]
    assert sells and -sells[0].quantity <= 0.05


def test_non_target_holding_is_exited(cfg):
    h = {"SGLNl_EQ": Holding("SGLNl_EQ", 0.5, 0.5, 61.40)}
    p = plan_rebalance(70.0, h, dict(PX, SGLNl_EQ=61.40), CCY, cfg, D)
    s = [o for o in p.orders if o.ticker == "SGLNl_EQ"]
    assert s and s[0].quantity == -0.5 and "exit" in s[0].reason


def test_annual_rebalance_once_per_month(cfg):
    h = {"VWRPl_EQ": Holding("VWRPl_EQ", 0.35, 0.35, 146.40), "IWMOl_EQ": Holding("IWMOl_EQ", 0.53, 0.53, PX["IWMOl_EQ"])}
    jan = date(2027, 1, 5)
    assert plan_rebalance(1.5, h, PX, CCY, cfg, jan, last_rebalance_month="2026-10").needs_rebalance
    assert not plan_rebalance(1.5, h, PX, CCY, cfg, jan, last_rebalance_month="2027-01").needs_rebalance


def test_min_trade_skips_dust(cfg):
    h = {"VWRPl_EQ": Holding("VWRPl_EQ", 0.336, 0.336, 146.40), "IWMOl_EQ": Holding("IWMOl_EQ", 0.555, 0.555, PX["IWMOl_EQ"])}
    p = plan_rebalance(1.5, h, PX, CCY, cfg, D, force=True)
    assert all(o.est_value_gbp >= cfg.min_trade_gbp for o in p.orders)


def test_qty_decimals_respected(cfg):
    p = plan_rebalance(100.0, {}, PX, CCY, cfg, D, qty_decimals={"VWRPl_EQ": 1, "IWMOl_EQ": 2})
    by = {o.ticker: o for o in p.orders}
    assert by["VWRPl_EQ"].quantity == 0.3 and by["IWMOl_EQ"].quantity == round_down(by["IWMOl_EQ"].quantity, 2)


def test_buys_scaled_to_cash(cfg):
    # holdings far below target but cash tiny relative to total: buys must not overdraw
    h = {"VWRPl_EQ": Holding("VWRPl_EQ", 0.6, 0.6, 146.40)}
    p = plan_rebalance(2.0, h, PX, CCY, cfg, D)
    assert p.projected_cash_gbp >= -0.01


def test_invalid_inputs(cfg):
    with pytest.raises(SafetyError):
        plan_rebalance(-1.0, {}, PX, CCY, cfg, D)
    with pytest.raises(SafetyError):
        plan_rebalance(100.0, {}, {"VWRPl_EQ": 146.4}, CCY, cfg, D)
    with pytest.raises(SafetyError):
        plan_rebalance(0.0, {}, PX, CCY, cfg, D)


def test_max_orders_per_run(cfg):
    cfg.max_orders_per_run = 1
    with pytest.raises(SafetyError):
        plan_rebalance(100.0, {}, PX, CCY, cfg, D)
