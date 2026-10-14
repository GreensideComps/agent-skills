import json, math, statistics as st, sys
sys.path.insert(0, "/home/user/agent-skills/equity")
from equity.portfolio import broad_sector
A_ = "/mnt/project-files/portfolio/audit/"
px = json.load(open(A_ + "prices_5y_daily.json")); C = px["closes"]
ev = json.load(open(A_ + "evidence.json")); R = ev["rows"]
snap = json.load(open(A_ + "api_snapshot.json"))
val = {p["instrument"]["ticker"]: p["walletImpact"]["currentValue"] for p in snap["positions"]}
tot = sum(val.values())
A = {t: v / tot for t, v in val.items()}
def norm(w): s = sum(w.values()); return {k: v / s for k, v in w.items() if v > 0}
EXIT_HARD = ["INTC_US_EQ", "BE_US_EQ", "TEM_US_EQ"]
B = norm({t: w for t, w in A.items() if t not in EXIT_HARD})
Cw = dict(A)
for t in ["INTC_US_EQ", "BE_US_EQ", "TEM_US_EQ", "TSLA_US_EQ", "UBER_US_EQ", "AMD_US_EQ"]: Cw[t] = 0
Cw.update({"NVDA_US_EQ": .11, "AVGO_US_EQ": .07, "AMZN_US_EQ": .07, "TSM_US_EQ": .05, "ASML_US_EQ": .05, "PLTR_US_EQ": .04,
           "ADBE_US_EQ": .04, "COST_US_EQ": .04, "MSCI_US_EQ": .04, "RL_US_EQ": .03, "A_US_EQ": .02, "VWRP.L": .03})
Cw = norm(Cw)
V = {"VWRP.L": 1.0}
SEMIS = {"NVDA_US_EQ", "AVGO_US_EQ", "TSM_US_EQ", "ASML_US_EQ", "AMD_US_EQ", "INTC_US_EQ"}
# Semis cap variant: B, then scale semis to 25% total, freed weight pro rata to non-semis, non-AI names
AI = {"compute/semis": SEMIS, "AI infrastructure & power": {"VRT_US_EQ", "VST_US_EQ", "BE_US_EQ"},
      "hyperscalers": {"MSFT_US_EQ", "GOOGL_US_EQ", "FB_US_EQ", "AMZN_US_EQ"}, "AI software": {"PLTR_US_EQ", "TEM_US_EQ"}}
AIALL = set().union(*AI.values())
def semis_cap(w, cap=0.25):
    s = sum(v for k, v in w.items() if k in SEMIS)
    if s <= cap: return w
    out = {k: (v * cap / s if k in SEMIS else v) for k, v in w.items()}
    free = s - cap; rest = {k: v for k, v in w.items() if k not in AIALL and k != "SPCX_US_EQ"}
    rs = sum(rest.values())
    for k, v in rest.items(): out[k] += free * v / rs
    return out
B2 = semis_cap(B)
PORTS = {"A keep": A, "B exit hard-risk only": B, "C proposed plan": Cw, "VWRP (global benchmark)": V,
         "B2 = B + semis capped at 25% (info)": B2}
# VWRP look-through (Vanguard factsheet 31 Aug 2026; top-10 only, lower bound)
VW_TOP = {"NVDA_US_EQ": .048, "AAPL_US_EQ": .043, "MSFT_US_EQ": .035, "GOOGL_US_EQ": .033, "AMZN_US_EQ": .023,
          "TSM_US_EQ": .017, "AVGO_US_EQ": .016, "FB_US_EQ": .012, "TSLA_US_EQ": .010}  # + Micron 1.0%
VW_SEMIS_LB = .048 + .017 + .016 + .010
COUNTRY = {"TSM_US_EQ": "Taiwan", "ASML_US_EQ": "Netherlands", "IBTAl_EQ": "US (Treasuries)"}
VW_COUNTRY = {"United States": .617, "Japan": .06, "Taiwan": .033, "United Kingdom": .033, "Canada": .03, "China": .027,
              "Korea": .025, "France": .02, "Switzerland": .02, "Germany": .019}
