"""Q203 earnings gap-down on growing, cash-generative stocks. Prereg /mnt/project-files/research/always-on/prereg/Q203.md."""
import os, sys, math, numpy as np, pandas as pd
from statistics import NormalDist
sys.path.insert(0, os.path.dirname(__file__))
from q183_ear_drift import load, liquid, events, portfolio, stats, D, COST
N = 422; ND = NormalDist()
R = load(); e = events(R); L = liquid(R.index)
mm = pd.read_csv(D + 'monthly_metrics.csv.gz', usecols=['cik', 'month', 'ttm_revenue', 'ttm_ocf', 'ttm_capex', 'shares_out'], parse_dates=['month'])
mm = mm[mm.cik.isin(R.columns)].sort_values(['cik', 'month'])
mm['rev12'] = mm.groupby('cik')['ttm_revenue'].shift(12)
mm['fcf'] = mm['ttm_ocf'] - mm['ttm_capex'].abs()
pm = pd.read_csv(D + 'prices_monthly.csv.gz', usecols=['cik', 'month', 'close_raw'], parse_dates=['month'])
mm = mm.merge(pm, on=['cik', 'month'], how='left'); mm['mcap'] = mm['close_raw'] * mm['shares_out']
e['date'] = R.index[e.i]
e['me'] = e['date'] - pd.offsets.MonthEnd(1)
e = e.merge(mm[['cik', 'month', 'ttm_revenue', 'rev12', 'fcf', 'mcap']].rename(columns={'month': 'me'}), on=['cik', 'me'], how='left')
e['liq'] = [bool(L[c].iloc[i]) if c in L else False for c, i in zip(e.cik, e.i)]
gap = (e.ear <= -0.10) & e.liq
good = (e.fcf > 0) & (e.ttm_revenue > e.rev12)
sel, ctl = gap & good, gap & ~good
print('events', len(e), 'gap', int(gap.sum()), 'sel', int(sel.sum()), 'ctrl', int(ctl.sum()))
Rv = R.values; spy = R[0].values
def trade_level(s, H, lag=0, cost=COST):
    out = []
    for c, i in zip(e.cik[s], e.i[s]):
        a = i + 2 + lag + 1
        if a + H > len(R): continue
        j = list(R.columns).index(c)
        x = np.nansum(Rv[a:a + H, j]) - np.nansum(spy[a:a + H])
        out.append(x - cost)
    return np.array(out)
def dsr(st):
    T = st['n_months']; sr = st['sr_m']; g = 0.5772
    emax = math.sqrt(1 / T) * ((1 - g) * ND.inv_cdf(1 - 1 / N) + g * ND.inv_cdf(1 - 1 / (N * math.e)))
    return ND.cdf((sr - emax) * math.sqrt(T - 1))
def show(name, s, H=60, lag=0, cost=COST):
    st = stats(portfolio(R, e, H, s, lag=lag, cost=cost)); tl = trade_level(s, H, lag, cost)
    thirds = [round(x.mean() * 1200, 1) for x in np.array_split(st['m'], 3)]
    t = tl.mean() / tl.std() * math.sqrt(len(tl)) if len(tl) > 1 else float('nan')
    print(f"{name}: trades {len(tl)} trade net {tl.mean()*100:+.2f}% (t {t:.2f}) hit {(tl>0).mean()*100:.0f}% | port {st['ann']:+.2f}%/yr t {st['t']} DSR {dsr(st):.4f} thirds {thirds}")
show('T1 full', sel)
show('control (fails fundamentals)', ctl)
show('T4 20d hold', sel, H=20)
show('T5 mcap>=10bn', sel & (e.mcap >= 1e10))
show('T6 costs x2', sel, cost=2 * COST)
show('T6 lag 1 day', sel, lag=1)
spyl = (1 + pd.Series(spy, index=R.index).fillna(0)).cumprod(); bull = (spyl > spyl.rolling(200).mean()).values
show('T3 bull', sel & pd.Series(bull[e.i], index=e.index)); show('T3 bear', sel & ~pd.Series(bull[e.i], index=e.index))
