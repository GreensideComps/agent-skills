"""Q192 large-cap gap-down reversal (pre-registered: prereg/Q192.md). Data truncated at 2022-12-31."""
import glob, os, sys, numpy as np, pandas as pd
from statistics import NormalDist
D = '/mnt/project-files/research-data/'; COST = 0.003
op, cl, vo = {}, {}, {}
for f in glob.glob(D + 'tiingo_daily/*.csv'):
    c = int(os.path.basename(f).split('_')[0])
    try: x = pd.read_csv(f, usecols=['date', 'adjOpen', 'adjClose', 'adjVolume'], parse_dates=['date']).set_index('date')
    except ValueError: continue
    x = x[(x.index <= '2022-12-31')]
    if len(x) < 300: continue
    op[c], cl[c], vo[c] = x.adjOpen, x.adjClose, x.adjVolume
O = pd.DataFrame(op).sort_index(); C = pd.DataFrame(cl).reindex(O.index)
V = pd.DataFrame(vo).reindex(O.index); V.pop(0)
spy_oc = C.pop(0) / O.pop(0) - 1
liq = ((C * V).rolling(20).median().shift(1) >= 1e7)
LIQ = len(sys.argv) > 2 and sys.argv[2] == 'liquid'
if LIQ: print('liquidity filter on')
gap = O / C.shift(1) - 1; oc = C / O - 1; co = O.shift(-1) / C - 1
k = pd.read_csv(D + '8k_items_large_2013_2026.csv.gz', parse_dates=['date']); k = k[k.cik.isin(O.columns)]
news = pd.DataFrame(False, index=O.index, columns=O.columns)
for c, d in zip(k.cik, k.date):
    i = O.index.searchsorted(d)
    for j in (i, i + 1):
        if j < len(O.index): news.iat[j, O.columns.get_loc(c)] = True
ev = (gap <= -0.04) & (O.index >= '2014-01-01')[:, None]
if LIQ: ev = ev & liq
def monthly(mask, ret, bench, cost=COST):
    r = ret.where(mask) - cost; d = r.mean(1).dropna() - bench.reindex(r.mean(1).dropna().index)
    return d.groupby(d.index.to_period('M')).sum(), r.stack().mean() + cost, int(mask.sum().sum())
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
m, avg, n = monthly(ev & ~news, oc, spy_oc); T = len(m); sr = m.mean() / m.std()
emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
dsr = nd.cdf((sr - emax) * np.sqrt(T - 1)); th = sum(x.mean() > 0 for x in np.array_split(m, 3))
c2 = monthly(ev & ~news, oc, spy_oc, cost=2 * COST)[0].mean() * 12
spy_co = (pd.Series(0.0, index=O.index))  # overnight benchmark ~0 relative; report raw
l1 = monthly(ev & ~news, co, spy_co)[0].mean() * 12
nm, navg, nn = monthly(ev & news, oc, spy_oc)
print(f"Q192 no-news gaps {n} months {T} ex/yr {m.mean()*100*12:.2f}% t {sr*np.sqrt(T):.2f} thirds+ {th}/3 cost2 {c2*100:.2f}% overnight-hold {l1*100:.2f}% DSR {dsr:.3f} | gross per trade {avg*100:.3f}% | news gaps {nn}: gross per trade {navg*100:.3f}%")
