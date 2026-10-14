import json, sys
sys.path.insert(0, "/home/user/agent-skills/equity")
from equity.store import Store
from equity.ingest import last_snapshot, latest_securities
from equity.research import current_bear_case
s = Store(); m = latest_securities(s)
snap = json.load(open("/mnt/project-files/portfolio/audit/api_snapshot.json"))
pos = snap["positions"]
tot = sum(p["walletImpact"]["currentValue"] for p in pos) if "walletImpact" in pos[0] else None
held = {p["instrument"]["ticker"] if "instrument" in p else p["ticker"]: p for p in pos}
print(list(pos[0].keys())) if not tot else None
extra = ["ADBE_US_EQ", "COST_US_EQ", "MSCI_US_EQ", "RL_US_EQ", "A_US_EQ", "META_US_EQ", "GOOGL_US_EQ", "MSFT_US_EQ",
         "GTES_US_EQ", "LOW_US_EQ", "VRT_US_EQ"]
sc = max(s.screens.read(), key=lambda r: r["ts_utc"]); by = {r["company_id"]: r for r in sc["results"]}
vals = {}
for v in s.valuations.read():
    if v["company_id"] not in vals or v["ts_utc"] > vals[v["company_id"]]["ts_utc"]: vals[v["company_id"]] = v
out = {}
for t in list(held) + [e for e in extra if e not in held]:
    sec = m.get(t) or {}
    cid = sec.get("company_id"); fs = last_snapshot(s, cid) if cid else None
    r = by.get(cid) or {}; v = vals.get(cid) or {}
    sm = (fs or {}).get("summary", {})
    p = held.get(t)
    out[t] = {"name": sec.get("name") or (p or {}).get("instrument", {}).get("name"), "isin": sec.get("isin"), "sec_match": sec.get("sec_match"),
              "value_gbp": p["walletImpact"]["currentValue"] if p else None, "weight": p["walletImpact"]["currentValue"] / tot if p else None,
              "sic": (fs or {}).get("sic"), "sic_description": (fs or {}).get("sic_description"), "template": (fs or {}).get("industry_template"),
              "latest_fy_end": sm.get("latest_fy_end"), "latest_filed": sm.get("latest_filed"), "confidence": (fs or {}).get("confidence"),
              **{k: sm.get(k) for k in ("revenue", "revenue_growth_yoy", "revenue_cagr_3y", "revenue_cagr_5y", "fcf", "fcf_margin", "fcf_margin_avg_5y",
                                        "fcf_per_share_cagr_3y", "fcf_per_share_cagr_5y", "fcf_positive_years", "fcf_years_known", "roic", "roic_avg_5y",
                                        "gross_margin", "operating_margin", "net_debt", "net_debt_to_ebitda", "interest_coverage", "share_change_cagr_3y",
                                        "sbc_pct_revenue", "cash_conversion_5y", "goodwill_pct_assets", "receivables_growth_yoy")},
              "screen_total": r.get("total"), "screen_rank": r.get("rank"), "eligible": r.get("eligible"), "failed_gates": r.get("failed_gates"),
              "unknown_critical_gates": r.get("unknown_critical_gates"), "subscores": r.get("scores"),
              "gate_details": {g["gate"]: g["detail"] for g in r.get("gates", []) if g["result"] != "pass"},
              "price_usd": v.get("price"), "market_cap": v.get("market_cap"), "multiples": v.get("multiples"),
              "implied_growth_5y": v.get("implied_growth_5y"), "history_growth": v.get("history_growth"),
              "scenarios": v.get("scenarios"), "valuation_notes": v.get("notes"),
              "bear_case_on_file": bool(cid and fs and current_bear_case(s, cid, fs)),
              "pie": {"quantity": p["quantity"], "in_pies": p.get("quantityInPies"), "tradeable": p.get("quantityAvailableForTrading"),
                      "currency": p["instrument"].get("currency") if "instrument" in p else p.get("currency")} if p else None}
json.dump({"sources": {"positions": "api_snapshot.json " + snap.get("fetched_utc", ""), "screen": sc["ts_utc"] + " " + sc.get("rid", ""),
                       "fundamentals": "SEC XBRL companyfacts, annual 10-K/20-F only", "valuation": "val-1.0 records"},
           "total_gbp": tot, "rows": out}, open("/mnt/project-files/portfolio/audit/evidence.json", "w"), indent=1, default=str)
def f(x, p="{:.0%}"):
    return "-" if x is None else p.format(x)
print("ticker wt rank tot fails revYoY rev3y fcfM fcfps3y roic ndE share3y sbc fcfY pe impl base_up fy_end")
for t, o in out.items():
    sc_ = o["scenarios"] or {}
    print(t[:6], f(o["weight"], "{:.1%}"), o["screen_rank"], f(o["screen_total"], "{:.0f}"), ",".join(o["failed_gates"] or []) or ".",
          f(o["revenue_growth_yoy"]), f(o["revenue_cagr_3y"]), f(o["fcf_margin"]), f(o["fcf_per_share_cagr_3y"]), f(o["roic"]),
          f(o["net_debt_to_ebitda"], "{:.1f}"), f(o["share_change_cagr_3y"], "{:+.1%}"), f(o["sbc_pct_revenue"], "{:.1%}"),
          f((o["multiples"] or {}).get("fcf_yield"), "{:.1%}"), f((o["multiples"] or {}).get("p_e"), "{:.0f}"), f(o["implied_growth_5y"]),
          f((sc_.get("base") or {}).get("upside")), o["latest_fy_end"], o["sec_match"])