def exposures(w):
    vw = w.get("VWRP.L", 0)
    sec, ctry, ai = {}, {}, {}
    for t, x in w.items():
        if t == "VWRP.L":
            sec["VWRP (look-through: ICB tech 34%)"] = sec.get("VWRP (look-through: ICB tech 34%)", 0) + x
            for c, cw in VW_COUNTRY.items(): ctry[c] = ctry.get(c, 0) + x * cw
            ctry["other (VWRP)"] = ctry.get("other (VWRP)", 0) + x * (1 - sum(VW_COUNTRY.values()))
            continue
        r = R.get(t, {})
        b = broad_sector(r.get("sic")) if r.get("sic") else ("Bond ETF" if t == "IBTAl_EQ" else "unclassified (SpaceX)")
        sec[b] = sec.get(b, 0) + x
        c = COUNTRY.get(t, "United States"); ctry[c] = ctry.get(c, 0) + x
        g = next((k for k, v in AI.items() if t in v), "not AI-linked")
        ai[g] = ai.get(g, 0) + x
    semis_direct = sum(x for t, x in w.items() if t in SEMIS)
    lt = {t: w.get(t, 0) + vw * VW_TOP.get(t, 0) for t in set(w) | set(VW_TOP) if t != "VWRP.L"}
    return {"semis_direct": semis_direct, "semis_incl_vwrp_lookthrough_lb": semis_direct + vw * VW_SEMIS_LB,
            "ai_linked_total": sum(v for k, v in ai.items() if k != "not AI-linked"), "ai_groups": ai,
            "sector": dict(sorted(sec.items(), key=lambda kv: -kv[1])), "country": dict(sorted(ctry.items(), key=lambda kv: -kv[1])),
            "usd_underlying": sum(x for t, x in w.items() if t != "VWRP.L") + vw * .617,
            "largest": max(lt.values()), "top5": sum(sorted(lt.values(), reverse=True)[:5]),
            "effective_n": 1 / sum(x * x for x in w.values()), "holdings": len(w)}
# GBP daily returns
fx = C["GBPUSD=X"]
def gbp_levels(t):
    c = C[t]
    if t == "VWRP.L": return c
    out, last = {}, None
    for d in sorted(c):
        f = fx.get(d)
        if f is None:
            prev = [x for x in fx if x <= d]
            if not prev: continue
            f = fx[max(prev)]
        out[d] = c[d] / f
    return out
LV = {t: gbp_levels(t) for t in C if t not in ("GBPUSD=X",)}
DATES = sorted(set(LV["SPY"]) | set(LV["VWRP.L"]))
def ffill(lv):
    out, last = {}, None
    for d in DATES:
        if d in lv: last = lv[d]
        if last is not None: out[d] = last
    return out
FL = {t: ffill(v) for t, v in LV.items()}
def rets(t, ds):
    f = FL[t]; return {b: f[b] / f[a] - 1 for a, b in zip(ds, ds[1:]) if a in f and b in f}
def port_series(w, start, end=None):
    ds = [d for d in DATES if d >= start and (end is None or d <= end)]
    rr = {t: rets(t, ds) for t in w}
    out, cov = [], []
    for a, b in zip(ds, ds[1:]):
        avail = {t: x for t, x in w.items() if b in rr[t]}
        s = sum(avail.values())
        out.append((b, sum(x / s * rr[t][b] for t, x in avail.items()) if s else 0.0)); cov.append(s)
    return out, min(cov) if cov else 0
def stats(series, bench=None):
    r = [x for _, x in series]
    lvl, peak, mdd = 1.0, 1.0, 0.0
    for x in r:
        lvl *= 1 + x; peak = max(peak, lvl); mdd = min(mdd, lvl / peak - 1)
    yrs = len(r) / 252
    o = {"ann_return": lvl ** (1 / yrs) - 1, "ann_vol": st.pstdev(r) * math.sqrt(252), "max_drawdown": mdd,
         "worst_21d": min(math.prod(1 + x for x in r[i:i + 21]) - 1 for i in range(0, len(r) - 21))}
    o["return_over_vol"] = o["ann_return"] / o["ann_vol"]
    if bench:
        # weekly (ISO week) returns: London and New York closes are hours apart, so daily co-movement is understated
        from datetime import date as _d
        def wk(ser):
            out = {}
            for d, x in ser:
                k = _d.fromisoformat(d).isocalendar()[:2]; out[k] = out.get(k, 1.0) * (1 + x)
            return {k: v - 1 for k, v in out.items()}
        a, b = wk(series), wk(bench); com = [(a[k], b[k]) for k in a if k in b]
        xs, ys = [c[0] for c in com], [c[1] for c in com]
        o["beta_vs_vwrp_weekly"] = st.covariance(xs, ys) / st.variance(ys); o["corr_vs_vwrp_weekly"] = st.correlation(xs, ys)
        o["tracking_error_vs_vwrp_weekly"] = st.pstdev([x - y for x, y in com]) * math.sqrt(52)
    return o
