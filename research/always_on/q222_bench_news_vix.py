"""Q222 bench batch 4: Q217 news-shock gated on VIX>=25 (prereg /mnt/project-files/research/always-on/prereg/Q222.md)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import q217_news_shock as q
from q218_bench_vix import gate
q.N = 440
P, V, spy = q.load(); ev, R, m = q.events(P, V, spy); g = gate(P.index); out = {}
mon, tr, ne = q.run(ev, R, m, spy, cond=g)
out['T1'] = {**q.st(mon), 'events': ne, 'trades': len(tr), 'trade_mean': float(tr.mean()), 'trade_win': float((tr > 0).mean())}
import numpy as np
out['T2_trade_thirds'] = [float(x.mean()) for x in np.array_split(tr, 3)]
for nm, kw in {'T4_20d': dict(hold=20), 'T5_large': dict(large=True), 'T6_cost2': dict(cost=2 * q.COST), 'T6_lag1': dict(lag=1)}.items():
    mo, t_, _ = q.run(ev, R, m, spy, cond=g, **kw); out[nm] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean()), 'trades': len(t_)}
mo, t_, n_ = q.run(ev, R, m, spy, cond=~g); out['complement_vix_lt25'] = {'trade_mean': float(t_.mean()), 'trades': len(t_)}
print(json.dumps(out, indent=1, default=float))
json.dump(out, open('/mnt/project-files/research/always-on/results/Q222.json', 'w'), indent=1, default=float)
