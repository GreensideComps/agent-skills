"""Fetch daily adjusted prices from Tiingo (owner's free key) for the Q183 universe.
Free tier: 50 requests/hour, 1000/day, 500 symbols/month -> run once per hourly wake, <=45 symbols.
Data is truncated at 2022-12-31 (holdout 2023-26 is never downloaded here).
Token is read from /mnt/project-files/market-agent/state/tiingo_token.txt (never committed)."""
import os, sys, json, time, urllib.request, pandas as pd
sys.path.insert(0, '/mnt/project-files/research/improve')
from tiingo_meter import record  # E10: shared monthly Tiingo bandwidth meter
D = '/mnt/project-files/research-data/'
OUT = D + 'tiingo_daily/'
TOK = open('/mnt/project-files/market-agent/state/tiingo_token.txt').read().strip()
END = '2022-12-31'
def universe(n=450):
    k = pd.read_csv(D + '8k_items_large_2013_2026.csv.gz')
    e = k[k['items'].astype(str).str.contains('2.02') & (k.date <= END)]
    p = pd.read_csv(D + 'prices_monthly.csv.gz', usecols=['cik', 'ticker', 'month'])
    m = p[p.cik.isin(e.cik)].sort_values('month').groupby('cik').ticker.last()
    m = m.sort_index().iloc[:n]
    return [('SPY', 0)] + [(t, c) for c, t in m.items()]
def fetch(t):
    u = f'https://api.tiingo.com/tiingo/daily/{t.lower().replace(".", "-")}/prices?startDate=2012-06-01&endDate={END}&format=csv&columns=date,close,adjClose,adjOpen,adjVolume,divCash,splitFactor'
    r = urllib.request.Request(u, headers={'Authorization': 'Token ' + TOK})
    b = urllib.request.urlopen(r, timeout=60).read()
    record(len(b))
    return b
if __name__ == '__main__':
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    done = 0; log = open(OUT + 'fetch_log.txt', 'a')
    for t, c in universe():
        f = OUT + f'{c}_{t}.csv'
        if os.path.exists(f) or os.path.exists(f + '.err'): continue
        if done >= lim: break
        try:
            b = fetch(t); open(f, 'wb').write(b); log.write(f'{t} ok {len(b)}\n')
        except Exception as ex:
            msg = str(ex); log.write(f'{t} err {msg}\n')
            if '429' in msg or 'limit' in msg.lower(): break
            open(f + '.err', 'w').write(msg)
        done += 1; time.sleep(1)
    n = len([x for x in os.listdir(OUT) if x.endswith('.csv')])
    print('fetched this run', done, 'files total', n)
