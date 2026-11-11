"""Q231-Q233 sell-rule track batch 1 (prereg /mnt/project-files/research/always-on/prereg/Q231.md). Data to 2022-12-31 only.
Reuses Q221 trade builders and summary unchanged; d = rule net excess - plain-hold net excess per trade."""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
import pick1 as p1
COST = q.COST


def _d(rows, exit_fn, cost=COST, lag=0):
    out = []
    for r in rows:
        H = len(r['path']); plain = r['path'][-1] - r['bench'][-1] - 2 * cost
        k = exit_fn(r)
        if k is not None:
            k = k + lag
            if k >= H - 1: k = None
        out.append(0.0 if k is None else (r['path'][k] - r['bench'][k] - 4 * cost) - plain)
    return np.array(out)


def run(name, rows, exit_fn, n):
    t = [r['t'] for r in rows]
    q.summ(name, _d(rows, exit_fn), t, n, {'costs2_mean_d_pct': float(_d(rows, exit_fn, 2 * COST).mean() * 100),
                                           'lag_mean_d_pct': float(_d(rows, exit_fn, lag=1).mean() * 100),
                                           'plain_mean_pct': float(np.mean([r['path'][-1] - r['bench'][-1] - 2 * COST for r in rows]) * 100)})


# ---- Q231 gap_rebound target exit ----
def gap_rows():
    import q218_bench_vix as qv
    import q203_earn_gapdown as g
    hi = pd.Series(qv.gate(g.R.index).values[g.e.i], index=g.e.index)
    s = g.sel & hi; R = g.R; cols = {c: j for j, c in enumerate(R.columns)}; Rv = R.values; spy = np.nan_to_num(Rv[:, cols[0]])
    rows = []
    for c, i in zip(g.e.cik[s], g.e.i[s]):
        a = i + 3; H = 60
        if a + H > len(R) or i < 1: continue
        x = np.nan_to_num(Rv[a:a + H, cols[c]])
        pre = float(np.prod(1 + np.nan_to_num(Rv[i - 1:a, cols[c]])))  # entry close / pre-drop close (close of day i-2)
        rows.append({'t': R.index[i], 'path': list(np.cumprod(1 + x) - 1), 'bench': list(np.cumprod(1 + spy[a:a + H]) - 1), 'pre': pre})
    return rows


def gap_target(r):
    lvl = 1.0 / r['pre'] - 1  # return from entry needed to regain pre-drop close
    return next((k for k, c in enumerate(r['path']) if c >= lvl), None)


# ---- Q232 buyback_value FCF-or-shares thesis exit ----
def bb_rows():
    """Same trades as q221.q206_trades (code copied, only the broke test extended): broke_k = post-entry filing shows
    shares up y/y OR FCF <= 0."""
    df = p1.load(); df = df[df['month'] <= '2022-12-31'].copy()
    g = df.groupby('cik'); df['mi'] = df['month'].dt.year * 12 + df['month'].dt.month
    for h in range(1, 7):
        f = g['px'].shift(-h); fm = g['mi'].shift(-h)
        df[f'f{h}'] = (f / df['px'] - 1).where(fm - df['mi'] == h)
    df['mcap_l1'] = g['mcap'].shift(1); df['ok_l1'] = (df['mi'] - g['mi'].shift(1)) == 1
    df['bby'] = df['ttm_buybacks'].abs() / df['mcap']
    key = df.set_index(['cik', 'mi'])[['sh_chg', 'fcf', 'last_filed']]
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
                    new = pd.notna(x['last_filed']) and pd.Timestamp(x['last_filed']) > t
                    bad = (pd.notna(x['sh_chg']) and x['sh_chg'] > 0) or (pd.notna(x['fcf']) and x['fcf'] <= 0)
                    broke.append(bool(new and bad))
                else: broke.append(False)
            rows.append({'t': t, 'path': path, 'bench': bench, 'broke': broke})
    return rows


def bb_thesis(r):
    return next((i for i, b in enumerate(r['broke']) if b), None)


# ---- Q233 pick-1 drop-out bands ----
def p1_rows():
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
        ranks = []  # rank of each cik in the sector-capped pick-1 list at month-ends fut[0..10] (k = 1..11)
        for mm2 in fut[:11]:
            s = p1.score(p1.universe(by[mm2])); out, per = [], {}
            for _, rr in s.iterrows():
                if per.get(rr['sic2'], 0) >= p1.PER_SIC: continue
                per[rr['sic2']] = per.get(rr['sic2'], 0) + 1; out.append(rr['cik'])
                if len(out) == 45: break
            ranks.append({c: j + 1 for j, c in enumerate(out)})
        for c in picks['cik']:
            if c not in R.index: continue
            x = R.loc[c].fillna(0.0).values
            rows.append({'t': m, 'path': list(np.cumprod(1 + x) - 1), 'bench': list(np.cumprod(1 + ew.values) - 1),
                         'rank': [rk.get(c, 999) for rk in ranks]})
    return rows


def band(K):
    # path index k is the return through month-end k+1; a check at month-end k (1..11) exits at path index k-1
    return lambda r: next((k for k, rk in enumerate(r['rank']) if rk > K), None)


def main():
    run('Q231_gap_target', gap_rows(), gap_target, 452)
    run('Q232_bb_fcf_or_shares', bb_rows(), bb_thesis, 453)
    pr = p1_rows()
    for nm, K, n in (('Q233a_band22', 22, 454), ('Q233b_band30', 30, 455), ('Q233c_band45', 45, 456)):
        run(nm, pr, band(K), n)
    json.dump(q.OUT, open('/mnt/project-files/research/always-on/results/Q231.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
