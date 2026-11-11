"""Q242 sizing track (prereg /mnt/project-files/research/always-on/prereg/Q242.md). Data to 2022-12-31 only."""
import os, sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
D = '/mnt/project-files/research-data/'
OUT = {}


def market():
    rows = []
    for line in open(D + 'french/F-F_Research_Data_Factors_daily.csv'):
        p = [x.strip() for x in line.split(',')]
        if len(p) == 5 and p[0].isdigit() and len(p[0]) == 8 and '19270101' <= p[0] <= '20221231':
            rows.append((pd.Timestamp(p[0]), float(p[1]) / 100, float(p[4]) / 100))
    d = pd.DataFrame(rows, columns=['date', 'mx', 'rf']).set_index('date')
    d['m'] = d['mx'] + d['rf']
    g = d.groupby(d.index.to_period('M'))
    mon = pd.DataFrame({'m': g['m'].apply(lambda x: (1 + x).prod() - 1), 'rf': g['rf'].apply(lambda x: (1 + x).prod() - 1),
                        'sig': g['mx'].std() * math.sqrt(252)})
    return mon


def w_vol(mon):
    s = mon['sig']; tgt = s.expanding().median()
    w = np.minimum(1.0, tgt / s).shift(1)
    w.iloc[:60] = 1.0
    return w.fillna(1.0)


def w_kelly(mon):
    ex = mon['m'] - mon['rf']
    mu = ex.rolling(120).mean().shift(1); var = ex.rolling(120).var().shift(1)
    return (0.5 * mu / var).clip(0, 1).fillna(1.0)


def maxdd(r):
    c = (1 + r).cumprod(); return float((c / c.cummax() - 1).min())


def run_mkt(name, mon, w, n, cost=0.001, lag=0):
    if lag: w = w.shift(lag).fillna(1.0)
    rule = w * mon['m'] + (1 - w) * mon['rf'] - cost * w.diff().abs().fillna(0.0)
    return rule - mon['m'], rule


def report_mkt(name, mon, wfn, n):
    w = wfn(mon); d, rule = run_mkt(name, mon, w, n)
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    sh = lambda r: float((r - mon['rf']).mean() / (r - mon['rf']).std() * math.sqrt(12))
    r = {'months': len(d), 'mean_w': float(w.mean()), 'mean_d_pct_m': float(d.mean() * 100), 't': float(t), 'dsr': q.dsr_m(d.values, n),
         'thirds_pct_m': [round(float(v.mean()) * 100, 3) for v in np.array_split(d.values, 3)],
         'costs2_mean_d_pct_m': float(run_mkt(name, mon, w, n, cost=0.002)[0].mean() * 100),
         'lag_mean_d_pct_m': float(run_mkt(name, mon, w, n, lag=1)[0].mean() * 100),
         'cagr_plain': float((1 + mon['m']).prod() ** (12 / len(d)) - 1), 'cagr_rule': float((1 + rule).prod() ** (12 / len(d)) - 1),
         'sharpe_plain': sh(mon['m']), 'sharpe_rule': sh(rule), 'maxdd_plain': maxdd(mon['m']), 'maxdd_rule': maxdd(rule)}
    OUT[name] = r; print(name, json.dumps(r))


def sizes(raw, ts):
    order = np.argsort(np.array(ts, dtype='datetime64[ns]'), kind='stable'); s = np.ones(len(raw)); past = []
    for i in order:
        s[i] = 1.0 if len(past) < 20 else float(np.clip(raw[i] / np.median(past), 0.25, 2.0))
        past.append(raw[i])
    return s


def trade_d(rows, size, exit_fn, cost=q.COST, lag=0):
    out = []
    for r, s in zip(rows, size):
        H = len(r['path']); plain = r['path'][-1] - r['bench'][-1] - 2 * cost
        k = exit_fn(r)
        if k is not None:
            k = k + lag
            if k >= H - 1: k = None
        rule = (r['path'][-1] - r['bench'][-1] - 2 * cost) if k is None else (r['path'][k] - r['bench'][k] - 4 * cost)
        out.append(s * rule - plain)
    return np.array(out)


