"""Internal paper portfolio for screener picks (milestone 5).

This is the evidence test for the screening process: does buying what the screen ranks
beat simply holding the index, after costs? It touches no broker. It is kept separate from
the Trading 212 Practice account, which is traded by a different (discretionary) process.

Integrity rules:
* A recommendation is logged *before* its outcome can be known: it records the screen
  run, the rank and scores, the valuation the price implied and the decision price, with a
  timestamp. Records are append-only and never edited, so hindsight cannot creep in.
* Fills are simulated at the logged decision price, worsened by the configured spread
  and FX costs. No fill uses a price from after the decision.
* The benchmark (SPY by default) is marked with the same price source and starts with the
  same cash on the same day.
* paper-1.1 (owner decision D-T14, 20 Oct 2026) adds VWRP as the PRIMARY benchmark, in its own book
  `benchmark_vwrp`, and keeps SPY as the secondary one. Nothing recorded under paper-1.0 is restated. The VWRP
  book starts at its first priced mark under paper-1.1: it is funded with the screen book's NAV that day and then
  bought and held. Its London line is priced in GBP and converted to USD at that day's GBPUSD close. VWRP is
  accumulating, so its price includes reinvested dividends while the screen book's prices do not; the report
  states this bias beside the number.
* Rebalancing is mechanical and monthly: hold the top `max_positions` ranked companies
  with total >= `min_total_score`, equal weight. Between rebalances only marking happens.

Limits stated up front: dividends are not included in either the portfolio or the
benchmark (Yahoo chart closes are price-only); with ~10 positions and monthly decisions it
will take years before the excess return means anything statistically.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .evidence import tier
from .store import Store, content_hash, utc_now

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "paper_portfolio.json"
BENCH_PREFIX = "BENCH:"


class PaperError(RuntimeError):
    pass


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def benchmark_security(cfg: dict) -> dict:
    sym = cfg["benchmark"]["symbol"]
    return {"t212_ticker": f"{BENCH_PREFIX}{sym}", "company_id": f"{BENCH_PREFIX}{sym}", "symbol": sym}


def primary_securities(cfg: dict) -> list[dict]:
    """The VWRP line and the GBPUSD rate to price each day (empty under paper-1.0 configs)."""
    pb = cfg.get("primary_benchmark")
    if not pb:
        return []
    return [{"t212_ticker": f"{BENCH_PREFIX}{x}", "company_id": f"{BENCH_PREFIX}{x}", "symbol": x, "yahoo": x}
            for x in (pb["symbol"], pb["fx_symbol"])]


def primary_price_usd(prices: dict[str, dict], cfg: dict, as_of: str) -> tuple[float | None, dict]:
    """VWRP's close in USD on `as_of` and how it was worked out, or (None, reason) if it cannot be priced."""
    pb = cfg["primary_benchmark"]
    today = date.fromisoformat(as_of)
    got = {}
    for key, sym in (("line", pb["symbol"]), ("fx", pb["fx_symbol"])):
        p = prices.get(f"{BENCH_PREFIX}{sym}")
        if not p:
            return None, {"status": "unpriced", "reason": f"no price for {sym}"}
        if (today - date.fromisoformat(p["date"])).days > cfg["max_price_age_days"]:
            return None, {"status": "unpriced", "reason": f"{sym} price is stale ({p['date']})"}
        got[key] = p
    unit = {"GBP": 1.0, "GBp": 0.01, "GBX": 0.01}.get(got["line"].get("currency"))
    if unit is None or got["fx"].get("currency") not in (None, "USD"):
        return None, {"status": "unpriced", "reason": f"unexpected currency {got['line'].get('currency')} / "
                                                      f"{got['fx'].get('currency')}"}
    gbp = got["line"]["close"] * unit
    usd = gbp * got["fx"]["close"]
    return usd, {"gbp_close": gbp, "gbpusd": got["fx"]["close"], "usd": usd, "line_rid": got["line"]["rid"],
                 "fx_rid": got["fx"]["rid"], "calc": f"{gbp:.4f} GBP x {got['fx']['close']:.5f} = {usd:.4f} USD"}


