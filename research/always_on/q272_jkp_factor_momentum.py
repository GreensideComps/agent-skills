"""Q272 gate-v3: JKP US factor momentum, long legs vs same-weight all-terciles average (prereg research/always_on/prereg/Q272.md)."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
import gate, stats
J = '/mnt/project-files/research-data/jkp/'
F = '/mnt/project-files/research-data/french'
COST = 0.01 / 12

def load(loc):
    fac = pd.read_csv(J + f'jkp_{loc}_all_factors_monthly_vw_cap_to2022.csv.gz', usecols=['name', 'direction'])
    d = fac.drop_duplicates('name').set_index('name')['direction']
    pf = pd.read_csv(J + f'jkp_{loc}_portfolios_monthly_vw_cap_to2022.csv.gz', usecols=['name', 'pf', 'date', 'ret'])
    pf['m'] = pf.date.str[:7]
    w = pf.pivot_table(index='m', columns=['pf', 'name'], values='ret').sort_index()
    names = sorted(set(w[1.0].columns) & set(w[3.0].columns) & set(d.index))
    hi, lo, mid = w[3.0][names], w[1.0][names], w[2.0].reindex(columns=names)
    flip = d[names] == -1
    long = hi.where(~flip, lo); short = lo.where(~flip, hi)
    allt = pd.concat([hi, mid, lo], axis=1).mean(axis=1)  # EW of all terciles of all factors available
    return long, short, allt

def build(long, short, allt, lag, cost, start, end):
    ls = long - short
    sig = ls.rolling(12, min_periods=12).sum().shift(1 + lag)
    ex, timing, nheld = {}, {}, []
    for m in long.index:
        if not (start <= m <= end): continue
        s = sig.loc[m]; r = long.loc[m]
        pick = s[(s > 0) & r.notna()].index
        if len(pick) < 10: continue
        comp = r[pick].mean()
        ex[m] = comp - allt.loc[m] - cost
        timing[m] = comp - r.dropna().mean()
        nheld.append(len(pick))
    return ex, timing, nheld

long, short, allt = load('usa')
ex, tim, nh = build(long, short, allt, 0, COST, '1963-07', '2022-12')
ex2, _, _ = build(long, short, allt, 0, 2 * COST, '1963-07', '2022-12')
lag, _, _ = build(long, short, allt, 1, COST, '1963-07', '2022-12')
b = gate.Batch(id='Q272', configs=('Q272a',), discovery=('1963-07', '1999-12'), confirmation=('2000-01', '2022-12'), data='none')
v = gate.verdict(b, {'Q272a': {'excess': ex, 'costs_x2': ex2, 'lag1': lag}})
ff = {}
for l in open(f'{F}/F-F_Research_Data_Factors.csv', encoding='latin-1'):
    p = [x.strip() for x in l.split(',')]
    if len(p) == 5 and p[0].isdigit() and len(p[0]) == 6:
        ff[f"{p[0][:4]}-{p[0][4:]}"] = float(p[1]) / 100
ann = lambda d: sum(d) / len(d) * 1200 if d else None
months = sorted(ex); x = [ex[m] for m in months]; mm = stats.moments(x)
vs_mkt = [ex[m] + allt.loc[m] - ff[m] for m in months if m in ff]  # composite - cost - Mkt-RF
dl, ds, da = load('developed')
dex, dtim, _ = build(dl, ds, da, 0, COST, '1991-01', '2022-12')
rep = {'gate': v, 'full_ann_pct': ann(x), 'n_months': len(x), 'sr_monthly': mm['sr'], 'skew': mm['skew'], 'kurt': mm['kurt'],
       'te_ann_pct': mm['sd'] * 12 ** 0.5 * 100, 'dsr_at_N': stats.deflated_sharpe_of(x, 407),
       'disc_ann_pct': ann(gate.window(ex, b.discovery)), 'conf_ann_pct': ann(gate.window(ex, b.confirmation)),
       'post2007_ann_pct': ann([ex[m] for m in months if m >= '2007-01']),
       'costx2_ann_pct': ann(list(ex2.values())), 'lag1_ann_pct': ann(list(lag.values())),
       'vs_mkt_rf_ann_pct': ann(vs_mkt), 'avg_factors_held': float(np.mean(nh)), 'n_factors': long.shape[1],
       'timing_spread_2000_22_ann_pct_precost': ann([tim[m] for m in tim if m >= '2000-01']),
       'timing_spread_1963_99_ann_pct_precost': ann([tim[m] for m in tim if m < '2000-01']),
       'developed_1991_2022_ann_pct': ann(list(dex.values())), 'developed_timing_ann_pct_precost': ann(list(dtim.values())),
       'developed_t': stats.moments(list(dex.values()))['sr'] * len(dex) ** 0.5}
print(json.dumps(rep, indent=1, default=str))
json.dump(rep, open('/mnt/project-files/research/always-on/results/Q272.json', 'w'), indent=1, default=str)
