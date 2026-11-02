"""Nov-to-Apr/May/Jun S&P-style seasonal vs buy and hold. Monthly data.
1926-2026: Ken French US market (CRSP VW, total return) + 1m T-bill.
1871-1925: Shiller S&P composite (avg monthly prices, divs) + GS10 as cash proxy (no T-bill series).
Cost: COST per switch (one-way), 2 switches/year."""
import pandas as pd, numpy as np, sys
D='/mnt/project-files/research-data/'
COSTS=[0.001,0.0025]
# French
rows=[]
for l in open(D+'french/F-F_Research_Data_Factors.csv'):
    p=[s.strip() for s in l.split(',')]
    if len(p)==5 and len(p[0])==6 and p[0].isdigit(): rows.append(p)
    if 'Annual' in l: break
f=pd.DataFrame(rows,columns=['ym','mrf','smb','hml','rf']).astype(float)
f['date']=pd.to_datetime(f.ym.astype(int).astype(str),format='%Y%m')
f['mkt']=(f.mrf+f.rf)/100; f['cash']=f.rf/100
f=f[['date','mkt','cash']]
# Shiller
x=pd.read_excel(D+'shiller/ie_data.xls',sheet_name='Data',skiprows=7)
x=x[pd.to_numeric(x.Date,errors='coerce').notna()].copy()
x['P']=pd.to_numeric(x.P);x['Dv']=pd.to_numeric(x.D);x['r10']=pd.to_numeric(x['Rate GS10'])
yr=(x.Date.astype(float)).astype(int); mo=((x.Date.astype(float)-yr)*100).round().astype(int)
x['date']=pd.to_datetime(dict(year=yr,month=mo,day=1))
x['mkt']=(x.P+x.Dv/12)/x.P.shift(1)-1; x['cash']=x.r10.shift(1)/100/12
s=x[(x.date<'1926-07-01')&(x.date>='1871-02-01')][['date','mkt','cash']]
s['src']='shiller'; f['src']='french'
m=pd.concat([s,f[f.date>='1926-07-01']]).reset_index(drop=True)

def run(m,last_in,cost):
    inm=m.date.dt.month.isin([11,12]+list(range(1,last_in+1)))
    r=np.where(inm,m.mkt,m.cash)
    # cost on entry (first Nov month) and exit (last in-month)
    entry=(m.date.dt.month==11); exitm=(m.date.dt.month==last_in)
    r=(1+r)*(1-cost*entry)*(1-cost*exitm)-1
    return pd.Series(r,index=m.index)

def stats(r,dates):
    w=(1+r).cumprod(); yrs=len(r)/12
    dd=(w/w.cummax()-1).min()
    return dict(total=w.iloc[-1]-1,cagr=w.iloc[-1]**(1/yrs)-1,maxdd=dd,vol=r.std()*np.sqrt(12))

def report(m,label):
    out=[];m=m.reset_index(drop=True)
    bh=m.mkt
    # season year = Nov..Oct, labelled by Nov year
    sy=np.where(m.date.dt.month>=11,m.date.dt.year,m.date.dt.year-1)
    for last,name in [(4,'Nov-Apr'),(5,'Nov-May'),(6,'Nov-Jun')]:
        for c in COSTS:
            st=run(m,last,c)
            a=stats(st,m.date);b=stats(bh,m.date)
            g=pd.DataFrame({'sy':sy,'s':st,'b':bh}).groupby('sy').agg(lambda v:(1+v).prod()-1)
            g=g[pd.Series(sy).value_counts().sort_index().reindex(g.index)==12]
            win=(g.s>g.b).mean()
            out.append(dict(period=label,strategy=name,cost=c,cagr=a['cagr'],bh_cagr=b['cagr'],
              total=a['total'],bh_total=b['total'],maxdd=a['maxdd'],bh_maxdd=b['maxdd'],
              vol=a['vol'],bh_vol=b['vol'],win_years=win,n_years=len(g)))
    return out
res=[]
P=[('1871-02','2026-09','1871-2026 all'),('1926-07','2022-12','1926-2022 (main, French)'),
   ('1871-02','1926-06','1871-1926 (Shiller, rough)'),('1993-01','2022-12','1993-2022 (SPY era)'),
   ('2007-01','2022-12','2007-2022'),('2023-01','2026-09','2023-Sep 2026 (partly seen)')]
for a,b,l in P:
    res+=report(m[(m.date>=a)&(m.date<=b+'-01')],l)
for d in range(1930,2030,10):
    res+=report(m[(m.date>=f'{d}-01')&(m.date<=f'{d+9}-12-01')],f'{d}s')
R=pd.DataFrame(res)
pd.set_option('display.width',250);pd.set_option('display.max_rows',500)
fmt=R.copy()
for c in ['cagr','bh_cagr','total','bh_total','maxdd','bh_maxdd','vol','bh_vol','win_years']:
    fmt[c]=(R[c]*100).round(1)
print(fmt.to_string(index=False))
R.to_csv('/mnt/project-files/research/seasonal-nov-jun/results.csv',index=False)
# winter vs summer average returns 1926-2022
mm=m[(m.date>='1926-07')&(m.date<='2022-12-01')]
w=mm.date.dt.month.isin([11,12,1,2,3,4]); 

def t(a,b=None):
    import math
    if b is None: return a.mean()/(a.std()/math.sqrt(len(a)))
    return (a.mean()-b.mean())/math.sqrt(a.var()/len(a)+b.var()/len(b))
for lo,hi in [('1926-07','2022-12-01'),('1871-02','2026-09-01'),('2007-01','2022-12-01')]:
    mm=m[(m.date>=lo)&(m.date<=hi)]
    w=mm.date.dt.month.isin([11,12,1,2,3,4])
    print(lo,hi,'winter %.2f%%/mo summer %.2f%%/mo cash-in-summer %.2f%%/mo  t(win-sum)=%.2f  t(summer-cash)=%.2f'%(mm.mkt[w].mean()*100,mm.mkt[~w].mean()*100,mm.cash[~w].mean()*100,t(mm.mkt[w],mm.mkt[~w]),t(mm.mkt[~w]-mm.cash[~w])))
    for last in (4,5,6):
        st=run(mm.reset_index(drop=True),last,0.001); ex=st-mm.cash.values; bx=mm.mkt.values-mm.cash.values
        print('  Sharpe Nov-%d %.2f vs B&H %.2f'%(last,ex.mean()/ex.std()*12**.5,bx.mean()/bx.std()*12**.5))
