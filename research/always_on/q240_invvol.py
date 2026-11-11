"""Q240b buyback_value inverse-vol sizing (prereg /mnt/project-files/research/always-on/prereg/Q240.md)."""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
import pick1 as p1


def cohorts():
    df = p1.load(); df = df[df['month'] <= '2022-12-31'].copy().sort_values(['cik', 'month'])
    g = df.groupby('cik'); df['mi'] = df['month'].dt.year * 12 + df['month'].dt.month
    df['f6'] = (g['px'].shift(-6) / df['px'] - 1).where(g['mi'].shift(-6) - df['mi'] == 6)
    r = g['px'].pct_change().where(df['mi'] - g['mi'].shift(1) == 1)
    df['vol'] = r.groupby(df['cik']).transform(lambda x: x.rolling(12, min_periods=10).std())
    df['vol_l1'] = df.groupby('cik')['vol'].shift(1)
    df['mcap_l1'] = g['mcap'].shift(1); df['ok_l1'] = (df['mi'] - g['mi'].shift(1)) == 1
    df['bby'] = df['ttm_buybacks'].abs() / df['mcap']
    out = []
    for t in sorted(df['month'].unique()):
        if t < pd.Timestamp('2014-12-01') or t > pd.Timestamp('2022-12-31') - pd.DateOffset(months=6): continue
        m = df[(df['month'] == t) & df['ok_l1']]; sic = m['sic'].fillna(0)
        u = m[(m['mcap_l1'] >= 2e9) & (m['close_raw'] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)].dropna(subset=['f6'])
        if len(u) < 50: continue
        thr = u['fcf_ev'].quantile(0.7); bthr = u['bby'].quantile(0.9)
        good = (u['fcf'] > 0) & (u['ttm_operating_income'] > 0) & (u['fcf_ev'] >= thr) & (u['nd_ebitda'] < 3) & (u['sh_chg'] < 0)
        s = u[(u['bby'] >= bthr) & good]
        if len(s) < 2: continue
        out.append((t, s['f6'].values, s['vol'].values, s['vol_l1'].values))
    return out


def d_series(cs, col=2):
    ds, ts = [], []
    for c in cs:
        t, f6, v = c[0], c[1], c[col]
        v = np.where(np.isnan(v), np.nanmedian(v) if np.isfinite(np.nanmedian(v)) else 1.0, v)
        w = (1 / v) / (1 / v).sum()
        ds.append(float((w * f6).sum() - f6.mean())); ts.append(t)
    return np.array(ds), ts


if __name__ == '__main__':
    cs = cohorts()
    d, ts = d_series(cs)
    q.summ('Q240b_bb_invvol', d, ts, 475, {'costs2_mean_d_pct': float(d.mean() * 100), 'lag_mean_d_pct': float(d_series(cs, 3)[0].mean() * 100),
           'n_cohorts': len(cs)})
    json.dump({k: v for k, v in q.OUT.items() if k.startswith('Q240')}, open('/mnt/project-files/research/always-on/results/Q240.json', 'w'), indent=1)
