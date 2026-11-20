"""Q245 dividend timing (prereg /mnt/project-files/research/always-on/prereg/Q245.md). Yahoo raw prices, data to 2022-12-31."""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import q221_exit_rules as q
sys.path.insert(0, '/mnt/project-files/research/always-on'); import stats as st
D = '/mnt/project-files/research-data'; R = f'{D}/yahoo_raw'; COST = 0.003
q.OUT = {}


def px(t):
    return pd.read_csv(f'{R}/{t}.csv', parse_dates=['date']).set_index('date').sort_index()


def run(lag=0, cost=COST):
    U = json.load(open(f'{D}/q245_universe.json')); spy = px('SPY')
    out = {'a': [], 'b': [], 'c': []}; missing = set()
    for yr, names in U.items():
        for t in names:
            if not os.path.exists(f'{R}/{t}_div.csv') or os.path.getsize(f'{R}/{t}.csv') < 100: missing.add(t); continue
            P = px(t); dv = pd.read_csv(f'{R}/{t}_div.csv', parse_dates=['ex_date'])
            dv['ex_date'] = pd.to_datetime(dv['ex_date']); dv = dv[dv.ex_date.dt.year == int(yr)]
            idx = P.index
            for _, r in dv.iterrows():
                if r.ex_date not in idx: continue
                i = idx.get_loc(r.ex_date)
                if i < 11: continue
                d_ex, d_cum = idx[i], idx[i - 1]
                if d_ex not in spy.index or d_cum not in spy.index: continue
                # a: cum close -> ex open (+div); lag: cannot enter later (same night) -> enter ex open? skip lag for a by using 2-day: not defined -> use same
                if lag == 0:
                    ra = (P.loc[d_ex, 'open'] + r.amount) / P.loc[d_cum, 'close'] - 1
                    sa = spy.loc[d_ex, 'open'] / spy.loc[d_cum, 'close'] - 1
                    out['a'].append((d_cum, ra - sa - 2 * cost))
                # b: buy close of i-2 (+lag), sell ex close
                e = idx[i - 2 + lag]
                if e < d_ex:
                    rb = (P.loc[d_ex, 'close'] + r.amount) / P.loc[e, 'close'] - 1
                    sb = spy.loc[d_ex, 'adjclose'] / spy.loc[e, 'adjclose'] - 1 if e in spy.index else np.nan
                    out['b'].append((e, rb - sb - 2 * cost))
                # c: buy close i-10 (+lag), sell close i-1
                e = idx[i - 10 + lag]
                rc = P.loc[d_cum, 'close'] / P.loc[e, 'close'] - 1
                sc = spy.loc[d_cum, 'adjclose'] / spy.loc[e, 'adjclose'] - 1 if e in spy.index else np.nan
                out['c'].append((e, rc - sc - 2 * cost))
    return {k: pd.DataFrame(v, columns=['t', 'd']).dropna() for k, v in out.items()}, missing


if __name__ == '__main__':
    base, missing = run(); c2, _ = run(cost=2 * COST); lg, _ = run(lag=1)
    print('missing', len(missing), sorted(missing))
    res = {}
    for k, n in zip('abc', (487, 488, 489)):
        df = base[k]
        extra = {'costs2_mean_pct': float(c2[k]['d'].mean() * 100),
                 'lag_mean_pct': float(lg[k]['d'].mean() * 100) if len(lg[k]) else None,
                 'gross_mean_pct': float((df['d'] + 2 * COST).mean() * 100)}
        r = q.summ('Q245' + k, df['d'].values, df['t'], n, extra)
        lagok = (extra['lag_mean_pct'] is None) or extra['lag_mean_pct'] > 0
        r['verdict'] = 'PASS' if (r['dsr'] > 0.95 and r['mean_d_pct'] > 0 and sum(x > 0 for x in r['thirds_pct']) >= 2 and extra['costs2_mean_pct'] > 0 and lagok) else ('FAIL (bench unproven)' if r['mean_d_pct'] > 0 else 'FAIL')
        mon = pd.Series(df['d'].values, index=pd.DatetimeIndex(df['t'])).groupby(lambda x: x.to_period('M')).mean()
        mm = st.moments(list(mon.values)); ds = st.deflated_sharpe_of(list(mon.values), 489)
        r.update({'sr_monthly': mm.get('sr', mon.mean() / mon.std(ddof=1)), 'n_months': len(mon), 'skew': mm.get('skew'), 'kurt': mm.get('kurt'),
                  'dsr_stats_py': ds, 'cluster_t_by_entry_date': st.cluster_t(list(df['d'].values), list(pd.to_datetime(df['t']).dt.strftime('%G-%V')))})
        res['Q245' + k] = r
    res['missing'] = sorted(missing)
    json.dump(res, open('/mnt/project-files/research/always-on/results/Q245.json', 'w'), indent=1)
    print(json.dumps({k: (v['verdict'] if isinstance(v, dict) else v) for k, v in res.items() if k != 'missing'}))
