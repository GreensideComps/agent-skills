"""Q184 dividend capture (pre-registered: prereg/Q184.md). Data truncated at 2022-12-31."""
import glob, os, sys, numpy as np, pandas as pd
from statistics import NormalDist
D = '/mnt/project-files/research-data/tiingo_daily/'; COST = 0.003
cl, dv, sp = {}, {}, {}
for f in glob.glob(D + '*.csv'):
    c = int(os.path.basename(f).split('_')[0])
    try: x = pd.read_csv(f, usecols=['date', 'close', 'divCash', 'splitFactor', 'adjClose'], parse_dates=['date']).set_index('date')
    except ValueError: continue
    x = x[x.index <= '2022-12-31']
    if len(x) < 300: continue
    if c == 0: spy = x.adjClose.pct_change(); continue
    cl[c], dv[c], sp[c] = x.close, x.divCash, x.splitFactor
CL = pd.DataFrame(cl).sort_index(); DV = pd.DataFrame(dv).reindex(CL.index).fillna(0); SP = pd.DataFrame(sp).reindex(CL.index).fillna(1)
spy = spy.reindex(CL.index)
idx = CL.index; Cv = CL.values; Dv = DV.values; Sv = SP.values
ev = [(i, j) for i, j in zip(*np.nonzero(Dv > 0)) if idx[i] >= pd.Timestamp('2013-12-20')]
print('stocks', CL.shape[1], 'ex-dates', len(ev))
def run(after, tax=0.15, cost=COST, early=0):
    # after: trading days held after ex-date (0 = sell at ex-day close); early: extra days bought before
    pos = {}  # day -> list of (daily return) for open positions
    yld, drop = [], []
    for i, j in ev:
        a, b = i - 1 - early, i + after
        if a < 1 or b >= len(idx) or np.isnan(Cv[a, j]) or np.isnan(Cv[b, j]): continue
        if (Sv[a + 1:b + 1, j] != 1).any(): continue
        px = Cv[a:b + 1, j]; d = np.zeros(len(px)); d[i - a] = Dv[i, j] * (1 - tax)
        r = (px[1:] + d[1:]) / px[:-1] - 1
        r[0] -= cost / 2; r[-1] -= cost / 2
        yld.append(Dv[i, j] / Cv[i - 1, j]); drop.append((Cv[i - 1, j] - Cv[i, j]) / Dv[i, j])
        for k, rr in enumerate(r): pos.setdefault(idx[a + 1 + k], []).append(rr)
    s = pd.Series({d: np.mean(v) for d, v in pos.items()}).sort_index()
    ex = (s - spy.reindex(s.index)).dropna()
    m = ex.groupby(ex.index.to_period('M')).sum(); m = m[m.index >= pd.Period('2014-01', 'M')]
    return m, np.mean(yld), np.median(drop), len(yld)
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
for tag, H in (('a', 0), ('b', 4)):
    m, y, dr, n = run(H); T = len(m); sr = m.mean() / m.std()
    emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
    dsr = nd.cdf((sr - emax) * np.sqrt(T - 1)); th = sum(x.mean() > 0 for x in np.array_split(m, 3))
    c2 = run(H, cost=2 * COST)[0].mean() * 12; l1 = run(H, early=1)[0].mean() * 12
    g0 = run(H, tax=0, cost=0)[0].mean() * 12; nt = run(H, tax=0)[0].mean() * 12
    print(f"Q184{tag} hold ex+{H}: trades {n} months {T} ex/yr {m.mean()*1200:.2f}% t {sr*np.sqrt(T):.2f} thirds+ {th}/3 cost2 {c2*100:.2f}% lag1 {l1*100:.2f}% DSR {dsr:.3f} | no-tax {nt*100:.2f}% gross {g0*100:.2f}% | avg yield {y*100:.2f}% median drop/div {dr:.2f}")
