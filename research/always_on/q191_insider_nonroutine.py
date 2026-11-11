"""Q191 non-routine insider purchases, large caps (pre-registered: prereg/Q191.md). Data truncated at 2022-12-31."""
import sys, numpy as np, pandas as pd
from statistics import NormalDist
from q183_ear_drift import load, COST
R = load(); R.pop(0); idx = R.index; bench = R.mean(1); Rv = R.values; col = {c: j for j, c in enumerate(R.columns)}
t = pd.read_csv('/mnt/project-files/research-data/insider_trades.csv.gz', usecols=['issuer_cik', 'filed', 'owner_cik', 'code'], parse_dates=['filed'])
t = t[t.issuer_cik.isin(col) & (t.filed <= '2022-12-31')].drop_duplicates(['issuer_cik', 'owner_cik', 'filed', 'code']).sort_values('filed')
evn, eva = [], []
for (iss, own), g in t.groupby(['issuer_cik', 'owner_cik']):
    fd = g.filed.values; isP = (g.code == 'P').values
    for k in np.nonzero(isP)[0]:
        d = fd[k]
        if d < np.datetime64('2016-01-01'): continue
        eva.append((iss, d))
        prior = fd[:k]; priorP = fd[:k][isP[:k]]
        old = ((d - prior) >= np.timedelta64(365, 'D')) & ((d - prior) <= np.timedelta64(730, 'D'))
        if old.any() and not ((d - priorP) <= np.timedelta64(730, 'D')).any(): evn.append((iss, d))
def dedup(ev):
    out, last = [], {}
    for iss, d in sorted(ev, key=lambda x: x[1]):
        if iss in last and d - last[iss] < np.timedelta64(30, 'D'): continue
        last[iss] = d; out.append((iss, d))
    return out
evn, eva = dedup(evn), dedup(eva)
def run(ev, H=125, lag=0, cost=COST):
    pos = {}
    for iss, d in ev:
        a = idx.searchsorted(pd.Timestamp(d)) + 1 + lag; b = a + H
        if b >= len(idx): continue
        r = Rv[a + 1:b + 1, col[iss]].copy()
        if np.isnan(r).any(): continue
        r[0] -= cost / 2; r[-1] -= cost / 2
        for tt, rr in zip(idx[a + 1:b + 1], r): pos.setdefault(tt, []).append(rr)
    s = pd.Series({tt: np.mean(v) for tt, v in pos.items()}).sort_index(); ex = s - bench.reindex(s.index)
    m = ex.groupby(ex.index.to_period('M')).sum(); return m[m.index >= pd.Period('2016-01', 'M')]
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
m = run(evn); T = len(m); sr = m.mean() / m.std()
emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
dsr = nd.cdf((sr - emax) * np.sqrt(T - 1)); th = sum(x.mean() > 0 for x in np.array_split(m, 3))
c2 = run(evn, cost=2 * COST).mean() * 12; l1 = run(evn, lag=1).mean() * 12; al = run(eva)
print(f"Q191 non-routine events {len(evn)} (all buys {len(eva)}) months {T} ex/yr {m.mean()*1200:.2f}% t {sr*np.sqrt(T):.2f} thirds+ {th}/3 cost2 {c2*100:.2f}% lag1 {l1*100:.2f}% DSR {dsr:.3f} | all-buys control {al.mean()*1200:.2f}%/yr t {al.mean()/al.std()*np.sqrt(len(al)):.2f}")