def run_trades(name, rows, raw, exit_fn, n):
    ts = [r['t'] for r in rows]; s = sizes(np.array(raw), ts)
    d = trade_d(rows, s, exit_fn)
    q.summ(name, d, ts, n, {'costs2_mean_d_pct': float(trade_d(rows, s, exit_fn, 2 * q.COST).mean() * 100),
                            'lag_mean_d_pct': float(trade_d(rows, s, exit_fn, lag=1).mean() * 100),
                            'mean_size': float(s.mean()), 'n_trades': len(rows)})


def bb_rows_vol():
    import pick1 as p1
    df = p1.load(); df = df[df['month'] <= '2022-12-31'].copy().sort_values(['cik', 'month'])
    g = df.groupby('cik'); df['mi'] = df['month'].dt.year * 12 + df['month'].dt.month
    for h in range(1, 7):
        df[f'f{h}'] = (g['px'].shift(-h) / df['px'] - 1).where(g['mi'].shift(-h) - df['mi'] == h)
    r = g['px'].pct_change().where(df['mi'] - g['mi'].shift(1) == 1)
    df['vol'] = r.groupby(df['cik']).transform(lambda x: x.rolling(12, min_periods=10).std())
    df['mcap_l1'] = g['mcap'].shift(1); df['ok_l1'] = (df['mi'] - g['mi'].shift(1)) == 1
    df['bby'] = df['ttm_buybacks'].abs() / df['mcap']
    rows = []
    for t in sorted(df['month'].unique()):
        if t < pd.Timestamp('2014-12-01') or t > pd.Timestamp('2022-12-31') - pd.DateOffset(months=6): continue
        m = df[(df['month'] == t) & df['ok_l1']]; sic = m['sic'].fillna(0)
        u = m[(m['mcap_l1'] >= 2e9) & (m['close_raw'] >= 5) & ~sic.between(6000, 6799) & ~sic.between(4900, 4999)].dropna(subset=['f6'])
        if len(u) < 50: continue
        bench = [u[f'f{k}'].mean() for k in range(1, 7)]
        thr = u['fcf_ev'].quantile(0.7); bthr = u['bby'].quantile(0.9)
        good = (u['fcf'] > 0) & (u['ttm_operating_income'] > 0) & (u['fcf_ev'] >= thr) & (u['nd_ebitda'] < 3) & (u['sh_chg'] < 0)
        s = u[(u['bby'] >= bthr) & good]
        med = s['vol'].median()
        for _, rr in s.iterrows():
            path = [rr[f'f{k}'] for k in range(1, 7)]
            if any(pd.isna(path)): continue
            v = rr['vol'] if pd.notna(rr['vol']) else (med if pd.notna(med) else 0.08)
            rows.append({'t': t, 'path': path, 'bench': bench, 'atr': float(v)})
    return rows


def vol_trail(r):
    lvl = np.array(r['path']) + 1; peak = np.maximum.accumulate(np.maximum(lvl, 1.0))
    hit = np.where(lvl[:5] < peak[:5] * (1 - 3 * r['atr']))[0]
    return int(hit[0]) if len(hit) else None


if __name__ == '__main__':
    mon = market()
    report_mkt('Q242a_mkt_voltarget', mon, w_vol, 476)
    report_mkt('Q242b_mkt_halfkelly', mon, w_kelly, 477)
    import q234_sell_rules2 as s2
    gr = s2.gap_rows()
    run_trades('Q242c_gap_atr_size_chandelier', gr, [1 / (3 * r['atr']) for r in gr], s2.chandelier, 478)
    br = bb_rows_vol()
    run_trades('Q242d_bb_risk_size_voltrail', br, [1 / (3 * r['atr']) for r in br], vol_trail, 479)
    OUT.update({k: v for k, v in q.OUT.items() if k.startswith('Q242')})
    json.dump(OUT, open('/mnt/project-files/research/always-on/results/Q242.json', 'w'), indent=1, default=float)
