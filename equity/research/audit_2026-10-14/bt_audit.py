"""Audit statistics for the M8 screen backtest. Usage: bt_audit.py ROWS.jsonl OUT.json"""
import sys, json, math, random, statistics as st, time
sys.path.insert(0, "/home/user/agent-skills/equity")
from collections import Counter, defaultdict
from equity import backtest
from equity.prices import _get

rows_path, out_path = sys.argv[1], sys.argv[2]
recs = [json.loads(l) for l in open(rows_path) if l.strip()]
spy = backtest.parse_monthly(_get(backtest.CHART.format(sym="SPY", end=int(time.time()))))
ev = backtest.evaluate(recs, spy)
rows = [r for rec in recs for r in rec["rows"]]
out = {"rows_file": rows_path, "companies": len(recs), "row_count": len(rows),
       "reproduced": {"mean_ic": ev["mean_ic"], "ic_t": ev["ic_t"], "ranked_win_rate": ev["ranked_win_rate"],
                      "pass": ev["pass"], "years": len(ev["years"])}}
Y = ev["years"]
ics = [y["ic"] for y in Y]
n = len(ics)
# what the t tests: one-sample t of mean yearly IC vs 0, years treated as independent
out["ic"] = {"per_year": {y["year"]: y["ic"] for y in Y}, "mean": st.mean(ics), "sd": st.stdev(ics),
             "se": st.stdev(ics) / math.sqrt(n), "t": ev["ic_t"], "df": n - 1,
             "positive_years": sum(i > 0 for i in ics)}
rng = random.Random(1)
boots = sorted(st.mean(rng.choice(ics) for _ in range(n)) for _ in range(20000))
out["ic"]["bootstrap95_mean"] = [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots))]]
out["ic"]["leave_one_out_t"] = {}
for i, y in enumerate(Y):
    rest = ics[:i] + ics[i + 1:]
    out["ic"]["leave_one_out_t"][y["year"]] = st.mean(rest) / (st.stdev(rest) / math.sqrt(len(rest)))
half = n // 2
out["ic"]["first_half_mean"] = st.mean(ics[:half]); out["ic"]["second_half_mean"] = st.mean(ics[half:])
# per-year cross-sectional significance: SE of Spearman ~ 1/sqrt(N-1)
out["ic"]["per_year_z"] = {y["year"]: y["ic"] * math.sqrt(y["scored"] - 1) for y in Y}

def binom_ge(k, n, p=0.5):
    return sum(math.comb(n, j) * p**j * (1 - p)**(n - j) for j in range(k, n + 1))

d = [y["ranked_minus_scored"] for y in Y]
wins = sum(x > 0 for x in d)
out["ranked_minus_scored"] = {"per_year": {y["year"]: y["ranked_minus_scored"] for y in Y}, "wins": wins, "n": n,
                              "binomial_p_one_sided": binom_ge(wins, n), "mean": st.mean(d), "median": st.median(d),
                              "t": st.mean(d) / (st.stdev(d) / math.sqrt(n)),
                              "ranked_share_of_scored": st.mean(y["ranked"] / y["scored"] for y in Y)}
tmb = [y["top_minus_bottom_quintile"] for y in Y]
out["top_minus_bottom"] = {"mean": st.mean(tmb), "t": st.mean(tmb) / (st.stdev(tmb) / math.sqrt(n)),
                           "positive_years": sum(x > 0 for x in tmb)}
# basket vs SPY, annual, no costs
rb = [y["ranked_return"] for y in Y]; sp = [y["spy_return"] for y in Y]; al = [y["scored_return"] for y in Y]
ex = [a - b for a, b in zip(rb, sp)]
def cagr(xs): return math.prod(1 + x for x in xs) ** (1 / len(xs)) - 1
out["vs_spy"] = {"ranked_cagr": cagr(rb), "scored_cagr": cagr(al), "spy_cagr": cagr(sp),
                 "ranked_mean": st.mean(rb), "ranked_sd": st.stdev(rb), "spy_mean": st.mean(sp), "spy_sd": st.stdev(sp),
                 "ranked_mean_over_sd": st.mean(rb) / st.stdev(rb), "spy_mean_over_sd": st.mean(sp) / st.stdev(sp),
                 "excess_mean": st.mean(ex), "excess_t": st.mean(ex) / (st.stdev(ex) / math.sqrt(n)),
                 "years_beat_spy": sum(x > 0 for x in ex),
                 "ranked_worst_year": min(rb), "spy_worst_year": min(sp)}
# coverage
cov = defaultdict(lambda: Counter())
for r in rows:
    cov[r["year"]]["rows"] += 1
    cov[r["year"]]["scored"] += r["total"] is not None
    cov[r["year"]]["eligible"] += bool(r["eligible"]) and r["total"] is not None
