"""Daily intelligence report: what the engine actually did and the account's real state.

Pipeline: collect (each source isolated, failures recorded) -> compute (pure)
-> render (Markdown + HTML) -> store under trading/reports/.

Provenance labels used throughout the report:
  [VERIFIED]   read from the Trading 212 API during this report run
  [JOURNAL]    the bot's own append-only records (decisions, attempts, snapshots)
  [SIMULATED]  shadow portfolios computed from public closing prices
  [ESTIMATE]   model-based figures (volatility, VaR, selling costs)
  [BACKTEST]   historical research results (registry), not live performance
  [EXAMPLE]    synthetic data used only for the sample report
"""
from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import adviser as adv
from . import performance as perf
from . import research_feed
from .config import KILL_FILE, ROOT

UK = ZoneInfo("Europe/London")
REPORTS = ROOT / "reports"
RESEARCH_STOP = ROOT.parent / "research" / "STOP"


# ---------------------------------------------------------------- collection

@dataclass
class Src:
    ok: bool
    data: Any
    error: str | None
    at: str


def fetch(fn: Callable, now: Callable[[], datetime]) -> Src:
    t = now().isoformat(timespec="seconds")
    try:
        return Src(True, fn(), None, t)
    except Exception as e:  # recorded and surfaced, never swallowed silently
        return Src(False, None, f"{type(e).__name__}: {str(e)[:300]}", t)


ORDER_PAGES = 40


def collect_account(ro, now: Callable[[], datetime]) -> dict[str, Src]:
    return {
        "summary": fetch(ro.account_summary, now),
        "positions": fetch(ro.positions, now),
        "pending": fetch(ro.pending_orders, now),
        "orders": fetch(lambda: ro.history_orders(limit=50, max_pages=ORDER_PAGES), now),
        "transactions": fetch(ro.history_transactions, now),
        "dividends": fetch(ro.history_dividends, now),
    }


# ---------------------------------------------------------------- helpers

