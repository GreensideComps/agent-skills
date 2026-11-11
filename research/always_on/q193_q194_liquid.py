"""Q193/Q194 liquid-only re-checks (prereg/Q193_Q194.md). Data truncated at 2022-12-31."""
import sys, numpy as np, pandas as pd
from statistics import NormalDist
import q183_ear_drift as q
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
def dsr(m):
    T = len(m); sr = m.mean() / m.std()
    emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
    return nd.cdf((sr - emax) * np.sqrt(T - 1)), sr * np.sqrt(T), sum(x.mean() > 0 for x in np.array_split(m, 3))
R = q.load(); L = q.liquid(R.index); idx = R.index
# ---- Q193
e = q.events(R)
ok = np.array([bool(L.iat[i, L.columns.get_loc(c)]) if c in L.columns else False for c, i in zip(e.cik, e.i)])
top = (e.pct >= 0.8).values & ok
s = q.stats(q.portfolio(R, e, 60, top)); m = s['m']; d, t, th = dsr(m)
c2 = q.stats(q.portfolio(R, e, 60, top, cost=2 * q.COST))['ann']; l1 = q.stats(q.portfolio(R, e, 60, top, lag=1))['ann']
Rv = np.nan_to_num(R.values); spy = Rv[:, list(R.columns).index(0)]; cols = {c: j for j, c in enumerate(R.columns)}
tg = [ (Rv[i+3:i+63, cols[c]] - spy[i+3:i+63]).sum() for c, i in zip(e.cik[top], e.i[top]) if i + 63 < len(idx)]
print(f"Q193 liquid events {top.sum()} (of {(e.pct>=0.8).sum()}) ex/yr {s['ann']}% t {t:.2f} thirds+ {th}/3 cost2 {c2}% lag1 {l1}% DSR {d:.3f} | trade-level gross 60d excess {np.mean(tg)*100:.2f}% (cost 0.30%)")
# ---- Q194
R2 = R.drop(columns=[0]); L2 = L.drop(columns=[0], errors='ignore').reindex(columns=R2.columns).fillna(False)
bench = R2.where(L2).mean(1); Rv2 = R2.values; col = {c: j for j, c in enumerate(R2.columns)}
t4 = pd.read_csv('/mnt/project-files/research-data/insider_trades.csv.gz', usecols=['issuer_cik', 'filed', 'owner_cik', 'code'], parse_dates=['filed'])
t4 = t4[t4.issuer_cik.isin(col) & (t4.filed <= '2022-12-31')].drop_duplicates(['issuer_cik', 'owner_cik', 'filed', 'code']).sort_values('filed')
ev = []
for (iss, own), gg in t4.groupby(['issuer_cik', 'owner_cik']):
    fd = gg.filed.values; isP = (gg.code == 'P').values
    for k in np.nonzero(isP)[0]:
        dd = fd[k]
        if dd < np.datetime64('2016-01-01'): continue
        prior = fd[:k]; priorP = fd[:k][isP[:k]]
        old = ((dd - prior) >= np.timedelta64(365, 'D')) & ((dd - prior) <= np.timedelta64(730, 'D'))
        if old.any() and not ((dd - priorP) <= np.timedelta64(730, 'D')).any(): ev.append((iss, dd))
out, last = [], {}
for iss, dd in sorted(ev, key=lambda x: x[1]):
    if iss in last and dd - last[iss] < np.timedelta64(30, 'D'): continue
    last[iss] = dd; out.append((iss, dd))
def run(H=125, lag=0, cost=q.COST, tl=None):
    pos = {}
    for iss, dd in out:
        a = idx.searchsorted(pd.Timestamp(dd)) + 1 + lag; b = a + H
        if b >= len(idx) or not L2.iat[a, col[iss]]: continue
        r = Rv2[a + 1:b + 1, col[iss]].copy()
        if np.isnan(r).any(): continue
        if tl is not None: tl.append(r.sum() - bench.values[a + 1:b + 1].sum())
        r[0] -= cost / 2; r[-1] -= cost / 2
        for tt, rr in zip(idx[a + 1:b + 1], r): pos.setdefault(tt, []).append(rr)
    s = pd.Series({tt: np.mean(v) for tt, v in pos.items()}).sort_index(); x = s - bench.reindex(s.index)
    m = x.groupby(x.index.to_period('M')).sum(); return m[m.index >= pd.Period('2016-01', 'M')]
tl = []; m = run(tl=tl); d, t, th = dsr(m)
print(f"Q194 liquid events {len(tl)} ex/yr {m.mean()*1200:.2f}% t {t:.2f} thirds+ {th}/3 cost2 {run(cost=2*q.COST).mean()*1200:.2f}% lag1 {run(lag=1).mean()*1200:.2f}% DSR {d:.3f} | trade-level gross 125d excess {np.mean(tl)*100:.2f}%")
