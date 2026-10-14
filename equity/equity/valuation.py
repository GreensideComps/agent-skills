"""Valuation (milestone 4): multiples, DCF scenarios and a reverse DCF, with every assumption stored.

The point is to make the price's implied expectations explicit, not to produce a precise
"fair value". So:
* The DCF starts from normalised FCF (the average of the last 3 fiscal years, which damps
  one-off years), grows it for 5 years at a scenario rate, fades the rate linearly to the
  terminal rate over years 6-10, and discounts at a fixed rate. Equity value = enterprise
  value - net debt. All parameters are in VALUATION_CONFIG and are stored with each result.
* Scenario growth rates are derived mechanically from the company's own history (FCF/share,
  else revenue CAGR) with caps, so nobody tunes them per company to get a desired answer.
* The reverse DCF solves for the 5-year growth rate the current enterprise value implies.
  "Price implies 18% a year for 5 years" is easier to argue with than a target price.
* No value is produced when its inputs are missing or the base FCF is not positive.
"""
from __future__ import annotations

from .store import Store, content_hash, utc_now

METHOD_VERSION = "val-1.0"
VALUATION_CONFIG = {
    "discount_rate": 0.09,
    "terminal_growth": 0.025,
    "explicit_years": 5,
    "fade_years": 5,
    "base_fcf": "mean of the last 3 fiscal years' FCF (all must be known)",
    "history_growth": "fcf_per_share_cagr_5y, else fcf_per_share_cagr_3y, else revenue_cagr_5y, else revenue_cagr_3y",
    "scenarios": {
        "bear": "base - 0.05, floored at -0.03",
        "base": "0.7 x history, clipped to [0, 0.15]",
        "bull": "base + 0.04, capped at 0.20",
    },
}


def _clip(x, lo, hi):
    return min(max(x, lo), hi)


def scenario_growth(history: float | None) -> dict[str, float] | None:
    if history is None:
        return None
    base = _clip(0.7 * history, 0.0, 0.15)
    return {"bear": max(base - 0.05, -0.03), "base": base, "bull": min(base + 0.04, 0.20)}


def dcf_ev(fcf0: float, g: float, cfg: dict = VALUATION_CONFIG) -> float:
    """Enterprise value of an FCF stream: g for `explicit_years`, linear fade to terminal, Gordon tail."""
    r, gt = cfg["discount_rate"], cfg["terminal_growth"]
    n1, n2 = cfg["explicit_years"], cfg["fade_years"]
    pv, f = 0.0, fcf0
    for t in range(1, n1 + n2 + 1):
        gr = g if t <= n1 else g + (gt - g) * (t - n1) / n2
        f *= 1 + gr
        pv += f / (1 + r) ** t
    tail = f * (1 + gt) / (r - gt)
    return pv + tail / (1 + r) ** (n1 + n2)


def implied_growth(fcf0: float, ev: float, cfg: dict = VALUATION_CONFIG, lo=-0.5, hi=1.0) -> float | None:
    """The explicit-period growth rate at which dcf_ev equals `ev` (bisection; None if out of range)."""
    if fcf0 <= 0 or ev <= 0:
        return None
    if not dcf_ev(fcf0, lo, cfg) <= ev <= dcf_ev(fcf0, hi, cfg):
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if dcf_ev(fcf0, mid, cfg) < ev:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def base_fcf(snap: dict) -> float | None:
    ends = sorted(snap.get("derived", {}))[-3:]
    vals = [snap["derived"][e].get("fcf") for e in ends]
    if len(vals) < 3 or any(v is None for v in vals):
        return None
    return sum(vals) / 3


def value_company(snap: dict, screen_result: dict, cfg: dict = VALUATION_CONFIG) -> dict:
    """Multiples, scenario values per share and the reverse DCF for one company."""
    s, v = snap["summary"], screen_result["valuation"]
    so = snap.get("shares_outstanding") or {}
    row = snap["years"].get(s.get("latest_fy_end"), {})
    mcap, ev, price = v.get("market_cap"), v.get("enterprise_value"), v.get("price")
    out = {"company_id": snap["company_id"], "entity_name": snap.get("entity_name"), "method_version": METHOD_VERSION,
           "assumptions": cfg, "snapshot_rid": snap["rid"], "price_rid": v.get("price_rid"), "price": price,
           "market_cap": mcap, "enterprise_value": ev, "notes": []}

    def ratio(a, b):
        return a / b if a is not None and b not in (None, 0) and b > 0 else None
    op, rev, eps = row.get("operating_income", {}).get("v"), s.get("revenue"), s.get("eps_diluted")
    out["multiples"] = {"p_fcf": ratio(mcap, s.get("fcf")), "ev_ebit": ratio(ev, op), "ev_sales": ratio(ev, rev),
                        "p_e": ratio(price, eps), "fcf_yield": v.get("fcf_yield")}
    if mcap is None or ev is None or not so.get("v"):
        out["notes"].append("no market value (see screen valuation gate)")
        return out
    fcf0 = base_fcf(snap)
    hist = next((s.get(k) for k in ("fcf_per_share_cagr_5y", "fcf_per_share_cagr_3y", "revenue_cagr_5y",
                                     "revenue_cagr_3y") if s.get(k) is not None), None)
    out.update({"base_fcf": fcf0, "history_growth": hist})
    if fcf0 is None or fcf0 <= 0:
        out["notes"].append("base FCF unknown or not positive: no DCF")
        return out
    growth = scenario_growth(hist)
    net_debt = ev - mcap
    if growth:
        out["scenarios"] = {}
        for name, g in growth.items():
            per_share = (dcf_ev(fcf0, g, cfg) - net_debt) / so["v"]
            out["scenarios"][name] = {"growth_5y": g, "value_per_share": per_share,
                                      "upside": per_share / price - 1 if price else None}
    else:
        out["notes"].append("no growth history: no scenarios")
    out["implied_growth_5y"] = implied_growth(fcf0, ev, cfg)
    if out["implied_growth_5y"] is None:
        out["notes"].append("implied growth outside -50%..100%")
    return out


def run(store: Store, screen_rec: dict, only_ranked: bool = False) -> list[dict]:
    """Value every company in a screen run that has a market value; append to valuations.jsonl."""
    from .ingest import unpacked  # noqa: PLC0415
    snaps = {s["rid"]: s for s in store.fundamentals.read()}
    out = []
    for r in screen_rec["results"]:
        if only_ranked and not r.get("rank"):
            continue
        if r["valuation"].get("market_cap") is None:
            continue
        val = value_company(unpacked(snaps[r["snapshot_rid"]]), r)
        val["screen_rid"] = screen_rec["rid"]
        val["rid"] = f"val:{METHOD_VERSION}:{content_hash([val['snapshot_rid'], val['price_rid']])}"
        val["ts_utc"] = utc_now()
        out.append(val)
    store.valuations.append(out)
    return out
