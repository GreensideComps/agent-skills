"""Q234 sell-rule batch 2 (prereg /mnt/project-files/research/always-on/prereg/Q234.md). Data to 2022-12-31 only."""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
import q231_sell_rules as s1
import pick1 as p1


def gap_rows():
    import q218_bench_vix as qv
    import q203_earn_gapdown as g
    hi = pd.Series(qv.gate(g.R.index).values[g.e.i], index=g.e.index)
    sel = g.sel & hi; R = g.R; cols = {c: j for j, c in enumerate(R.columns)}; Rv = R.values; spy = np.nan_to_num(Rv[:, cols[0]])
    rows = []
    for c, i in zip(g.e.cik[sel], g.e.i[sel]):
        a = i + 3; H = 60
        if a + H > len(R) or i < 22: continue
        j = cols[c]; x = np.nan_to_num(Rv[a:a + H, j])
        sig = float(np.nanstd(Rv[i - 21:i - 1, j], ddof=1))
        lv = [1.0 / float(np.prod(1 + np.nan_to_num(Rv[t + 1:a, j]))) for t in range(i - 1, a)]  # close_t / entry close
        rows.append({'t': R.index[i], 'path': list(np.cumprod(1 + x) - 1), 'bench': list(np.cumprod(1 + spy[a:a + H]) - 1),
                     'atr': 1.2 * sig, 'low': min(lv)})
    return rows


def chandelier(r):
    lvl = np.array(r['path']) + 1; peak = np.maximum.accumulate(np.maximum(lvl, 1.0))
    hit = np.where(lvl < peak * (1 - 3 * r['atr']))[0]
    return int(hit[0]) if len(hit) else None


def new_low(r):
    hit = np.where(np.array(r['path']) + 1 < r['low'])[0]
    return int(hit[0]) if len(hit) else None


def p1_rows():
    df = p1.load(); df = df[df['month'] <= '2022-12-31'].copy()
    df = df.sort_values(['cik', 'month']); g = df.groupby('cik')
    mi = df['month'].dt.year * 12 + df['month'].dt.month
    df['r3'] = (df['px'] / g['px'].shift(3) - 1).where(mi - g['month'].shift(3).pipe(lambda s: s.dt.year * 12 + s.dt.month) == 3)
    by = {m: x for m, x in df.groupby('month')}; months = sorted(by)
    rows = []
    for m in months:
        if m.month != 12 or m < pd.Timestamp('2014-12-31') or m > pd.Timestamp('2021-12-31'): continue
        u = p1.universe(by[m])
        if len(u) < 50: continue
        picks = p1.pick(u); fut = [mm for mm in months if mm > m][:12]
        if len(fut) < 12: continue
        R = pd.DataFrame({k: p1.universe(by[mm2]).set_index('cik')['ret_next'] for k, mm2 in enumerate([m] + fut[:11])})
        ew = R.mean()
        info = []
        for mm2 in fut[:11]:
            uu = p1.universe(by[mm2]).set_index('cik')
            info.append((uu['mom'], uu['r3'].rank(pct=True)))
        for c in picks['cik']:
            if c not in R.index: continue
            x = R.loc[c].fillna(0.0).values
            rows.append({'t': m, 'path': list(np.cumprod(1 + x) - 1), 'bench': list(np.cumprod(1 + ew.values) - 1),
                         'mom': [mo.get(c, np.nan) for mo, _ in info], 'rs': [rs.get(c, np.nan) for _, rs in info]})
    return rows


def mom_neg(r):
    return next((k for k, v in enumerate(r['mom']) if pd.notna(v) and v < 0), None)


def rs_bottom(r, kmin=3):
    # index k is month-end k+1; checks allowed from month-end 3 (index 2)
    return next((k for k, v in enumerate(r['rs']) if k >= kmin - 1 and pd.notna(v) and v <= 1 / 3), None)


def bb_rows():
    df = p1.load(); df = df[df['month'] <= '2022-12-31'].copy()
    g = df.groupby('cik'); df['mi'] = df['month'].dt.year * 12 + df['month'].dt.month
    for h in range(1, 7):
        f = g['px'].shift(-h); fm = g['mi'].shift(-h)
        df[f'f{h}'] = (f / df['px'] - 1).where(fm - df['mi'] == h)
    df['r3'] = (df['px'] / g['px'].shift(3) - 1).where(df['mi'] - g['mi'].shift(3) == 3)
    df['mcap_l1'] = g['mcap'].shift(1); df['ok_l1'] = (df['mi'] - g['mi'].shift(1)) == 1
    df['bby'] = df['ttm_buybacks'].abs() / df['mcap']
    rsr = {}
    for t, m in df.groupby('month'):
        sic = m['sic'].fillna(0)
        u = m[m['ok_l1'] & (m['mcap_l1'] >= 2e9) & (m['close_raw'] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)]
        rsr[t] = u.set_index('cik')['r3'].rank(pct=True)
    months = sorted(rsr)
    rows = []
    for t in months:
        if t < pd.Timestamp('2014-12-01') or t > pd.Timestamp('2022-12-31') - pd.DateOffset(months=6): continue
        m = df[(df['month'] == t) & df['ok_l1']]; sic = m['sic'].fillna(0)
        u = m[(m['mcap_l1'] >= 2e9) & (m['close_raw'] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)].dropna(subset=['f6'])
        if len(u) < 50: continue
        bench = [u[f'f{k}'].mean() for k in range(1, 7)]
        thr = u['fcf_ev'].quantile(0.7); bthr = u['bby'].quantile(0.9)
        good = (u['fcf'] > 0) & (u['ttm_operating_income'] > 0) & (u['fcf_ev'] >= thr) & (u['nd_ebitda'] < 3) & (u['sh_chg'] < 0)
        ti = months.index(t)
        for _, r in u[(u['bby'] >= bthr) & good].iterrows():
            path = [r[f'f{k}'] for k in range(1, 7)]
            if any(pd.isna(path)): continue
            rs = [rsr[months[ti + k]].get(r['cik'], np.nan) if ti + k < len(months) else np.nan for k in range(1, 6)]
            rows.append({'t': t, 'path': path, 'bench': bench, 'rs': rs})
    return rows


def main():
    gr = gap_rows()
    s1.run('Q234a_gap_chandelier', gr, chandelier, 457)
    s1.run('Q234b_gap_new_low', gr, new_low, 458)
    pr = p1_rows()
    s1.run('Q234c_p1_mom_neg', pr, mom_neg, 459)
    s1.run('Q234d_p1_rs_bottom', pr, rs_bottom, 460)
    s1.run('Q234e_bb_rs_bottom', bb_rows(), rs_bottom, 461)
    json.dump({k: v for k, v in q.OUT.items() if k.startswith('Q234')},
              open('/mnt/project-files/research/always-on/results/Q234.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
