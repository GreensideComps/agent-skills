"""Q239 sell-rule batch 6: longer holds (prereg /mnt/project-files/research/always-on/prereg/Q239.md)."""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
import q238_holds_trims as h
import pick1 as p1
COST = 0.003


def p1_rows(H=19):
    df = p1.load(); df = df[df['month'] <= '2022-12-31']
    by = {m: g for m, g in df.groupby('month')}; months = sorted(by)
    rows = []
    for m in months:
        if m.month != 12 or m < pd.Timestamp('2014-12-31'): continue
        fut = [mm for mm in months if mm > m]
        if len(fut) < H: continue
        ms = [m] + fut[:H - 1]
        R = pd.DataFrame({k: p1.universe(by[x]).set_index('cik')['ret_next'] for k, x in enumerate(ms)})
        ew = R.mean()
        for c in p1.pick(p1.universe(by[m]))['cik']:
            if c not in R.index: continue
            x = R.loc[c].fillna(0.0).values
            rows.append({'t': m, 'path': list(np.cumprod(1 + x) - 1), 'bench': list(np.cumprod(1 + ew.values) - 1)})
    return rows


if __name__ == '__main__':
    bb = [r for r in h.bb_rows(13) if all(pd.notna(r['path'][:13]))]
    t = [r['t'] for r in bb]
    q.summ('Q239a_bb12', h.hold_d(bb, 6, 12), t, 473, {'costs2_mean_d_pct': float(h.hold_d(bb, 6, 12, 2 * COST).mean() * 100),
           'lag_mean_d_pct': float(h.hold_d(bb, 6, 12, lag=1).mean() * 100), 'n_rows': len(bb)})
    pr = p1_rows()
    t = [r['t'] for r in pr]
    q.summ('Q239b_p1_18m', h.hold_d(pr, 12, 18), t, 474, {'costs2_mean_d_pct': float(h.hold_d(pr, 12, 18, 2 * COST).mean() * 100),
           'lag_mean_d_pct': float(h.hold_d(pr, 12, 18, lag=1).mean() * 100), 'n_rows': len(pr)})
    json.dump({k: v for k, v in q.OUT.items() if k.startswith('Q239')},
              open('/mnt/project-files/research/always-on/results/Q239.json', 'w'), indent=1)
