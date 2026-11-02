"""Calendar and trend timing rules on US market vs buy and hold.
KF market (CRSP VW total return) + 1m T-bill. Monthly rules on monthly data; 200-day rule on daily data.
Signals use only data up to the prior close. Cost 0.10% per switch (one way)."""
import pandas as pd, numpy as np, math
D='/mnt/project-files/research-data/french/'
COST=0.001
def kf(fn,n):
    rows=[]
    for l in open(D+fn):
        p=[s.strip() for s in l.split(',')]
        if len(p)==5 and len(p[0])==n and p[0].isdigit(): rows.append(p)
        elif rows and n==6 and 'Annual' in l: break
    f=pd.DataFrame(rows,columns=['d','mrf','smb','hml','rf']).astype({'mrf':float,'rf':float})
    f['date']=pd.to_datetime(f.d,format='%Y%m' if n==6 else '%Y%m%d')
    f['mkt']=(f.mrf+f.rf)/100; f['cash']=f.rf/100
    return f[['date','mkt','cash']].reset_index(drop=True)
m=kf('F-F_Research_Data_Factors.csv',6); d=kf('F-F_Research_Data_Factors_daily.csv',8)

def apply(df,inmkt):
    inmkt=pd.Series(inmkt,index=df.index).astype(bool)
    sw=inmkt.ne(inmkt.shift(1)).astype(float); sw.iloc[0]=float(inmkt.iloc[0])
    return np.where(inmkt,df.mkt,df.cash)*1+0 - sw*COST, inmkt.mean(), sw.sum()

rules={}
mo=m.date.dt.month
rules['Skip September']=('m',mo!=9)
rules['Skip Sep and Oct']=('m',~mo.isin([9,10]))
rules['Skip Aug and Sep']=('m',~mo.isin([8,9]))
# rolling worst month: avoid the calendar month with lowest mean excess return over the prior 30 years
ex=m.mkt-m.cash; avoid=[]
for i in range(len(m)):
    past=m.iloc[max(0,i-360):i]; 
    if len(past)<120: avoid.append(True); continue
    mm=(past.mkt-past.cash).groupby(past.date.dt.month).mean()
    avoid.append(m.date.dt.month[i]!=mm.idxmin())
rules['Avoid worst month (rolling 30y)']=('m',pd.Series(avoid))
# trend: price index from total return (close enough; dividends small monthly)
lvl=(1+m.mkt).cumprod()
rules['10-month average']=('m',(lvl>lvl.rolling(10).mean()).shift(1).fillna(True))
rules['12-month momentum']=('m',(lvl/lvl.shift(12)-1>(1+m.cash).cumprod()/(1+m.cash).cumprod().shift(12)-1).shift(1).fillna(True))
dl=(1+d.mkt).cumprod()
rules['200-day average (daily)']=('d',(dl>dl.rolling(200).mean()).shift(1).fillna(True))
rules['50/200-day cross (daily)']=('d',(dl.rolling(50).mean()>dl.rolling(200).mean()).shift(1).fillna(True))

def stats(df,r,per):
    w=(1+pd.Series(r,index=df.index)).cumprod(); yrs=len(r)/per
    ex=pd.Series(r,index=df.index)-df.cash
    return w.iloc[-1]**(1/yrs)-1,(w/w.cummax()-1).min(),ex.mean()/ex.std()*math.sqrt(per)
out=[]
for lo,hi,lab in [('1927-01-01','2022-12-31','1927-2022'),('2007-01-01','2022-12-31','2007-2022'),('2023-01-01','2026-09-30','2023-Sep 2026 (partly seen)')]:
    for name,(fq,sig) in rules.items():
        df=(m if fq=='m' else d); per=12 if fq=='m' else 252
        k=(df.date>=lo)&(df.date<=hi); sub=df[k]; s=sig[k]
        r,inpct,nsw=apply(sub,s.values)
        c,dd,sh=stats(sub,r,per); bc,bdd,bsh=stats(sub,sub.mkt.values,per)
        # yearly win rate
        yr=pd.DataFrame({'y':sub.date.dt.year.values,'s':r,'b':sub.mkt.values}).groupby('y').agg(lambda v:(1+v).prod()-1)
        # t-stat of monthly-ish diff
        diff=pd.Series(r-sub.mkt.values); t=diff.mean()/diff.std()*math.sqrt(len(diff))
        out.append(dict(period=lab,rule=name,cagr=c*100,bh=bc*100,gap=(c-bc)*100,maxdd=dd*100,bh_dd=bdd*100,sharpe=sh,bh_sharpe=bsh,
            win_years=(yr.s>yr.b).mean()*100,pct_invested=inpct*100,trades_per_yr=nsw/(len(sub)/per),t_vs_bh=t))
R=pd.DataFrame(out).round(2); pd.set_option('display.width',250)
print(R.to_string(index=False)); R.to_csv('/mnt/project-files/research/timing-rules/results.csv',index=False)
