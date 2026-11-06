"""Q220 bench batch 3: Q200 cheap-crash gated on credit stress (prereg Q220.md). Data to 2022 only."""
import sys, io, contextlib
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
with contextlib.redirect_stdout(io.StringIO()):
    import q200_cheap_crash as q
q.N = 435
F = '/mnt/project-files/research-data/fred/'
baa = pd.read_csv(F + 'BAA.csv', parse_dates=['observation_date']).set_index('observation_date').BAA
aaa = pd.read_csv(F + 'AAA.csv', parse_dates=['observation_date']).set_index('observation_date').AAA
sp = (baa - aaa).dropna(); sp = sp[sp.index <= '2022-12-31']
sp.index = sp.index + pd.offsets.MonthEnd(0)
gate = (sp > sp.rolling(60).median()).shift(1)  # month t uses month t-1 reading
orig = q.df.copy()


def gated(on=True, **kw):
    keep = orig['month'].map(lambda m: bool(gate.get(m, False)) == on)
    q.df = orig.copy()
    q.df.loc[~keep, 'r1'] = 0.0  # no crash event can fire in gated-out months
    try:
        return q.run(**kw)
    finally:
        q.df = orig


print('gate on months (2014-12..2022-09):', int(gate['2014-12-31':'2022-09-30'].sum()), 'of', len(gate['2014-12-31':'2022-09-30']))
q.report('T1 full (credit stress)', *gated())
q.report('T3 ref gate-off', *gated(on=False))
q.report('T4 1m hold', *gated(hold=1))
q.report('T5 >=10bn', *gated(min_cap=1e10))
q.report('T6 costs x2', *gated(cost=2 * q.COST))
q.report('T6 lag entry', *gated(col='lag3'))
