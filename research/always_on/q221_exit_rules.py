"""Q221 exit rules vs plain hold (prereg /mnt/project-files/research/always-on/prereg/Q221.md). Data to 2022-12-31 only."""
import os, sys, math, json
from statistics import NormalDist
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import pick1 as p1
COST = 0.003; ND = NormalDist(); OUT = {}


def dsr_m(x, n):
    x = np.asarray(x, float); T = len(x); sr = x.mean() / x.std(ddof=1) if x.std(ddof=1) > 0 else 0.0; g = 0.5772
    emax = math.sqrt(1 / T) * ((1 - g) * ND.inv_cdf(1 - 1 / n) + g * ND.inv_cdf(1 - 1 / (n * math.e)))
    return float(ND.cdf((sr - emax) * math.sqrt(T - 1)))


def summ(name, d, t_entry, n, extra=None):
    d = pd.Series(np.asarray(d, float), index=pd.DatetimeIndex(t_entry)).sort_index()
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std(ddof=1) > 0 else float('nan')
    mon = d.groupby(d.index.to_period('M')).mean()
    th = [float(x.mean()) for x in np.array_split(d.values, 3)]
    r = {'trades': len(d), 'triggered': int((d != 0).sum()), 'mean_d_pct': float(d.mean() * 100), 't': float(t),
         'dsr': dsr_m(mon.values, n), 'thirds_pct': [round(x * 100, 3) for x in th]}
    if extra: r.update(extra)
    OUT[name] = r; print(name, json.dumps(r)); return r


def lock_exit(path, lag=0, trig=0.25):
    """path: cumulative return from entry at each period end (1..H). Returns exit index (0-based) or None."""
    peak = -1e9
    for k, c in enumerate(path):
        if peak >= trig and c <= peak / 2:
            j = k + lag
            return j if j < len(path) - 1 else None
        peak = max(peak, c)
    return None


# ---------- Q206 buyback_value (monthly) ----------
def q206_trades():
    df = p1.load(); df = df[df['month'] <= '2022-12-31'].copy()
    g = df.groupby('cik'); df['mi'] = df['month'].dt.year * 12 + df['month'].dt.month
    for h in range(1, 7):
        f = g['px'].shift(-h); fm = g['mi'].shift(-h)
        df[f'f{h}'] = (f / df['px'] - 1).where(fm - df['mi'] == h)
    df['mcap_l1'] = g['mcap'].shift(1); df['ok_l1'] = (df['mi'] - g['mi'].shift(1)) == 1
    df['bby'] = df['ttm_buybacks'].abs() / df['mcap']
    key = df.set_index(['cik', 'mi'])[['sh_chg', 'last_filed']]
    rows = []
    for t in sorted(df['month'].unique()):
        if t < pd.Timestamp('2014-12-01') or t > pd.Timestamp('2022-12-31') - pd.DateOffset(months=6): continue
        m = df[(df['month'] == t) & df['ok_l1']]; sic = m['sic'].fillna(0)
        u = m[(m['mcap_l1'] >= 2e9) & (m['close_raw'] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)].dropna(subset=['f6'])
        if len(u) < 50: continue
        bench = [u[f'f{k}'].mean() for k in range(1, 7)]
        thr = u['fcf_ev'].quantile(0.7); bthr = u['bby'].quantile(0.9)
        good = (u['fcf'] > 0) & (u['ttm_operating_income'] > 0) & (u['fcf_ev'] >= thr) & (u['nd_ebitda'] < 3) & (u['sh_chg'] < 0)
        for _, r in u[(u['bby'] >= bthr) & good].iterrows():
            path = [r[f'f{k}'] for k in range(1, 7)]
            if any(pd.isna(path)): continue
            broke = []
            for k in range(1, 6):
                kk = (r['cik'], r['mi'] + k)
                if kk in key.index:
                    x = key.loc[kk]
                    if isinstance(x, pd.DataFrame): x = x.iloc[-1]
                    broke.append(bool(pd.notna(x['sh_chg']) and x['sh_chg'] > 0 and pd.notna(x['last_filed']) and pd.Timestamp(x['last_filed']) > t))
                else: broke.append(False)
            rows.append({'t': t, 'path': path, 'bench': bench, 'broke': broke})
    return rows


