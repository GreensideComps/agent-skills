import json, sys, time
sys.path.insert(0, "/home/user/agent-skills/equity")
from equity.prices import _get
from equity.portfolio import parse_daily
ev = json.load(open("/mnt/project-files/portfolio/audit/evidence.json"))
syms = {}
for t in ev["rows"]:
    syms[t] = t[:-6].replace(".", "-") if t.endswith("_US_EQ") else t[:-4] + ".L"
syms["FB_US_EQ"] = "META"; syms["SPCX_US_EQ"] = "SPCX"
for x in ["VWRP.L", "QQQ", "SPY", "ACWI", "SOXX", "GBPUSD=X", "IBTA.L"]:
    syms[x] = x
U = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5y&interval=1d&events=div%2Csplits"
out, meta, fail = {}, {}, {}
for t, s in syms.items():
    try:
        b = _get(U.format(sym=s)); res = json.loads(b)["chart"]["result"][0]
        out[t] = parse_daily(b); meta[t] = {"symbol": s, "currency": res["meta"].get("currency"), "first": min(out[t]), "last": max(out[t]), "n": len(out[t])}
    except Exception as e:
        fail[t] = f"{s}: {type(e).__name__} {e}"[:200]
    time.sleep(0.3)
json.dump({"retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": "Yahoo Finance chart API (unofficial), adjclose, range=5y daily",
           "meta": meta, "failed": fail, "closes": out}, open("/tmp/claude-0/-home-user-agent-skills/e3962bd6-0eb3-5260-a6e4-5b7d7758e396/scratchpad/px5y.json", "w"))
for t, m in meta.items(): print(t, m)
print("FAILED", fail)
