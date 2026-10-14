"""Real-portfolio monitoring (milestone 6, demo stand-in for the owner's ISA).

Read-only by construction: holdings come from the trading bot's ReadOnlyClient, which can
only call GET endpoints (account summary, positions); no order method is reachable. Until the
owner adds a read-only Invest/ISA key, the account read is the Practice (demo) account, into
which the owner copied their ISA pies with real weights (not real average prices).

Each run stores one snapshot (`portfolio.jsonl`, keyed by date) and reports:
* holdings joined to the research database: screen score, rank, failed gates, the growth the
  price implies, and a bear case if one exists;
* exposure: by company, sector (SEC SIC description), currency, and pie vs free holdings;
* concentration: largest position, top 5, Herfindahl index and its effective number of holdings;
* co-movement: one year of daily returns per holding, giving the portfolio's annualised
  volatility, the average pairwise correlation, beta to the Nasdaq-100 (QQQ) and the largest
  recent moves;
* flags against fixed thresholds in config/portfolio.json (not tuned to this portfolio).
"""
from __future__ import annotations

import json
import math
import statistics
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .prices import PriceError, _get
from .store import Store, content_hash, utc_now

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "portfolio.json"
DAILY = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"


BROAD_SECTORS = [  # approximate, from SIC ranges; used for the sector-concentration flag
    ("Technology", [(3570, 3579), (3661, 3679), (3820, 3829), (7370, 7379)]),
    ("Communication", [(4800, 4899), (2710, 2741), (7810, 7849)]),
    ("Health care", [(2830, 2836), (3840, 3851), (8000, 8099), (8730, 8734)]),
    ("Financials", [(6000, 6499), (6700, 6797), (6799, 6799)]),
    ("Real estate", [(6500, 6553), (6798, 6798)]),
    ("Utilities", [(4900, 4949)]),
    ("Energy", [(1300, 1399), (2900, 2999)]),
    ("Consumer discretionary", [(2300, 2399), (3710, 3716), (3940, 3949), (5000, 5199), (5200, 5999), (7000, 7099),
                                (7900, 7999)]),
    ("Consumer staples", [(100, 999), (2000, 2199)]),
    ("Materials", [(1000, 1299), (1400, 1499), (2400, 2699), (2800, 2829), (2840, 2899), (3000, 3399)]),
    ("Industrials", [(1500, 1799), (3400, 3569), (3580, 3660), (3680, 3709), (3717, 3819), (3830, 3839),
                     (3852, 3939), (3950, 3999), (4000, 4799), (7300, 7369), (7380, 7399), (8700, 8729)]),
]


def broad_sector(sic) -> str:
    try:
        n = int(sic)
    except (TypeError, ValueError):
        return "unknown"
    for name, ranges in BROAD_SECTORS:
        if any(a <= n <= b for a, b in ranges):
            return name
    return "other"


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def snapshot(client, today: date | None = None) -> dict:
    """Read the account (GET only). No account id is stored."""
    today = today or date.today()
    s = client.account_summary()
    pos = []
    for p in client.positions():
        wi = p.get("walletImpact") or {}
        pos.append({"t212_ticker": p["instrument"]["ticker"], "name": p["instrument"].get("name"),
                    "isin": p["instrument"].get("isin"), "currency": p["instrument"].get("currency"),
                    "quantity": p.get("quantity"), "quantity_in_pies": p.get("quantityInPies") or 0,
                    "price": p.get("currentPrice"), "value_gbp": wi.get("currentValue"),
                    "cost_gbp": wi.get("totalCost")})
    rec = {"as_of": today.isoformat(), "ts_utc": utc_now(), "account_currency": s.get("currency"),
           "total_value": s.get("totalValue"), "cash": s.get("cash"), "positions": pos,
           "source": "Trading 212 API (read-only GET: account summary, positions)"}
    rec["rid"] = f"portfolio:{rec['as_of']}:{content_hash([pos, s.get('totalValue')])}"
    return rec


def yahoo_symbol(t212_ticker: str, master: dict) -> str | None:
    s = master.get(t212_ticker)
    if s and s.get("symbol") and t212_ticker.endswith("_US_EQ"):
        return s["symbol"].replace(".", "-").replace("/", "-")
    if t212_ticker.endswith("_US_EQ"):
        return t212_ticker[:-6]
    if t212_ticker.endswith("l_EQ"):
        return t212_ticker[:-4] + ".L"
    return None


