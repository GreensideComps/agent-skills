"""Q223 bench batch 5: single-stock -7% day (vs SPY) rebound gated on VIX>=25 (prereg /mnt/project-files/research/always-on/prereg/Q223.md)."""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import q217_news_shock as q
from q218_bench_vix import gate
q.N = 441
P, V, spy = q.load()   # 2012-10 .. 2022-12 window from q217
R = P.pct_change(fill_method=None); m = spy.pct_change(); rel = R.sub(m, axis=0)
liq = V.rolling(20).median().shift(1) >= 1e7
ev, last = [], {}
A = rel.values; L = liq.values
for i in range(len(P.index)):
    for j in np.where((A[i] <= -0.07) & L[i])[0]:
        c = P.columns[j]
        if c in last and i - last[c] < 10: continue
        last[c] = i; ev.append((i - 1, c, float(V[c].iloc[max(0, i - 20):i].median())))  # run() enters at i-1+1 = event-day close
ev.sort()
g = gate(P.index); out = {}
def gi(c): return pd.Series([bool(c.iloc[e[0] + 1]) for e in ev])
mon, tr, ne = q.run(ev, R, m, spy, cond=g.shift(-1).fillna(False))
yrs = pd.Series([P.index[e[0] + 1].year for e in ev if g.iloc[e[0] + 1]])
out['T1'] = {**q.st(mon), 'events': ne, 'trades': len(tr), 'trade_mean': float(tr.mean()), 'median': float(np.median(tr)), 'top_year_share': float(yrs.value_counts(normalize=True).iloc[0]), 'top_year': int(yrs.value_counts().index[0])}
out['T2_trade_thirds'] = [float(x.mean()) for x in np.array_split(tr, 3)]
gs = g.shift(-1).fillna(False)
for nm, kw in {'T4_1d': dict(hold=1), 'T5_large': dict(large=True), 'T6_cost2': dict(cost=2 * q.COST), 'T6_lag1': dict(lag=1)}.items():
    mo, t_, _ = q.run(ev, R, m, spy, cond=gs, **kw); out[nm] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean()), 'trades': len(t_)}
mo, t_, _ = q.run(ev, R, m, spy, cond=~gs); out['T3_complement'] = {'trade_mean': float(t_.mean()), 'trades': len(t_), 'ann': float(mo.mean() * 12)}
print(json.dumps(out, indent=1, default=float))
json.dump(out, open('/mnt/project-files/research/always-on/results/Q223.json', 'w'), indent=1, default=float)