out["coverage"] = {y: dict(c) for y, c in sorted(cov.items())}
out["errors"] = Counter((rec["error"] or "").split(":")[0] for rec in recs if rec["error"])
out["no_rows"] = sum(1 for rec in recs if not rec["rows"])
out["templates_scored"] = Counter(r["template"] for r in rows if r["total"] is not None)
out["templates_unscored"] = Counter(r["template"] for r in rows if r["total"] is None)
out["failed_gates_scored"] = Counter(g for r in rows if r["total"] is not None for g in (r["failed_gates"] or []))
# turnover of ranked basket
memb = {y: {r["company_id"] for r in rows if r["year"] == y and r["total"] is not None and r["eligible"]} for y in backtest.YEARS}
to = []
for y in list(backtest.YEARS)[1:]:
    a, b = memb[y - 1], memb[y]
    if a and b:
        to.append(len(b - a) / len(b))
out["ranked_turnover_new_share_mean"] = st.mean(to) if to else None
# regime: SPY up >10% / flat / down
reg = defaultdict(list)
for y in Y:
    k = "spy>+10%" if y["spy_return"] > 0.10 else ("spy<0" if y["spy_return"] < 0 else "spy 0..10%")
    reg[k].append(y)
out["regime"] = {k: {"years": [y["year"] for y in v], "mean_ic": st.mean(y["ic"] for y in v),
                     "mean_ranked_minus_scored": st.mean(y["ranked_minus_scored"] for y in v)} for k, v in reg.items()}
# exploratory (post hoc, not pre-registered): IC of each sub-score, pooled per year mean
subs = defaultdict(list)
for y in backtest.YEARS:
    sc = [r for r in rows if r["year"] == y and r["total"] is not None]
    if len(sc) < 20: continue
    for k in sc[0]["scores"]:
        pairs = [(r["scores"].get(k), r["fwd_return"]) for r in sc if r["scores"].get(k) is not None]
        if len(pairs) >= 20:
            subs[k].append(backtest.spearman([p[0] for p in pairs], [p[1] for p in pairs]))
out["exploratory_subscore_ic"] = {k: {"mean": st.mean(v), "t": st.mean(v) / (st.stdev(v) / math.sqrt(len(v))), "years": len(v)}
                                  for k, v in subs.items() if len(v) > 2}
# size and sector (only if audit fields exist)
if rows and "market_cap" in rows[0]:
    by_size = defaultdict(list); by_sec = defaultdict(list)
    for y in backtest.YEARS:
        sc = [r for r in rows if r["year"] == y and r["total"] is not None and r.get("market_cap")]
        if len(sc) < 30: continue
        caps = sorted(r["market_cap"] for r in sc)
        t1, t2 = caps[len(caps) // 3], caps[2 * len(caps) // 3]
        for lab, grp in (("small", [r for r in sc if r["market_cap"] < t1]), ("mid", [r for r in sc if t1 <= r["market_cap"] < t2]),
                         ("large", [r for r in sc if r["market_cap"] >= t2])):
            ic = backtest.spearman([r["total"] for r in grp], [r["fwd_return"] for r in grp])
            if ic is not None: by_size[lab].append(ic)
        out.setdefault("median_mcap_by_year", {})[y] = caps[len(caps) // 2]
        out.setdefault("large_mcap_over_10bn", {})[y] = sum(c >= 1e10 for c in caps)
    out["ic_by_size_tercile"] = {k: {"mean": st.mean(v), "years": len(v), "t": st.mean(v) / (st.stdev(v) / math.sqrt(len(v)))} for k, v in by_size.items() if len(v) > 2}
    def sec(s):
        try: s = int(s)
        except Exception: return "unknown"
        if 6000 <= s < 6800: return "finance"
        if 3570 <= s <= 3579 or 3670 <= s <= 3679 or 7370 <= s <= 7379 or 3660 <= s <= 3669: return "tech"
        if 2830 <= s <= 2836 or 3840 <= s <= 3851 or 8000 <= s < 8100: return "health"
        if 1300 <= s < 1400 or 2900 <= s < 3000: return "energy"
        if 2000 <= s < 4000: return "other manufacturing"
        if 5000 <= s < 6000: return "trade/retail"
        if 4000 <= s < 5000: return "transport/utilities"
        return "other"
    pooled = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["total"] is not None: pooled[sec(r.get("sic"))][r["year"]].append(r)
    for k, yrs in pooled.items():
        ics_k = [backtest.spearman([r["total"] for r in v], [r["fwd_return"] for r in v]) for v in yrs.values() if len(v) >= 10]
        ics_k = [i for i in ics_k if i is not None]
        by_sec[k] = {"scored_rows": sum(len(v) for v in yrs.values()), "years_with_10plus": len(ics_k),
                     "mean_ic": st.mean(ics_k) if ics_k else None}
    out["ic_by_sector"] = by_sec
json.dump(out, open(out_path, "w"), indent=1, default=str)
print(json.dumps({k: out[k] for k in ("reproduced", "ic", "ranked_minus_scored", "top_minus_bottom", "vs_spy")}, indent=1, default=str)[:4000])
