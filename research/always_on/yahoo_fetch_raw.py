"""Yahoo raw daily OHLC (split-adjusted, not dividend-adjusted) + dividend events, honest UA, to 2022-12-31."""
import sys, json, time, urllib.request, csv, os
UA = "agent-skills-research/1.0 (https://github.com/greensidecomps/agent-skills)"
END = 1672531200


def fetch(sym, out, start=1388534400):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={start}&period2={END}&interval=1d&events=div,split"
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30))["chart"]["result"][0]
    q = d["indicators"]["quote"][0]; off = d["meta"].get("gmtoffset", 0); adj = d["indicators"].get("adjclose", [{}])[0].get("adjclose")
    day = lambda ts: time.strftime("%Y-%m-%d", time.gmtime(ts + off))
    with open(os.path.join(out, f"{sym}.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "open", "high", "low", "close", "adjclose"])
        for i, ts in enumerate(d.get("timestamp", [])):
            if day(ts) <= "2022-12-31" and q["close"][i] is not None and q["open"][i] is not None:
                w.writerow([day(ts), q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i] if adj else ""])
    divs = d.get("events", {}).get("dividends", {})
    with open(os.path.join(out, f"{sym}_div.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["ex_date", "amount"])
        for v in sorted(divs.values(), key=lambda x: x["date"]):
            if day(v["date"]) <= "2022-12-31": w.writerow([day(v["date"]), v["amount"]])
    return len(divs)


if __name__ == "__main__":
    out = sys.argv[1]; todo = sys.argv[2:]
    for s in todo:
        for k in range(3):
            try: print(s, fetch(s, out), flush=True); break
            except Exception as e:
                print(s, "ERR", e, flush=True)
                if "429" not in str(e): break
                time.sleep(60 * (k + 1))
        time.sleep(6)
