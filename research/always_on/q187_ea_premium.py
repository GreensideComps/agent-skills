"""Q187 earnings-announcement premium (pre-registered: prereg/Q187.md). Data truncated at 2022-12-31."""
import sys, numpy as np, pandas as pd
from statistics import NormalDist
from q183_ear_drift import load, D, COST
R = load(); spy = R.pop(0); idx = R.index; bench = R.mean(1)
k = pd.read_csv(D + '8k_items_large_2013_2026.csv.gz', parse_dates=['date'])
k = k[k['items'].astype(str).str.contains('2.02') & k.cik.isin(R.columns) & (k.date <= '2022-12-31')].drop_duplicates(['cik', 'date'])
act = {c: np.sort(g.date.values) for c, g in k.groupby('cik')}
col = {c: j for j, c in enumerate(R.columns)}; Rv = R.values
def run(lag=0, cost=COST):
    pos = {}; hit = []
    for c, ds in act.items():
        for d in ds:
            e = idx.searchsorted(pd.Timestamp(d) + pd.Timedelta(days=364))
            a, b = e - 6 + lag, e + 1
            if a < 1 or b >= len(idx) or idx[a] < pd.Timestamp('2014-01-01'): continue
            if ds[-1] > d + np.timedelta64(300, 'D'):
                near = ds[np.argmin(np.abs(ds - (d + np.timedelta64(364, 'D'))))]
                hit.append(abs(idx.searchsorted(near) - e) <= 5)
            r = Rv[a + 1:b + 1, col[c]].copy()
            if np.isnan(r).any(): continue
            r[0] -= cost / 2; r[-1] -= cost / 2
            for t, rr in zip(idx[a + 1:b + 1], r): pos.setdefault(t, []).append(rr)
    s = pd.Series({t: np.mean(v) for t, v in pos.items()}).sort_index()
    ex = s - bench.reindex(s.index)
    return ex.groupby(ex.index.to_period('M')).sum(), np.mean(hit)
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
m, hit = run(); T = len(m); sr = m.mean() / m.std()
emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
dsr = nd.cdf((sr - emax) * np.sqrt(T - 1)); th = sum(x.mean() > 0 for x in np.array_split(m, 3))
c2 = run(cost=2 * COST)[0].mean() * 12; l1 = run(lag=1)[0].mean() * 12; g0 = run(cost=0)[0].mean() * 12
print(f"Q187 months {T} ex/yr {m.mean()*1200:.2f}% t {sr*np.sqrt(T):.2f} thirds+ {th}/3 cost2 {c2*100:.2f}% lag1 {l1*100:.2f}% gross {g0*100:.2f}% DSR {dsr:.3f} | expected-date hit rate {hit*100:.0f}%")
