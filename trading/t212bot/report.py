"""Performance report: real demo account vs shadow portfolios, fill quality,
and an honest read on what is (not yet) statistically meaningful."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import pandas as pd

from .config import ROOT, StrategyConfig
from .journal import Journal
from .shadow import PriceBook, gem_nav, static_nav

REPORT_PATH = ROOT / "PERFORMANCE.md"


def account_series(j: Journal) -> pd.Series:
    rows = j.snapshots()
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(r["ts_utc"]): float(r["total_value_gbp"]) for r in rows if r["total_value_gbp"]})
    s.index = s.index.tz_convert(None) if s.index.tz is not None else s.index
    return s.groupby(s.index.normalize()).last()


def build(j: Journal, cfg: StrategyConfig, book: PriceBook | None = None) -> dict:
    book = book or PriceBook()
    state = j.load_state()
    inc = state.get("inception") or {}
    out = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "strategy": cfg.name}
    acct = account_series(j)
    out["account"] = acct
    first_trade = next((e for e in j.events("order_placed")), None)
    if not first_trade:
        out["note"] = "no trades yet"
        return out
    start = pd.Timestamp(first_trade["ts_utc"]).tz_convert(None).normalize().date()
    capital = float(inc.get("total_value_gbp") or 100.0)
    shadows = {}
    for name, spec in cfg.shadow_portfolios.items():
        if spec["type"] == "static":
            shadows[name] = static_nav(book, cfg.yahoo_symbols, spec["targets"], start, capital)
        elif spec["type"] == "gem12":
            roles = {"US": cfg.yahoo_symbols[spec["us"]], "INTL": cfg.yahoo_symbols[spec["intl"]],
                     "BOND": cfg.yahoo_symbols[spec["bond"]]}
            nav, log = gem_nav(book, roles, start, capital)
            shadows[name] = nav
            out[f"{name}_log"] = log
    # same-rules shadow of the live strategy at closing prices (implementation shortfall)
    shadows["B_live_rules_at_close"] = static_nav(book, cfg.yahoo_symbols, cfg.targets, start, capital)
    out["shadows"] = shadows
    out["start"] = start
    out["capital"] = capital
    fills = j.events("order_reconciled")
    out["fills"] = fills
    return out


def _ret(s: pd.Series) -> float:
    return float(s.iloc[-1] / s.iloc[0] - 1) if len(s) > 1 else 0.0


def render(data: dict) -> str:
    L = [f"# Live demo performance: `{data['strategy']}`", "",
         f"_Generated {data['generated_utc']} UTC by `python -m t212bot report`. Demo (paper) account only._", ""]
    acct = data.get("account", pd.Series(dtype=float))
    if "shadows" not in data:
        L += ["No trades yet.", ""]
        return "\n".join(L)
    cap = data["capital"]
    L += [f"Inception: **{data['start']}**, starting capital **£{cap:.2f}**.", "", "## Value since inception", "",
          "| Portfolio | Value now | Return | Notes |", "|---|---|---|---|"]
    if len(acct):
        L.append(f"| **B (real demo account)** | £{acct.iloc[-1]:.2f} | {acct.iloc[-1] / cap - 1:+.2%} | real fills, real costs |")
    notes = {"B_live_rules_at_close": "same targets, frictionless-ish fills at daily close",
             "A_benchmark_vwrp": "100% VWRP at daily close", "C_gem12": "GEM-12 dual momentum at daily close"}
    for k, s in data["shadows"].items():
        if len(s):
            L.append(f"| {k} | £{s.iloc[-1]:.2f} | {s.iloc[-1] / cap - 1:+.2%} | {notes.get(k, '')} |")
    L.append("")
    fills = data.get("fills", [])
    if fills:
        L += ["## Execution quality (real fills vs reference quote at order time)", "",
              "| Order | Ticker | Status | Fill price | Reference | Slippage (bps, + = worse) | Cost vs reference (£) |",
              "|---|---|---|---|---|---|---|"]
        for f in fills:
            L.append(f"| {f['order_id']} | {f['ticker']} | {f['status']} | {f.get('fill_price')} | {f.get('reference_price')} | "
                     f"{f.get('slippage_bps_vs_reference', '')} | {f.get('cost_vs_reference_gbp', '')} |")
        L.append("")
    # statistical honesty
    a, b = data["shadows"].get("A_benchmark_vwrp"), acct
    L += ["## Is any of this meaningful yet?", ""]
    if a is not None and len(b) > 1:
        days = (b.index[-1] - b.index[0]).days
        yrs = max(days / 365.25, 1 / 365.25)
        diff = (b.iloc[-1] / cap - 1) - (a.iloc[-1] / cap - 1)
        te = 0.075  # research estimate of momentum-tilt tracking error vs world (annualised)
        se = te * math.sqrt(yrs) * 0.5  # 50% tilt halves tracking error
        t = diff / se if se > 0 else float("nan")
        L += [f"- Days live: **{days}**. Difference vs 100% VWRP: **{diff:+.2%}**.",
              f"- Expected noise (1 s.e.) over this period from tracking error alone: ±{se:.2%} → t ≈ {t:.2f}.",
              "- |t| < 2 means the difference is indistinguishable from luck. Research estimates ~50+ years "
              "would be needed to confirm a 2%/yr edge, so treat short-run results as tests of the plumbing, not the strategy.", ""]
    else:
        L += ["- Not enough history yet.", ""]
    return "\n".join(L)


def write(data: dict) -> str:
    md = render(data)
    REPORT_PATH.write_text(md)
    return md


def summary_json(data: dict) -> str:
    def conv(v):
        if isinstance(v, pd.Series):
            return {str(k.date() if hasattr(k, "date") else k): round(float(x), 4) for k, x in v.items()}
        return v
    return json.dumps({k: conv(v) if not isinstance(v, dict) else {kk: conv(vv) for kk, vv in v.items()}
                       for k, v in data.items()}, default=str, indent=1)
