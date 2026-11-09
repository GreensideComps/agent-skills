"""Q237 sell-rule batch 4 (prereg /mnt/project-files/research/always-on/prereg/Q237.md). Data to 2022-12-31 only."""
import os, sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
import pick1 as p1
COST = 0.003; OUT = {}


def build():
    df = p1.load(); df = df[df['month'] <= '2022-12-31']
    by = {m: g for m, g in df.groupby('month')}; months = sorted(by)
    years = []
    for m in months:
        if m.month != 12 or m < pd.Timestamp('2014-12-31') or m > pd.Timestamp('2021-12-31'): continue
        fut = [mm for mm in months if mm > m][:12]
        if len(fut) < 12: continue
        ms = [m] + fut[:11]
        U = [p1.universe(by[x]) for x in ms]
        R = [u.set_index('cik')['ret_next'] for u in U]
        S = [p1.score(u).set_index('cik')['score'] for u in U]
        years.append({'picks': list(p1.pick(U[0])['cik']), 'R': R, 'S': S, 'ew': [r.mean() for r in R], 'm': fut})
    return years


def sim(years, rule, cost=COST, lag=0):
    out = []
    for y in years:
        hold = list(y['picks']); val = np.ones(len(hold)) / len(hold)
        for k in range(12):
            before = val.sum()  # value at month start, before any trade cost
            if k >= 1 and rule == 'swap':
                kk = k - lag
                if kk >= 1:
                    s = y['S'][kk]; sd = s.std()
                    hs = np.array([s.get(c, s.min()) for c in hold])
                    cand = s[~s.index.isin(hold)]
                    if len(cand):
                        best = cand.idxmax()
                        w = int(np.argmin(hs))
                        if cand.max() - hs[w] > sd:
                            val = val.copy(); val[w] *= (1 - 2 * cost); hold[w] = best
            if k >= 1 and rule == 'rebal' and (lag == 0 or k % 2 == 0):
                tot = val.sum(); tgt = np.ones(len(val)) * tot / len(val)
                c = cost * np.abs(tgt - val).sum(); val = tgt * (1 - c / tot)
            r = np.array([y['R'][k].get(c, 0.0) if pd.notna(y['R'][k].get(c, 0.0)) else 0.0 for c in hold])
            val = val * (1 + r)
            out.append((y['m'][k], val.sum() / before - 1 - y['ew'][k]))
    return pd.Series(dict(out)).sort_index()


def run(name, years, rule, n):
    plain = sim(years, 'none')
    d = sim(years, rule) - plain
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    th = [float(v.mean()) for v in np.array_split(d.values, 3)]
    r = {'months': len(d), 'mean_d_pct_m': float(d.mean() * 100), 't': float(t), 'dsr': q.dsr_m(d.values, n),
         'thirds_pct_m': [round(v * 100, 3) for v in th],
         'costs2_mean_d_pct_m': float((sim(years, rule, cost=2 * COST) - plain).mean() * 100),
         'lag_mean_d_pct_m': float((sim(years, rule, lag=1) - plain).mean() * 100),
         'plain_excess_pct_m': float(plain.mean() * 100)}
    OUT[name] = r; print(name, json.dumps(r))


if __name__ == '__main__':
    ys = build()
    run('Q237a_swap', ys, 'swap', 466); run('Q237b_rebal', ys, 'rebal', 467)
    json.dump(OUT, open('/mnt/project-files/research/always-on/results/Q237.json', 'w'), indent=1)
