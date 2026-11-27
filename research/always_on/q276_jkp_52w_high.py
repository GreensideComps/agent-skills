"""Q276 gate-v3: US long-only 52-week-high tilt, JKP prc_highprc_252d long tercile vs its own all-terciles average (prereg research/always_on/prereg/Q276.md)."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
import gate, stats
J = '/mnt/project-files/research-data/jkp/'
F = '/mnt/project-files/research-data/french'
FAC = 'prc_highprc_252d'
COST = 0.005 / 12

def load(loc):
    fac = pd.read_csv(J + f'jkp_{loc}_all_factors_monthly_vw_cap_to2022.csv.gz', usecols=['name', 'direction'])
    d = int(fac[fac.name == FAC].direction.iloc[0])
    pf = pd.read_csv(J + f'jkp_{loc}_portfolios_monthly_vw_cap_to2022.csv.gz', usecols=['name', 'pf', 'date', 'ret'])
    pf = pf[pf.name == FAC].copy(); pf['m'] = pf.date.str[:7]
    w = pf.pivot_table(index='m', columns='pf', values='ret').sort_index().dropna()
    long = w[3.0] if d == 1 else w[1.0]
    return long, w.mean(axis=1), d

def series(long, allt, cost, start='1900-01', end='2022-12'):
    return {m: long[m] - allt[m] - cost for m in long.index if start <= m <= end}

long, allt, direction = load('usa')
ex = series(long, allt, COST, '1927-01')
ex2 = series(long, allt, 2 * COST, '1927-01')
ms = sorted(ex); lag = {ms[i]: ex[ms[i + 1]] for i in range(len(ms) - 1)}
b = gate.Batch(id='Q276', configs=('Q276a',), discovery=(ms[0], '1999-12'), confirmation=('2000-01', '2022-12'), data='none')
v = gate.verdict(b, {'Q276a': {'excess': ex, 'costs_x2': ex2, 'lag1': lag}})
ff = {}
for l in open(f'{F}/F-F_Research_Data_Factors.csv', encoding='latin-1'):
    p = [x.strip() for x in l.split(',')]
    if len(p) == 5 and p[0].isdigit() and len(p[0]) == 6:
        ff[f"{p[0][:4]}-{p[0][4:]}"] = float(p[1]) / 100
ann = lambda d: sum(d) / len(d) * 1200 if d else None
x = [ex[m] for m in ms]; mm = stats.moments(x)
roll = pd.Series(x, index=ms).rolling(12).sum()
dl, da, _ = load('developed')
dex = series(dl, da, COST, '1991-01')
rep = {'gate': v, 'direction': direction, 'first_month': ms[0], 'full_ann_pct': ann(x), 'n_months': len(x), 'sr_monthly': mm['sr'],
       'skew': mm['skew'], 'kurt': mm['kurt'], 'te_ann_pct': mm['sd'] * 12 ** 0.5 * 100, 'dsr_at_N': stats.deflated_sharpe_of(x, 409),
       'disc_ann_pct': ann(gate.window(ex, b.discovery)), 'conf_ann_pct': ann(gate.window(ex, b.confirmation)),
       '1963_99_ann_pct': ann([ex[m] for m in ms if '1963-07' <= m <= '1999-12']),
       'post2007_ann_pct': ann([ex[m] for m in ms if m >= '2007-01']),
       'costx2_ann_pct': ann(list(ex2.values())), 'lag1_ann_pct': ann(list(lag.values())),
       'worst12_pct': float(roll.min() * 100), 'worst12_end': str(roll.idxmin()),
       'vs_mkt_rf_ann_pct': ann([long[m] - COST - ff[m] for m in ms if m in ff]),
       'developed_1991_2022_ann_pct': ann(list(dex.values())),
       'developed_t': stats.moments(list(dex.values()))['sr'] * len(dex) ** 0.5}
print(json.dumps(rep, indent=1, default=str))
json.dump(rep, open('/mnt/project-files/research/always-on/results/Q276.json', 'w'), indent=1, default=str)
