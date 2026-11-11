"""Q243 averaging down / sell-when-expensive (prereg /mnt/project-files/research/always-on/prereg/Q243.md). Data to 2022-12-31 only."""
import os, sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
import q237_swaps_trims as q237
import pick1 as p1
COST = 0.003


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
        G = [p1.score(u).set_index('cik') for u in U]
        years.append({'picks': list(p1.pick(U[0])['cik']), 'R': [u.set_index('cik')['ret_next'] for u in U],
                      'G': G, 'S': [g['score'] for g in G], 'med': [g['fcf_ev'].median() for g in G],
                      'p30': [g['fcf_ev'].quantile(0.3) for g in G], 'ew': [u['ret_next'].mean() for u in U], 'm': fut})
    return years


def ret(y, k, c):
    v = y['R'][k].get(c, 0.0)
    return 0.0 if pd.isna(v) else float(v)


def sim(years, rule, cost=COST, lag=0):
    out = []
    for y in years:
        hold = list(y['picks']); n = len(hold); val = np.ones(n) / n
        cum = np.ones(n); topped = [False] * n
        for k in range(12):
            before = val.sum(); kk = k - lag
            if k >= 1 and kk >= 1:
                G = y['G'][kk]
                if rule in ('a', 'b'):
                    thr = 0.85 if rule == 'a' else 0.75
                    for i, c in enumerate(hold):
                        # cum at kk: product of returns up to month kk-1
                        cum_kk = np.prod([1 + ret(y, j, c) for j in range(kk)])
                        if not topped[i] and cum_kk <= thr and c in G.index and G.loc[c, 'fcf_ev'] >= y['med'][kk]:
                            add = val.sum() / n; others = [j for j in range(n) if j != i]
                            osum = val[others].sum()
                            if osum <= add: continue
                            val = val.copy(); val[others] *= (1 - add / osum); val[i] += add
                            val *= (1 - 2 * cost * add / val.sum()); topped[i] = True
                elif rule in ('c', 'd'):
                    bad = []
                    for i, c in enumerate(hold):
                        if c not in G.index: bad.append((-np.inf, i))
                        elif G.loc[c, 'fcf_ev'] < y['p30'][kk]: bad.append((G.loc[c, 'fcf_ev'], i))
                    if bad:
                        bad.sort(); i = bad[0][1]
                        if rule == 'c':
                            s = y['S'][kk]; cand = s[~s.index.isin(hold)]
                            if len(cand):
                                val = val.copy(); val[i] *= (1 - 2 * cost); hold[i] = cand.idxmax()
                        else:
                            amt = val[i]; others = [j for j in range(len(hold)) if j != i]
                            val = val.copy(); val[others] += amt * (1 - 2 * cost) * val[others] / val[others].sum(); val[i] = 0.0
            r = np.array([ret(y, k, c) for c in hold])
            val = val * (1 + r)
            out.append((y['m'][k], val.sum() / before - 1 - y['ew'][k]))
    return pd.Series(dict(out)).sort_index()


def stats(d, n):
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    return {'months': len(d), 'mean_d_pct_m': round(float(d.mean() * 100), 3), 'ann_d_pct': round(float(d.mean() * 1200), 2),
            't': round(float(t), 2), 'dsr': round(float(q.dsr_m(d.values, n)), 3),
            'thirds_pct_m': [round(float(v.mean()) * 100, 3) for v in np.array_split(d.values, 3)]}


if __name__ == '__main__':
    years = build(); plain = sim(years, 'none'); OUT = {}
    swap = q237.sim(q237.build(), 'swap')
    for rule, n in zip('abcd', range(480, 484)):
        x = sim(years, rule); d = x - plain; r = stats(d, n)
        r['costs2_mean_d_pct_m'] = round(float((sim(years, rule, cost=2 * COST) - plain).mean() * 100), 3)
        r['lag_mean_d_pct_m'] = round(float((sim(years, rule, lag=1) - plain).mean() * 100), 3)
        r['vs_dropout_swap_mean_pct_m'] = round(float((x - swap.reindex(x.index)).mean() * 100), 3)
        th = r['thirds_pct_m']
        r['verdict'] = 'PASS' if (r['dsr'] > 0.95 and sum(v > 0 for v in th) >= 2 and r['costs2_mean_d_pct_m'] > 0 and r['lag_mean_d_pct_m'] > 0 and r['mean_d_pct_m'] > 0) else ('FAIL (bench unproven)' if r['mean_d_pct_m'] > 0 else 'FAIL')
        OUT['Q243' + rule] = r; print(rule, r)
    json.dump(OUT, open('/mnt/project-files/research/always-on/results/Q243.json', 'w'), indent=1)
