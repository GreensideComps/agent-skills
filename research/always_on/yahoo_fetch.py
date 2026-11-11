"""Free daily OHLC from Yahoo chart API, honest UA, slow; data capped at 2022-12-31 for research (owner approved 11 Nov 2026)."""
import sys, json, time, urllib.request, csv, os
UA = "agent-skills-research/1.0 (https://github.com/greensidecomps/agent-skills)"
END = 1672531200  # 2023-01-01 00:00 UTC


def fetch(sym, out_dir, start=1420070400):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={start}&period2={END}&interval=1d&events=div,split"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    d = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    q = d["indicators"]["quote"][0]; adj = d["indicators"].get("adjclose", [{}])[0].get("adjclose")
    rows = []
    for i, ts in enumerate(d.get("timestamp", [])):
        day = time.strftime("%Y-%m-%d", time.gmtime(ts + d["meta"].get("gmtoffset", 0)))
        if day > "2022-12-31" or q["close"][i] is None: continue
        f = (adj[i] / q["close"][i]) if adj and adj[i] else 1.0
        rows.append([day] + [round(q[k][i] * f, 6) if q[k][i] is not None else "" for k in ("open", "high", "low", "close")] + [q["volume"][i]])
    with open(os.path.join(out_dir, f"{sym}.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date", "adj_open", "adj_high", "adj_low", "adj_close", "volume"]); w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    out = sys.argv[1]
    for s in sys.argv[2:]:
        try: print(s, fetch(s, out))
        except Exception as e: print(s, "ERR", e)
        time.sleep(2)