def _mark_primary(store: Store, prices: dict[str, dict], as_of: str, cfg: dict, port_nav: float) -> dict:
    pb = cfg["primary_benchmark"]
    book, cid = pb["book"], f"{BENCH_PREFIX}{pb['symbol']}"
    usd, how = primary_price_usd(prices, cfg, as_of)
    st = state(store, book)
    if st["cash"] is None:
        if usd is None:
            return {**how, "status": "not started"}
        now = utc_now()
        qty = port_nav / (usd * (1 + _cost(cfg)))  # all cash, as the SPY book does
        store.paper.append([
            {"rid": f"paper:{book}:fund", "book": book, "kind": "fund", "amount": port_nav, "as_of": as_of,
             "ts_utc": now, "seq": 1, "method_version": cfg["method_version"],
             "reason": "funded with the screen book's NAV on the VWRP book's first priced mark"},
            {"rid": f"paper:{book}:{as_of}:buy:{content_hash([cid, qty])}", "book": book, "kind": "buy",
             "company_id": cid, "qty": qty, "decision_price": usd, "fill_price": usd * (1 + _cost(cfg)),
             "price_rid": how["line_rid"], "fx_rid": how["fx_rid"], "price_date": as_of, "calc": how["calc"],
             "reason": "primary benchmark buy-and-hold", "as_of": as_of, "ts_utc": now, "seq": 2,
             "method_version": cfg["method_version"]}])
        st = state(store, book)
    start = next(t for t in store.paper.read() if t["book"] == book and t["kind"] == "fund")
    if usd is None:
        return {**how, "status": "unpriced", "start": start["as_of"], "start_nav": start["amount"]}
    nav = st["cash"] + st["positions"].get(cid, 0.0) * usd
    return {"status": "marked", "nav": nav, "start": start["as_of"], "start_nav": start["amount"], **how}


def state(store: Store, book: str) -> dict:
    """Replay trades for a book ('portfolio' or 'benchmark') -> {cash, positions{cid: qty}, last_rebalance}."""
    cash, pos, last = None, {}, None
    for t in sorted((t for t in store.paper.read() if t["book"] == book), key=lambda t: (t["ts_utc"], t["seq"])):
        if t["kind"] == "fund":
            cash = (cash or 0.0) + t["amount"]
        elif t["kind"] in ("buy", "sell"):
            sign = 1 if t["kind"] == "buy" else -1
            pos[t["company_id"]] = pos.get(t["company_id"], 0.0) + sign * t["qty"]
            cash -= sign * t["qty"] * t["fill_price"]
            if abs(pos[t["company_id"]]) < 1e-12:
                del pos[t["company_id"]]
        if t["kind"] == "rebalance_marker":
            last = t["as_of"]
    return {"cash": cash, "positions": pos, "last_rebalance": last}


def _cost(cfg: dict) -> float:
    c = cfg["costs"]
    return (c["commission_bps"] + c["spread_bps"] + c["fx_bps"]) / 10_000


def targets(screen_rec: dict, cfg: dict) -> list[dict]:
    ranked = sorted((r for r in screen_rec["results"] if r.get("rank") and r["total"] >= cfg["min_total_score"]),
                    key=lambda r: r["rank"])
    return ranked[: cfg["max_positions"]]


def due(store: Store, as_of: str) -> bool:
    last = state(store, "portfolio")["last_rebalance"]
    return last is None or last[:7] < as_of[:7]


