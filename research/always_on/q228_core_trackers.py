"""Q228: S&P 500 / Nasdaq-100 / developed-only vs All-World (VWRP) as the core holding, GBP, after fees.
Pre-registration: /mnt/project-files/research/always-on/prereg/Q228.md. Data to 2022-12 only (holdout untouched)."""
import csv, gzip, json, math, statistics as st, sys
D = "/mnt/project-files/research-data/"
END = "2022-12"

def french(fn):
    out = {}
    for line in open(D + "french/" + fn, encoding="latin-1"):
        p = [x.strip() for x in line.split(",")]
        if "Annual" in line: break
        if len(p) > 2 and p[0].isdigit() and len(p[0]) == 6:
            m = p[0][:4] + "-" + p[0][4:]
            v = float(p[1]); rf = float(p[-1])
            if v > -99: out[m] = (v + rf) / 100
    return out

def fred(fn):
    out = {}
    for r in csv.DictReader(open(D + "fred/" + fn)):
        k = [x for x in r if x != "observation_date"][0]
        if r[k] not in ("", "."): out[r["observation_date"][:7]] = float(r[k])
    return out

us = french("F-F_Research_Data_Factors.csv")
dev = french("Developed_3_Factors.csv")
exus = french("Developed_ex_US_3_Factors.csv")
em = french("Emerging_5_Factors.csv")
fx = fred("DEXUSUK_m_eop_to2022.csv")  # USD per GBP, month-end
ndx_px = fred("NASDAQ100_m_eop_to2022.csv")
months = sorted(m for m in dev if "1990-07" <= m <= END and m in us and m in em and m in exus)
def prev(m):
    y, mo = int(m[:4]), int(m[5:])
    return f"{y-1}-12" if mo == 1 else f"{y}-{mo-1:02d}"
ndx = {m: ndx_px[m] / ndx_px[prev(m)] - 1 + 0.008 / 12 for m in months}
fee = {"ALLW": 0.0019, "US": 0.0007, "NDX": 0.0030, "DEV": 0.0020, "EXUS": 0.0020, "MIX": 0.0013}
usd = {"ALLW": {m: 0.9 * dev[m] + 0.1 * em[m] for m in months}, "US": us, "NDX": ndx, "DEV": dev, "EXUS": exus}
usd["MIX"] = {m: 0.5 * us[m] + 0.5 * usd["ALLW"][m] for m in months}
fxr = {m: fx[prev(m)] / fx[m] - 1 for m in months}  # GBP return of holding 1 USD
gbp = {k: {m: (1 + v[m]) * (1 + fxr[m]) - 1 - fee[k] / 12 for m in months} for k, v in usd.items()}
usdnet = {k: {m: v[m] - fee[k] / 12 for m in months} for k, v in usd.items()}

def stats(series, ms):
    r = [series[m] for m in ms]
    w = 1; peak = 1; mdd = 0; path = []
    for x in r:
        w *= 1 + x; peak = max(peak, w); mdd = min(mdd, w / peak - 1); path.append(w)
    yrs = len(r) / 12
    w12 = min((path[i] / (path[i-12] if i >= 12 else 1) - 1) for i in range(11, len(r))) if len(r) >= 12 else None
    return {"cagr": w ** (1 / yrs) - 1, "vol": st.pstdev(r) * math.sqrt(12), "mdd": mdd, "worst12": w12}

def excess(a, b, ms):
    d = [a[m] - b[m] for m in ms]
    t = st.mean(d) / (st.stdev(d) / math.sqrt(len(d)))
    ca = stats(a, ms)["cagr"]; cb = stats(b, ms)["cagr"]
    return {"ex_cagr": ca - cb, "t": t, "n": len(d)}

def sub(lo, hi): return [m for m in months if lo <= m <= hi]
P = {"full 1990-07..2022-12": months, "1990s 1990-07..1999-12": sub("1990-07", "1999-12"),
     "2000s 2000-01..2009-12": sub("2000-01", "2009-12"), "2010-01..2022-12": sub("2010-01", "2022-12"),
     "2007-01..2022-12": sub("2007-01", "2022-12")}
third = len(months) // 3
T = [months[:third], months[third:2*third], months[2*third:]]
res = {"periods": {}, "thirds": {}, "rolling10": {}, "usd": {}, "bullbear": {}, "drag05": {}}
for name, ms in P.items():
    res["periods"][name] = {k: {**stats(gbp[k], ms), **({} if k == "ALLW" else excess(gbp[k], gbp["ALLW"], ms))} for k in gbp}
for k in gbp:
    if k == "ALLW": continue
    res["thirds"][k] = [excess(gbp[k], gbp["ALLW"], ms)["ex_cagr"] for ms in T]
    res["usd"][k] = excess(usdnet[k], usdnet["ALLW"], months)
    wins = 0; tot = 0
    for i in range(0, len(months) - 120 + 1):
        ms = months[i:i+120]; tot += 1
        wins += stats(gbp[k], ms)["cagr"] > stats(gbp["ALLW"], ms)["cagr"]
    res["rolling10"][k] = {"share_beat": wins / tot, "n": tot}
    res["drag05"][k] = res["periods"]["full 1990-07..2022-12"][k]["ex_cagr"] - 0.005
# bull/bear by All-World (GBP) vs its 10-month average, known at prior month-end
lvl = {}; w = 1
for m in months: w *= 1 + gbp["ALLW"][m]; lvl[m] = w
bull, bear = [], []
for i, m in enumerate(months[10:], start=10):
    pm = months[i-1]; avg = st.mean(lvl[x] for x in months[i-10:i])
    (bull if lvl[pm] >= avg else bear).append(m)
for k in gbp:
    if k == "ALLW": continue
    res["bullbear"][k] = {"bull": excess(gbp[k], gbp["ALLW"], bull), "bear": excess(gbp[k], gbp["ALLW"], bear)}
# proxy check vs actual VWRL/VWRP (GBP) 2012-06..2022-12
bm = {}
with gzip.open(D + "edge/benchmarks_daily_gbp_to_2022.csv.gz", "rt") as f:
    for r in csv.DictReader(f):
        v = r["VWRL"] or r["VWRP"]
        if v: bm[r["date"][:7]] = float(v)  # last close in month (VWRL is dist, adjclose = total return)
pm = [m for m in months if m >= "2012-07" and prev(m) in bm and m in bm]
act = {m: bm[m] / bm[prev(m)] - 1 for m in pm}
res["proxy_check"] = {"months": len(pm), "actual_cagr": stats(act, pm)["cagr"], "proxy_cagr": stats(gbp["ALLW"], pm)["cagr"],
                      "corr": st.correlation([act[m] for m in pm], [gbp["ALLW"][m] for m in pm])}
# verdicts
full = res["periods"]["full 1990-07..2022-12"]; late = res["periods"]["2007-01..2022-12"]
res["verdict"] = {}
for k, tag in [("US", "Q228a"), ("NDX", "Q228b"), ("DEV", "Q228c")]:
    ok = (full[k]["ex_cagr"] > 0 and full[k]["t"] >= 3.5 and late[k]["ex_cagr"] > 0 and late[k]["t"] >= 2.5
          and sum(x > 0 for x in res["thirds"][k]) >= 2 and full[k]["mdd"] >= full["ALLW"]["mdd"] - 0.05)
    res["verdict"][tag] = "PASS" if ok else "FAIL"
json.dump(res, open(sys.argv[1], "w"), indent=1)
