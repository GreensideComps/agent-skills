"""Q218 strategy bench batch 1: VIX>=25 gate (prereg /mnt/project-files/research/always-on/prereg/Q218.md).
Data to 2022-12-31 only."""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))

VIX = pd.read_csv('/mnt/project-files/research-data/fred/VIXCLS.csv', parse_dates=['observation_date'],
                  na_values='.').set_index('observation_date').VIXCLS
VIX = VIX[VIX.index <= '2022-12-31'].ffill()


def gate(index):
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return pd.Series((VIX.reindex(idx, method='ffill') >= 25).values, index=index)


def q218a():
    import q216_selloff_overreaction as q
    q.N = 432
    P, V, spy = q.load(); g = gate(P.index)
    out = {}
    mon, tr, ne = q.run(P, V, spy, cond=g)
    out['T1'] = {**q.st(mon), 'events': ne, 'trades': len(tr), 'trade_mean': float(tr.mean()) if len(tr) else None}
    out['T2'] = {k: float(mon[(mon.index >= a) & (mon.index <= b)].sum() * 12 / max(1, ((mon.index >= a) & (mon.index <= b)).sum()))
                 for k, (a, b) in {'2010-14': ('2010-01', '2014-12'), '2015-18': ('2015-01', '2018-12'), '2019-22': ('2019-01', '2022-12')}.items()}
    for nm, kw in {'T4_1d': dict(hold=1), 'T5_large': dict(large=True), 'T6_cost2': dict(cost=2 * q.COST), 'T6_lag1': dict(lag=1)}.items():
        mo, t_, _ = q.run(P, V, spy, cond=g, **kw)
        out[nm] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean()) if len(t_) else None, 'trades': len(t_)}
    return out


def q218b():
    import q203_earn_gapdown as q
    q.N = 433
    g = gate(q.R.index).values
    hi = pd.Series(g[q.e.i], index=q.e.index)
    print('--- Q218b (VIX>=25) ---')
    q.show('T1 full', q.sel & hi)
    q.show('T4 20d hold', q.sel & hi, H=20)
    q.show('T5 mcap>=10bn', q.sel & hi & (q.e.mcap >= 1e10))
    q.show('T6 costs x2', q.sel & hi, cost=2 * q.COST)
    q.show('T6 lag 1 day', q.sel & hi, lag=1)
    q.show('ref: VIX<25', q.sel & ~hi)


if __name__ == '__main__':
    a = q218a(); print('--- Q218a ---'); print(json.dumps(a, indent=1, default=float))
    json.dump(a, open('/mnt/project-files/research/always-on/results/Q218a.json', 'w'), indent=1, default=float)
    q218b()