def rebalance(store: Store, screen_rec: dict, prices: dict[str, dict], cfg: dict | None = None,
              valuations: dict[str, dict] | None = None, force: bool = False) -> dict:
    """Log recommendations and simulated trades for one rebalance. Idempotent per run date."""
    cfg = cfg or load_config()
    as_of = screen_rec["as_of"]
    if not force and not due(store, as_of):
        return {"rebalanced": False, "reason": f"not due (last rebalance {state(store, 'portfolio')['last_rebalance']})"}
    valuations = valuations or {}
    today = date.fromisoformat(as_of)

    def px(cid):
        p = prices.get(cid)
        if not p or (today - date.fromisoformat(p["date"])).days > cfg["max_price_age_days"]:
            raise PaperError(f"no fresh price for {cid}")
        return p
    # Check every price this rebalance needs before writing anything, so a refusal leaves no partial state.
    needed = set(state(store, "portfolio")["positions"]) | {r["company_id"] for r in targets(screen_rec, cfg)}
    for cid in needed | {benchmark_security(cfg)["company_id"]}:
        px(cid)
    seq = [0]
    now = utc_now()
    recs, trades = [], []

    def trade(book, kind, cid, qty, p, reason):
        seq[0] += 1
        slip = _cost(cfg) if kind == "buy" else -_cost(cfg)
        trades.append({"rid": f"paper:{book}:{as_of}:{seq[0]}:{content_hash([cid, kind, qty])}", "book": book,
                       "kind": kind, "company_id": cid, "qty": qty, "decision_price": p["close"],
                       "fill_price": p["close"] * (1 + slip), "price_rid": p["rid"], "price_date": p["date"],
                       "reason": reason, "as_of": as_of, "ts_utc": now, "seq": seq[0],
                       "screen_rid": screen_rec["rid"], "method_version": cfg["method_version"]})
    # Funding: both books start with the same cash on the first rebalance.
    for book in ("portfolio", "benchmark"):
        if state(store, book)["cash"] is None:
            seq[0] += 1
            trades.append({"rid": f"paper:{book}:fund", "book": book, "kind": "fund", "amount": cfg["starting_cash"],
                           "as_of": as_of, "ts_utc": now, "seq": seq[0], "method_version": cfg["method_version"]})
    store.paper.append([t for t in trades if t["kind"] == "fund"])
    trades = []

    st = state(store, "portfolio")
    tg = targets(screen_rec, cfg)
    tgt_ids = [r["company_id"] for r in tg]
    nav = st["cash"] + sum(q * px(c)["close"] for c, q in st["positions"].items())
    # Sells first (names leaving, then trims), so their cash funds the buys.
    for cid, q in st["positions"].items():
        if cid not in tgt_ids:
            trade("portfolio", "sell", cid, q, px(cid), "left the target set")
    for r in tg:  # an empty target set just sells everything
        cid, p = r["company_id"], px(r["company_id"])
        # Leave room for the costs of this rebalance so cash never goes negative.
        target_qty = (nav * (1 - _cost(cfg)) / len(tg)) / (p["close"] * (1 + _cost(cfg)))
        held = st["positions"].get(cid, 0.0)
        v = valuations.get(cid, {})
        recs.append({"rid": f"rec:{as_of}:{cid}", "company_id": cid, "entity_name": r.get("entity_name"),
                     "action": "hold" if held else "buy", "rank": r["rank"], "total": r["total"],
                     "scores": r["scores"], "decision_price": p["close"], "price_rid": p["rid"],
                     "implied_growth_5y": v.get("implied_growth_5y"),
                     "base_case_upside": ((v.get("scenarios") or {}).get("base") or {}).get("upside"),
                     "screen_rid": screen_rec["rid"], "as_of": as_of, "ts_utc": now,
                     "evidence_tier": tier(screen_rec.get("method_version", "")),
                     "method_version": cfg["method_version"],
                     "basis": "screen rank within mandate (top N, total >= min); logged before outcome"})
        diff = target_qty - held
        if abs(diff) * p["close"] < 1.0:
            continue
        trade("portfolio", "buy" if diff > 0 else "sell", cid, abs(diff), p,
              "new position" if not held else "equal-weight rebalance")
    for cid in st["positions"]:
        if cid not in tgt_ids:
            recs.append({"rid": f"rec:{as_of}:{cid}", "company_id": cid, "action": "sell",
                         "decision_price": px(cid)["close"], "screen_rid": screen_rec["rid"], "as_of": as_of,
                         "evidence_tier": tier(screen_rec.get("method_version", "")),
                         "ts_utc": now, "method_version": cfg["method_version"],
                         "basis": "no longer in the target set"})
    # Benchmark: buy once with all its cash, then hold.
    bst = state(store, "benchmark")
    bid = benchmark_security(cfg)["company_id"]
    if not bst["positions"]:
        p = px(bid)
        trade("benchmark", "buy", bid, bst["cash"] / (p["close"] * (1 + _cost(cfg))), p, "benchmark buy-and-hold")
    seq[0] += 1
    trades.append({"rid": f"paper:portfolio:{as_of}:rebalance", "book": "portfolio", "kind": "rebalance_marker",
                   "as_of": as_of, "ts_utc": now, "seq": seq[0], "targets": tgt_ids,
                   "method_version": cfg["method_version"]})
    store.recommendations.append(recs)
    written = store.paper.append(trades)
    return {"rebalanced": True, "targets": tgt_ids, "trades": len(trades) - 1, "written": written,
            "recommendations": len(recs)}


def mark(store: Store, prices: dict[str, dict], as_of: str, cfg: dict | None = None) -> dict:
    """Mark the books at the latest prices; append one NAV record per day. `excess_return` stays the SPY
    comparison (unchanged since paper-1.0); `excess_return_vwrp` is the primary one, from the VWRP book's start."""
    cfg = cfg or load_config()
    out = {}
    for book in ("portfolio", "benchmark"):
        st = state(store, book)
        if st["cash"] is None:
            raise PaperError("paper portfolio not started (no rebalance yet)")
        missing = [c for c in st["positions"] if c not in prices]
        value = st["cash"] + sum(q * prices[c]["close"] for c, q in st["positions"].items() if c in prices)
        out[book] = {"nav": value, "cash": st["cash"], "positions": len(st["positions"]), "unpriced": missing}
    rec = {"rid": f"nav:{as_of}", "as_of": as_of, "ts_utc": utc_now(), **out}
    rec["excess_return"] = out["portfolio"]["nav"] / out["benchmark"]["nav"] - 1
    if cfg.get("primary_benchmark"):
        v = _mark_primary(store, prices, as_of, cfg, out["portfolio"]["nav"])
        rec["method_version"] = cfg["method_version"]
        rec["benchmark_vwrp"] = v
        if v["status"] == "marked":
            # The VWRP book was funded with the screen book's NAV on its start day, so this ratio is the screen
            # book's return since then relative to VWRP's.
            rec["excess_return_vwrp"] = out["portfolio"]["nav"] / v["nav"] - 1
    store.paper_nav.append(rec)
    return rec


