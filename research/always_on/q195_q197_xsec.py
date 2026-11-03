"""Q195-Q197 yearly cross-sectional signals (prereg/Q195_Q197.md). Data truncated at 2022-12-31."""
import sys, numpy as np, pandas as pd
from statistics import NormalDist
import q183_ear_drift as q
R = q.load(); L = q.liquid(R.index); spy = R.pop(0); L = L.reindex(columns=R.columns).fillna(False)
M = (1 + R.fillna(0)).resample('ME').prod() - 1; M = M.where(R.resample('ME').count() > 0); M.index = M.index.to_period('M')
def signals(f0, f1):
    W = R[(R.index >= f0) & (R.index < f1)]; s = spy.reindex(W.index)
    ok = (W.count() >= 200) & L.loc[:W.index[-1]].iloc[-1]
    W = W.loc[:, ok]; out = {}
    for c in W.columns:
        y = W[c].dropna(); x = s.reindex(y.index); b = np.cov(y, x)[0, 1] / x.var(); e = y - b * x
        pret = (1 + y).prod() - 1
        out[c] = dict(rmom=e.sum() / e.std(), ivol=e.std(), pret=pret, id=np.sign(pret) * ((y < 0).mean() - (y > 0).mean()))
    return pd.DataFrame(out).T
def pick(S, which):
    if which == 'rmom': return S.index[S.rmom.rank(pct=True) > 0.8]
    if which == 'ivol': return S.index[S.ivol.rank(pct=True) <= 0.2]
    top = S[S.pret.rank(pct=True) > 2 / 3]; return top.index[top.id.rank(pct=True) <= 0.5]
def run(which, month=1, cost=q.COST):
    rows, prev = [], set()
    for y in range(2014, 2023):
        f0 = f'{y-1}-{month:02d}-01'; f1 = f'{y-1}-12-01' if month == 1 else f'{y}-01-01'
        S = signals(f0, f1); sel = list(pick(S, which)); allc = list(S.index)
        start = pd.Period(f'{y}-{month:02d}', 'M'); per = [p for p in M.index if start <= p < start + 12 and p <= pd.Period('2022-12', 'M')]
        mm = M.loc[per]
        def bh(cols):
            gr = (1 + mm[cols].fillna(0)).cumprod().mean(1); return gr.pct_change().fillna(gr.iloc[0] - 1)
        ex = bh(sel) - bh(allc); turn = 1 - len(prev & set(sel)) / max(len(sel), 1); ex.iloc[0] -= cost * turn; prev = set(sel)
        rows.append(ex)
    return pd.concat(rows)
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
for tag, w in (('Q195 residual momentum', 'rmom'), ('Q196 frog-in-the-pan', 'fip'), ('Q197 low IVOL', 'ivol')):
    m = run(w); T = len(m); sr = m.mean() / m.std()
    emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
    d = nd.cdf((sr - emax) * np.sqrt(T - 1)); th = sum(x.mean() > 0 for x in np.array_split(m, 3))
    yr = m.groupby(m.index.year).sum()
    print(f"{tag}: months {T} ex/yr {m.mean()*1200:.2f}% t {sr*np.sqrt(T):.2f} thirds+ {th}/3 cost2 {run(w, cost=2*q.COST).mean()*1200:.2f}% lag(Feb) {run(w, month=2).mean()*1200:.2f}% DSR {d:.3f} | years+ {(yr>0).sum()}/{len(yr)}")