def _f(x, nd=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def _parse(ts: str) -> datetime:
    return perf.parse_ts(ts)


def _journal_series(snapshots: list[dict]) -> list[tuple[datetime, float]]:
    out = []
    for r in snapshots:
        try:
            if r.get("total_value_gbp") not in (None, ""):
                out.append((_parse(r["ts_utc"]), float(r["total_value_gbp"])))
        except Exception:
            continue
    return out


def _events_since(events: list[dict], since: datetime, kinds: set[str] | None = None) -> list[dict]:
    out = []
    for e in events:
        try:
            if _parse(e["ts_utc"]) >= since and (kinds is None or e["kind"] in kinds):
                out.append(e)
        except Exception:
            continue
    return out


def _event_reason(e: dict) -> str:
    if e.get("kind") == "plan":
        rs = e.get("reasons") or []
        return ", ".join(rs) if rs else "checked - no rebalance needed"
    body = e.get("body")
    if body:
        try:
            b = json.loads(body)
            return f"{b.get('detail') or b.get('title') or ''} ({str(b.get('type', b.get('code', ''))).rsplit('/', 1)[-1]})".strip()
        except Exception:
            return str(body)[:160]
    return str(e.get("reason") or e.get("error") or "")


# ---------------------------------------------------------------- compute

def compute(acct: dict[str, Src], journal_snaps: list[dict], journal_events: list[dict], strategy_name: str,
            adviser_cfg: dict, adviser_state: dict, research: dict, market: dict, prev: dict | None,
            delivery: dict | None, now: datetime, example: bool = False, kill: str | None = None,
            research_stop: bool = False) -> tuple[dict, dict]:
    """Returns (metrics, new_adviser_state)."""
    report_date = now.astimezone(UK).date()
    M: dict[str, Any] = {
        "meta": {"report_date": report_date.isoformat(), "generated_utc": now.isoformat(timespec="seconds"),
                 "generated_uk": now.astimezone(UK).strftime("%Y-%m-%d %H:%M %Z"),
                 "environment": "PRACTICE (demo) account - demo.trading212.com; live trading is disabled in code",
                 "strategy": strategy_name, "example": example},
        "data_status": {k: {"ok": s.ok, "error": s.error, "at": s.at} for k, s in acct.items()},
        "alerts": [],
    }
    alerts = M["alerts"]
    for k, s in acct.items():
        if not s.ok:
            alerts.append({"level": "CRITICAL" if k in ("summary", "positions") else "WARN",
                           "msg": f"Trading 212 API call '{k}' failed: {s.error}"})

    S = acct["summary"].data if acct["summary"].ok else None
    P = acct["positions"].data if acct["positions"].ok else None
    orders = acct["orders"].data if acct["orders"].ok else []
    txs = acct["transactions"].data if acct["transactions"].ok else []
    divs = acct["dividends"].data if acct["dividends"].ok else []
    history_complete = acct["orders"].ok and acct["transactions"].ok and acct["dividends"].ok and len(orders) < 50 * ORDER_PAGES

    # ---------------- account
    flows = perf.extract_flows(txs)
    fills = perf.fill_stats(orders)
    dividends_total = sum(float(d.get("amount") or 0) for d in divs if str(d.get("type", "")).upper() != "INTEREST")
    interest_total = sum(float(d.get("amount") or 0) for d in divs if str(d.get("type", "")).upper() == "INTEREST")
    if S is not None and P is not None:
        cash = S.get("cash") or {}
        inv = S.get("investments") or {}
        total = float(S.get("totalValue") or 0)
        holdings = []
        for p in P:
            wi = p.get("walletImpact") or {}
            val = float(wi.get("currentValue") or 0)
            ins = p.get("instrument") or {}
            holdings.append({"ticker": ins.get("ticker"), "name": ins.get("name"), "quantity": p.get("quantity"),
                             "price": p.get("currentPrice"), "currency": ins.get("currency"), "value_gbp": _f(val),
                             "weight": _f(val / total, 4) if total else None,
                             "unrealized_pl_gbp": _f(wi.get("unrealizedProfitLoss")), "cost_gbp": _f(wi.get("totalCost"))})
        M["account"] = {"currency": S.get("currency"), "total_value": _f(total), "cash_available": _f(cash.get("availableToTrade")),
                        "cash_reserved": _f(cash.get("reservedForOrders")), "cash_in_pies": _f(cash.get("inPies")),
                        "invested_value": _f(inv.get("currentValue")), "holdings": holdings}
        checks = perf.reconcile(S, P, flows, fills, dividends_total, interest_total, history_complete)
    else:
        total = None
        M["account"] = None
        checks = [perf.Check("Reconciliation", "SKIP", "account summary/positions unavailable")]
        alerts.append({"level": "CRITICAL", "msg": "Account state could not be read - values below are missing, not zero."})
    M["reconciliation"] = [c.to_dict() for c in checks]
    recon_ok = all(c.status in ("PASS", "WARN") for c in checks) and any(c.status == "PASS" for c in checks)
    for c in checks:
        if c.status == "FAIL":
            alerts.append({"level": "CRITICAL", "msg": f"Reconciliation failed: {c.name} - {c.detail}"})

    # ---------------- flows & performance
    series = _journal_series(journal_snaps)
    if total is not None:
        series = series + [(now, total)]
    pf = perf.time_weighted(series, flows.contributions)
    gain = (total - flows.net) if total is not None and acct["transactions"].ok else None
    M["performance"] = {
        "deposits": _f(flows.deposits), "withdrawals": _f(flows.withdrawals), "net_contributions": _f(flows.net),
        "realized_pl": _f((S or {}).get("investments", {}).get("realizedProfitLoss")) if S else None,
        "unrealized_pl": _f((S or {}).get("investments", {}).get("unrealizedProfitLoss")) if S else None,
        "trading_fees": _f(fills.fees), "fees_by_type": {k: _f(v) for k, v in fills.fees_by_type.items()},
        "account_fees": _f(flows.fees), "dividends": _f(dividends_total), "interest": _f(interest_total),
        "investment_gain": _f(gain), "twr_since_inception": _f(pf.twr, 6), "hwm_index": _f(pf.hwm, 6),
        "drawdown_from_hwm": _f(pf.drawdown, 6), "max_drawdown": _f(pf.max_drawdown, 6), "twr_periods": pf.periods,
        "first_snapshot": series[0][0].isoformat() if series else None,
        "unclassified_transactions": len(flows.other)}
    if not acct["transactions"].ok:
        alerts.append({"level": "WARN", "msg": "Deposits/withdrawals unavailable - contribution-adjusted figures not computed."})

    # ---------------- orders
    since_24h, since_7d = now - timedelta(hours=24), now - timedelta(days=7)

    def recent(o, since):
        try:
            return _parse(o["created"]) >= since
        except Exception:
            return False
    M["orders"] = {
        "verified_all": fills.orders, "verified_24h": [o for o in fills.orders if recent(o, since_24h)],
        "verified_7d_count": sum(1 for o in fills.orders if recent(o, since_7d)),
        "pending_now": [{"id": o.get("id"), "ticker": o.get("ticker"), "quantity": o.get("quantity"), "status": o.get("status"),
                         "created": o.get("createdAt")} for o in (acct["pending"].data or [])] if acct["pending"].ok else None,
        "journal_24h": [{"ts": e["ts_utc"], "kind": e["kind"], "ticker": e.get("ticker"), "quantity": e.get("quantity"),
                         "reason": _event_reason(e)}
                        for e in _events_since(journal_events, since_24h,
                                               {"order_placed", "order_rejected", "order_abandoned", "order_resized",
                                                "order_ambiguous", "order_ambiguous_resolution", "run_failed", "run_deferred",
                                                "run_skipped", "run_halted", "plan"})],
    }
    for o in M["orders"]["pending_now"] or []:
        try:
            if _parse(o["created"]) < now - timedelta(days=1):
                alerts.append({"level": "WARN", "msg": f"Order {o['id']} ({o['ticker']}) has been pending for over a day."})
        except Exception:
            pass

    # ---------------- benchmarks
    M["benchmarks"] = market.get("shadow") or {"error": "shadow portfolios unavailable"}

    # ---------------- risk
    risk: dict[str, Any] = {}
    if M["account"]:
        ws = {h["ticker"]: (h["weight"] or 0) for h in M["account"]["holdings"]}
        cash_w = (M["account"]["cash_available"] or 0) / total if total else None
        risk["weights"] = ws
        risk["cash_weight"] = _f(cash_w, 4)
        risk["largest_position"] = max(ws.items(), key=lambda kv: kv[1]) if ws else None
        risk["hhi"] = _f(sum(w * w for w in ws.values()), 4)
        risk["effective_positions"] = _f(1 / risk["hhi"], 2) if risk["hhi"] else None
        ccy: dict[str, float] = {}
        for h in M["account"]["holdings"]:
            ccy[h["currency"] or "?"] = ccy.get(h["currency"] or "?", 0) + (h["weight"] or 0)
        risk["listing_currency_weights"] = {k: _f(v, 4) for k, v in ccy.items()}
    risk.update(market.get("risk") or {"estimate_error": "volatility estimate unavailable"})
    risk["drawdown_from_hwm"] = M["performance"]["drawdown_from_hwm"]
    changes = []
    if prev and M["account"] and prev.get("account"):
        pv, cv = prev["account"].get("total_value"), M["account"]["total_value"]
        if pv:
            changes.append(f"Value £{pv:.2f} → £{cv:.2f} ({cv / pv - 1:+.2%}) since the {prev['meta']['report_date']} report.")
        pw = {h["ticker"]: h["weight"] or 0 for h in prev["account"].get("holdings", [])}
        for t in sorted(set(pw) | set(risk.get("weights", {}))):
            a, b = pw.get(t, 0), risk["weights"].get(t, 0)
            if t not in pw:
                changes.append(f"New holding {t} ({b:.1%}).")
            elif t not in risk["weights"]:
                changes.append(f"Holding {t} closed.")
            elif abs(b - a) >= 0.03:
                changes.append(f"{t} weight {a:.1%} → {b:.1%}.")
        if prev.get("reconciliation_ok") is not None and prev.get("reconciliation_ok") != recon_ok:
            changes.append(f"Reconciliation status changed: {'OK' if prev['reconciliation_ok'] else 'FAILED'} → {'OK' if recon_ok else 'FAILED'}.")
    elif not prev:
        changes.append("No previous report to compare against (first report).")
    risk["material_changes"] = changes
    M["risk"] = risk
    M["reconciliation_ok"] = recon_ok

    # ---------------- research
    M["research"] = research

    # ---------------- adviser
    stale_reasons = []
    if not recon_ok:
        stale_reasons.append("reconciliation did not pass")
    if not acct["transactions"].ok:
        stale_reasons.append("deposit/withdrawal history unavailable")
    if M["account"] is None:
        stale_reasons.append("account state unavailable")
    if M["account"]:
        holdings = [adv.Holding(h["ticker"], h["value_gbp"] or 0, "GBP" if h["currency"] in ("GBP", "GBX") else (h["currency"] or "OTHER"),
                                h["unrealized_pl_gbp"] or 0) for h in M["account"]["holdings"]]
        inp = adv.AdviserInput(report_date, total, M["account"]["cash_available"] or 0, flows.net, holdings,
                               twr=pf.twr, drawdown_from_hwm=pf.drawdown, data_reliable=not stale_reasons,
                               reliability_issues=stale_reasons)
        rec = adv.advise(inp, adviser_cfg, adviser_state)
        events = adv.detect_events(adviser_state, gain or 0.0, pf.drawdown, flows.net, rec)
        notify, why = adv.should_notify(rec, adviser_state, adviser_cfg, report_date)
        # notification is only recorded once the alert is actually delivered (see daily.run)
        new_state = adv.update_state(adviser_state, rec, gain or 0.0, pf.drawdown, flows.net, False, report_date)
        M["adviser"] = {**rec.to_dict(), "events": events, "notify": notify, "notify_reason": why,
                        "_state_inputs": {"gain": gain or 0.0, "drawdown": pf.drawdown, "net": flows.net}}
    else:
        M["adviser"] = {"amount_gbp": 0.0, "reason_code": "DATA_NOT_RELIABLE",
                        "headline": "No withdrawal assessment today: account data could not be read.", "notify": False,
                        "notify_reason": "data unavailable", "events": []}
        new_state = adviser_state

    # ---------------- health
    health = []
    for k, s in acct.items():
        health.append({"check": f"API {k}", "status": "PASS" if s.ok else "FAIL", "detail": s.error or f"read at {s.at}"})
    health.append({"check": "Reconciliation", "status": "PASS" if recon_ok else "FAIL",
                   "detail": f"{sum(c.status == 'PASS' for c in checks)} passed, {sum(c.status == 'FAIL' for c in checks)} failed, "
                             f"{sum(c.status == 'SKIP' for c in checks)} skipped"})
    runs = [e for e in journal_events if e.get("kind") == "run_start"]
    if runs:
        last = runs[-1]
        age = now - _parse(last["ts_utc"])
        outcome = [e["kind"] for e in journal_events if e.get("run_id") == last.get("run_id") and e["kind"] in
                   ("run_end", "run_failed", "run_deferred", "run_skipped", "run_halted", "plan")]
        st = "PASS" if age <= timedelta(days=4) else "WARN"
        health.append({"check": "Trading bot last run", "status": st,
                       "detail": f"{last['ts_utc']} ({age.days}d {age.seconds // 3600}h ago); events: {', '.join(outcome) or 'none'}"})
        if st == "WARN":
            alerts.append({"level": "WARN", "msg": f"The trading bot has not run for {age.days} days - check the scheduled routine."})
    else:
        health.append({"check": "Trading bot last run", "status": "WARN", "detail": "no runs recorded in the journal"})
    fails7 = _events_since(journal_events, now - timedelta(days=7), {"run_failed", "order_ambiguous"})
    health.append({"check": "Bot failures (7 days)", "status": "PASS" if not fails7 else "WARN",
                   "detail": f"{len(fails7)} failure event(s)" + (f"; latest: {fails7[-1].get('error', fails7[-1]['kind'])}" if fails7 else "")})
    log = research.get("log") or []
    if log:
        try:
            ld = date.fromisoformat(log[-1]["date"][:10])
            st = "PASS" if (report_date - ld).days <= 2 else "WARN"
            health.append({"check": "Research loop activity", "status": st, "detail": f"last LOG.md entry {ld} ({(report_date - ld).days} day(s) ago)"})
        except ValueError:
            health.append({"check": "Research loop activity", "status": "WARN", "detail": "LOG.md date unparseable"})
    else:
        health.append({"check": "Research loop activity", "status": "WARN", "detail": "no LOG.md entries"})
    if research.get("registry_problems"):
        health.append({"check": "Experiment registry", "status": "WARN", "detail": "; ".join(research["registry_problems"][:5])})
    else:
        health.append({"check": "Experiment registry", "status": "PASS", "detail": f"{len(research.get('experiments', []))} records valid"})
    pd_ = market.get("price_data_last_date")
    if pd_:
        lag = (report_date - date.fromisoformat(pd_)).days
        health.append({"check": "Market data freshness", "status": "PASS" if lag <= 4 else "WARN", "detail": f"latest close {pd_} ({lag}d old)"})
        if lag > 4:
            alerts.append({"level": "WARN", "msg": f"Market price data is stale (latest close {pd_})."})
    else:
        health.append({"check": "Market data freshness", "status": "WARN", "detail": market.get("market_error", "no market data")})
    if delivery:
        st = {"sent": "PASS", "failed": "FAIL"}.get(delivery.get("status"), "WARN")
        health.append({"check": "Previous email delivery", "status": st,
                       "detail": f"{delivery.get('report_date')}: {delivery.get('status')} via {delivery.get('provider')} {delivery.get('detail', '')}".strip()})
        if st == "FAIL":
            alerts.append({"level": "CRITICAL", "msg": f"The previous report email was NOT delivered ({delivery.get('detail', '')})."})
    else:
        health.append({"check": "Previous email delivery", "status": "WARN", "detail": "no delivery recorded yet"})
    if kill:
        health.append({"check": "Trading kill switch", "status": "WARN", "detail": kill})
    if research_stop:
        health.append({"check": "Research STOP file", "status": "WARN", "detail": "research/STOP present - research loop paused"})
    M["health"] = health

    # ---------------- priorities
    pr = [f"[{a['level']}] {a['msg']}" for a in alerts if a["level"] == "CRITICAL"]
    pr += [f"[WARN] {a['msg']}" for a in alerts if a["level"] == "WARN"]
    pr += [f"[HEALTH] {h['check']}: {h['detail']}" for h in health if h["status"] in ("FAIL", "WARN") and not any(h["detail"] in p for p in pr)]
    nxt = next((a for a in research.get("agenda", []) if a["status"].upper().startswith("OPEN")), None)
    if nxt:
        pr.append(f"[RESEARCH] Next agenda item: {nxt['id']} {nxt['title']}")
    pend = [e for e in research.get("experiments", []) if e.get("decision") == "PENDING_RERUN"]
    if pend:
        pr.append(f"[RESEARCH] {len(pend)} experiment(s) awaiting a verifiable re-run: " + ", ".join(f"{e['id']} {e['title']}" for e in pend))
    M["priorities"] = pr or ["No open issues."]
    M["email_last_delivery"] = delivery
    return M, new_state


# ---------------------------------------------------------------- research bundle

def research_bundle() -> dict:
    recs, problems = research_feed.load_registry()
    return {"experiments": recs, "registry_problems": problems, "agenda": research_feed.agenda(),
            "trials_total": research_feed.trial_counter(), "log": research_feed.log_entries()}


# ---------------------------------------------------------------- market (benchmarks + risk estimate)

def market_bundle(journal, cfg, book=None) -> dict:
    """Shadow benchmarks and a volatility estimate from public prices. Never raises."""
    out: dict[str, Any] = {}
    try:
        from . import report as rep
        from .shadow import PriceBook
        book = book or PriceBook()
        data = rep.build(journal, cfg, book)
        if "shadows" in data:
            cap = data["capital"]
            out["shadow"] = {"inception": str(data["start"]), "capital": cap,
                             "portfolios": {k: {"value": _f(s.iloc[-1]), "return": _f(s.iloc[-1] / cap - 1, 6), "as_of": str(s.index[-1].date())}
                                            for k, s in data["shadows"].items() if len(s)}}
            last_dates = [s.index[-1].date() for s in data["shadows"].values() if len(s)]
            if last_dates:
                out["price_data_last_date"] = max(last_dates).isoformat()
        else:
            out["shadow"] = {"note": data.get("note", "no trades yet")}
        # volatility estimate of current target weights from 1y of daily closes
        import numpy as np
        import pandas as pd
        rets = {}
        for t in cfg.targets:
            s = book.gbp_tr(cfg.yahoo_symbols[t])
            rets[t] = s.pct_change().dropna().iloc[-252:]
        df = pd.DataFrame(rets).dropna()
        w = np.array([cfg.targets[t] for t in df.columns])
        port = df.values @ w
        sd = float(np.std(port, ddof=1))
        out["risk"] = {"est_annual_vol": _f(sd * math.sqrt(252), 4), "est_daily_vol": _f(sd, 5),
                       "est_var95_1d_pct": _f(1.645 * sd, 5), "vol_window_days": int(len(df)),
                       "estimate_basis": "target weights x last 252 daily GBP total returns (public prices); not a forecast"}
    except Exception as e:
        out["market_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        out.setdefault("shadow", {"error": out["market_error"]})
    return out


# ---------------------------------------------------------------- rendering

def _money(x):
    return "n/a" if x is None else f"£{x:,.2f}"


def _pct(x, nd=2):
    return "n/a" if x is None else f"{x:+.{nd}%}"


def render_md(M: dict) -> str:
    m = M["meta"]
    L = []
    if m.get("example"):
        L += ["> **EXAMPLE DATA - this sample report uses synthetic numbers to show the format. It is not your account.**", ""]
    L += [f"# Daily intelligence report - {m['report_date']}", "",
          f"Generated {m['generated_uk']} ({m['generated_utc']} UTC). Strategy `{m['strategy']}`.",
          f"Environment: **{m['environment']}**.", ""]
    crit = [a for a in M["alerts"] if a["level"] == "CRITICAL"]
    warn = [a for a in M["alerts"] if a["level"] == "WARN"]
    hw = [h for h in M.get("health", []) if h["status"] in ("WARN", "FAIL")]
    if crit or warn:
        L += ["## ⚠ Attention", ""]
        L += [f"> **CRITICAL:** {a['msg']}" for a in crit] + [f"> WARNING: {a['msg']}" for a in warn] + [""]
    elif hw:
        L += [f"**Status: account data verified and reconciled; {len(hw)} system-health item(s) need attention: "
              + "; ".join(f"{h['check']} ({h['detail']})" for h in hw) + ".**", ""]
    else:
        L += ["**Status: all data sources responded, the account reconciles, and every health check passed.**", ""]
    L += ["Labels: [VERIFIED] Trading 212 API, read now · [JOURNAL] bot records · [SIMULATED] shadow portfolios at public "
          "closing prices · [ESTIMATE] model output · [BACKTEST] historical research", ""]

    # account
    A = M.get("account")
    L += ["## 1. Account [VERIFIED]", ""]
    if A:
        L += [f"| Total value | Cash available | Reserved | In pies | Invested |", "|---|---|---|---|---|",
              f"| **{_money(A['total_value'])}** | {_money(A['cash_available'])} | {_money(A['cash_reserved'])} | "
              f"{_money(A['cash_in_pies'])} | {_money(A['invested_value'])} |", "",
              "| Holding | Quantity | Price | Value | Weight | Unrealised P&L |", "|---|---|---|---|---|---|"]
        for h in A["holdings"]:
            L.append(f"| {h['ticker']} ({h['name']}) | {h['quantity']} | {h['price']} {h['currency']} | {_money(h['value_gbp'])} | "
                     f"{(h['weight'] or 0):.1%} | {_money(h['unrealized_pl_gbp'])} |")
        if not A["holdings"]:
            L.append("| (no holdings) | | | | | |")
    else:
        L.append("**Unavailable** - account state could not be read (see Attention). Figures are missing, not zero.")
    L.append("")

    # flows
    Pf = M["performance"]
    L += ["## 2. Money in/out and performance [VERIFIED + JOURNAL]", "",
          "| Deposits | Withdrawals | Net contributions | Investment gain | Realised P&L | Unrealised P&L | Trading fees | Dividends | Interest |",
          "|---|---|---|---|---|---|---|---|---|",
          f"| {_money(Pf['deposits'])} | {_money(Pf['withdrawals'])} | {_money(Pf['net_contributions'])} | **{_money(Pf['investment_gain'])}** | "
          f"{_money(Pf['realized_pl'])} | {_money(Pf['unrealized_pl'])} | {_money(Pf['trading_fees'])} | {_money(Pf['dividends'])} | {_money(Pf['interest'])} |", ""]
    if Pf["fees_by_type"]:
        L.append("Fees by type: " + ", ".join(f"{k} {_money(v)}" for k, v in Pf["fees_by_type"].items()) + ".")
    L += [f"Contribution-adjusted (time-weighted) return since {Pf['first_snapshot'] or 'n/a'}: **{_pct(Pf['twr_since_inception'])}** "
          f"over {Pf['twr_periods']} snapshot interval(s). Drawdown from high-water mark {_pct(Pf['drawdown_from_hwm'])}; "
          f"worst {_pct(Pf['max_drawdown'])}. (Snapshot values are verified API reads stored in the journal.)", ""]

    # orders
    O = M["orders"]
    L += ["## 3. Orders [VERIFIED] and bot attempts [JOURNAL]", ""]
    L.append(f"Verified orders in the last 24h: **{len(O['verified_24h'])}**; last 7 days: {O['verified_7d_count']}; all time: {len(O['verified_all'])}.")
    pend = O["pending_now"]
    L.append("Pending orders now: " + ("unknown (API failed)" if pend is None else (str(len(pend)) if pend else "none")) + ".")
    L.append("")
    if O["verified_all"]:
        L += ["| Created (UTC) | Ticker | Side | Status | Qty | Fill price | Fees | Net value | Source |", "|---|---|---|---|---|---|---|---|---|"]
        for o in sorted(O["verified_all"], key=lambda o: o.get("created") or "", reverse=True)[:15]:
            L.append(f"| {o['created']} | {o['ticker']} | {o['side']} | {o['status']} | {o['filled'] or o['quantity']} | "
                     f"{o['fill_price']} | {_money(o['fees'])} | {_money(o['net_value'])} | {o['initiated']} |")
        L.append("")
    if O["journal_24h"]:
        L += ["Bot decisions and attempts in the last 24h:", ""]
        for e in O["journal_24h"]:
            L.append(f"- {e['ts']} **{e['kind']}** {e.get('ticker') or ''} {e.get('quantity') or ''} - {str(e.get('reason') or '')[:160]}")
        L.append("")
    else:
        L += ["No bot decisions or order attempts recorded in the last 24h.", ""]

    # benchmarks
    B = M["benchmarks"]
    L += ["## 4. Benchmarks and strategy [SIMULATED vs VERIFIED]", ""]
    if B.get("portfolios"):
        L += [f"Since inception {B['inception']} with £{B['capital']:.2f}:", "", "| Portfolio | Value | Return | Price as of (latest daily bar; intraday if the market is open) |", "|---|---|---|---|"]
        if A:
            L.append(f"| **Real account [VERIFIED]** | {_money(A['total_value'])} | {_pct(Pf['twr_since_inception'])} (TWR) | now |")
        for k, v in B["portfolios"].items():
            L.append(f"| {k} [SIMULATED] | {_money(v['value'])} | {_pct(v['return'])} | {v['as_of']} |")
        L += ["", "Short periods are dominated by noise; differences of this size are not evidence of skill (see research section)."]
    else:
        L.append(f"Unavailable: {B.get('error') or B.get('note')}")
    L.append("")

    # risk
    R = M["risk"]
    L += ["## 5. Risk", ""]
    if R.get("weights") is not None:
        lp = R.get("largest_position")
        L.append(f"- Concentration [VERIFIED]: largest position {lp[0]} {lp[1]:.1%}; HHI {R['hhi']}; "
                 f"≈{R['effective_positions']} effective positions; cash {R['cash_weight']:.1%}." if lp else "- No positions.")
        L.append(f"- Listing-currency weights [VERIFIED]: {R.get('listing_currency_weights')} (underlying holdings are global equities either way).")
    if R.get("est_annual_vol") is not None:
        L.append(f"- Volatility [ESTIMATE]: ≈{R['est_annual_vol']:.1%}/yr; one-day 95% VaR ≈ {R['est_var95_1d_pct']:.2%} "
                 f"(≈{_money((R['est_var95_1d_pct'] or 0) * ((A or {}).get('total_value') or 0))}). Basis: {R['estimate_basis']}.")
    else:
        L.append(f"- Volatility estimate unavailable: {R.get('estimate_error') or 'market data error'}.")
    L.append(f"- Drawdown from high-water mark [JOURNAL]: {_pct(R.get('drawdown_from_hwm'))}.")
    L += ["- Material changes: " + (" ".join(R["material_changes"]) if R["material_changes"] else "none."), ""]

    # research
    RS = M["research"]
    L += ["## 6. Research [BACKTEST - historical, not live performance]", ""]
    exps = RS.get("experiments", [])
    if exps:
        by = {}
        for e in exps:
            by[e["decision"]] = by.get(e["decision"], 0) + 1
        L.append(f"Experiment registry: {len(exps)} records ({', '.join(f'{k} {v}' for k, v in sorted(by.items()))}); "
                 f"cumulative configurations tested (for multiple-testing correction): {RS.get('trials_total')}.")
        L += ["", "| ID | Experiment | Decision | Key out-of-sample evidence | Main limitation |", "|---|---|---|---|---|"]
        for e in exps:
            L.append(f"| {e['id']} | {e['title']} | **{e['decision']}** | {str(e.get('decision_detail', ''))[:140]} | {(e.get('limitations') or [''])[0][:90]} |")
        L.append("")
    promoted = [e for e in exps if e.get("promoted")]
    L.append("Promoted to live (demo) trading: " + (", ".join(f"{e['id']} {e['title']}" for e in promoted) or "none") + ".")
    if RS.get("log"):
        last = RS["log"][-1]
        L.append(f"Latest research log entry ({last['date']}, {last['item']}): {last['result']} → {last['decision'].rstrip('.')}.")
    L += ["Controls: pre-registered parameter grids, in-sample/out-of-sample split, survivorship-free index data where available, "
          "costs and a one-day lag included, bootstrap tests and a deflated Sharpe ratio using the cumulative trial count. "
          "Strategies change only through research/PROMOTION_GATE.md (at most one change per quarter).", ""]

    # adviser
    AD = M["adviser"]
    L += ["## 7. Withdrawal adviser (recommendation only - never acts)", "", f"**{AD['headline']}**", ""]
    for x in AD.get("explanation", []):
        L.append(f"- {x}")
    for x in AD.get("calculation", []):
        L.append(f"- Calculation: {x}")
    if AD.get("scenarios"):
        sc = AD["scenarios"]
        keys = [k for k in sc[0] if k.endswith("_portfolio_in_10y") or k.endswith(("_in_5y", "_in_15y", "_in_20y"))]
        L += ["", "| Withdraw now | Remaining now | " + " | ".join(k.replace("_", " ") for k in keys) + " | Loss avoided on withdrawn £ in a shock |",
              "|---|---|" + "---|" * len(keys) + "---|"]
        for row in sc:
            L.append(f"| {_money(row['withdraw_gbp'])} | {_money(row['remaining_now_gbp'])} | " + " | ".join(_money(row[k]) for k in keys)
                     + f" | {_money(row['shock_loss_avoided_on_withdrawn'])} |")
        L.append("")
    if AD.get("selling_required_gbp"):
        L.append(f"- Selling required: about {_money(AD['selling_required_gbp'])} (est. cost {_money(AD['est_selling_cost_gbp'])}): "
                 + "; ".join(f"{p['ticker']} {_money(p['sell_gbp'])}" for p in AD["sell_plan"]))
    for n in AD.get("wrapper_notes", []):
        L.append(f"- {n}")
    for a in AD.get("assumptions", []):
        L.append(f"- Assumption: {a}")
    if AD.get("uncertainty"):
        L.append(f"- Uncertainty: {AD['uncertainty']}")
    L += [f"- Events: {', '.join(AD.get('events') or []) or 'none'}. Notification: {'SENT' if AD.get('notify') else 'not sent'} ({AD.get('notify_reason')}).", ""]

    # health
    L += ["## 8. Data quality, reconciliation and system health", "", "| Check | Status | Detail |", "|---|---|---|"]
    for c in M["reconciliation"]:
        L.append(f"| {c['name']} | {c['status']} | {c['detail']} |")
    for h in M["health"]:
        L.append(f"| {h['check']} | {h['status']} | {h['detail']} |")
    L.append("")

    # priorities
    L += ["## 9. Recommended priorities and unresolved issues", ""]
    for i, p in enumerate(M["priorities"], 1):
        L.append(f"{i}. {p}")
    L += ["", "---", "_Generated by `python -m t212bot daily-report`. Practice account only. Nothing in this report is financial advice; "
          "recommendations are produced by documented rules and never executed automatically._"]
    text = "\n".join(L) + "\n"
    if m.get("example"):
        text = text.replace("[VERIFIED]", "[EXAMPLE]").replace("[VERIFIED + JOURNAL]", "[EXAMPLE]").replace("[JOURNAL]", "[EXAMPLE]").replace("[SIMULATED]", "[EXAMPLE]")
    return text


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"_(Generated.+?)_", r"<em>\1</em>", s)
    return s


def md_to_html(md: str, title: str) -> str:
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-|\s]+\|$", lines[i + 1]):
            head = [c.strip() for c in ln.strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        m = re.match(r"^(#{1,4}) (.*)$", ln)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif ln.startswith("> "):
            out.append(f"<div class='alert'>{_inline(ln[2:])}</div>")
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif re.match(r"^\d+\. ", ln):
            items = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                items.append(f"<li>{_inline(re.sub(r'^\d+\. ', '', lines[i]))}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.strip():
            out.append(f"<p>{_inline(ln)}</p>")
        i += 1
    css = ("body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:860px;margin:auto;padding:16px;color:#1b1b1b;background:#fff}"
           "table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}th,td{border:1px solid #ddd;padding:4px 6px;text-align:left}"
           "th{background:#f3f4f6}.alert{background:#fff4e5;border-left:4px solid #d97706;padding:6px 10px;margin:4px 0}"
           "h1{font-size:22px}h2{font-size:17px;margin-top:22px;border-bottom:1px solid #eee}code{background:#f3f4f6;padding:0 3px}")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{css}</style></head><body>{''.join(out)}</body></html>"


# ---------------------------------------------------------------- storage

def store(M: dict, root: Path = REPORTS, name: str | None = None) -> dict[str, Path]:
    d = M["meta"]["report_date"]
    name = name or d
    (root / "daily").mkdir(parents=True, exist_ok=True)
    (root / "metrics").mkdir(parents=True, exist_ok=True)
    md = render_md(M)
    paths = {"md": root / "daily" / f"{name}.md", "html": root / "daily" / f"{name}.html", "json": root / "metrics" / f"{name}.json"}
    paths["md"].write_text(md)
    paths["html"].write_text(md_to_html(md, f"Daily report {d}"))
    paths["json"].write_text(json.dumps(M, indent=1, default=str))
    return paths


def previous_metrics(report_date: str, root: Path = REPORTS) -> dict | None:
    files = sorted(p for p in (root / "metrics").glob("20*.json") if p.stem < report_date)
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text())
    except Exception:
        return None


def load_state(root: Path = REPORTS) -> dict:
    p = root / "adviser_state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(state: dict, root: Path = REPORTS) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "adviser_state.json.tmp"
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True, default=str))
    tmp.replace(root / "adviser_state.json")


def kill_status() -> str | None:
    return f"kill file present: {KILL_FILE}" if KILL_FILE.exists() else None


def research_stopped() -> bool:
    return RESEARCH_STOP.exists()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
