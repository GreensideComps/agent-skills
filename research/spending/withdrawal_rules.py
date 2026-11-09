"""Spending-money (withdrawal) rules tested on history. Planning study, not an edge trial (does not add to N).
Data (all free, already in research-data, cut at 2022-12 so the 2023-26 holdout is untouched):
  World: VWRP proxy = 90% Ken French Developed + 10% Emerging, USD -> GBP via FRED month-end, minus 0.19%/yr OCF (as Q228).
  Long run: Shiller S&P 500 real total return 1871-2022 (US only, so flattering; used as a stress test across 1929, 1966-82).
Inflation: US CPI (FRED CPIAUCSL for the world test, Shiller CPI for the long run). No UK CPI in the free data; stated as a caveat.
Money is taken out once a year in January (sell VWRP, move to cash). No tax (ISA)."""
import csv, json, math, statistics as st, sys
import xlrd
D = "/mnt/project-files/research-data/"

def french(fn):
    out = {}
    for line in open(D + "french/" + fn, encoding="latin-1"):
        p = [x.strip() for x in line.split(",")]
        if "Annual" in line: break
        if len(p) > 2 and p[0].isdigit() and len(p[0]) == 6:
            v = float(p[1]); rf = float(p[-1])
            if v > -99: out[p[0][:4] + "-" + p[0][4:]] = (v + rf) / 100
    return out
def fred(fn):
    out = {}
    for r in csv.DictReader(open(D + "fred/" + fn)):
        k = [x for x in r if x != "observation_date"][0]
        if r[k] not in ("", "."): out[r["observation_date"][:7]] = float(r[k])
    return out
def prev(m):
    y, mo = int(m[:4]), int(m[5:]); return f"{y-1}-12" if mo == 1 else f"{y}-{mo-1:02d}"

# ---------- yearly series: (nominal return, inflation) per calendar year ----------
dev = french("Developed_3_Factors.csv"); em = french("Emerging_5_Factors.csv")
fx = fred("DEXUSUK_m_eop_to2022.csv"); cpi = fred("CPIAUCSL.csv")
world = {}
for y in range(1991, 2023):
    g = 1
    for mo in range(1, 13):
        m = f"{y}-{mo:02d}"
        usd = 0.9 * dev[m] + 0.1 * em[m]
        g *= (1 + usd) * (fx[prev(m)] / fx[m]) * (1 - 0.0019 / 12)
    world[y] = (g - 1, cpi[f"{y}-12"] / cpi[f"{y-1}-12"] - 1)

sh = xlrd.open_workbook(D + "shiller/ie_data.xls").sheet_by_name("Data")
tr = {}; sc = {}
for i in range(8, sh.nrows):
    r = sh.row_values(i)
    if not isinstance(r[0], float): continue
    ds = f"{r[0]:.2f}"; y, mo = int(ds[:4]), int(ds[5:7])
    if mo == 12 and isinstance(r[9], float): tr[y] = r[9]; sc[y] = r[4]  # Dec real TR index, Dec CPI
us = {}
for y in range(1872, 2023):
    if y in tr and y - 1 in tr:
        real = tr[y] / tr[y - 1]; infl = sc[y] / sc[y - 1]
        us[y] = (real * infl - 1, infl - 1)

# ---------- rules: return the amount to take this January (nominal) ----------
def simulate(series, start, years, rule, rate):
    bal = 100.0; idx = 1.0  # price index since start
    hist = []; first = None; last = None; vals = [bal]; out_real = []
    hw = 100.0
    for k in range(years):
        y = start + k
        if rule == "fixed_real":       # X% of the starting pot, raised with inflation every year
            take = rate * 100 * idx
        elif rule == "pct":            # X% of whatever the pot is worth this January
            take = rate * bal
        elif rule == "smoothed":       # endowment style: X% of the average of the last 3 January values
            take = rate * st.mean(vals[-3:])
        elif rule == "guardrails":     # Guyton-Klinger style: fixed real, but cut 10% if rate drifts >20% above start rate, raise 10% if >20% below
            if last is None: take = rate * bal
            else:
                take = last * (1 + infl_prev if not down_prev else 1)
                cur = take / bal if bal > 0 else 9
                if cur > rate * 1.2: take *= 0.9
                elif cur < rate * 0.8: take *= 1.1
        elif rule == "gains_over_line": # keep the real starting pot plus 10% buffer; take only what is above it
            line = 110 * idx; take = max(0.0, bal - line)
        take = min(take, bal)
        bal -= take; out_real.append(take / idx); last = take
        r, infl = series[y]
        bal *= 1 + r; idx *= 1 + infl
        infl_prev = infl; down_prev = r < 0
        vals.append(bal)
    out = out_real
    nz = [x for x in out]
    cuts = [out[i] / out[i - 1] - 1 for i in range(1, len(out)) if out[i - 1] > 0]
    return {"ran_out": bal <= 0.01, "end_real_pct_of_start": bal / idx,
            "total_taken_real": sum(out), "avg_take_real": st.mean(out), "min_take_real": min(out),
            "max_take_real": max(out), "years_zero": sum(1 for x in out if x < 0.01),
            "worst_cut": min(cuts) if cuts else 0.0}

RULES = [("fixed_real", 0.03), ("fixed_real", 0.04), ("fixed_real", 0.05),
         ("pct", 0.03), ("pct", 0.04), ("pct", 0.05),
         ("smoothed", 0.03), ("smoothed", 0.035), ("smoothed", 0.04), ("guardrails", 0.045), ("gains_over_line", 0)]

def table(series, years, starts):
    res = {}
    for rule, rate in RULES:
        runs = [simulate(series, s, years, rule, rate) for s in starts]
        name = f"{rule}_{rate*100:g}%" if rate else rule
        res[name] = {
            "windows": len(runs),
            "ran_out_share": st.mean(r["ran_out"] for r in runs),
            "avg_yearly_take_real_median": st.median(r["avg_take_real"] for r in runs),
            "lowest_year_take_worst": min(r["min_take_real"] for r in runs),
            "end_real_median": st.median(r["end_real_pct_of_start"] for r in runs),
            "end_real_worst": min(r["end_real_pct_of_start"] for r in runs),
            "end_below_start_share": st.mean(r["end_real_pct_of_start"] < 100 for r in runs),
            "years_with_nothing_avg": st.mean(r["years_zero"] for r in runs),
            "worst_one_year_cut": min(r["worst_cut"] for r in runs)}
    return res

out = {
  "world_gbp_full_1991_2022": {n: simulate(world, 1991, 32, r, x) for (r, x) in RULES for n in [f"{r}_{x*100:g}%" if x else r]},
  "world_gbp_10y_windows": table(world, 10, list(range(1991, 2014))),
  "world_gbp_20y_windows": table(world, 20, list(range(1991, 2004))),
  "us_1872_2022_30y_windows": table(us, 30, list(range(1872, 1994))),
  "data": {"world_cagr_nominal": math.prod(1 + world[y][0] for y in world) ** (1 / len(world)) - 1,
           "world_cagr_real": math.prod((1 + world[y][0]) / (1 + world[y][1]) for y in world) ** (1 / len(world)) - 1,
           "us_real_cagr_1872_2022": math.prod((1 + us[y][0]) / (1 + us[y][1]) for y in us) ** (1 / len(us)) - 1,
           "world_years": [min(world), max(world)], "worst_world_year": min(world.items(), key=lambda kv: kv[1][0])}}
json.dump(out, open(sys.argv[1], "w"), indent=1)
