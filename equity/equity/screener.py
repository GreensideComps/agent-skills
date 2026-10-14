"""Master Stock Screener v1 (milestone 3).

Five separately reported scores, each 0-100 on absolute scales from config/screener.json:
FCF per share (30), business quality (25), growth (20), valuation (20) and risk fit (5).
Data confidence is reported next to them, not blended in: it gates, it does not score.

Rules that keep it honest:
* Every sub-score names its metric, its value and its scale. A missing metric is
  skipped and the component re-weights over what is present; if less than
  `min_component_coverage` of a component is present the component is None, and so is
  the total. Nothing is imputed.
* Mandatory gates are evaluated before ranking, each with pass / fail / unknown and the
  number it was decided on. Only companies with no failed gate and no unknown critical
  gate are ranked. Scores are still shown for the rest, so a near miss is visible.
* Business quality is measured from proxies (ROIC, margins, cash conversion, SBC), per
  the plan's default (AUDIT_AND_PLAN.md §8, decision 4). Moats are research notes, not scores.
* Valuation needs a market cap, which needs the price and the share count in the same
  unit. For 20-F/40-F filers the US line is usually an ADR with an unknown ratio, so their
  valuation is reported unavailable rather than guessed.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .store import Store, content_hash, utc_now

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "screener.json"
FOREIGN_FORMS = ("20-F", "20-F/A", "40-F", "40-F/A")
CRITICAL_GATES = ("industry_supported", "data_confidence", "fcf_positive_latest", "valuation_available")


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def scale(x: float | None, zero: float, full: float) -> float | None:
    """Linear 0-100 between `zero` and `full` (either direction), clipped."""
    if x is None:
        return None
    t = (x - zero) / (full - zero)
    return 100.0 * min(max(t, 0.0), 1.0)


def _latest_row(snap: dict) -> dict:
    fy = snap["summary"].get("latest_fy_end")
    return snap["years"].get(fy, {}) if fy else {}


def valuation_inputs(snap: dict, price: dict | None, today: date, max_age_days: int) -> tuple[dict, list[str]]:
    """Market cap, EV, FCF yield and EBIT yield, with the reasons when unavailable."""
    s, row, notes = snap["summary"], _latest_row(snap), []
    so = snap.get("shares_outstanding")
    out = {"price": None, "price_date": None, "market_cap": None, "enterprise_value": None,
           "fcf_yield": None, "ebit_yield": None}
    if price is None:
        return out, ["no_price"]
    out.update({"price": price["close"], "price_date": price["date"], "price_rid": price["rid"]})
    if (today - date.fromisoformat(price["date"])).days > max_age_days:
        notes.append("stale_price")
    if price.get("currency") != snap.get("reporting_currency"):
        notes.append(f"currency_mismatch:{price.get('currency')}!={snap.get('reporting_currency')}")
    if any(v.get("form") in FOREIGN_FORMS for v in row.values()):
        notes.append("adr_ratio_unknown")
    if not so:
        notes.append("no_share_count")
    if notes:
        return out, notes
    mcap = price["close"] * so["v"]
    out["market_cap"] = mcap
    if s.get("fcf") is not None and mcap > 0:
        out["fcf_yield"] = s["fcf"] / mcap
    op = row.get("operating_income", {}).get("v")
    if s.get("net_debt") is not None:
        ev = mcap + s["net_debt"]
        out["enterprise_value"] = ev
        if op is not None and ev > 0:
            out["ebit_yield"] = op / ev
    return out, notes


def metrics(snap: dict, val: dict) -> dict:
    s = snap["summary"]
    known = s.get("fcf_years_known") or 0
    nd, nde = s.get("net_debt"), s.get("net_debt_to_ebitda")
    return {**{k: s.get(k) for k in s}, **{k: val.get(k) for k in ("fcf_yield", "ebit_yield")},
            "fcf_consistency": (s["fcf_positive_years"] / known)
            if known and s.get("fcf_positive_years") is not None else None,
            "ebitda": snap.get("derived", {}).get(s.get("latest_fy_end"), {}).get("ebitda"),
            "net_debt_to_ebitda_or_cash": 0.0 if nd is not None and nd <= 0 else nde}


def component(spec: list[dict], m: dict, min_cov: float) -> dict:
    parts, wsum, acc = [], 0.0, 0.0
    for sub in spec:
        name = sub["metric"]
        x = m.get(name)
        if x is None and sub.get("fallback"):
            name, x = sub["fallback"], m.get(sub["fallback"])
        sc = scale(x, sub["zero"], sub["full"])
        parts.append({"metric": name, "value": x, "score": sc, "weight": sub["weight"],
                      "scale": [sub["zero"], sub["full"]]})
        if sc is not None:
            wsum += sub["weight"]
            acc += sub["weight"] * sc
    total_w = sum(sub["weight"] for sub in spec)
    cov = wsum / total_w if total_w else 0.0
    return {"score": acc / wsum if wsum and cov >= min_cov else None, "coverage": cov, "parts": parts}


def gates(snap: dict, m: dict, val_notes: list[str], val: dict, g: dict) -> list[dict]:
    def gate(name, ok, detail):
        return {"gate": name, "result": "unknown" if ok is None else ("pass" if ok else "fail"), "detail": detail}

    nd, nde, cov = m.get("net_debt"), m.get("net_debt_to_ebitda"), m.get("interest_coverage")
    if nd is None:
        lev = gate("leverage", None, "net debt unknown")
    elif nd <= 0:
        lev = gate("leverage", True, f"net cash {nd:,.0f}")
    elif m.get("ebitda") is None:
        lev = gate("leverage", None, "net debt, EBITDA unknown")
    elif nde is None:
        lev = gate("leverage", False, f"net debt with non-positive EBITDA {m['ebitda']:,.0f}")
    else:
        lev = gate("leverage", nde <= g["max_net_debt_to_ebitda"], f"net debt/EBITDA {nde:.2f} "
                   f"(max {g['max_net_debt_to_ebitda']})")
    if nd is not None and nd <= 0:
        ic = gate("interest_coverage", True, "net cash")
    else:
        ic = gate("interest_coverage", None if cov is None else cov >= g["min_interest_coverage"],
                  "unknown" if cov is None else f"{cov:.1f}x (min {g['min_interest_coverage']}x)")
    fc, dil = m.get("fcf_consistency"), m.get("share_change_cagr_3y")
    fcf = m.get("fcf")
    return [
        gate("industry_supported", snap.get("screen_supported"),
             f"template {snap.get('industry_template', 'unclassified')}"),
        gate("data_confidence", snap["confidence"] != "low", f"{snap['confidence']}"),
        gate("fcf_positive_latest", None if fcf is None else fcf > 0,
             "unknown" if fcf is None else f"FCF {fcf:,.0f}"),
        gate("fcf_consistency", None if fc is None else fc >= g["min_fcf_positive_share"],
             "unknown" if fc is None else f"{m.get('fcf_positive_years')}/{m.get('fcf_years_known')} years "
             f"positive (min {g['min_fcf_positive_share']:.0%})"),
        lev, ic,
        gate("dilution", None if dil is None else dil <= g["max_share_change_cagr_3y"],
             "unknown" if dil is None else f"share count {dil:+.1%}/yr over 3y "
             f"(max {g['max_share_change_cagr_3y']:+.0%})"),
        gate("valuation_available", not val_notes and val.get("fcf_yield") is not None,
             ", ".join(val_notes) or ("ok" if val.get("fcf_yield") is not None else "no FCF yield")),
    ]


def score_company(snap: dict, price: dict | None, cfg: dict, today: date) -> dict:
    val, notes = valuation_inputs(snap, price, today, cfg["gates"]["max_price_age_days"])
    m = metrics(snap, val)
    comps = {name: component(spec, m, cfg["min_component_coverage"]) for name, spec in cfg["components"].items()}
    w = cfg["weights"]
    total = None
    if all(comps[c]["score"] is not None for c in w):
        total = sum(w[c] * comps[c]["score"] for c in w) / sum(w.values())
    gs = gates(snap, m, notes, val, cfg["gates"])
    failed = [x["gate"] for x in gs if x["result"] == "fail"]
    unknown_critical = [x["gate"] for x in gs if x["result"] == "unknown" and x["gate"] in CRITICAL_GATES]
    return {"company_id": snap["company_id"], "entity_name": snap.get("entity_name"),
            "snapshot_rid": snap["rid"], "method_fundamentals": snap.get("method_version"),
            "data_confidence": snap["confidence"], "total": total,
            "scores": {c: comps[c]["score"] for c in comps}, "components": comps,
            "valuation": val, "gates": gs, "failed_gates": failed, "unknown_critical_gates": unknown_critical,
            "eligible": not failed and not unknown_critical and total is not None}


def run(store: Store, cfg: dict | None = None, today: date | None = None) -> dict:
    """Score every company's latest snapshot, rank the eligible ones, append one run record."""
    from .ingest import unpacked  # noqa: PLC0415
    from .prices import latest_prices  # noqa: PLC0415
    cfg = cfg or load_config()
    today = today or date.today()
    latest: dict[str, dict] = {}
    for s in store.fundamentals.read():
        if s["company_id"] not in latest or s["retrieved_utc"] > latest[s["company_id"]]["retrieved_utc"]:
            latest[s["company_id"]] = s
    prices = latest_prices(store)
    results = [score_company(unpacked(s), prices.get(cid), cfg, today) for cid, s in sorted(latest.items())]
    ranked = sorted((r for r in results if r["eligible"]), key=lambda r: -r["total"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    # The ledger keeps scores, gates, valuation and ranks; the per-metric breakdown is
    # recomputed on demand from the snapshot and price ids it names (see `explain`).
    stored = [{k: v for k, v in r.items() if k != "components"} |
              {"coverage": {c: round(x["coverage"], 3) for c, x in r["components"].items()}} for r in results]
    body = {"method_version": cfg["method_version"], "config_hash": content_hash(cfg), "as_of": today.isoformat(),
            "results": stored}
    rec = {"rid": f"screen:{cfg['method_version']}:{today}:{content_hash(body)}", "ts_utc": utc_now(),
           "weights": cfg["weights"], "gates_config": cfg["gates"], "companies": len(results),
           "eligible": len(ranked), **body}
    store.screens.append(rec)
    return rec


def explain(store: Store, company_id: str, cfg: dict | None = None) -> tuple[dict, dict] | None:
    """(latest run's stored result, recomputed full breakdown) for one company. The breakdown
    uses the exact snapshot and price the run used, and the current config, which must match
    the run's config hash (otherwise the caller is told)."""
    from .ingest import unpacked  # noqa: PLC0415
    cfg = cfg or load_config()
    runs = store.screens.read()
    if not runs:
        return None
    rec = max(runs, key=lambda r: r["ts_utc"])
    r = next((x for x in rec["results"] if x["company_id"] == company_id), None)
    if r is None:
        return None
    snap = next(s for s in store.fundamentals.read() if s["rid"] == r["snapshot_rid"])
    pr = r["valuation"].get("price_rid")
    price = next((p for p in store.prices.read() if p["rid"] == pr), None) if pr else None
    full = score_company(unpacked(snap), price, cfg, date.fromisoformat(rec["as_of"]))
    full["config_matches_run"] = content_hash(cfg) == rec["config_hash"]
    full["run_rid"] = rec["rid"]
    return r, full


def report(rec: dict, top: int = 25, valuations: dict | None = None, alerts: dict | None = None) -> str:
    """Markdown summary of a run: ranked list, then why the others were not ranked."""
    from collections import Counter  # noqa: PLC0415
    res = rec["results"]
    ranked = sorted((r for r in res if r.get("rank")), key=lambda r: r["rank"])
    from .evidence import banner  # noqa: PLC0415
    lines = [f"# Stock screen {rec['as_of']} ({rec['method_version']})", "",
             banner(rec["method_version"], "val-1.0"), "",
             f"{rec['companies']} companies scored, **{rec['eligible']} passed every gate**. Weights: "
             + ", ".join(f"{k} {v}" for k, v in rec["weights"].items())
             + ". Scores are 0-100 on absolute scales (`config/screener.json`). This is a screen for research, "
             "not a recommendation: a ranked company still needs a recorded, independent bear case before it can "
             "become a candidate. Valuation columns use mechanical DCF assumptions, not price targets.", "",
             "| # | Company | Total | FCF/sh | Quality | Growth | Valuation | Risk | Data | FCF yield | Price implies "
             "(5y FCF growth) | Base-case value vs price |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    valuations = valuations or {}

    def f(x):
        return "" if x is None else f"{x:.0f}"
    for r in ranked[:top]:
        sc, v = r["scores"], r["valuation"]
        lines.append(f"| {r['rank']} | {r['entity_name']} | **{r['total']:.0f}** | {f(sc['fcf_per_share'])} | "
                     f"{f(sc['quality'])} | {f(sc['growth'])} | {f(sc['valuation'])} | {f(sc['risk_fit'])} | "
                     f"{r['data_confidence']} | {v['fcf_yield']:.1%} | {_implied(valuations.get(r['company_id']))} | "
                     f"{_upside(valuations.get(r['company_id']))} |")
    fails = Counter(g for r in res if not r["eligible"] for g in r["failed_gates"] + r["unknown_critical_gates"])
    lines += ["", "## Why the others were not ranked", "",
              "A company can fail several gates; counts are per gate.", "",
              "| Gate | Companies failing or unknown |", "|---|---|"]
    lines += [f"| {g} | {n} |" for g, n in fails.most_common()]
    near = sorted((r for r in res if not r["eligible"] and r["total"] is not None and len(r["failed_gates"]) == 1
                   and not r["unknown_critical_gates"]), key=lambda r: -r["total"])[:10]
    if near:
        lines += ["", "## Near misses (one failed gate)", "", "| Company | Total | Failed gate | Detail |",
                  "|---|---|---|---|"]
        for r in near:
            g = next(x for x in r["gates"] if x["result"] == "fail")
            lines.append(f"| {r['entity_name']} | {r['total']:.0f} | {g['gate']} | {g['detail']} |")
    if alerts is not None:
        lines += ["", "## Alerts (changes since the previous run)", ""]
        if alerts.get("baseline"):
            lines.append("First run of this method: baseline recorded, nothing to compare with.")
        elif not alerts["alerts"]:
            lines.append("No changes.")
        lines += [f"- **{a['kind']}** {a.get('entity_name')}: {a['text']}" for a in alerts.get("alerts", [])]
    lines += ["", "Valuation method and assumptions: `equity/equity/valuation.py` (stored with every record in "
              "`valuations.jsonl`). Base-case values are mechanical, not price targets."]
    return "\n".join(lines) + "\n"


def _implied(v: dict | None) -> str:
    ig = (v or {}).get("implied_growth_5y")
    return "" if ig is None else f"{ig:+.0%}/yr"


def _upside(v: dict | None) -> str:
    b = ((v or {}).get("scenarios") or {}).get("base")
    return "" if not b or b.get("upside") is None else f"{b['upside']:+.0%}"
