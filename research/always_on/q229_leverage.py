"""Q229: leveraged daily-reset US ETPs and a ~1.5x mix vs VWRP. Prereg: /mnt/project-files/research/always-on/prereg/Q229.md"""
import json, math, statistics as st, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import q228_core_trackers as q  # reuses its loaded series (runs its main on import; output path arg ignored there)
D = q.D
daily = []
for line in open(D + "french/F-F_Research_Data_Factors_daily.csv"):
    p = [x.strip() for x in line.split(",")]
    if len(p) == 5 and p[0].isdigit() and len(p[0]) == 8 and p[0] <= "20221231":
        daily.append((p[0][:4] + "-" + p[0][4:6], (float(p[1]) + float(p[4])) / 100, float(p[4]) / 100))

def lev_monthly(L, fee=0.0075, spread=0.005):
    out = {}; v = 1.0; dead = False; cur = None; start = 1.0; minv = 1.0; peak = 1.0; mdd = 0.0
    for m, r, rf in daily:
        if m != cur:
            if cur is not None: out[cur] = v / start - 1 if start > 0 else 0.0
            cur = m; start = v
        if not dead:
            d = L * r - (L - 1) * (rf + spread / 252) - fee / 252
            v *= 1 + d
            if v <= 0.05 * peak and v <= 0.0001 or 1 + d <= 0: v = 0.0; dead = True
        peak = max(peak, v); mdd = min(mdd, v / peak - 1 if peak else -1)
    out[cur] = v / start - 1 if start > 0 else 0.0
    return out, mdd

ms = q.months
gbp = {"ALLW": q.gbp["ALLW"], "US1x": q.gbp["US"]}
usd_full = {}
for L in (2, 3):
    lm, mdd_full = lev_monthly(L)
    usd_full[f"{L}x"] = mdd_full
    gbp[f"US{L}x"] = {m: (1 + lm[m]) * (1 + q.fxr[m]) - 1 for m in ms}
    lm2, _ = lev_monthly(L, spread=0.01)
    gbp[f"US{L}x_spread1"] = {m: (1 + lm2[m]) * (1 + q.fxr[m]) - 1 for m in ms}
# mixes, rebalanced each April
def mix(w3):
    out = {}; a = 1 - w3; b = w3
    for m in ms:
        if m.endswith("-04"):
            t = a + b; a, b = t * (1 - w3), t * w3
        t0 = a + b
        a *= 1 + gbp["ALLW"][m]; b *= 1 + gbp["US3x"][m]
        out[m] = (a + b) / t0 - 1
    return out
gbp["MIX150"] = mix(0.25); gbp["MIX125"] = mix(0.125)
# full-history USD wipe-out check for the 1.5x idea: 75% US1x + 25% US3x (no global series pre-1990)
res = {"periods": {}, "thirds": {}, "rolling10": {}, "usd_1926_maxdd": usd_full, "spread1": {}}
P = {"full": ms, "2000-2009": [m for m in ms if "2000-01" <= m <= "2009-12"], "2007-2022": [m for m in ms if m >= "2007-01"],
     "2010-2022": [m for m in ms if m >= "2010-01"]}
for n, pm in P.items():
    res["periods"][n] = {k: {**q.stats(v, pm), **({} if k == "ALLW" else q.excess(v, gbp["ALLW"], pm))} for k, v in gbp.items()}
th = len(ms) // 3; T = [ms[:th], ms[th:2*th], ms[2*th:]]
for k in gbp:
    if k == "ALLW": continue
    res["thirds"][k] = [q.excess(gbp[k], gbp["ALLW"], t)["ex_cagr"] for t in T]
    w = sum(q.stats(gbp[k], ms[i:i+120])["cagr"] > q.stats(gbp["ALLW"], ms[i:i+120])["cagr"] for i in range(len(ms) - 119))
    res["rolling10"][k] = w / (len(ms) - 119)
F = res["periods"]["full"]; LT = res["periods"]["2007-2022"]
res["verdict"] = {}
for k, tag in [("US2x", "Q229a"), ("US3x", "Q229b"), ("MIX150", "Q229c")]:
    wiped = usd_full.get(k[2:], -0.5) <= -0.95 if k != "MIX150" else False
    ok = (F[k]["ex_cagr"] > 0 and F[k]["t"] >= 3.5 and LT[k]["t"] >= 2.5 and sum(x > 0 for x in res["thirds"][k]) >= 2
          and F[k]["mdd"] > -0.60 and not wiped)
    res["verdict"][tag] = "PASS" if ok else "FAIL"
json.dump(res, open(sys.argv[2], "w"), indent=1)
