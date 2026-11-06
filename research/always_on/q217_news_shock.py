"""Q217 news-shock overreaction on non-earnings 8-Ks (prereg /mnt/project-files/research/always-on/prereg/Q217.md).
Tiingo daily data and 8-K items, 2013-2022 only."""
import os, sys, glob, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import pick1 as p1

D = '/mnt/project-files/research-data/'
N = 431
COST = 0.003


def load():
    px, dv = {}, {}
    for f in glob.glob(D + 'tiingo_daily/*.csv'):
        try:
            c = int(os.path.basename(f).split('_')[0])
            x = pd.read_csv(f, usecols=['date', 'adjClose', 'adjVolume'], parse_dates=['date']).set_index('date')
        except ValueError:
            continue
        if len(x) < 300:
            continue
        px[c] = x.adjClose; dv[c] = x.adjClose * x.adjVolume
    P = pd.DataFrame(px).sort_index(); V = pd.DataFrame(dv).reindex(P.index)
    spy = pd.read_csv(D + 'tiingo_etf/SPY.csv', usecols=['date', 'adjClose'], parse_dates=['date']).set_index('date').adjClose
    idx = P.index[(P.index >= '2012-10-01') & (P.index <= '2022-12-31')]
    if getattr(idx, 'tz', None) is not None:
        idx = idx.tz_localize(None); P.index = P.index.tz_localize(None); V.index = V.index.tz_localize(None)
    return P.reindex(idx), V.reindex(idx), spy.reindex(idx)


def events(P, V, spy):
    k = pd.read_csv(D + '8k_items_large_2013_2026.csv.gz', parse_dates=['date'])
    k = k[(k.date >= '2013-01-01') & (k.date <= '2022-12-31') & k.cik.isin(P.columns)]
    k = k[~k['items'].astype(str).str.contains('2.02', regex=False)]
    R = P.pct_change(fill_method=None); m = spy.pct_change()
    rel2 = (R + R.shift(-1)).sub(m + m.shift(-1), axis=0)  # d0 and d0+1
    liq = V.rolling(20).median().shift(1) >= 1e7
    dates = P.index; ev, last = [], {}
    for c, d in sorted(zip(k.cik, k.date), key=lambda x: x[1]):
        i = dates.searchsorted(d)
        if i >= len(dates) - 2:
            continue
        if not liq.iat[i, P.columns.get_loc(c)]:
            continue
        r = rel2.iat[i, P.columns.get_loc(c)]
        if not (r <= -0.08):
            continue
        if c in last and i - last[c] < 10:
            continue
        last[c] = i
        ev.append((i, c, float(V[c].iloc[max(0, i - 20):i].median())))
    return ev, R, m


def run(ev, R, m, spy, hold=5, lag=0, cost=COST, large=False, cond=None, start=None, end=None):
    dates = R.index
    if large:
        med = np.median([e[2] for e in ev]); ev = [e for e in ev if e[2] >= med]
    if cond is not None:
        ev = [e for e in ev if cond.iloc[e[0]]]
    W = pd.DataFrame(0.0, index=dates, columns=['w', 'x']); trades = []
    rel = R.sub(m, axis=0)
    for i, c, _ in ev:
        e = i + 1 + lag
        if e + hold >= len(dates):
            continue
        sl = rel[c].iloc[e + 1:e + hold + 1].fillna(0.0).values
        W.iloc[e + 1:e + hold + 1, 0] += 0.1
        W.iloc[e + 1:e + hold + 1, 1] += 0.1 * sl
        W.iloc[e + 1, 1] -= 0.1 * cost; W.iloc[e + hold, 1] -= 0.1 * cost
        tr = (1 + R[c].iloc[e + 1:e + hold + 1].fillna(0)).prod() - (1 + m.iloc[e + 1:e + hold + 1]).prod()
        trades.append(tr - 2 * cost)
    scale = 1 / W.w.clip(lower=1.0)
    ex = W.x * scale
    ex = ex[ex.index >= '2013-01-01']
    mon = ex.groupby(ex.index.to_period('M')).sum()
    return mon, np.array(trades), len(ev)


def st(s):
    x = p1.stats(pd.Series(s.values)); x['dsr'] = p1.dsr(x, N); return x


if __name__ == '__main__':
    P, V, spy = load()
    ev, R, m = events(P, V, spy)
    out = {}
    mon, tr, ne = run(ev, R, m, spy)
    out['T1'] = {**st(mon), 'events': ne, 'trades': len(tr), 'trade_mean': float(tr.mean()), 'trade_win': float((tr > 0).mean())}
    out['T2'] = {k: float(mon[(mon.index >= a) & (mon.index <= b)].mean() * 12)
                 for k, (a, b) in {'2013-16': ('2013-01', '2016-12'), '2017-19': ('2017-01', '2019-12'), '2020-22': ('2020-01', '2022-12')}.items()}
    ma = spy.rolling(200).mean()
    for nm, c in {'bull': spy > ma, 'bear': spy <= ma}.items():
        mo, t_, n_ = run(ev, R, m, spy, cond=c)
        out['T3_' + nm] = {'ann': float(mo.mean() * 12), 'events': n_, 'trade_mean': float(t_.mean()) if len(t_) else None}
    mo, t_, _ = run(ev, R, m, spy, hold=20); out['T4_20d'] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean())}
    mo, t_, _ = run(ev, R, m, spy, large=True); out['T5_large'] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean())}
    mo, t_, _ = run(ev, R, m, spy, cost=2 * COST); out['T6_cost2'] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean())}
    mo, t_, _ = run(ev, R, m, spy, lag=1); out['T6_lag1'] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean())}
    print(json.dumps(out, indent=1, default=float))
    json.dump(out, open('/mnt/project-files/research/always-on/results/Q217.json', 'w'), indent=1, default=float)
