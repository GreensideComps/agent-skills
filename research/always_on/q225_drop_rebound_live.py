"""Q225 exact live drop_rebound rule (prereg /mnt/project-files/research/always-on/prereg/Q225.md). Data to 2022-12-31.
TSLA, UBER, XOM not fetched (Tiingo monthly symbol cap hit) -> 12 of 15 names; disclosed."""
import os, sys, json, math, glob
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import pick1 as p1
from q218_bench_vix import VIX
N = 442; COST = 0.003; O = '/mnt/project-files/research-data/tiingo_ohlc/'
spy = pd.read_csv(O + 'SPY.csv', parse_dates=['date']).set_index('date')
k8 = pd.read_csv('/mnt/project-files/research-data/8k_items_large_2013_2026.csv.gz', parse_dates=['date'])
k8 = k8[k8['items'].astype(str).str.contains('2.02', regex=False)]
cos = pd.read_csv('/mnt/project-files/research-data/sec_companies.csv.gz')
tcol = [c for c in cos.columns if 'ticker' in c.lower()][0]; ccol = [c for c in cos.columns if c.lower() == 'cik'][0]
def clip(x): return max(-1.0, min(1.0, x))
def scores(c, i):
    p = c.iloc[:i]  # up to t-1
    if len(p) < 253: return None, None
    x = p.iloc[-1]; ma50 = p.iloc[-50:].mean(); ma200 = p.iloc[-200:].mean()
    lng = np.mean([clip((x / ma200 - 1) / 0.10), clip((p.iloc[-22] / p.iloc[-253] - 1) / 0.30), 0.5 if ma50 > ma200 else -0.5])
    off = x / p.iloc[-252:].max() - 1; vol = p.pct_change().iloc[-20:].std() * math.sqrt(252)
    med = np.mean([clip((x / p.iloc[-64] - 1) / 0.15), clip((x / p.iloc[-127] - 1) / 0.25), clip((off + 0.10) / 0.10)]) - max(0.0, (vol - 0.35) / 0.35)
    return lng, med
def run(gate=True, cost=COST, lag=False, names=None):
    trades = []
    for f in sorted(glob.glob(O + '*.csv')):
        t = os.path.basename(f)[:-4]
        if t == 'SPY' or (names and t not in names): continue
        d = pd.read_csv(f, parse_dates=['date']).set_index('date'); C = d.adjClose
        ck = cos[cos[tcol].astype(str).str.upper() == t][ccol]
        ed = set(k8[k8.cik.isin(ck)].date) if len(ck) else set()
        idx = d.index; nxt = -1
        for i in range(253, len(idx) - 12):
            if idx[i] < pd.Timestamp('2013-01-01') or i <= nxt: continue
            prev = C.iloc[i - 1]
            if d.adjLow.iloc[i] > 0.95 * prev: continue
            if any((e > idx[i]) and (e <= idx[min(i + 3, len(idx) - 1)]) for e in ed): continue
            if gate:
                l, m = scores(C, i)
                if l is None or l < 0 or m < -0.3: continue
            if lag: s = i + 1; ent = d.adjOpen.iloc[s]
            else: s = i; ent = min(d.adjOpen.iloc[i], 0.95 * prev)
            ex, j = None, s
            for j in range(s + 1, s + 11):
                if d.adjLow.iloc[j] <= ent * 0.92: ex = ent * 0.92; break
                if d.adjHigh.iloc[j] >= ent * 1.06: ex = ent * 1.06; break
            if ex is None: ex = C.iloc[j]
            sp = spy.adjClose.reindex(idx)
            r = ex / ent - 1 - (sp.iloc[j] / sp.iloc[s] - 1) - 2 * cost
            trades.append((idx[s], t, r, bool(VIX.reindex([idx[i]], method='ffill').iloc[0] >= 25))); nxt = j
    return pd.DataFrame(trades, columns=['d', 't', 'r', 'vixhi'])
def summ(df):
    r = df.r; tt = r.mean() / (r.std() / math.sqrt(len(r))) if len(r) > 1 else float('nan')
    mon = df.groupby(df.d.dt.to_period('M')).r.sum() * 0.02 / 0.02  # per-2%-slot monthly sum of trade returns
    mon = mon.reindex(pd.period_range('2013-01', '2022-12', freq='M'), fill_value=0.0)
    s = p1.stats(pd.Series(mon.values * 0.02)); s['dsr'] = p1.dsr(s, N)
    return {'trades': len(r), 'mean': float(r.mean()), 't': float(tt), 'hit': float((r > 0).mean()), 'dsr': float(s['dsr']), 'thirds': [float(x.mean()) for x in np.array_split(r.values, 3)]}
if __name__ == '__main__':
    out = {}; T1 = run(); out['T1'] = summ(T1)
    out['T3_vixhi'] = float(T1[T1.vixhi].r.mean()) if T1.vixhi.any() else None; out['T3_vixlo'] = float(T1[~T1.vixhi].r.mean())
    out['T4_nogate'] = summ(run(gate=False)); out['T6_cost2'] = summ(run(cost=2 * COST)); out['T6_lag'] = summ(run(lag=True))
    out['T5_8names'] = summ(run(names={'JPM', 'AAPL', 'WMT', 'UNH', 'COST', 'LLY', 'ORCL', 'MA'}))
    print(json.dumps(out, indent=1)); json.dump(out, open('/mnt/project-files/research/always-on/results/Q225.json', 'w'), indent=1)
