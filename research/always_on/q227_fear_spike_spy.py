"""Q227 buy SPY after a VIX fear spike (prereg /mnt/project-files/research/always-on/prereg/Q227.md). Data to 2022-12-31."""
import json, math, numpy as np, pandas as pd
from q218_bench_vix import VIX
COST = 0.003
s = pd.read_csv('/mnt/project-files/research-data/tiingo_etf/SPY.csv', usecols=['date', 'adjClose'], parse_dates=['date']).set_index('date').adjClose
if s.index.tz is not None: s.index = s.index.tz_localize(None)
s = s[s.index <= '2022-12-31']; v = VIX.reindex(s.index, method='ffill'); vc = v.pct_change()
def run(H=10, lag=0, cost=COST, lvl=25):
    ev, last = [], -99
    for i in range(1, len(s) - H - lag - 1):
        if v.iloc[i] >= lvl and vc.iloc[i] >= 0.20 and i - last >= 10:
            last = i; a = i + lag; ev.append((s.index[i], s.iloc[a + H] / s.iloc[a] - 1 - 2 * cost))
    r = pd.Series([x[1] for x in ev], index=[x[0] for x in ev])
    base = (s.shift(-H) / s - 1).dropna().mean()
    d = r - base; t = d.mean() / (d.std() / math.sqrt(len(d))) if len(d) > 1 else float('nan')
    return {'events': len(r), 'mean': float(r.mean()), 'base': float(base), 'excess': float(d.mean()), 't': float(t), 'hit': float((r > 0).mean()), 'thirds': [float(x.mean()) for x in np.array_split(d.values, 3)], 'dates': [str(x.date()) for x in r.index]}
out = {'T1': run(), 'T3_vix30': run(lvl=30), 'T4_20d': run(H=20), 'T5_2d': run(H=2), 'T6_lag1': run(lag=1), 'T6_cost2': run(cost=2 * COST)}
for k, x in out.items(): print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in x.items() if a != 'dates'})
print(out['T1']['dates'])
json.dump(out, open('/mnt/project-files/research/always-on/results/Q227.json', 'w'), indent=1)