WINDOWS = {"1y": "2025-10-14", "3y": "2023-10-14", "5y": "2021-10-14", "2022 bear (2022-01-03..2022-12-30)": ("2022-01-03", "2022-12-30")}
# per-name betas to SOXX and QQQ (5y, GBP terms)
def beta(t, b, start="2021-10-14"):
    ds = [d for d in DATES if d >= start]; ra, rb = rets(t, ds), rets(b, ds)
    com = [d for d in ra if d in rb]
    return st.covariance([ra[d] for d in com], [rb[d] for d in com]) / st.variance([rb[d] for d in com]) if len(com) > 60 else None
BETAS = {t: {"soxx": beta(t, "SOXX"), "qqq": beta(t, "QQQ")} for t in LV if t not in ("SOXX", "QQQ")}
res = {"method": {"returns": "Yahoo adjclose (dividends reinvested), converted to GBP daily with GBPUSD=X; VWRP.L already GBP",
                  "benchmark_relative": "beta, correlation and tracking error use weekly returns (London vs New York close timing)", "rebalancing": "constant weights, rebalanced daily (an idealisation); names without history on a date are dropped and the rest renormalised",
                  "windows_end": DATES[-1], "benchmark": "VWRP.L (Vanguard FTSE All-World, GBP line)",
                  "scenario": "linear: portfolio shock = sum(weight x 5y beta to SOXX or QQQ) x index shock; ignores non-linearity and idiosyncratic moves"},
       "portfolios": {}}
for name, w in PORTS.items():
    o = {"weights": {k: round(v, 4) for k, v in sorted(w.items(), key=lambda kv: -kv[1])}, "exposures": exposures(w), "windows": {}}
    for wn, s in WINDOWS.items():
        start, end = (s if isinstance(s, tuple) else (s, None))
        ser, cov = port_series(w, start, end); bser, _ = port_series(V, start, end)
        o["windows"][wn] = {**stats(ser, bser), "min_weight_with_history": cov}
    bs = {k: sum(x * (BETAS.get(t, {}).get(k) or 0) for t, x in w.items()) for k in ("soxx", "qqq")}
    o["scenarios"] = {"semis index -40%": bs["soxx"] * -0.40, "Nasdaq-100 -30%": bs["qqq"] * -0.30, "beta_soxx": bs["soxx"], "beta_qqq": bs["qqq"]}
    res["portfolios"][name] = o
res["name_betas_5y_gbp"] = BETAS
# 1y average pairwise correlation vs 5y for current holdings (data check)
def avgcorr(ts, start):
    ds = [d for d in DATES if d >= start]; rr = {t: rets(t, ds) for t in ts}
    cs = []
    for i, a in enumerate(ts):
        for b in ts[i + 1:]:
            com = [d for d in rr[a] if d in rr[b]]
            if len(com) > 60: cs.append(st.correlation([rr[a][d] for d in com], [rr[b][d] for d in com]))
    return st.mean(cs)
eq = [t for t in A if t not in ("IBTAl_EQ", "SPCX_US_EQ", "TEM_US_EQ")]
res["data_check_avg_pairwise_corr"] = {"1y": avgcorr(eq, "2025-10-14"), "5y": avgcorr(eq, "2021-10-14")}
json.dump(res, open(A_ + "risk_comparison.json", "w"), indent=1, default=str)
for n, o in res["portfolios"].items():
    e = o["exposures"]
    print(f"\n## {n}: holdings {e['holdings']} effN {e['effective_n']:.1f} semis {e['semis_direct']:.1%} (+VWRP lt {e['semis_incl_vwrp_lookthrough_lb']:.1%}) AI-linked {e['ai_linked_total']:.1%} largest {e['largest']:.1%} top5 {e['top5']:.1%} USD {e['usd_underlying']:.0%}")
    print("   sector", {k: round(v, 3) for k, v in e["sector"].items()})
    print("   country", {k: round(v, 3) for k, v in list(e["country"].items())[:5]})
    for wn, s in o["windows"].items():
        print("  ", wn, {k: round(v, 3) for k, v in s.items()})
    print("   scen", {k: round(v, 3) for k, v in o["scenarios"].items()})
print(res["data_check_avg_pairwise_corr"])
