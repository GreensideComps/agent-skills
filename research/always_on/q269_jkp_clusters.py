"""Q269 gate-v3 (benchmark fixed to Mkt-RF: JKP rets are excess returns; first run subtracted RF twice) (prereg research/always_on/prereg/Q269.md). JKP USA long-leg composite vs market, data to 2022-12."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
import gate, stats
J = '/mnt/project-files/research-data/jkp/'
F = '/mnt/project-files/research-data/french'
cl = pd.read_csv(J + 'cluster_labels.csv')
members = cl[cl.cluster.isin(['Debt Issuance', 'Profit Growth', 'Seasonality'])]
names = set(members.characteristic)
FAST = {'niq_su', 'saleq_su', 'niq_at_chg1', 'niq_be_chg1', 'ocf_at_chg1', 'ret_12_7', 'coskew_21d'}
slow = {n for n in names if n not in FAST and not n.startswith('seas_')}
fac = pd.read_csv(J + 'jkp_usa_all_factors_monthly_vw_cap_to2022.csv.gz', usecols=['name', 'direction'])
direc = fac.drop_duplicates('name').set_index('name')['direction'].to_dict()
pf = pd.read_csv(J + 'jkp_usa_portfolios_monthly_vw_cap_to2022.csv.gz')
pf = pf[pf.name.isin(names)]
pf = pf[pf.apply(lambda r: r.pf == (3 if direc[r['name']] == 1 else 1), axis=1)]
pf['m'] = pf.date.str[:7]
wide = pf.pivot_table(index='m', columns='name', values='ret')
ff = {}
for l in open(f'{F}/F-F_Research_Data_Factors.csv', encoding='latin-1'):
    p = [x.strip() for x in l.split(',')]
    if len(p) == 5 and p[0].isdigit() and len(p[0]) == 6:
        ff[f"{p[0][:4]}-{p[0][4:]}"] = float(p[1]) / 100  # JKP portfolio returns are EXCESS of T-bill, so compare with Mkt-RF (bug fix 16 Nov, see Q269.md)
cost = 0.005 / 12
def series(cols, c):
    w = wide[[x for x in cols if x in wide.columns]]
    out = {}
    for m, row in w.iterrows():
        v = row.dropna()
        if len(v) >= 10 and m in ff and '1963-07' <= m <= '2022-12':
            out[m] = v.mean() - ff[m] - c
    return out
ex = series(names, cost); ex2 = series(names, 2 * cost); lag = series(slow, cost)
b = gate.Batch(id='Q269', configs=('Q269a',), discovery=('1963-07', '1999-12'), confirmation=('2000-01', '2022-12'), data='none')
v = gate.verdict(b, {'Q269a': {'excess': ex, 'costs_x2': ex2, 'lag1': lag}})
months = sorted(ex); x = [ex[m] for m in months]; mm = stats.moments(x)
post07 = [ex[m] for m in months if m >= '2007-01']
percl = {}
for c in ['Debt Issuance', 'Profit Growth', 'Seasonality']:
    s = series(set(members[members.cluster == c].characteristic), cost) if c != 'Debt Issuance' else None
    if c == 'Debt Issuance':
        w = wide[[n for n in members[members.cluster == c].characteristic if n in wide.columns]]
        s = {m: r.dropna().mean() - ff[m] - cost for m, r in w.iterrows() if r.notna().sum() >= 4 and m in ff and '1963-07' <= m <= '2022-12'}
    percl[c] = sum(s.values()) / len(s) * 1200
rep = {'gate': v, 'full_ann_pct': sum(x) / len(x) * 1200, 'n_months': len(x), 'first': months[0], 'sr_monthly': mm['sr'],
       'skew': mm['skew'], 'kurt': mm['kurt'], 'te_ann_pct': mm['sd'] * 12 ** 0.5 * 100,
       'dsr_at_N': stats.deflated_sharpe_of(x, 406), 'post2007_ann_pct': sum(post07) / len(post07) * 1200,
       'disc_ann_pct': sum(gate.window(ex, b.discovery)) / len(gate.window(ex, b.discovery)) * 1200,
       'conf_ann_pct': sum(gate.window(ex, b.confirmation)) / len(gate.window(ex, b.confirmation)) * 1200,
       'lag1_ann_pct': sum(lag.values()) / len(lag) * 1200, 'costx2_ann_pct': sum(ex2.values()) / len(ex2) * 1200,
       'per_cluster_ann_pct_descriptive': percl, 'n_factors': len(wide.columns)}
print(json.dumps(rep, indent=1, default=str))
json.dump(rep, open('/mnt/project-files/research/always-on/results/Q269.json', 'w'), indent=1, default=str)
