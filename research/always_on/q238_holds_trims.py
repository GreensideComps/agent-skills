"""Q238 sell-rule batch 5: hold lengths and cohort trims (prereg /mnt/project-files/research/always-on/prereg/Q238.md)."""
import os, sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
import pick1 as p1
COST = 0.003


def gap_rows(H):
    import q218_bench_vix as qv
    import q203_earn_gapdown as g
    hi = pd.Series(qv.gate(g.R.index).values[g.e.i], index=g.e.index)
    s = g.sel & hi; R = g.R; cols = {c: j for j, c in enumerate(R.columns)}; Rv = R.values; spy = np.nan_to_num(Rv[:, cols[0]])
    rows = []
    for c, i in zip(g.e.cik[s], g.e.i[s]):
        a = i + 3
        if a + H > len(R): continue
        x = np.nan_to_num(Rv[a:a + H, cols[c]])
        rows.append({'t': R.index[i], 'path': list(np.cumprod(1 + x) - 1), 'bench': list(np.cumprod(1 + spy[a:a + H]) - 1)})
    return rows


def hold_d(rows, base, alt, cost=COST, lag=0):
    """d = excess at alt-hold minus excess at base-hold (path indices are periods-1). Shorter alt pays an extra round trip."""
    out = []
    for r in rows:
        p, b = r['path'], r['bench']
        ex = lambda k: p[k - 1] - b[k - 1]
        A = alt + lag
        extra = 2 * cost if alt < base else 0.0
        out.append(ex(A) - ex(base) - extra)
    return np.array(out)


def bb_rows(H=9):
    df = p1.load(); df = df[df['month'] <= '2022-12-31'].copy()
    g = df.groupby('cik'); df['mi'] = df['month'].dt.year * 12 + df['month'].dt.month
    for h in range(1, H + 1):
        f = g['px'].shift(-h); fm = g['mi'].shift(-h)
        df[f'f{h}'] = (f / df['px'] - 1).where(fm - df['mi'] == h)
    df['mcap_l1'] = g['mcap'].shift(1); df['ok_l1'] = (df['mi'] - g['mi'].shift(1)) == 1
    df['bby'] = df['ttm_buybacks'].abs() / df['mcap']
    rows = []
    for t in sorted(df['month'].unique()):
        if t < pd.Timestamp('2014-12-01') or t > pd.Timestamp('2022-12-31') - pd.DateOffset(months=6): continue
        m = df[(df['month'] == t) & df['ok_l1']]; sic = m['sic'].fillna(0)
        u = m[(m['mcap_l1'] >= 2e9) & (m['close_raw'] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)].dropna(subset=['f6'])
        if len(u) < 50: continue
        thr = u['fcf_ev'].quantile(0.7); bthr = u['bby'].quantile(0.9)
        good = (u['fcf'] > 0) & (u['ttm_operating_income'] > 0) & (u['fcf_ev'] >= thr) & (u['nd_ebitda'] < 3) & (u['sh_chg'] < 0)
        bench = [u[f'f{k}'].mean() for k in range(1, H + 1)]
        for _, r in u[(u['bby'] >= bthr) & good].iterrows():
            rows.append({'t': t, 'path': [r[f'f{k}'] for k in range(1, H + 1)], 'bench': bench})
    return rows


def summ(name, d, t, n, extra):
    q.summ(name, d, t, n, extra)


def cohort_trim(rows, cost=COST, lag=0):
    by = {}
    for r in rows:
        if all(pd.notna(r['path'][:6])): by.setdefault(r['t'], []).append(r)
    out, ts = [], []
    for t, rs in sorted(by.items()):
        P = np.array([[1.0] + list(np.array(r['path'][:6]) + 1) for r in rs])  # levels 0..6
        mret = P[:, 1:] / P[:, :-1] - 1
        drift = P[:, 6].mean() - 1
        val = np.ones(len(rs)) / len(rs)
        for k in range(6):
            if k >= 1 and (lag == 0 or k in (2, 4)):
                tot = val.sum(); tgt = np.full(len(val), tot / len(val))
                c = cost * np.abs(tgt - val).sum(); val = tgt * (1 - c / tot)
            val = val * (1 + mret[:, k])
        out.append(val.sum() - 1 - drift); ts.append(t)
    return np.array(out), ts


if __name__ == '__main__':
    g60 = gap_rows(60); g90 = gap_rows(91)
    for nm, rows, base, alt, n in (('Q238a_gap40', g60, 60, 40, 468), ('Q238b_gap90', g90, 60, 90, 469)):
        t = [r['t'] for r in rows]
        summ(nm, hold_d(rows, base, alt), t, n, {'costs2_mean_d_pct': float(hold_d(rows, base, alt, 2 * COST).mean() * 100),
             'lag_mean_d_pct': float(hold_d(rows, base, alt, lag=1).mean() * 100), 'n_rows': len(rows)})
    bb = bb_rows(10)
    bb6 = [r for r in bb if all(pd.notna(r['path'][:6]))]
    bb10 = [r for r in bb if all(pd.notna(r['path'][:10]))]
    t = [r['t'] for r in bb6]
    summ('Q238c_bb3', hold_d(bb6, 6, 3), t, 470, {'costs2_mean_d_pct': float(hold_d(bb6, 6, 3, 2 * COST).mean() * 100),
         'lag_mean_d_pct': float(hold_d(bb6, 6, 3, lag=1).mean() * 100)})
    t = [r['t'] for r in bb10]
    summ('Q238d_bb9', hold_d(bb10, 6, 9), t, 471, {'costs2_mean_d_pct': float(hold_d(bb10, 6, 9, 2 * COST).mean() * 100),
         'lag_mean_d_pct': float(hold_d(bb10, 6, 9, lag=1).mean() * 100), 'n_rows': len(bb10)})
    d, ts = cohort_trim(bb6)
    summ('Q238e_bb_trim', d, ts, 472, {'costs2_mean_d_pct': float(cohort_trim(bb6, 2 * COST)[0].mean() * 100),
         'lag_mean_d_pct': float(cohort_trim(bb6, lag=1)[0].mean() * 100)})
    json.dump({k: v for k, v in q.OUT.items() if k.startswith('Q238')},
              open('/mnt/project-files/research/always-on/results/Q238.json', 'w'), indent=1)