def report(store: Store, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    navs = sorted(store.paper_nav.read(), key=lambda r: r["as_of"])
    if not navs:
        return "# Paper portfolio\n\nNot started.\n"
    first, last = navs[0], navs[-1]
    st = state(store, "portfolio")
    recs = [r for r in store.recommendations.read() if r["as_of"] == st["last_rebalance"]]
    start = cfg["starting_cash"]
    from .evidence import banner  # noqa: PLC0415
    lines = [f"# Screen-1.0 forward test: paper portfolio ({cfg['method_version']}), {last['as_of']}", "",
             banner(cfg["method_version"], "screen-1.0"), "",
             f"Simulated, no broker. Started {first['as_of']} with {start:,.0f} {cfg['base_currency']} in each book. "
             f"Costs {_cost(cfg) * 1e4:.0f} bps per trade. Dividends excluded from the screen book and SPY.", "",
             "| Book | NAV | Return since start |", "|---|---|---|",
             f"| Screen-1.0 forward test | {last['portfolio']['nav']:,.2f} | {last['portfolio']['nav'] / start - 1:+.2%} |",
             f"| {'Secondary benchmark' if cfg.get('primary_benchmark') else 'Benchmark'} "
             f"({cfg['benchmark']['symbol']}) | {last['benchmark']['nav']:,.2f} | "
             f"{last['benchmark']['nav'] / start - 1:+.2%} |",
             f"| **Excess vs {cfg['benchmark']['symbol']}** | | **{last['excess_return']:+.2%}** |", "",
             *_primary_lines(navs, cfg),
             f"{len(navs)} daily marks. This says nothing about skill yet: with ~{cfg['max_positions']} positions and "
             "monthly decisions, years of data are needed before the excess return is distinguishable from luck.", "",
             f"## Current holdings (last rebalance {st['last_rebalance']})", "",
             "| Company | Rank at decision | Total | Decision price | Price implied 5y FCF growth |", "|---|---|---|---|---|"]
    for r in sorted((r for r in recs if r["action"] != "sell"), key=lambda r: r["rank"]):
        ig = r.get("implied_growth_5y")
        lines.append(f"| {r['entity_name']} | {r['rank']} | {r['total']:.0f} | {r['decision_price']:,.2f} | "
                     f"{'' if ig is None else f'{ig:+.0%}'} |")
    return "\n".join(lines) + "\n"


def _primary_lines(navs: list[dict], cfg: dict) -> list[str]:
    """The VWRP comparison, labelled with when it started and the dividend bias it carries."""
    pb = cfg.get("primary_benchmark")
    if not pb:
        return []
    v = navs[-1].get("benchmark_vwrp")
    head = [f"## Primary benchmark: VWRP ({pb['symbol']}, from {cfg['method_version']})", ""]
    if not v or v.get("status") == "not started":
        return head + [f"Not started yet: {(v or {}).get('reason', 'no mark under ' + cfg['method_version'] + ' yet')}."
                       " Results before the VWRP book starts are compared with SPY only.", ""]
    if v["status"] != "marked":
        return head + [f"Started {v['start']}; not priced today ({v['reason']}).", ""]
    return head + [
        f"Started {v['start']} with {v['start_nav']:,.2f} {cfg['base_currency']} (the screen book's NAV that day). "
        "Everything before that date is compared with SPY only and is not restated.", "",
        "| Book | NAV | Return since VWRP start |", "|---|---|---|",
        f"| VWRP (total return, accumulating) | {v['nav']:,.2f} | {v['nav'] / v['start_nav'] - 1:+.2%} |",
        f"| **Excess vs VWRP** | | **{navs[-1]['excess_return_vwrp']:+.2%}** |", "",
        f"Priced as {v['calc']}. The screen book is price-only (dividends excluded) while VWRP's price includes "
        "reinvested dividends, so this comparison is biased against the screen book by roughly its dividend yield "
        "(about 1-1.5% a year, an estimate).", ""]
