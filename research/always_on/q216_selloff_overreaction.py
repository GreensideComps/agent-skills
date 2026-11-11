"""Q216 market sell-off single-stock overreaction (prereg /mnt/project-files/research/always-on/prereg/Q216.md).
Tiingo daily data to 2022-12-31 only."""
import os, sys, glob, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import pick1 as p1

D = '/mnt/project-files/research-data/'
N = 430
COST = 0.003  # one way


def load():
    px, dv = {}, {}
    for f in glob.glob(D + 'tiingo_daily/*.csv'):
        try:
            x = pd.read_csv(f, usecols=['date', 'adjClose', 'adjVolume'], parse_dates=['date']).set_index('date')
        except ValueError:
            continue
        if len(x) < 300:
            continue
        k = os.path.basename(f)[:-4]
        px[k] = x.adjClose; dv[k] = x.adjClose * x.adjVolume
    P = pd.DataFrame(px).sort_index(); V = pd.DataFrame(dv).reindex(P.index)
    spy = pd.read_csv(D + 'tiingo_etf/SPY.csv', usecols=['date', 'adjClose'], parse_dates=['date']).set_index('date').adjClose
    idx = P.index[(P.index >= '2009-10-01') & (P.index <= '2022-12-31')]
    P, V, spy = P.reindex(idx), V.reindex(idx), spy.reindex(idx)
    if P.index.tz is not None:
        pass
    return P, V, spy


def run(P, V, spy, hold=5, lag=0, cost=COST, top=10, large=False, start='2010-01-01', cond=None):
    R = P.pct_change(fill_method=None); m = spy.pct_change()
    liq = V.rolling(20).median().shift(1) >= 1e7
    rel = R.sub(m, axis=0)
    dates = R.index
    ex = pd.Series(0.0, index=dates); trades = []
    events = [i for i, d in enumerate(dates) if d >= pd.Timestamp(start) and m.iloc[i] <= -0.02]
    if cond is not None:
        events = [i for i in events if cond.iloc[i]]
    for i in events:
        r = rel.iloc[i][liq.iloc[i].fillna(False)].dropna()
        r = r[r <= -0.03]
        if large and len(r):
            dvi = V.iloc[i - 20:i].median()[r.index]
            r = r[dvi >= dvi.median()]
        names = r.nsmallest(top).index
        if len(names) == 0:
            continue
        e = i + lag
        if e + hold >= len(dates):
            continue
        sl = rel.iloc[e + 1:e + hold + 1][names].fillna(0.0)
        daily = sl.mean(axis=1) * 0.2
        ex.iloc[e + 1:e + hold + 1] += daily.values
        ex.iloc[e + 1] -= 0.2 * cost; ex.iloc[e + hold] -= 0.2 * cost
        cum = (1 + R.iloc[e + 1:e + hold + 1][names].fillna(0)).prod() - (1 + m.iloc[e + 1:e + hold + 1]).prod()
        trades += list(cum - 2 * cost)
    mon = ex[ex.index >= start].groupby(ex.index[ex.index >= start].to_period('M')).sum()
    return mon, np.array(trades), len(events)


def st(s):
    x = p1.stats(pd.Series(s.values))
    x['dsr'] = p1.dsr(x, N)
    return x


if __name__ == '__main__':
    P, V, spy = load()
    out = {}
    mon, tr, ne = run(P, V, spy)
    out['T1'] = {**st(mon), 'events': ne, 'trades': len(tr), 'trade_mean': float(tr.mean()), 'trade_win': float((tr > 0).mean())}
    out['T2'] = {k: float(mon[(mon.index >= a) & (mon.index <= b)].sum() / max(1, ((mon.index >= a) & (mon.index <= b)).sum()) * 12)
                 for k, (a, b) in {'2010-14': ('2010-01', '2014-12'), '2015-18': ('2015-01', '2018-12'), '2019-22': ('2019-01', '2022-12')}.items()}
    ma = spy.rolling(200).mean()
    for nm, c in {'bull': spy > ma, 'bear': spy <= ma}.items():
        mo, t_, n_ = run(P, V, spy, cond=c)
        out['T3_' + nm] = {'ann': float(mo.mean() * 12), 'events': n_, 'trade_mean': float(t_.mean()) if len(t_) else None}
    mo, t_, _ = run(P, V, spy, hold=1); out['T4_1d'] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean())}
    mo, t_, _ = run(P, V, spy, large=True); out['T5_large'] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean())}
    mo, t_, _ = run(P, V, spy, cost=2 * COST); out['T6_cost2'] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean())}
    mo, t_, _ = run(P, V, spy, lag=1); out['T6_lag1'] = {'ann': float(mo.mean() * 12), 'trade_mean': float(t_.mean())}
    print(json.dumps(out, indent=1, default=float))
    json.dump(out, open('/mnt/project-files/research/always-on/results/Q216.json', 'w'), indent=1, default=float)
