"""Q186 lottery avoidance, yearly (pre-registered: prereg/Q186.md). Data truncated at 2022-12-31."""
import glob, os, sys, numpy as np, pandas as pd
from statistics import NormalDist
D = '/mnt/project-files/research-data/tiingo_daily/'; COST = 0.003
px = {}
for f in glob.glob(D + '*.csv'):
    c = int(os.path.basename(f).split('_')[0])
    if c == 0: continue
    try: s = pd.read_csv(f, usecols=['date', 'adjClose'], parse_dates=['date']).set_index('date').adjClose
    except ValueError: continue
    px[c] = s[s.index <= '2022-12-31']
P = pd.DataFrame(px).sort_index(); R = P.pct_change(fill_method=None)
M = P.resample('ME').last().pct_change(fill_method=None)
def run(month=1, cost=COST):
    out, prev_w = [], None
    for y in range(2014, 2023):
        past = R[(R.index >= f'{y-1}-{month:02d}-01') & (R.index < f'{y}-{month:02d}-01')] if month != 1 else R[R.index.year == y - 1]
        ok = past.count() >= 200; mx = past.max()[ok]
        if not len(mx): continue
        q = mx.rank(pct=True); keep = q[q <= 0.8].index; allc = q.index; top = q[q > 0.8].index; bot = q[q <= 0.2].index
        start = pd.Period(f'{y}-{month:02d}', 'M'); per = [p for p in M.index.to_period('M') if start <= p < start + 12 and p <= pd.Period('2022-12', 'M')]
        mm = M.copy(); mm.index = mm.index.to_period('M'); mm = mm.loc[per]
        def bh(cols):
            g = (1 + mm[cols].fillna(0)).cumprod(); v = g.mean(1); return v.pct_change().fillna(v.iloc[0] - 1)
        w = pd.Series(1 / len(keep), keep).reindex(allc, fill_value=0) - pd.Series(1 / len(allc), allc)
        ex = bh(keep) - bh(allc); ex.iloc[0] -= cost / 2 * (w.abs().sum())  # extra turnover vs benchmark, approx
        out.append(pd.DataFrame({'ex': ex, 'ls': bh(bot) - bh(top)}))
    return pd.concat(out)
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
d = run(); m = d.ex; T = len(m); sr = m.mean() / m.std()
emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
dsr = nd.cdf((sr - emax) * np.sqrt(T - 1)); th = sum(x.mean() > 0 for x in np.array_split(m, 3))
c2 = run(cost=2 * COST).ex.mean() * 12; l1 = run(month=2).ex.mean() * 12
print(f"Q186 months {T} ex/yr {m.mean()*1200:.2f}% t {sr*np.sqrt(T):.2f} thirds+ {th}/3 cost2 {c2*100:.2f}% lag(Feb) {l1*100:.2f}% DSR {dsr:.3f} | bottom-top MAX spread {d.ls.mean()*1200:.2f}%/yr t {d.ls.mean()/d.ls.std()*np.sqrt(T):.2f}")
