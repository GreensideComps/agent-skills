"""Independent check of a stored daily report against freshly fetched raw API data.

Deliberately does NOT import performance.py or intel.py. Every figure is re-derived here from the raw
Trading 212 responses with separate, simple code, so a bug in the report pipeline cannot hide itself.

Figures fall into two groups:
- price-independent (cash, quantities, orders, fills, fees, deposits, cost basis, realised P&L): must match exactly;
- price-dependent (values, unrealised P&L, total): the report was taken at an earlier time, so they are checked
  for internal arithmetic, and the live difference must be explained by the observed price move.
"""
from __future__ import annotations

import csv
import inspect
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

TOL = 0.015          # £, rounding to pennies on both sides
PASS, FAIL, INFO = "PASS", "FAIL", "INFO"


def _r(x):
    return None if x is None else round(float(x), 2)


def _row(check, report, independent, ok, note=""):
    return {"check": check, "report": report, "independent": independent,
            "status": INFO if ok is None else (PASS if ok else FAIL), "note": note}


def _close(a, b, tol=TOL):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------- independent derivations from raw

def raw_fees(orders: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for o in orders:
        for t in ((o.get("fill") or {}).get("walletImpact") or {}).get("taxes") or []:
            out[t.get("name") or t.get("type") or "UNKNOWN"] = out.get(t.get("name") or t.get("type") or "UNKNOWN", 0.0) + abs(float(t.get("quantity") or 0))
    return {k: round(v, 2) for k, v in out.items()}


def raw_flows(transactions: list[dict]) -> list[tuple[datetime, float]]:
    out = []
    for t in transactions:
        typ = (t.get("type") or "").upper()
        if typ == "DEPOSIT":
            out.append((_ts(t["dateTime"]), float(t["amount"])))
        elif typ == "WITHDRAW":
            out.append((_ts(t["dateTime"]), -abs(float(t["amount"]))))
    return out


def twr_from_snapshots(snaps: list[tuple[datetime, float]], flows: list[tuple[datetime, float]]) -> tuple[float, float]:
    """Chain-linked Modified Dietz between consecutive snapshots; returns (twr, max drawdown of the index)."""
    snaps = sorted((s for s in snaps if s[1] > 0), key=lambda s: s[0])     # stable: ties keep journal order
    idx, peak, mdd = 1.0, 1.0, 0.0
    for (t0, v0), (t1, v1) in zip(snaps, snaps[1:]):
        span = (t1 - t0).total_seconds()
        fl = [(t, a) for t, a in flows if t0 < t <= t1]
        f = sum(a for _, a in fl)
        w = sum(a * ((t1 - t).total_seconds() / span if span else 0) for t, a in fl)
        denom = v0 + w
        if denom <= 0:
            continue
        idx *= 1 + (v1 - v0 - f) / denom
        peak = max(peak, idx)
        mdd = min(mdd, idx / peak - 1)
    return idx - 1, mdd


def load_snapshots(path: Path, until: datetime | None = None) -> list[tuple[datetime, float]]:
    out = []
    if not path.exists():
        return out
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                t, v = _ts(r["ts_utc"]), float(r["total_value_gbp"])
            except Exception:
                continue
            if until is None or t <= until:
                out.append((t, v))
    return out


# ---------------------------------------------------------------- the comparison

def verify(M: dict, raw: dict, snapshots: list[tuple[datetime, float]]) -> list[dict]:
    rows: list[dict] = []
    acct, perf, S = M["account"], M["performance"], raw["summary"]
    cash = S.get("cash") or {}
    inv = S.get("investments") or {}

    # --- cash: price-independent
    rows.append(_row("Cash available", acct["cash_available"], _r(cash.get("availableToTrade")), _close(acct["cash_available"], cash.get("availableToTrade"))))
    rows.append(_row("Cash reserved for orders", acct["cash_reserved"], _r(cash.get("reservedForOrders")), _close(acct["cash_reserved"], cash.get("reservedForOrders"))))
    rows.append(_row("Cash in pies", acct["cash_in_pies"], _r(cash.get("inPies")), _close(acct["cash_in_pies"], cash.get("inPies"))))

    # --- holdings
    live = {p["instrument"]["ticker"]: p for p in raw["positions"]}
    rep = {h["ticker"]: h for h in acct["holdings"]}
    rows.append(_row("Holdings: same instruments", sorted(rep), sorted(live), sorted(rep) == sorted(live)))
    for tk in sorted(set(rep) | set(live)):
        h, p = rep.get(tk), live.get(tk)
        if not h or not p:
            rows.append(_row(f"{tk}: present in both", bool(h), bool(p), False))
            continue
        rows.append(_row(f"{tk}: quantity", h["quantity"], p["quantity"], abs(h["quantity"] - p["quantity"]) < 1e-9))
        rows.append(_row(f"{tk}: cost basis £", h.get("cost_gbp"), _r(p["walletImpact"]["totalCost"]), _close(h.get("cost_gbp"), p["walletImpact"]["totalCost"])))
        # price-dependent: is the value change explained by the price change? (FX holdings also move with GBP/USD)
        live_v = float(p["walletImpact"]["currentValue"])
        px_ratio = float(p["currentPrice"]) / float(h["price"]) if h.get("price") else None
        implied = h["value_gbp"] * px_ratio if px_ratio else None
        fx_tol = 0.003 * live_v if p["instrument"].get("currency") != acct.get("currency") else 0
        ok = implied is not None and abs(implied - live_v) <= max(0.02, fx_tol)
        rows.append(_row(f"{tk}: value £ (report time vs now)", h["value_gbp"], _r(live_v), ok,
                         f"price {h['price']} -> {p['currentPrice']}; report value x price ratio = £{implied:.2f}"
                         + (" (±0.3% allowed for FX)" if fx_tol else "")))
        rows.append(_row(f"{tk}: report value = cost + unrealised", h["value_gbp"], _r(h["cost_gbp"] + h["unrealized_pl_gbp"]),
                         _close(h["value_gbp"], h["cost_gbp"] + h["unrealized_pl_gbp"], 0.02)))

    # --- report internal arithmetic (price-dependent figures, all at report time)
    s_val = sum(h["value_gbp"] for h in acct["holdings"])
    rows.append(_row("Report: invested = Σ holding values", acct["invested_value"], _r(s_val), _close(acct["invested_value"], s_val, 0.02)))
    tot = acct["cash_available"] + acct["cash_reserved"] + acct["cash_in_pies"] + acct["invested_value"]
    rows.append(_row("Report: total = cash + invested", acct["total_value"], _r(tot), _close(acct["total_value"], tot, 0.02)))
    rows.append(_row("Report: gain = total − net contributions", perf["investment_gain"], _r(acct["total_value"] - perf["net_contributions"]),
                     _close(perf["investment_gain"], acct["total_value"] - perf["net_contributions"], 0.02)))
    rows.append(_row("Report: Σ unrealised = unrealised P&L", perf["unrealized_pl"], _r(sum(h["unrealized_pl_gbp"] for h in acct["holdings"])),
                     _close(perf["unrealized_pl"], sum(h["unrealized_pl_gbp"] for h in acct["holdings"]), 0.02)))
    rows.append(_row("Total value now (informational)", acct["total_value"], _r(S.get("totalValue")), None, "differs only by market moves since the report"))

    # --- cost basis & realised P&L: price-independent
    rows.append(_row("Total cost basis", _r(sum(h["cost_gbp"] for h in acct["holdings"])), _r(inv.get("totalCost")),
                     _close(sum(h["cost_gbp"] for h in acct["holdings"]), inv.get("totalCost"), 0.02)))
    rows.append(_row("Realised P&L", perf["realized_pl"], _r(inv.get("realizedProfitLoss")), _close(perf["realized_pl"], inv.get("realizedProfitLoss"))))

    # --- transactions
    flows = raw_flows(raw["transactions"])
    dep = sum(a for _, a in flows if a > 0)
    wd = -sum(a for _, a in flows if a < 0)
    rows.append(_row("Deposits", perf["deposits"], _r(dep), _close(perf["deposits"], dep)))
    rows.append(_row("Withdrawals", perf["withdrawals"], _r(wd), _close(perf["withdrawals"], wd)))
    divs = sum(float(d.get("amount") or 0) for d in raw["dividends"])
    rows.append(_row("Dividends", perf["dividends"], _r(divs), _close(perf["dividends"], divs)))
    interest = sum(float(t.get("amount") or 0) for t in raw["transactions"] if (t.get("type") or "").upper() in ("INTEREST", "CASHBACK"))
    rows.append(_row("Interest / cashback", perf["interest"], _r(interest), _close(perf["interest"], interest)))
    known = {"DEPOSIT", "WITHDRAW", "INTEREST", "CASHBACK"}
    other = [t for t in raw["transactions"] if (t.get("type") or "").upper() not in known]
    rows.append(_row("Transactions of other types", perf.get("unclassified_transactions", 0), len(other), len(other) == perf.get("unclassified_transactions", 0),
                     ", ".join(sorted({t.get('type', '?') for t in other})) or "none"))

    # --- orders and fills
    ro = {o["id"]: o for o in M["orders"]["verified_all"]}
    raw_o = {r["order"]["id"]: r for r in raw["orders"]}
    rows.append(_row("Orders: same set", len(ro), len(raw_o), set(ro) == set(raw_o)))
    for oid in sorted(set(ro) & set(raw_o)):
        a, r = ro[oid], raw_o[oid]
        f = r.get("fill") or {}
        wi = f.get("walletImpact") or {}
        fees = round(sum(abs(float(t.get("quantity") or 0)) for t in wi.get("taxes") or []), 2)
        same = (a["side"] == r["order"]["side"] and a["status"] == r["order"]["status"] and a["ticker"] == r["order"]["ticker"]
                and abs(a["filled"] - float(r["order"].get("filledQuantity") or 0)) < 1e-9 and _close(a["fill_price"], f.get("price"), 1e-6)
                and _close(a["net_value"], wi.get("netValue")) and _close(a["fees"], fees))
        rows.append(_row(f"Order {oid} ({a['ticker']} {a['side']})",
                         f"{a['status']} {a['filled']} @ {a['fill_price']}, net £{a['net_value']}, fees £{a['fees']}",
                         f"{r['order']['status']} {r['order'].get('filledQuantity')} @ {f.get('price')}, net £{wi.get('netValue')}, fees £{fees}", same))
    rows.append(_row("Pending orders", len(M["orders"]["pending_now"]), len(raw["pending"]), None, "live state now; may legitimately differ"))

    # --- fees
    fees = raw_fees(raw["orders"])
    rows.append(_row("Trading fees total", perf["trading_fees"], _r(sum(fees.values())), _close(perf["trading_fees"], sum(fees.values()))))
    rows.append(_row("Fees by type", perf["fees_by_type"], fees, {k: round(v, 2) for k, v in perf["fees_by_type"].items()} == fees))

    # --- quantities = Σ fills
    q: dict[str, float] = {}
    for r in raw["orders"]:
        fq = float((r.get("fill") or {}).get("quantity") or 0)
        q[r["order"]["ticker"]] = q.get(r["order"]["ticker"], 0) + (fq if r["order"]["side"] == "BUY" else -abs(fq))
    for tk, p in live.items():
        rows.append(_row(f"{tk}: quantity = Σ fills", round(q.get(tk, 0), 6), p["quantity"], abs(q.get(tk, 0) - p["quantity"]) < 1e-6))

    # --- cash ledger from raw history alone
    buys = sum(float(((r.get("fill") or {}).get("walletImpact") or {}).get("netValue") or 0) for r in raw["orders"] if r["order"]["side"] == "BUY")
    sells = sum(float(((r.get("fill") or {}).get("walletImpact") or {}).get("netValue") or 0) for r in raw["orders"] if r["order"]["side"] == "SELL")
    exp_cash = dep - wd - buys + sells + divs + interest
    act_cash = float(cash.get("availableToTrade") or 0) + float(cash.get("reservedForOrders") or 0) + float(cash.get("inPies") or 0)
    rows.append(_row("Cash ledger: deposits − buys + sells + income", _r(exp_cash), _r(act_cash), _close(exp_cash, act_cash, 0.02),
                     f"£{dep:.2f} − £{buys:.2f} + £{sells:.2f} + £{divs + interest:.2f}; fill netValue already includes FX fees"))

    # --- time-weighted return, recomputed from the journal snapshots up to report time
    # the report records its own snapshot a few seconds after `generated_utc`; allow a short window for it
    until = _ts(M["meta"]["generated_utc"]) + timedelta(minutes=2)
    twr, mdd = twr_from_snapshots([s for s in snapshots if s[0] <= until], flows)
    rows.append(_row("Time-weighted return", perf["twr_since_inception"], round(twr, 4), abs(twr - perf["twr_since_inception"]) < 0.0005,
                     f"chain-linked over {len([s for s in snapshots if s[0] <= until])} journal snapshots; flows from raw transactions"))
    rows.append(_row("Max drawdown", perf["max_drawdown"], round(mdd, 4), abs(mdd - perf["max_drawdown"]) < 0.0005))
    return rows


# ---------------------------------------------------------------- recommendation-only guarantees (static)

def adviser_safety(spec_path: Path) -> list[dict]:
    from . import adviser, readonly
    rows = []
    src = inspect.getsource(adviser)
    bad = [w for w in ("T212Client", "place_", "market_order", "limit_order", "cancel", "urllib", "requests") if w in src]
    rows.append(_row("Adviser code has no client, order or network calls", "none", bad or "none", not bad))
    allowed = sorted(readonly.READ_METHODS)
    writes = [m for m in allowed if re.search("place|cancel|market_order|limit_order|stop_order|create|update|delete", m)]
    rows.append(_row("Read-only client allowlist contains no order methods", allowed, writes or "none", not writes))
    paths = re.findall(r"^  (/api/v0/\S+):", spec_path.read_text(), re.M) if spec_path.exists() else []
    money = [p for p in paths if re.search("withdraw|transfer|payout|deposit|bank", p, re.I)]
    rows.append(_row("Trading 212 API has no money-movement endpoint", f"{len(paths)} paths in spec", money or "none", bool(paths) and not money,
                     f"source: {spec_path.name}"))
    return rows


def render(date: str, M: dict, rows: list[dict], safety: list[dict], fetched_utc: str) -> str:
    fails = [r for r in rows + safety if r["status"] == FAIL]
    out = [f"# Report verification: {date}", "",
           f"Stored report generated {M['meta']['generated_utc']}; raw API re-fetched {fetched_utc} (read-only client).",
           "Independent code path: `t212bot/verify.py` does not use the report's calculation modules.", "",
           f"**Result: {'ALL CHECKS PASS' if not fails else f'{len(fails)} DISCREPANCIES'}** "
           f"({sum(r['status'] == PASS for r in rows + safety)} pass, {len(fails)} fail, {sum(r['status'] == INFO for r in rows + safety)} informational)", "",
           "| Check | Report | Independent (raw API) | Status | Note |", "|---|---|---|---|---|"]
    for r in rows + safety:
        out.append(f"| {r['check']} | {json.dumps(r['report'], default=str, ensure_ascii=False)} | {json.dumps(r['independent'], default=str, ensure_ascii=False)} | {r['status']} | {r['note']} |")
    if fails:
        out += ["", "## Discrepancies", ""] + [f"- **{r['check']}**: report {r['report']} vs {r['independent']}. {r['note']}" for r in fails]
    return "\n".join(out) + "\n"
