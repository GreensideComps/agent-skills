"""Q219 bench batch 2: momentum gated on calm uptrend (prereg /mnt/project-files/research/always-on/prereg/Q219.md).
Data to 2022-12-31 only."""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stock_screener'))
import pick1 as p1

N = 434; COST = 0.003
D = '/mnt/project-files/research-data/'
spy = pd.read_csv(D + 'tiingo_etf/SPY.csv', usecols=['date', 'adjClose'], parse_dates=['date']).set_index('date').adjClose
if spy.index.tz is not None:
    spy.index = spy.index.tz_localize(None)
spy_m = spy[spy.index <= '2022-12-31'].resample('ME').last()
vix = pd.read_csv(D + 'fred/VIXCLS.csv', parse_dates=['observation_date'], na_values='.').set_index('observation_date').VIXCLS
vix_m = vix[vix.index <= '2022-12-31'].ffill().resample('ME').last()
GATE = (spy_m > spy_m.rolling(10).mean()) & (vix_m < 25)

df = p1.load()
df = df[(df.month >= '2010-12-31') & (df.month <= '2022-12-31')]
by = {m: g for m, g in df.groupby('month')}
months = sorted(by)


def run(top=0.10, min_cap=2e9, cost=COST, lag=0, gate='on'):
    rows, prev = [], set()
    for k, m in enumerate(months[:-1]):
        if m > pd.Timestamp('2022-11-30'):
            break
        mg = months[k - lag] if k - lag >= 0 else None
        if mg is None:
            continue
        g_on = bool(GATE.get(mg, False))
        u = p1.universe(by[mg], min_cap).dropna(subset=['mom'])
        cur = p1.universe(by[m], min_cap).dropna(subset=['ret_next'])
        ew = cur['ret_next'].mean()
        active = {'on': g_on, 'off': not g_on, 'all': True}[gate]
        if not active or len(u) < 50:
            hold = set()
        else:
            hold = set(u.nlargest(max(1, int(len(u) * top)), 'mom')['cik'])
        r = cur.set_index('cik')['ret_next'].reindex(list(hold)).fillna(0.0).mean() if hold else ew
        turn = len(hold ^ prev) / max(len(hold), len(prev), 1) if (hold or prev) else 0.0
        ex = (r - ew) - cost * turn * (2 if (bool(hold) != bool(prev)) else 1)
        rows.append({'month': m, 'ex': ex, 'on': bool(hold)})
        prev = hold
    s = pd.DataFrame(rows).set_index('month')
    return s


def st(s):
    x = p1.stats(s['ex']); x['dsr'] = p1.dsr(x, N); return x


if __name__ == '__main__':
    out = {}
    s = run()
    on = s[s.on]['ex']
    out['T1'] = {**st(s), 'months_on': int(s.on.sum()), 'mean_on_month': float(on.mean())}
    out['T2'] = [float(x.mean() * 12) for x in np.array_split(s['ex'].values, 3)]
    out['T3_ungated'] = {'ann': float(run(gate='all')['ex'].mean() * 12)}
    off = run(gate='off'); out['T3_gate_off_months'] = {'mean_on_month': float(off[off.on]['ex'].mean())}
    out['T4_top20'] = {'ann': float(run(top=0.2)['ex'].mean() * 12)}
    out['T5_10bn'] = {'ann': float(run(min_cap=1e10)['ex'].mean() * 12)}
    out['T6_cost2'] = {'ann': float(run(cost=2 * COST)['ex'].mean() * 12)}
    out['T6_lag1'] = {'ann': float(run(lag=1)['ex'].mean() * 12)}
    print(json.dumps(out, indent=1, default=float))
    json.dump(out, open('/mnt/project-files/research/always-on/results/Q219.json', 'w'), indent=1, default=float)
