"""Orchestrates one bot run with every safety check in the path to an order."""
from __future__ import annotations

import dataclasses
import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .client import AmbiguousOrderError, ApiError, NotFound, T212Client
from .config import ROOT, SafetyError, StrategyConfig, kill_switch_engaged
from .journal import Journal, utcnow
from .market import YahooQuotes, check_against_t212, check_fresh, to_gbp, tradable_now
from .planner import Holding, plan_rebalance, round_down
from .signals import resolve_targets

TERMINAL = {"FILLED", "CANCELLED", "REJECTED", "REPLACED"}
CACHE = ROOT / "cache"


def _instrument_ccy(meta: dict) -> str:
    return meta["currencyCode"]


class Bot:
    def __init__(self, client: T212Client, cfg: StrategyConfig, journal: Journal,
                 quotes: YahooQuotes | None = None, now=utcnow, sleep=time.sleep,
                 instruments: list[dict] | None = None, exchanges: list[dict] | None = None,
                 env: dict | None = None, kill_file: Path | None = None, daily_loader=None):
        self.c, self.cfg, self.j = client, cfg, journal
        self._daily_loader = daily_loader
        self.q = quotes or YahooQuotes()
        self.now, self.sleep = now, sleep
        self._instruments, self._exchanges = instruments, exchanges
        self._env, self._kill_file = env, kill_file

    # ------------------------------------------------------------ metadata
    def instruments(self) -> dict[str, dict]:
        if self._instruments is None:
            p = CACHE / "instruments.json"
            if p.exists() and time.time() - p.stat().st_mtime < 86400:
                self._instruments = json.loads(p.read_text())
            else:
                self._instruments = self.c.instruments()
                CACHE.mkdir(exist_ok=True)
                p.write_text(json.dumps(self._instruments))
        return {i["ticker"]: i for i in self._instruments}

    def exchanges(self) -> list[dict]:
        if self._exchanges is None:
            self._exchanges = self.c.exchanges()
        return self._exchanges

    # ------------------------------------------------------------ helpers
    def _kill(self) -> str | None:
        kw = {"env": self._env} if self._env is not None else {}
        if self._kill_file is not None:
            kw["kill_file"] = self._kill_file
        return kill_switch_engaged(**kw)

    def _t212_price_ccy(self, pos: dict, meta: dict) -> float:
        px = float(pos.get("currentPrice") or 0)
        return px / 100 if meta["currencyCode"] == "GBX" else px

    def _quotes(self, tickers, positions_by_ticker, meta, require_fresh: bool):
        gbpusd = self.q.gbpusd()
        if require_fresh:
            check_fresh(gbpusd, self.now())
        prices_gbp, refs = {}, {}
        for t in tickers:
            sym = self.cfg.yahoo_symbols.get(t)
            if not sym:
                raise SafetyError(f"no reference symbol for {t}")
            q = self.q.quote(sym)
            ccy = "GBP" if meta[t]["currencyCode"] in ("GBP", "GBX") else meta[t]["currencyCode"]
            if q.currency != ccy:
                raise SafetyError(f"{t}: Yahoo currency {q.currency} != instrument currency {ccy}")
            if require_fresh:
                check_fresh(q, self.now())
            if t in positions_by_ticker:
                check_against_t212(q, self._t212_price_ccy(positions_by_ticker[t], meta[t]), self.cfg.max_price_divergence)
            prices_gbp[t] = to_gbp(q.price, q.currency, gbpusd.price)
            refs[t] = {"price": q.price, "currency": q.currency, "as_of": q.as_of.isoformat(), "symbol": sym,
                       "gbpusd": gbpusd.price, "price_gbp": prices_gbp[t]}
        return prices_gbp, refs

    def _holdings(self, positions, prices_gbp, meta) -> dict[str, Holding]:
        out = {}
        for p in positions:
            t = p["instrument"]["ticker"]
            px = prices_gbp.get(t)
            if px is None:
                wi = p.get("walletImpact") or {}
                px = (wi.get("currentValue") or 0) / p["quantity"] if p["quantity"] else 0
            out[t] = Holding(t, float(p["quantity"]), float(p.get("quantityAvailableForTrading", p["quantity"])), px)
        return out

    # ------------------------------------------------------------ order flow
    def _place(self, ticker: str, qty: float, ref: dict, reason: str, state: dict) -> dict | None:
        decs = state.setdefault("qty_decimals", {})
        d0 = decs.get(ticker, self.cfg.default_qty_decimals)
        sign = 1 if qty > 0 else -1
        for d in range(d0, -1, -1):
            q = sign * round_down(abs(qty), d)
            cash_now = None
            if q > 0:
                capped, cash_now = self._cap_buy(q, d, ref, state)
                if capped < q:
                    self.j.event("order_resized", ticker=ticker, planned=q, capped=capped, cash_gbp=cash_now,
                                 reserve=self._reserve(state))
                q = capped
                if q * ref["price_gbp"] < self.cfg.min_trade_gbp:
                    self.j.event("order_abandoned", ticker=ticker, reason="below minimum after cash cap", cash_gbp=cash_now)
                    return None
            if q == 0:
                break
            placed_at = self.now()
            try:
                order = self.c.place_market_order(ticker, q)
            except AmbiguousOrderError as e:
                self.j.event("order_ambiguous", ticker=ticker, quantity=q, error=str(e))
                found = self._find_recent_order(ticker, q, placed_at)
                self.j.event("order_ambiguous_resolution", ticker=ticker, found=found)
                raise SafetyError(f"ambiguous order outcome for {ticker}; stopped (found={bool(found)})")
            except ApiError as e:
                if e.status == 400 and "insufficient-free" in e.body and q > 0:
                    # Rejected before reaching the book, so retrying is safe. Funds from a
                    # just-filled order can be held briefly: wait, refresh cash, resize.
                    if cash_now is not None:
                        fee = self.cfg.fx_fee if ref.get("currency") != "GBP" else 0.0
                        self._learn_reserve(state, cash_now, q * ref["price_gbp"] * (1 + fee), accepted=False)
                    order = self._retry_buy_with_fresh_cash(ticker, q, d, ref, reason, e, state)
                    if order:
                        decs[ticker] = d
                        return order
                    raise
                precision = e.status == 400 and re.search(r"quantity|precision|decimal|fraction", e.body, re.I)
                self.j.event("order_rejected", ticker=ticker, quantity=q, status=e.status, body=e.body[:500],
                             will_retry_lower_precision=bool(precision) and d > 0)
                if precision and d > 0:
                    continue
                raise
            decs[ticker] = d
            if q > 0 and cash_now is not None:
                fee = self.cfg.fx_fee if ref.get("currency") != "GBP" else 0.0
                self._learn_reserve(state, cash_now, q * ref["price_gbp"] * (1 + fee), accepted=True)
            self.j.event("order_placed", ticker=ticker, quantity=q, order_id=order.get("id"), status=order.get("status"),
                         reference=ref, reason=reason, response=order)
            return order
        return None

    # Trading 212 holds extra cash on market BUYs (not documented). Observed on the
    # demo on 2026-10-13: £50.70 free rejected £49.17 and £48.67 buys and accepted
    # £46.71, so the hold is between ~4.2% and ~8.5%. Bounds are learned per run.
    DEFAULT_RESERVE = 0.06

    def _reserve(self, state) -> float:
        r = state.get("buy_reserve", {})
        lo, hi = r.get("lower"), r.get("upper")
        if lo is not None and hi is not None and lo < hi:
            return min((lo + hi) / 2, self.DEFAULT_RESERVE * 2)   # bisection narrows the interval
        if hi is not None:                # only "it worked with this much headroom": weak info
            return min(hi, self.DEFAULT_RESERVE)
        if lo is not None:
            return max(self.DEFAULT_RESERVE, lo + 0.02)
        return self.DEFAULT_RESERVE

    def _learn_reserve(self, state, cash: float, value: float, accepted: bool) -> None:
        if value <= 0:
            return
        ratio = cash / value - 1
        r = state.setdefault("buy_reserve", {})
        if accepted:
            r["upper"] = round(min(r["upper"], ratio) if "upper" in r else ratio, 4)
        else:
            r["lower"] = round(max(r["lower"], ratio) if "lower" in r else ratio, 4)

    def _cap_buy(self, q: float, d: int, ref: dict, state: dict) -> tuple[float, float]:
        cash = float(self.c.account_summary()["cash"]["availableToTrade"])
        fee = self.cfg.fx_fee if ref.get("currency") != "GBP" else 0.0
        fit = round_down(cash / (1 + self._reserve(state)) / (1 + fee) / ref["price_gbp"], d)
        return min(q, fit), cash

    def _retry_buy_with_fresh_cash(self, ticker, q, d, ref, reason, first_err, state=None):
        state = state if state is not None else {}
        self.j.event("order_rejected", ticker=ticker, quantity=q, status=first_err.status,
                     body=first_err.body[:500], will_retry_with_fresh_cash=True)
        fee = self.cfg.fx_fee if ref.get("currency") != "GBP" else 0.0
        for frac in (1.0, 0.97, 0.93):
            self.sleep(6)
            cash = float(self.c.account_summary()["cash"]["availableToTrade"])
            fit = round_down(cash * frac / (1 + self._reserve(state)) / (1 + fee) / ref["price_gbp"], d)
            q2 = min(q, fit)
            if q2 <= 0 or q2 * ref["price_gbp"] < self.cfg.min_trade_gbp:
                self.j.event("order_abandoned", ticker=ticker, reason="not enough cash for minimum trade", cash_gbp=cash)
                return None
            try:
                order = self.c.place_market_order(ticker, q2)
            except ApiError as e:
                if e.status == 400 and "insufficient-free" in e.body:
                    self._learn_reserve(state, cash, q2 * ref["price_gbp"] * (1 + fee), accepted=False)
                    self.j.event("order_rejected", ticker=ticker, quantity=q2, status=e.status, body=e.body[:500],
                                 will_retry_with_fresh_cash=frac != 0.93, cash_gbp=cash)
                    continue
                raise
            self._learn_reserve(state, cash, q2 * ref["price_gbp"] * (1 + fee), accepted=True)
            self.j.event("order_placed", ticker=ticker, quantity=q2, order_id=order.get("id"), status=order.get("status"),
                         reference=ref, reason=reason + f" (resized to fresh cash £{cash:.2f})", response=order)
            return order
        return None

    def _find_recent_order(self, ticker, qty, since: datetime):
        try:
            for o in self.c.pending_orders() or []:
                if o.get("ticker") == ticker and abs(float(o.get("quantity", 0)) - qty) < 1e-9:
                    return {"where": "pending", "id": o.get("id")}
            for it in self.c.history_orders(ticker=ticker, limit=10, max_pages=1):
                o = it.get("order", {})
                if abs(float(o.get("quantity", 0)) - qty) < 1e-9:
                    return {"where": "history", "id": o.get("id"), "status": o.get("status")}
        except Exception as e:  # reconciliation itself failed: record and stop
            return {"where": "unknown", "error": str(e)}
        return None

    def _await(self, order_id: int, timeout_s: float = 120) -> str:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            try:
                o = self.c.get_order(order_id)
            except NotFound:
                return "NOT_PENDING"
            st = o.get("status", "")
            if st in TERMINAL:
                return st
            self.sleep(2)
        return "TIMEOUT"

    # ------------------------------------------------------------ reconcile
    def reconcile(self) -> list[dict]:
        done = {e["order_id"] for e in self.j.events("order_reconciled")}
        todo = [e for e in self.j.events("order_placed") if e.get("order_id") and e["order_id"] not in done]
        out = []
        by_ticker: dict[str, list[dict]] = {}
        for e in todo:
            by_ticker.setdefault(e["ticker"], []).append(e)
        for ticker, evs in by_ticker.items():
            hist = self.c.history_orders(ticker=ticker, limit=50, max_pages=3)
            idx = {it.get("order", {}).get("id"): it for it in hist}
            for e in evs:
                it = idx.get(e["order_id"])
                if not it:
                    continue
                o, f = it.get("order", {}), it.get("fill") or {}
                status = o.get("status")
                rec = {"order_id": e["order_id"], "ticker": ticker, "status": status,
                       "filled_quantity": o.get("filledQuantity"), "fill_price": f.get("price"),
                       "filled_at": f.get("filledAt"), "wallet_impact": f.get("walletImpact")}
                ref = e.get("reference") or {}
                wi = f.get("walletImpact") or {}
                side = 1 if e["quantity"] > 0 else -1
                qty = abs(o.get("filledQuantity") or 0)
                # Compare in GBP: the fill price is quoted in the instrument's unit (GBX for most LSE lines, USD...),
                # the reference is not, so price/price can be off by 100x. netValue is GBP; listed taxes/fees (FX fee) are
                # removed so this measures price only (fees stay in cost_vs_reference_gbp).
                if wi.get("currency") == "GBP" and wi.get("netValue") and qty and ref.get("price_gbp"):
                    fees = sum(abs(float(x.get("quantity") or 0)) for x in wi.get("taxes") or [])
                    rec["fill_price_gbp"] = round((abs(wi["netValue"]) - side * fees) / qty, 6)
                    rec["slippage_bps_vs_reference"] = round(side * (rec["fill_price_gbp"] / ref["price_gbp"] - 1) * 1e4, 2)
                    rec["reference_price"] = ref["price_gbp"]
                    rec["reference_as_of"] = ref.get("as_of")
                elif f.get("price") and ref.get("price") and ref.get("currency") == o.get("currency"):
                    rec["slippage_bps_vs_reference"] = round(side * (f["price"] / ref["price"] - 1) * 1e4, 2)
                    rec["reference_price"] = ref["price"]
                    rec["reference_as_of"] = ref.get("as_of")
                if wi.get("netValue") is not None and ref.get("price_gbp") and o.get("filledQuantity"):
                    ideal = abs(o["filledQuantity"]) * ref["price_gbp"]
                    rec["cost_vs_reference_gbp"] = round((abs(wi["netValue"]) - ideal) * (1 if e["quantity"] > 0 else -1), 4)
                if status in TERMINAL or f:
                    self.j.event("order_reconciled", **rec)
                    out.append(rec)
        return out

    def _resolve_signal(self, state: dict) -> StrategyConfig:
        """Static strategies pass through; a trend strategy gets today's targets.
        Any data problem raises SafetyError before an order can be planned."""
        if self.cfg.signal is None:
            return self.cfg
        if self._daily_loader is None:
            from .shadow import yahoo_daily
            self._daily_loader = yahoo_daily
        targets, info = resolve_targets(self.cfg, self.now().date(), self._daily_loader)
        prev = state.get("signal_on")
        self.j.event("signal", targets=targets, changed=prev is not None and prev != info["on"], **info)
        state["signal_on"] = info["on"]
        return dataclasses.replace(self.cfg, targets=targets)

    # ------------------------------------------------------------ main
    def run(self, execute: bool = False, force: bool = False) -> dict:
        j = self.j
        state = j.load_state()
        state.setdefault("strategy", self.cfg.name)
        j.event("run_start", execute=execute, force=force, strategy=self.cfg.name)

        summary = self.c.account_summary()
        positions = self.c.positions() or []
        snap = j.snapshot(summary, positions)
        if "inception" not in state:
            state["inception"] = {"ts_utc": snap["ts_utc"], "total_value_gbp": snap["total_value_gbp"]}

        recon = self.reconcile()

        kill = self._kill()
        if kill:
            j.event("run_halted", reason=kill)
            j.save_state(state)
            return {"status": "halted", "reason": kill}

        pending = self.c.pending_orders() or []
        if pending:
            j.event("run_skipped", reason="pending orders exist", pending=[{"id": o.get("id"), "ticker": o.get("ticker"), "status": o.get("status")} for o in pending])
            j.save_state(state)
            return {"status": "skipped", "reason": "pending orders exist"}

        try:
            cfg = self._resolve_signal(state)
        except Exception as e:  # never trade on a broken or stale signal; still keep the snapshot
            j.event("run_failed", reason=f"signal: {e}")
            j.save_state(state)
            raise SafetyError(f"signal unavailable, not trading: {e}") from None
        meta = self.instruments()
        pos_by = {p["instrument"]["ticker"]: p for p in positions}
        tickers = sorted(set(cfg.targets) | set(pos_by))
        unknown = [t for t in tickers if t not in meta]
        if unknown:
            raise SafetyError(f"tickers not in Trading 212 instrument list: {unknown}")
        # Market hours first: outside a session quotes are legitimately stale, so
        # plan on them for the record but never trade on them.
        closed_reason = None
        if execute:
            exch = self.exchanges()
            for t in tickers:
                ok, why = tradable_now(exch, meta[t]["workingScheduleId"], self.now(),
                                       cfg.open_buffer_minutes, cfg.close_buffer_minutes)
                if not ok:
                    closed_reason = f"{t}: {why}"
                    break
        prices_gbp, refs = self._quotes(tickers, pos_by, meta, require_fresh=execute and closed_reason is None)
        currencies = {t: ("GBP" if meta[t]["currencyCode"] in ("GBP", "GBX") else meta[t]["currencyCode"]) for t in tickers}
        holdings = self._holdings(positions, prices_gbp, meta)
        cash = float(summary["cash"]["availableToTrade"])
        today = self.now().date()
        plan = plan_rebalance(cash, holdings, prices_gbp, currencies, cfg, today,
                              state.get("last_rebalance_month"), state.get("qty_decimals"), force=force)
        j.event("plan", needs_rebalance=plan.needs_rebalance, reasons=plan.reasons, total_value_gbp=plan.total_value_gbp,
                cash_gbp=plan.cash_gbp, current_weights=plan.current_weights, target_weights=plan.target_weights,
                drift=plan.drift, orders=[asdict(o) for o in plan.orders], references=refs)
        result = {"status": "planned", "plan": plan, "reconciled": recon}
        if not plan.needs_rebalance or not plan.orders:
            state["last_check_utc"] = self.now().isoformat(timespec="seconds")
            j.save_state(state)
            result["status"] = "no_action"
            return result
        if not execute:
            j.save_state(state)
            result["status"] = "dry_run"
            return result

        if closed_reason:
            j.event("run_deferred", reason=closed_reason)
            j.save_state(state)
            result["status"] = "deferred"
            result["reason"] = closed_reason
            return result

        placed = []
        for o in [x for x in plan.orders if x.side == "SELL"]:
            order = self._place(o.ticker, o.quantity, refs[o.ticker], o.reason, state)
            if order:
                placed.append((order, self._await(order["id"])))
        if placed:
            self.sleep(3)
            summary = self.c.account_summary()
            positions = self.c.positions() or []
            holdings = self._holdings(positions, prices_gbp, meta)
            cash = float(summary["cash"]["availableToTrade"])
            plan2 = plan_rebalance(cash, holdings, prices_gbp, currencies, cfg, today,
                                   state.get("last_rebalance_month"), state.get("qty_decimals"), force=True)
            buys = [x for x in plan2.orders if x.side == "BUY"]
            j.event("replan_after_sells", cash_gbp=cash, orders=[asdict(o) for o in buys])
        else:
            buys = [x for x in plan.orders if x.side == "BUY"]
        for o in buys:
            order = self._place(o.ticker, o.quantity, refs[o.ticker], o.reason, state)
            if order:
                placed.append((order, self._await(order["id"])))

        state["last_rebalance_month"] = today.strftime("%Y-%m")
        state["last_rebalance_utc"] = self.now().isoformat(timespec="seconds")
        j.save_state(state)
        self.sleep(5)
        result["reconciled"] = recon + self.reconcile()
        summary = self.c.account_summary()
        positions = self.c.positions() or []
        result["final_snapshot"] = j.snapshot(summary, positions)
        result["placed"] = [{"id": o.get("id"), "ticker": o.get("ticker"), "quantity": o.get("quantity"), "final": st} for o, st in placed]
        j.event("run_end", placed=result["placed"])
        result["status"] = "executed"
        return result
