"""Q236 sell-rule batch 3: portfolio-level risk rules (prereg /mnt/project-files/research/always-on/prereg/Q236.md)."""
import os, sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import q221_exit_rules as q
import q231_sell_rules as s1
COST = 0.003; OUT = {}


def bb_series():
    rows = s1.bb_rows(); acc = {}
    for r in rows:
        p = [0.0] + list(r['path']); b = [0.0] + list(r['bench'])
        for k in range(1, 7):
            m = (r['t'] + pd.offsets.MonthEnd(k))
            ex = (1 + p[k]) / (1 + p[k - 1]) - (1 + b[k]) / (1 + b[k - 1]) - 2 * COST / 6
            acc.setdefault(m, []).append(ex)
    return pd.Series({m: np.mean(v) for m, v in acc.items()}).sort_index()


def p1_series():
    d = pd.read_csv('/mnt/project-files/research/improve/q199_monthly_series.csv', parse_dates=['month'])
    d = d[d['month'] <= '2022-12-31']
    return pd.Series((d['port'] - d['univ']).values, index=d['month'])


def w_kill(x):
    cum = (1 + x).cumprod(); dd = cum / cum.cummax() - 1
    return (dd > -0.10).astype(float).shift(1).fillna(1.0)


def w_vol(x):
    sig = x.rolling(6).std(); tgt = sig.expanding().median()
    w = np.minimum(1.0, tgt / sig).where(np.arange(len(x)) >= 12, 1.0).fillna(1.0)
    return w.shift(1).fillna(1.0)


def evaluate(name, x, wfn, n, cost=COST, lag=0):
    w = wfn(x)
    if lag: w = w.shift(lag).fillna(1.0)
    rule = w * x - cost * w.diff().abs().fillna(0.0)
    return rule - x, rule


def maxdd(x):
    c = (1 + x).cumprod(); return float((c / c.cummax() - 1).min())


def run(name, x, wfn, n):
    d, rule = evaluate(name, x, wfn, n)
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std(ddof=1) > 0 else float('nan')
    th = [float(v.mean()) for v in np.array_split(d.values, 3)]
    r = {'months': len(d), 'months_reduced': int((wfn(x) < 1).sum()), 'mean_d_pct_m': float(d.mean() * 100), 't': float(t),
         'dsr': q.dsr_m(d.values, n), 'thirds_pct_m': [round(v * 100, 3) for v in th],
         'costs2_mean_d_pct_m': float(evaluate(name, x, wfn, n, cost=2 * COST)[0].mean() * 100),
         'lag_mean_d_pct_m': float(evaluate(name, x, wfn, n, lag=1)[0].mean() * 100),
         'plain_mean_pct_m': float(x.mean() * 100), 'maxdd_plain': maxdd(x), 'maxdd_rule': maxdd(rule)}
    OUT[name] = r; print(name, json.dumps(r))


if __name__ == '__main__':
    bb, p1s = bb_series(), p1_series()
    run('Q236a_bb_kill', bb, w_kill, 462); run('Q236b_bb_vol', bb, w_vol, 463)
    run('Q236c_p1_kill', p1s, w_kill, 464); run('Q236d_p1_vol', p1s, w_vol, 465)
    json.dump(OUT, open('/mnt/project-files/research/always-on/results/Q236.json', 'w'), indent=1)