def q206_eval(rows, rule, cost=COST, lag=0):
    d = []
    for r in rows:
        plain = r['path'][-1] - r['bench'][-1] - 2 * cost
        if rule == 'thesis':
            k = next((i for i, b in enumerate(r['broke']) if b), None)
            if k is not None: k = k + lag if k + lag < 5 else None
        else:
            k = lock_exit(r['path'], lag)
        d.append(0.0 if k is None else (r['path'][k] - r['bench'][k] - 4 * cost) - plain)
    return np.array(d)


# ---------- gap_rebound (daily) ----------
def gap_trades():
    import q218_bench_vix as qv
    import q203_earn_gapdown as q
    hi = pd.Series(qv.gate(q.R.index).values[q.e.i], index=q.e.index)
    s = q.sel & hi; R = q.R; cols = {c: j for j, c in enumerate(R.columns)}; Rv = R.values; spy = np.nan_to_num(Rv[:, cols[0]])
    rows = []
    for c, i in zip(q.e.cik[s], q.e.i[s]):
        a = i + 3; H = 60
        if a + H > len(R): continue
        x = np.nan_to_num(Rv[a:a + H, cols[c]])
        rows.append({'t': R.index[i], 'path': list(np.cumprod(1 + x) - 1), 'bench': list(np.cumprod(1 + spy[a:a + H]) - 1)})
    return rows


def lock_eval(rows, cost=COST, lag=0):
    d = []
    for r in rows:
        plain = r['path'][-1] - r['bench'][-1] - 2 * cost
        k = lock_exit(r['path'], lag)
        d.append(0.0 if k is None else (r['path'][k] - r['bench'][k] - 4 * cost) - plain)
    return np.array(d)


# ---------- pick-1 screener (monthly, Dec picks held 12m) ----------
def pick1_trades():
    df = p1.load(); df = df[df['month'] <= '2022-12-31']
    by = {m: g for m, g in df.groupby('month')}; months = sorted(by)
    rows = []
    for m in months:
        if m.month != 12 or m < pd.Timestamp('2014-12-31') or m > pd.Timestamp('2021-12-31'): continue
        u = p1.universe(by[m])
        if len(u) < 50: continue
        picks = p1.pick(u); fut = [mm for mm in months if mm > m][:12]
        if len(fut) < 12: continue
        R = pd.DataFrame({k: p1.universe(by[mm2]).set_index('cik')['ret_next'] for k, mm2 in enumerate([m] + fut[:11])})
        ew = R.mean()
        for c in picks['cik']:
            if c not in R.index: continue
            x = R.loc[c].fillna(0.0).values
            rows.append({'t': m, 'path': list(np.cumprod(1 + x) - 1), 'bench': list(np.cumprod(1 + ew.values) - 1)})
    return rows


if __name__ == '__main__':
    bb = q206_trades()
    for nm, rule, n in (('Q221a_thesis', 'thesis', 436), ('Q221b1_lock_buyback', 'lock', 437)):
        t = [r['t'] for r in bb]
        summ(nm, q206_eval(bb, rule), t, n, {'costs2_mean_d_pct': float(q206_eval(bb, rule, cost=2 * COST).mean() * 100),
                                            'lag_mean_d_pct': float(q206_eval(bb, rule, lag=1).mean() * 100),
                                            'plain_mean_pct': float(np.mean([r['path'][-1] - r['bench'][-1] - 2 * COST for r in bb]) * 100)})
    for nm, rows, n in (('Q221b2_lock_gap_rebound', gap_trades(), 438), ('Q221c_lock_pick1', pick1_trades(), 439)):
        t = [r['t'] for r in rows]
        summ(nm, lock_eval(rows), t, n, {'costs2_mean_d_pct': float(lock_eval(rows, cost=2 * COST).mean() * 100),
                                         'lag_mean_d_pct': float(lock_eval(rows, lag=1).mean() * 100),
                                         'plain_mean_pct': float(np.mean([r['path'][-1] - r['bench'][-1] - 2 * COST for r in rows]) * 100)})
    json.dump(OUT, open('/mnt/project-files/research/always-on/results/Q221.json', 'w'), indent=1)
