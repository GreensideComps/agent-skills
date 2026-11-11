"""Q226 social_trend (Wikipedia attention) backtest, prereg /mnt/project-files/research/always-on/prereg/Q226.md (+addendum).
Prices: Yahoo daily (honest UA, owner approved 11 Nov 2026), research-data/yahoo_daily, to 2022-12-31 only."""
import os, sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import q221_exit_rules as q
D = '/mnt/project-files/research-data'; COST = 0.003; N = 444
q.OUT = {}


def load():
    pv = pd.read_csv(f'{D}/wiki_pageviews/pageviews_2015_2022.csv', dtype={'date': str})
    ex = f'{D}/wiki_pageviews/pageviews_2015_2022_extra.csv'
    if os.path.exists(ex): pv = pd.concat([pv, pd.read_csv(ex, dtype={'date': str})])
    pv['date'] = pd.to_datetime(pv['date']); pv['ticker'] = pv['ticker'].str.strip('"').replace({'OAC': 'HIMS', 'SG1': 'SG'})
    P = {}
    for t in pv['ticker'].unique():
        f = f'{D}/yahoo_daily/{t}.csv'
        if os.path.exists(f) and os.path.getsize(f) > 100:
            P[t] = pd.read_csv(f, parse_dates=['date']).set_index('date').sort_index()
    spy = pd.read_csv(f'{D}/yahoo_daily/SPY.csv', parse_dates=['date']).set_index('date').sort_index()
    vix = pd.read_csv(f'{D}/fred/VIXCLS.csv'); vix.columns = ['date', 'vix']
    vix['date'] = pd.to_datetime(vix['date']); vix['vix'] = pd.to_numeric(vix['vix'], errors='coerce')
    vix = vix.dropna().set_index('date')['vix']
    return pv, P, spy, vix


def signals(pv, P):
    """weekly scans: returns dict ticker -> DataFrame(friday, z, fire)"""
    out = {}
    fridays = pd.date_range('2016-07-01', '2022-12-30', freq='W-FRI')
    for t, g in pv.groupby('ticker'):
        if t not in P: continue
        v = g.set_index('date')['views'].asfreq('D')
        m28 = v.rolling(28, min_periods=28).mean()
        px = P[t]['adj_close']; rows = []
        for f in fridays:
            if f not in m28.index or pd.isna(m28.get(f)): continue
            base = [m28.get(f - pd.Timedelta(days=7 * k)) for k in range(1, 53)]
            if any(b is None or pd.isna(b) for b in base): continue
            sd = np.std(base, ddof=1)
            if sd <= 0: continue
            z = (m28[f] - np.mean(base)) / sd
            last7 = v[f - pd.Timedelta(days=6):f].sum(); prior7 = v[f - pd.Timedelta(days=13):f - pd.Timedelta(days=7)].sum()
            h = px[:f]
            if len(h) < 21 or (f - h.index[-1]).days > 5: continue
            ret20 = h.iloc[-1] / h.iloc[-21] - 1
            rows.append((f, z, bool(z >= 3 and last7 > prior7 and ret20 <= 0.15)))
        out[t] = pd.DataFrame(rows, columns=['fri', 'z', 'fire']).set_index('fri')
    return out


def trades(S, P, spy, lag=0):
    res = []
    end = pd.Timestamp('2022-12-30')
    for t, s in S.items():
        px = P[t]; days = px.index; busy_until = pd.Timestamp('1900-01-01')
        zs = s['z']
        for f in s.index[s['fire']]:
            if f <= busy_until: continue
            nxt = days[days > f]
            if len(nxt) <= lag: continue
            ed = nxt[lag]; ep = px.loc[ed, 'adj_open']
            stop, tp, tstop = ep * 0.88, ep * 1.25, ed + pd.Timedelta(days=84)
            exit_d = exit_p = None; how = None
            pending_attn = False
            for d in days[days >= ed]:
                o, h, l, c = px.loc[d, ['adj_open', 'adj_high', 'adj_low', 'adj_close']]
                if pending_attn and d > ed:
                    exit_d, exit_p, how = d, o, 'attn'; break
                if d > ed and o <= stop: exit_d, exit_p, how = d, o, 'stop'; break
                if d > ed and o >= tp: exit_d, exit_p, how = d, o, 'tp'; break
                if l <= stop: exit_d, exit_p, how = d, stop, 'stop'; break
                if h >= tp: exit_d, exit_p, how = d, tp, 'tp'; break
                if d >= tstop or d >= end: exit_d, exit_p, how = d, c, 'time' if d < end else 'end'; break
                if d in zs.index and d > ed and zs[d] < 1: pending_attn = True
            if exit_d is None: continue
            busy_until = exit_d
            r = exit_p / ep - 1
            sp_e = spy.loc[ed, 'adj_open']
            sp_x = spy.loc[exit_d, 'adj_open'] if how == 'attn' else spy.loc[exit_d, 'adj_close']
            res.append({'t': t, 'fri': f, 'entry': ed, 'exit': exit_d, 'how': how, 'ret': r, 'ex': r - (sp_x / sp_e - 1)})
    return pd.DataFrame(res).sort_values('entry')


if __name__ == '__main__':
    pv, P, spy, vix = load()
    print('names with prices:', len(P), sorted(P))
    S = signals(pv, P); T = trades(S, P, spy)
    net = T['ex'] - 2 * COST
    T['vix'] = [vix[:f].iloc[-1] for f in T['fri']]
    r = q.summ('Q226', net.values, T['entry'], N, {
        'costs2_mean_pct': float((T['ex'] - 4 * COST).mean() * 100),
        'lag_mean_pct': float((trades(S, P, spy, lag=1)['ex'] - 2 * COST).mean() * 100),
        'exits': T['how'].value_counts().to_dict(), 'names_traded': int(T['t'].nunique()),
        'gated_vix25': {'n': int((T['vix'] >= 25).sum()), 'mean_pct': float(net[T['vix'] >= 25].mean() * 100) if (T['vix'] >= 25).any() else None},
        'complement': {'n': int((T['vix'] < 25).sum()), 'mean_pct': float(net[T['vix'] < 25].mean() * 100)}})
    th = r['thirds_pct']
    r['verdict'] = 'PASS' if (r['dsr'] > 0.95 and r['mean_d_pct'] > 0 and sum(x > 0 for x in th) >= 2 and r['costs2_mean_pct'] > 0 and r['lag_mean_pct'] > 0) else 'FAIL'
    g = r['gated_vix25']
    r['bench'] = bool(g['mean_pct'] is not None and g['mean_pct'] > 0 and g['mean_pct'] > r['complement']['mean_pct'])
    print(json.dumps(r, default=str, indent=1))
    T.to_csv('/mnt/project-files/research/always-on/results/Q226_trades.csv', index=False)
    json.dump(r, open('/mnt/project-files/research/always-on/results/Q226.json', 'w'), indent=1, default=str)
