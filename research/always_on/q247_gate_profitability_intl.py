"""Q246 gate-v3 batch 1 (prereg /mnt/project-files/research/always-on/prereg/Q247.md). Data to 2022-12."""
import os, sys, json, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import gate, stats
F = '/mnt/project-files/research-data/french'


def french_block(path, header_start):
    lines = open(path, encoding='latin-1').read().splitlines()
    i = next(k for k, l in enumerate(lines) if l.strip().startswith(header_start))
    hdr = [h.strip() for h in lines[i + 1].split(',')]
    out = {}
    for l in lines[i + 2:]:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 2 or not p[0].isdigit() or len(p[0]) != 6: break
        out[f"{p[0][:4]}-{p[0][4:]}"] = dict(zip(hdr[1:], map(float, p[1:])))
    return out


op = french_block(f'{F}/Developed_ex_US_6_Portfolios_ME_OP.csv', 'Average Value Weighted Returns -- Monthly')
ff = {}
for l in open(f'{F}/Developed_ex_US_3_Factors.csv', encoding='latin-1'):
    p = [x.strip() for x in l.split(',')]
    if len(p) == 5 and p[0].isdigit() and len(p[0]) == 6:
        ff[f"{p[0][:4]}-{p[0][4:]}"] = (float(p[1]) + float(p[4])) / 100
months = sorted(m for m in op if m in ff and '1990-07' <= m <= '2022-12')
cost = 0.001 / 12
ex = {m: op[m]['BIG HiOP'] / 100 - ff[m] - cost for m in months}
ex2 = {m: v - cost for m, v in ex.items()}
lag = {m: (0.0 if m.endswith('-07') else v) for m, v in ex.items()}
b = gate.Batch(id='Q247', configs=('Q247a',), discovery=('1990-07', '2005-12'), confirmation=('2006-01', '2022-12'), data='none')
v = gate.verdict(b, {'Q247a': {'excess': ex, 'costs_x2': ex2, 'lag1': lag}})
x = [ex[m] for m in months]; mm = stats.moments(x)
post07 = [ex[m] for m in months if m >= '2007-01']
rep = {'gate': v, 'full_ann_pct': sum(x) / len(x) * 1200, 'n_months': len(x), 'sr_monthly': mm['sr'], 'skew': mm['skew'], 'kurt': mm['kurt'],
       'te_ann_pct': mm['sd'] * (12 ** 0.5) * 100, 'dsr_at_N491': stats.deflated_sharpe_of(x, 491),
       'post2007_ann_pct': sum(post07) / len(post07) * 1200,
       'disc_ann_pct': sum(gate.window(ex, b.discovery)) / len(gate.window(ex, b.discovery)) * 1200,
       'conf_ann_pct': sum(gate.window(ex, b.confirmation)) / len(gate.window(ex, b.confirmation)) * 1200}
print(json.dumps(rep, indent=1, default=str))
json.dump(rep, open('/mnt/project-files/research/always-on/results/Q247.json', 'w'), indent=1, default=str)
