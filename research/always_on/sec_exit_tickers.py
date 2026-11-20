"""S11 prep: recover the old trading symbol of each SEC filer that stopped filing 2012-22 (research-data/sec_exits.json),
from dei:TradingSymbol in its last XBRL 10-K/10-Q instance on EDGAR. Output research-data/sec_exit_tickers.csv.
The SEC User-Agent is read from the market-agent state file at run time and never stored in the repo."""
import json, re, time, csv, sys, urllib.request
import pandas as pd
D = '/mnt/project-files/research-data'
UA = open('/mnt/project-files/market-agent/state/sec_user_agent.txt').read().strip()
OUT = f'{D}/sec_exit_tickers.csv'


def get(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Encoding': 'identity'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:
            if getattr(e, 'code', None) == 404: return None
            time.sleep(2 * (k + 1))
    return None


exits = json.load(open(f'{D}/sec_exits.json'))
f = pd.read_csv(f'{D}/sec_facts_panel.csv.gz', usecols=['cik', 'filed', 'form', 'accn'], dtype={'cik': str})
f = f[f.cik.isin(exits.keys()) & f.form.isin(['10-K', '10-Q', '10-K/A', '10-Q/A'])]
last = f.sort_values('filed').groupby('cik').tail(3)  # up to 3 latest filings to try
done = {}
try:
    for r in csv.DictReader(open(OUT)): done[r['cik']] = r
except FileNotFoundError:
    pass
rows = list(done.values())
for cik, g in last.groupby('cik'):
    if cik in done: continue
    sym, src = '', ''
    for accn, filed in zip(g.accn[::-1], g.filed[::-1]):
        idx = get(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace("-", "")}/index.json'); time.sleep(0.25)
        if not idx: continue
        names = [i['name'] for i in json.loads(idx)['directory']['item']]
        inst = [n for n in names if n.endswith('.xml') and not re.search(r'_(cal|def|lab|pre)\.xml$|FilingSummary|^R\d', n)]
        for n in inst[:2]:
            body = get(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace("-", "")}/{n}'); time.sleep(0.25)
            m = body and re.search(rb'<dei:TradingSymbol[^>]*>\s*([^<\s]+)\s*<', body)
            if m: sym, src = m.group(1).decode().upper(), f'{accn} {filed}'; break
        if sym: break
    rows.append({'cik': cik, 'name': exits[cik]['name'], 'class': exits[cik]['class'], 'last': exits[cik]['last'], 'ticker': sym, 'source': src})
    if len(rows) % 25 == 0:
        pd.DataFrame(rows).to_csv(OUT, index=False); print(len(rows), sum(1 for r in rows if r['ticker']), flush=True)
pd.DataFrame(rows).to_csv(OUT, index=False)
print('done', len(rows), 'with ticker', sum(1 for r in rows if r['ticker']))
