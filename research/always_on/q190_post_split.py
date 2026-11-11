"""Q190 post-split drift (pre-registered: prereg/Q190.md). Data truncated at 2022-12-31."""
import glob, os, sys, numpy as np, pandas as pd
from statistics import NormalDist
D = '/mnt/project-files/research-data/tiingo_daily/'; COST = 0.003
px, dv, sp = {}, {}, {}
for f in glob.glob(D + '*.csv'):
    c = int(os.path.basename(f).split('_')[0])
    if c == 0: continue
    try: x = pd.read_csv(f, usecols=['date', 'adjClose', 'divCash', 'splitFactor'], parse_dates=['date']).set_index('date')
    except ValueError: continue
    x = x[x.index <= '2022-12-31']
    if len(x) < 300: continue
    px[c], dv[c], sp[c] = x.adjClose, x.divCash, x.splitFactor
P = pd.DataFrame(px).sort_index(); R = P.pct_change(fill_method=None); idx = R.index; bench = R.mean(1); Rv = R.values
evu = []
for j, c in enumerate(P.columns):
    s_ = sp[c]
    for t in s_[(s_ > 1) & (s_.index >= '2013-06-01') & (s_.index <= '2021-12-31')].index: evu.append((idx.get_loc(t), j))
def run(ev, H=250, lag=0, cost=COST):
    pos = {}
    for i, j in ev:
        a = i + lag; b = a + H
        if b >= len(idx) or idx[a] < pd.Timestamp("2013-12-20"): continue
        r = Rv[a + 1:b + 1, j].copy()
        if np.isnan(r).any(): continue
        r[0] -= cost / 2; r[-1] -= cost / 2
        for t, rr in zip(idx[a + 1:b + 1], r): pos.setdefault(t, []).append(rr)
    s = pd.Series({t: np.mean(v) for t, v in pos.items()}).sort_index(); ex = s - bench.reindex(s.index)
    m = ex.groupby(ex.index.to_period('M')).sum(); return m[m.index >= pd.Period('2014-01', 'M')]
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
m = run(evu); T = len(m); sr = m.mean() / m.std()
emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
dsr = nd.cdf((sr - emax) * np.sqrt(T - 1)); th = sum(x.mean() > 0 for x in np.array_split(m, 3))
c2 = run(evu, cost=2 * COST).mean() * 12; l1 = run(evu, lag=1).mean() * 12
print(f"Q190 splits {len(evu)} months {T} ex/yr {m.mean()*1200:.2f}% t {sr*np.sqrt(T):.2f} thirds+ {th}/3 cost2 {c2*100:.2f}% lag1 {l1*100:.2f}% DSR {dsr:.3f}")
