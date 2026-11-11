"""Q183 earnings-announcement-return drift (prereg/Q183.md). Tiingo daily data to 2022-12-31 only."""
import os, sys, glob, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
D = '/mnt/project-files/research-data/'
COST = 0.003  # round trip
def load():
    px = {}
    for f in glob.glob(D + 'tiingo_daily/*.csv'):
        c = int(os.path.basename(f).split('_')[0])
        try: s = pd.read_csv(f, usecols=['date', 'adjClose'], parse_dates=['date']).set_index('date').adjClose
        except ValueError: continue  # ticker not found / empty response
        if len(s) > 300: px[c] = s
    P = pd.DataFrame(px).sort_index(); P = P[P.index <= '2022-12-31']
    return P.pct_change(fill_method=None)
def liquid(index, thresh=1e7):
    """Ex-ante liquidity mask (LOOP.md 3 Nov): prior-20d median adjClose*adjVolume >= thresh."""
    dv = {}
    for f in glob.glob(D + 'tiingo_daily/*.csv'):
        c = int(os.path.basename(f).split('_')[0])
        try: x = pd.read_csv(f, usecols=['date', 'adjClose', 'adjVolume'], parse_dates=['date']).set_index('date')
        except ValueError: continue
        dv[c] = x.adjClose * x.adjVolume
    V = pd.DataFrame(dv).reindex(index)
    return V.rolling(20).median().shift(1) >= thresh
def events(R):
    k = pd.read_csv(D + '8k_items_large_2013_2026.csv.gz', parse_dates=['date'])
    k = k[k['items'].astype(str).str.contains('2.02') & k.cik.isin(R.columns) & (k.date >= '2013-06-01') & (k.date <= '2022-12-31')]
    k = k.drop_duplicates(['cik', 'date']).sort_values('date')
    idx = R.index; out = []
    for c, d in zip(k.cik, k.date):
        i = idx.searchsorted(d)
        if i < 1 or i + 2 >= len(idx): continue
        ex = R[c].iloc[i-1:i+2] - R[0].iloc[i-1:i+2]
        if ex.isna().any(): continue
        out.append((c, i, ex.sum()))
    e = pd.DataFrame(out, columns=['cik', 'i', 'ear'])
    # rank vs trailing 250 events only (no look-ahead)
    e['pct'] = [np.nan if j < 250 else (e.ear.iloc[j-250:j] < e.ear.iloc[j]).mean() for j in range(len(e))]
    return e
def portfolio(R, e, H, sel, lag=0, cost=COST):
    n = len(R); w = np.zeros((n, R.shape[1])); cols = {c: j for j, c in enumerate(R.columns)}
    tc = np.zeros(n)
    for c, i in zip(e.cik[sel], e.i[sel]):
        s = i + 2 + lag + 1  # bought at close of day +2(+lag): earns from next day
        if s >= n: continue
        w[s:min(s + H, n), cols[c]] += 1; tc[s] += cost / 2; tc[min(s + H, n - 1)] += cost / 2
    cnt = w.sum(1); Rv = np.nan_to_num(R.values)
    gross = np.where(cnt > 0, (w * Rv).sum(1) / np.maximum(cnt, 1), 0.0)
    pos = np.where(cnt > 0, 1.0, 0.0)
    costd = np.where(cnt > 0, np.array([0.0] * n), 0.0)
    # cost per position spread over the book: tc counts per event, divide by open positions
    costd = np.where(cnt > 0, tc / np.maximum(cnt, 1), 0.0)
    net = gross - costd
    ex = pd.Series(net - pos * Rv[:, list(R.columns).index(0)], index=R.index)
    return ex[ex.index >= '2014-01-01']
def stats(ex):
    m = (1 + ex).resample('ME').prod() - 1
    t = m.mean() / m.std() * np.sqrt(len(m)); ann = m.mean() * 12
    thirds = [x.mean() > 0 for x in np.array_split(m, 3)]
    return dict(n_months=len(m), ann=round(ann * 100, 2), t=round(t, 2), sr_m=m.mean() / m.std(), thirds=sum(thirds), m=m)
if __name__ == '__main__':
    R = load(); e = events(R); print('stocks', R.shape[1] - 1, 'events', len(e))
    top = e.pct >= 0.8; bot = e.pct <= 0.2
    from statistics import NormalDist as _ND; _n = _ND()
    class norm: ppf = staticmethod(_n.inv_cdf); cdf = staticmethod(_n.cdf)
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 394
    for tag, H in (('a', 60), ('b', 20)):
        s = stats(portfolio(R, e, H, top)); c2 = stats(portfolio(R, e, H, top, cost=2 * COST)); l1 = stats(portfolio(R, e, H, top, lag=1))
        bt = stats(portfolio(R, e, H, bot))
        # DSR: expected max SR under N trials
        g = 0.5772; sr = s['sr_m']; T = s['n_months']
        emax = np.sqrt(1 / T) * ((1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * np.e)))
        dsr = norm.cdf((sr - emax) * np.sqrt(T - 1))
        print(f"Q183{tag} H{H}: ex/yr {s['ann']}% t {s['t']} thirds+ {s['thirds']}/3 cost2 {c2['ann']}% lag1 {l1['ann']}% bottomQ {bt['ann']}% DSR {dsr:.3f}")