def parse_daily(body: bytes) -> dict[str, float]:
    res = (json.loads(body).get("chart", {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise PriceError("no chart result")
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or res["indicators"]["quote"][0]["close"]
    return {datetime.fromtimestamp(t, timezone.utc).date().isoformat(): float(c)
            for t, c in zip(res["timestamp"], adj) if c is not None}


def returns(closes: dict[str, float]) -> dict[str, float]:
    ds = sorted(closes)
    return {d: closes[d] / closes[p] - 1 for p, d in zip(ds, ds[1:]) if closes[p]}


def _cov(a: dict[str, float], b: dict[str, float]) -> tuple[float, int] | None:
    common = sorted(set(a) & set(b))
    if len(common) < 60:
        return None
    x, y = [a[d] for d in common], [b[d] for d in common]
    return statistics.covariance(x, y), len(common)


def risk(weights: dict[str, float], rets: dict[str, dict[str, float]], bench: dict[str, float] | None) -> dict:
    """Annualised vol (weights renormalised over holdings with history), avg correlation, beta."""
    names = [n for n in weights if n in rets and len(rets[n]) >= 60]
    covered = sum(weights[n] for n in names)
    out = {"covered_weight": covered, "with_history": len(names), "vol_annual": None, "avg_correlation": None,
           "beta_qqq": None}
    if len(names) < 2 or covered <= 0:
        return out
    w = {n: weights[n] / covered for n in names}
    var, corrs = 0.0, []
    sd = {n: statistics.pstdev(list(rets[n].values())) for n in names}
    for i, a in enumerate(names):
        for b in names[i:]:
            c = _cov(rets[a], rets[b])
            if c is None:
                continue
            var += (1 if a == b else 2) * w[a] * w[b] * c[0]
            if a != b and sd[a] and sd[b]:
                corrs.append(c[0] / (sd[a] * sd[b]))
    out["vol_annual"] = math.sqrt(max(var, 0.0) * 252)
    out["avg_correlation"] = statistics.mean(corrs) if corrs else None
    if bench and len(bench) > 60:
        days = sorted(set.intersection(set(bench), *(set(rets[n]) for n in names)))
        if len(days) > 60:
            port = [sum(w[n] * rets[n][d] for n in names) for d in days]
            b = [bench[d] for d in days]
            out["beta_qqq"] = statistics.covariance(port, b) / statistics.variance(b)
    return out


def analyse(snap: dict, store: Store, rets: dict[str, dict[str, float]] | None = None,
            bench: dict[str, float] | None = None, cfg: dict | None = None) -> dict:
    from .ingest import last_snapshot, latest_securities  # noqa: PLC0415
    from .research import current_bear_case  # noqa: PLC0415
    cfg = cfg or load_config()
    master = latest_securities(store)
    runs = store.screens.read()
    screen = max(runs, key=lambda r: r["ts_utc"]) if runs else None
    by_cid = {r["company_id"]: r for r in screen["results"]} if screen else {}
    vals = {}
    for v in store.valuations.read():
        if v["company_id"] not in vals or v["ts_utc"] > vals[v["company_id"]]["ts_utc"]:
            vals[v["company_id"]] = v
    total = sum(p["value_gbp"] or 0 for p in snap["positions"]) + sum(
        float(x or 0) for x in (snap.get("cash") or {}).values())
    rows = []
    for p in sorted(snap["positions"], key=lambda p: -(p["value_gbp"] or 0)):
        sec = master.get(p["t212_ticker"]) or {}
        cid = sec.get("company_id")
        fs = last_snapshot(store, cid) if cid and sec.get("sec_match") == "high" else None
        sr = by_cid.get(cid) or {}
        v = vals.get(cid) or {}
        rows.append({"t212_ticker": p["t212_ticker"], "name": sec.get("name") or p["name"], "company_id": cid,
                     "weight": (p["value_gbp"] or 0) / total if total else 0, "value_gbp": p["value_gbp"],
                     "currency": p["currency"], "in_pie": (p["quantity_in_pies"] or 0) > 0,
                     "sector": (fs or {}).get("sic_description") or ("ETF, fund or unmapped" if not sec else "not in research DB"),
                     "broad_sector": broad_sector((fs or {}).get("sic")) if fs else
                     ("ETF, fund or unmapped" if not sec else "unknown"),
                     "researched": fs is not None, "confidence": (fs or {}).get("confidence"),
                     "screen_total": sr.get("total"), "screen_rank": sr.get("rank"),
                     "failed_gates": sr.get("failed_gates"), "implied_growth_5y": v.get("implied_growth_5y"),
                     "bear_case": bool(cid and current_bear_case(store, cid, fs))})
    w = {r["t212_ticker"]: r["weight"] for r in rows}
    hhi = sum(x * x for x in w.values())
    by = {}
    for key in ("broad_sector", "sector", "currency"):
        agg: dict[str, float] = {}
        for r in rows:
            agg[r[key]] = agg.get(r[key], 0) + r["weight"]
        by[key] = dict(sorted(agg.items(), key=lambda kv: -kv[1]))
    conc = {"largest": max(w.values(), default=0), "top5": sum(sorted(w.values(), reverse=True)[:5]),
            "hhi": hhi, "effective_holdings": 1 / hhi if hhi else None, "holdings": len(rows),
            "cash_weight": 1 - sum(w.values())}
    rk = risk(w, rets or {}, bench)
    moves = []
    for r in rows:
        rr = (rets or {}).get(r["t212_ticker"])
        if rr:
            ds = sorted(rr)
            r1 = rr[ds[-1]]
            r5 = math.prod(1 + rr[d] for d in ds[-5:]) - 1
            r["move_1d"], r["move_5d"] = r1, r5
            moves.append(r)
    t = cfg["thresholds"]
    flags = []
    for r in rows:
        if r["weight"] > t["max_position_weight"]:
            flags.append(f"{r['name']} is {r['weight']:.1%} of the portfolio (threshold {t['max_position_weight']:.0%})")
        if abs(r.get("move_5d") or 0) > t["move_5d"]:
            flags.append(f"{r['name']} moved {r['move_5d']:+.1%} over 5 trading days")
        if r["failed_gates"]:
            flags.append(f"{r['name']} fails screen gates: {', '.join(r['failed_gates'])}")
    for s, x in by["broad_sector"].items():
        if x > t["max_sector_weight"]:
            flags.append(f"broad sector '{s}' is {x:.0%} of the portfolio (threshold {t['max_sector_weight']:.0%})")
    if rk["avg_correlation"] is not None and rk["avg_correlation"] > t["max_avg_correlation"]:
        flags.append(f"holdings move together: average pairwise correlation {rk['avg_correlation']:.2f} "
                     f"(threshold {t['max_avg_correlation']:.2f})")
    if rk["vol_annual"] is not None and rk["vol_annual"] > t["max_vol_annual"]:
        flags.append(f"annualised volatility {rk['vol_annual']:.0%} (threshold {t['max_vol_annual']:.0%})")
    return {"as_of": snap["as_of"], "snapshot_rid": snap["rid"], "total_value": total, "rows": rows, "exposure": by,
            "concentration": conc, "risk": rk, "flags": flags, "screen_rid": screen["rid"] if screen else None}


def fetch_returns(snap: dict, store: Store, get=_get, pause: float = 0.3, sleep=time.sleep):
    from .ingest import latest_securities  # noqa: PLC0415
    master = latest_securities(store)
    rets, failed = {}, []
    for i, p in enumerate(snap["positions"]):
        sym = yahoo_symbol(p["t212_ticker"], master)
        if i:
            sleep(pause)
        try:
            rets[p["t212_ticker"]] = returns(parse_daily(get(DAILY.format(sym=sym))))
        except (PriceError, OSError, ValueError, KeyError, TypeError) as e:
            failed.append(f"{p['t212_ticker']} ({sym}): {e}")
    try:
        bench = returns(parse_daily(get(DAILY.format(sym="QQQ"))))
    except (PriceError, OSError, ValueError) as e:
        bench, failed = None, failed + [f"QQQ: {e}"]
    return rets, bench, failed


def report(a: dict, failed: list[str] | None = None) -> str:
    def pc(x, f="{:.1%}"):
        return "" if x is None else f.format(x)
    c, rk = a["concentration"], a["risk"]
    lines = [f"# Portfolio monitor, {a['as_of']}", "",
             "Read-only. Source: the Trading 212 **demo** account, holding copies of the owner's ISA pies (real "
             "weights, not real average prices or profits).", "",
             f"Total value £{a['total_value']:,.2f} in {c['holdings']} holdings; cash {pc(c['cash_weight'])}.", ""]
    lines += ["## Flags", ""] + ([f"- {f}" for f in a["flags"]] or ["- none"]) + [""]
    lines += ["## Concentration and risk", "", "| Measure | Value |", "|---|---|",
              f"| Largest position | {pc(c['largest'])} |", f"| Top 5 | {pc(c['top5'])} |",
              f"| Effective number of holdings (1/HHI) | {pc(c['effective_holdings'], '{:.1f}')} |",
              f"| Annualised volatility (1y daily) | {pc(rk['vol_annual'], '{:.0%}')} |",
              f"| Average pairwise correlation | {pc(rk['avg_correlation'], '{:.2f}')} |",
              f"| Beta to Nasdaq-100 (QQQ) | {pc(rk['beta_qqq'], '{:.2f}')} |",
              f"| Weight with a year of price history | {pc(rk['covered_weight'])} |", ""]
    for key, title in (("broad_sector", "Broad sector (approximate, from SIC)"), ("sector", "SEC SIC industry"),
                       ("currency", "Currency")):
        lines += [f"## Exposure: {title}", "", f"| {title} | Weight |", "|---|---|"]
        lines += [f"| {k} | {pc(v)} |" for k, v in a["exposure"][key].items()] + [""]
    lines += ["## Holdings", "", "| Holding | Weight | 5-day move | Screen score | Rank | Price implies (5y FCF growth) "
              "| Failed gates | Data |", "|---|---|---|---|---|---|---|---|"]
    for r in a["rows"]:
        data = (r["confidence"] or "") if r["researched"] else "not researched yet"
        lines.append(f"| {r['name']} | {pc(r['weight'])} | {pc(r.get('move_5d'), '{:+.1%}')} | "
                     f"{pc(r['screen_total'], '{:.0f}')} | {r['screen_rank'] or ''} | "
                     f"{pc(r['implied_growth_5y'], '{:+.0%}')} | {', '.join(r['failed_gates'] or [])} | {data} |")
    if failed:
        lines += ["", "Price history unavailable for: " + "; ".join(failed)]
    lines += ["", "Thresholds are in `equity/config/portfolio.json`. Screen columns are blank for holdings the screen "
              "does not cover (funds, non-SEC filers, financials) or has not scored yet."]
    return "\n".join(lines) + "\n"
