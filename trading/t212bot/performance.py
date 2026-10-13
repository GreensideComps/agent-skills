"""Contribution-adjusted performance and account reconciliation (pure functions).

Definitions
-----------
net contributions  = deposits − withdrawals (money you put in, not earnings)
investment gain    = total value − net contributions
time-weighted return (TWR) = chain-linked Modified-Dietz returns between
    account snapshots, so deposits/withdrawals do not count as performance
high-water mark    = running maximum of the TWR wealth index; drawdown is
    measured from it

Reconciliation identities (verified by hand against the demo account on
2026-10-13; API values are rounded to 2 dp, hence the tolerance):
  R1 total value      = available + reserved + in pies + investments value
  R2 investments      = Σ positions walletImpact.currentValue
  R3 cash             = deposits − withdrawals − Σ buy netValue + Σ sell netValue
                        + dividends + interest − other fees
  R4 investment gain  = unrealised + realised + dividends + interest − fees
  R5 holdings qty     = Σ filled buys − Σ filled sells per ticker
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

CONTRIB_TYPES = {"DEPOSIT": 1, "WITHDRAW": -1, "WITHDRAWAL": -1}


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass(frozen=True)
class CashFlow:
    ts: datetime
    amount: float        # + into the account, − out of it
    kind: str
    reference: str = ""


@dataclass
class Flows:
    contributions: list[CashFlow] = field(default_factory=list)
    fees: float = 0.0            # account-level fees from /transactions (positive = cost)
    other: list[dict] = field(default_factory=list)   # TRANSFER/unknown types, surfaced in the report

    @property
    def deposits(self) -> float:
        return sum(f.amount for f in self.contributions if f.amount > 0)

    @property
    def withdrawals(self) -> float:
        return -sum(f.amount for f in self.contributions if f.amount < 0)

    @property
    def net(self) -> float:
        return self.deposits - self.withdrawals


def extract_flows(transactions: list[dict]) -> Flows:
    out = Flows()
    for t in transactions:
        typ = str(t.get("type", "")).upper()
        amt = float(t.get("amount") or 0)
        if typ in CONTRIB_TYPES:
            out.contributions.append(CashFlow(parse_ts(t["dateTime"]), CONTRIB_TYPES[typ] * abs(amt), typ, t.get("reference", "")))
        elif typ == "FEE":
            out.fees += abs(amt)
        else:
            out.other.append(t)
    out.contributions.sort(key=lambda f: f.ts)
    return out


@dataclass
class FillStats:
    buys_net: float = 0.0
    sells_net: float = 0.0
    fees: float = 0.0
    fees_by_type: dict = field(default_factory=dict)
    qty_by_ticker: dict = field(default_factory=dict)
    orders: list[dict] = field(default_factory=list)


def fill_stats(history_items: list[dict]) -> FillStats:
    s = FillStats()
    for it in history_items:
        o, f = it.get("order") or {}, it.get("fill") or {}
        rec = {"id": o.get("id"), "ticker": o.get("ticker"), "side": o.get("side"), "type": o.get("type"),
               "status": o.get("status"), "quantity": o.get("quantity"), "filled": o.get("filledQuantity"),
               "created": o.get("createdAt"), "initiated": o.get("initiatedFrom"),
               "fill_price": f.get("price"), "filled_at": f.get("filledAt")}
        wi = f.get("walletImpact") or {}
        fee = 0.0
        for tax in wi.get("taxes") or []:
            q = abs(float(tax.get("quantity") or 0))
            fee += q
            s.fees_by_type[tax.get("name", "UNKNOWN")] = s.fees_by_type.get(tax.get("name", "UNKNOWN"), 0.0) + q
        s.fees += fee
        rec["fees"] = round(fee, 4)
        rec["net_value"] = wi.get("netValue")
        if f and float(f.get("quantity") or 0) != 0:
            qty = float(f.get("quantity") or o.get("filledQuantity") or 0)
            nv = abs(float(wi.get("netValue") or 0))
            if o.get("side") == "SELL" or qty < 0:
                s.sells_net += nv
                s.qty_by_ticker[o.get("ticker")] = s.qty_by_ticker.get(o.get("ticker"), 0.0) - abs(qty)
            else:
                s.buys_net += nv
                s.qty_by_ticker[o.get("ticker")] = s.qty_by_ticker.get(o.get("ticker"), 0.0) + abs(qty)
        s.orders.append(rec)
    return s


# ---------------------------------------------------------------- returns

@dataclass
class Perf:
    twr: float | None
    index: list[tuple[str, float]]
    hwm: float | None
    drawdown: float | None
    max_drawdown: float | None
    periods: int


def time_weighted(snapshots: list[tuple[datetime, float]], flows: list[CashFlow]) -> Perf:
    snaps = sorted((t, v) for t, v in snapshots if v is not None)
    if len(snaps) < 2:
        return Perf(None, [(snaps[0][0].isoformat(), 1.0)] if snaps else [], None if not snaps else 1.0, 0.0 if snaps else None, 0.0 if snaps else None, 0)
    idx, hwm, mdd = 1.0, 1.0, 0.0
    series = [(snaps[0][0].isoformat(), 1.0)]
    periods = 0
    for (t0, v0), (t1, v1) in zip(snaps, snaps[1:]):
        span = (t1 - t0).total_seconds()
        inside = [f for f in flows if t0 < f.ts <= t1]
        F = sum(f.amount for f in inside)
        weighted = sum(f.amount * ((t1 - f.ts).total_seconds() / span if span > 0 else 0.0) for f in inside)
        denom = v0 + weighted
        if denom <= 0:
            continue
        r = (v1 - v0 - F) / denom
        idx *= 1 + r
        periods += 1
        hwm = max(hwm, idx)
        mdd = min(mdd, idx / hwm - 1)
        series.append((t1.isoformat(), idx))
    return Perf(idx - 1, series, hwm, idx / hwm - 1, mdd, periods)


# ---------------------------------------------------------------- reconciliation

@dataclass
class Check:
    name: str
    status: str          # PASS / WARN / FAIL / SKIP
    detail: str
    expected: float | None = None
    actual: float | None = None

    def to_dict(self):
        return asdict(self)


def tolerance(total: float) -> float:
    return max(0.05, abs(total) * 0.0005)


def reconcile(summary: dict, positions: list[dict], flows: Flows, fills: FillStats,
              dividends_total: float, interest_total: float = 0.0, history_complete: bool = True) -> list[Check]:
    checks: list[Check] = []
    cash = summary.get("cash") or {}
    inv = summary.get("investments") or {}
    total = float(summary.get("totalValue") or 0)
    tol = tolerance(total)
    avail, reserved, pies = (float(cash.get(k) or 0) for k in ("availableToTrade", "reservedForOrders", "inPies"))
    inv_value = float(inv.get("currentValue") or 0)

    def mk(name, expected, actual, what):
        diff = actual - expected
        st = "PASS" if abs(diff) <= tol else "FAIL"
        checks.append(Check(name, st, f"{what}: expected £{expected:.2f}, actual £{actual:.2f}, diff £{diff:+.2f} (tol £{tol:.2f})", round(expected, 4), round(actual, 4)))

    mk("R1 total = cash + investments", avail + reserved + pies + inv_value, total, "total value")
    pos_sum = sum(float((p.get("walletImpact") or {}).get("currentValue") or 0) for p in positions)
    mk("R2 investments = Σ positions", pos_sum, inv_value, "investments value")
    if history_complete:
        exp_cash = flows.deposits - flows.withdrawals - fills.buys_net + fills.sells_net + dividends_total + interest_total - flows.fees
        mk("R3 cash ledger", exp_cash, avail + reserved + pies, "cash from transaction history")
    else:
        checks.append(Check("R3 cash ledger", "SKIP", "order/transaction history incomplete (API error or pagination cap)"))
    gain = total - flows.net
    exp_gain = float(inv.get("unrealizedProfitLoss") or 0) + float(inv.get("realizedProfitLoss") or 0) + dividends_total + interest_total - fills.fees - flows.fees
    mk("R4 gain = P&L components", exp_gain, gain, "investment gain")
    if history_complete:
        api_qty = {p["instrument"]["ticker"]: float(p["quantity"]) for p in positions}
        bad = []
        for t in set(api_qty) | set(fills.qty_by_ticker):
            a, h = api_qty.get(t, 0.0), fills.qty_by_ticker.get(t, 0.0)
            if abs(a - h) > 1e-6:
                bad.append(f"{t}: positions {a} vs fills {h}")
        checks.append(Check("R5 holdings = Σ fills", "FAIL" if bad else "PASS", "; ".join(bad) or "all position quantities match filled orders"))
    else:
        checks.append(Check("R5 holdings = Σ fills", "SKIP", "history incomplete"))
    if flows.other:
        checks.append(Check("R6 unclassified transactions", "WARN", f"{len(flows.other)} transaction(s) of type(s) {sorted({o.get('type') for o in flows.other})} not classified"))
    return checks
