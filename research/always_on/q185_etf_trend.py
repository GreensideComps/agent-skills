"""Q185 cross-asset ETF trend (pre-registered: prereg/Q185.md). Tiingo, data truncated at 2022-12-31."""
import os, sys, urllib.request, io, numpy as np, pandas as pd
from statistics import NormalDist
D = '/mnt/project-files/research-data/tiingo_etf/'; os.makedirs(D, exist_ok=True)
TOK = open('/mnt/project-files/market-agent/state/tiingo_token.txt').read().strip()
ETF = ['TLT', 'IEF', 'GLD', 'DBC', 'EFA', 'SPY']; COST = 0.003
def get(t):
    f = D + t + '.csv'
    if not os.path.exists(f):
        u = f'https://api.tiingo.com/tiingo/daily/{t}/prices?startDate=2006-01-01&endDate=2022-12-31&format=csv&columns=date,adjClose'
        open(f, 'wb').write(urllib.request.urlopen(urllib.request.Request(u, headers={'Authorization': 'Token ' + TOK}), timeout=60).read())
    s = pd.read_csv(f, parse_dates=['date']).set_index('date').adjClose
    return s[s.index <= '2022-12-31'].resample('ME').last()
P = pd.DataFrame({t: get(t) for t in ETF}).dropna(); r = P.pct_change()
sig = (P / P.shift(12) - 1 > 0).astype(float)
def run(lag=0, cost=COST):
    w = (sig.shift(1 + lag) / len(ETF)).loc['2008-02':'2022-12']
    rr = r.loc[w.index]; gross = (w * rr).sum(1)
    tc = w.diff().abs().sum(1).fillna(w.iloc[0].abs().sum()) * cost / 2
    bench = rr.mean(1); return gross - tc, bench
s, b = run(); ex = s - b; T = len(ex); sr = ex.mean() / ex.std()
N = int(sys.argv[1]); nd = NormalDist(); g = 0.5772
emax = np.sqrt(1 / T) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * np.e)))
dsr = nd.cdf((sr - emax) * np.sqrt(T - 1))
th = [x.mean() > 0 for x in np.array_split(ex, 3)]
c2 = (run(cost=2 * COST)[0] - b).mean() * 12; l1 = (run(lag=1)[0] - b).mean() * 12
def dd(x): c = (1 + x).cumprod(); return (c / c.cummax() - 1).min()
spy = r.SPY.loc[s.index]
print(f"months {T} ex/yr {ex.mean()*1200:.2f}% t {sr*np.sqrt(T):.2f} thirds+ {sum(th)}/3 cost2 {c2*100:.2f}% lag1 {l1*100:.2f}% DSR {dsr:.3f}")
for n, x in (('trend', s), ('EW hold', b), ('SPY', spy)):
    print(f"  {n}: CAGR {((1+x).prod()**(12/T)-1)*100:.1f}% Sharpe {x.mean()/x.std()*np.sqrt(12):.2f} maxDD {dd(x)*100:.0f}%")
