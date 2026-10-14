"""Pure order planning: current holdings + prices + targets -> orders.

No I/O here, so every rule is unit-tested. Values are in GBP.

Rebalance triggers (any one):
  * uninvested cash above cash_buffer_pct + deploy_cash_threshold_pct
  * any holding drifts more than drift_band_abs from its target weight
  * annual rebalance month and drift above annual_rebalance_min_drift,
    if not already rebalanced this calendar month
  * a holding that is not in the target set (it is sold)
Order rules:
  * long-only; sells never exceed quantityAvailableForTrading
  * quantities rounded DOWN to the allowed decimals
  * trades below min_trade_gbp are skipped
  * the 0.15% FX fee is budgeted on non-GBP instruments
  * buys are scaled down if projected cash would breach half the buffer
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

from .config import SafetyError, StrategyConfig


@dataclass(frozen=True)
class Holding:
    ticker: str
    quantity: float
    quantity_available: float
    price_gbp: float

    @property
    def value_gbp(self) -> float:
        return self.quantity * self.price_gbp


@dataclass(frozen=True)
class PlannedOrder:
    ticker: str
    side: str            # BUY / SELL
    quantity: float      # signed: + buy, - sell (API convention)
    est_value_gbp: float
    price_gbp: float
    reason: str


@dataclass
class Plan:
    total_value_gbp: float
    cash_gbp: float
    current_weights: dict[str, float]
    target_weights: dict[str, float]
    drift: dict[str, float]
    needs_rebalance: bool
    reasons: list[str] = field(default_factory=list)
    orders: list[PlannedOrder] = field(default_factory=list)
    projected_cash_gbp: float = 0.0


def round_down(x: float, decimals: int) -> float:
    if x <= 0:
        return 0.0
    q = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_DOWN))


def plan_rebalance(cash_gbp: float, holdings: dict[str, Holding], prices_gbp: dict[str, float],
                   currencies: dict[str, str], cfg: StrategyConfig, today: date,
                   last_rebalance_month: str | None = None,
                   qty_decimals: dict[str, int] | None = None, force: bool = False) -> Plan:
    if cash_gbp < 0:
        raise SafetyError("negative cash")
    qty_decimals = qty_decimals or {}
    for t in cfg.targets:
        if prices_gbp.get(t, 0) <= 0:
            raise SafetyError(f"missing/invalid price for target {t}")
    total = cash_gbp + sum(h.value_gbp for h in holdings.values())
    if total <= 0:
        raise SafetyError("account has no value")
    investable = total * (1 - cfg.cash_buffer_pct)
    universe = sorted(set(cfg.targets) | set(holdings))
    tgt_w = {t: cfg.targets.get(t, 0.0) * (1 - cfg.cash_buffer_pct) for t in universe}
    cur_w = {t: (holdings[t].value_gbp / total if t in holdings else 0.0) for t in universe}
    drift = {t: cur_w[t] - tgt_w[t] for t in universe}
    max_drift = max((abs(d) for d in drift.values()), default=0.0)

    reasons = []
    cash_w = cash_gbp / total
    if cfg.targets and cash_w > cfg.cash_buffer_pct + cfg.deploy_cash_threshold_pct:  # all-cash target: cash is the goal
        reasons.append(f"uninvested cash {cash_w:.1%} > {cfg.cash_buffer_pct + cfg.deploy_cash_threshold_pct:.1%}")
    if max_drift > cfg.drift_band_abs:
        worst = max(drift, key=lambda t: abs(drift[t]))
        reasons.append(f"{worst} drift {drift[worst]:+.1%} beyond ±{cfg.drift_band_abs:.0%} band")
    ym = today.strftime("%Y-%m")
    if (today.month == cfg.annual_rebalance_month and last_rebalance_month != ym
            and max_drift > cfg.annual_rebalance_min_drift):
        reasons.append(f"annual rebalance month, max drift {max_drift:.1%}")
    strays = [t for t in holdings if t not in cfg.targets and holdings[t].quantity > 0]
    if strays:
        reasons.append(f"holdings outside target set: {strays}")
    if force:
        reasons.append("forced rebalance")
    plan = Plan(total, cash_gbp, cur_w, tgt_w, drift, bool(reasons), reasons)
    if not plan.needs_rebalance:
        plan.projected_cash_gbp = cash_gbp
        return plan

    def dec(t):
        return qty_decimals.get(t, cfg.default_qty_decimals)

    def fee(t):
        return cfg.fx_fee if currencies.get(t, "GBP") != "GBP" else 0.0

    sells, buys = [], []
    proceeds = 0.0
    for t in universe:
        cur_val = holdings[t].value_gbp if t in holdings else 0.0
        tgt_val = cfg.targets.get(t, 0.0) * investable
        diff = tgt_val - cur_val
        px = prices_gbp.get(t) or (holdings[t].price_gbp if t in holdings else 0)
        if diff < -cfg.min_trade_gbp:
            avail = holdings[t].quantity_available if t in holdings else 0.0
            if t not in cfg.targets:
                qty = round_down(avail, dec(t))
            else:
                qty = min(round_down(-diff / px, dec(t)), round_down(avail, dec(t)))
            if qty > 0 and qty * px >= cfg.min_trade_gbp:
                sells.append(PlannedOrder(t, "SELL", -qty, qty * px, px, "reduce to target" if t in cfg.targets else "exit non-target holding"))
                proceeds += qty * px * (1 - fee(t))
        elif diff > cfg.min_trade_gbp:
            buys.append((t, diff, px))

    cash_avail = cash_gbp + proceeds - total * cfg.cash_buffer_pct * 0.5
    want = sum(d for _, d, _ in buys)
    scale = min(1.0, cash_avail / want) if want > 0 else 1.0
    if scale < 1.0:
        plan.reasons.append(f"buys scaled to {scale:.1%} to respect cash buffer")
    spent = 0.0
    for t, d, px in buys:
        budget = max(0.0, d * scale)
        qty = round_down(budget / (1 + fee(t)) / px, dec(t))
        if qty > 0 and qty * px >= cfg.min_trade_gbp:
            buys_val = qty * px
            spent += buys_val * (1 + fee(t))
            plan.orders.append(PlannedOrder(t, "BUY", qty, buys_val, px, "increase to target"))
    plan.orders = sells + plan.orders
    if len(plan.orders) > cfg.max_orders_per_run:
        raise SafetyError(f"{len(plan.orders)} orders exceeds max_orders_per_run={cfg.max_orders_per_run}")
    plan.projected_cash_gbp = cash_gbp + proceeds - spent
    if plan.projected_cash_gbp < -0.01:
        raise SafetyError(f"plan would overdraw cash: {plan.projected_cash_gbp:.2f}")
    return plan
