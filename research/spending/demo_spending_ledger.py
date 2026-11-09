"""Paper spending ledger for the T212 DEMO account (owner 9 Nov 2026: apply the spending rule to demo first; Claude decides).
Rule (WITHDRAWAL_PLAN.md): 3.5% a year of the average of the last three yearly values, paid monthly (1/12 per month).
Until three yearly values exist, the average uses the monthly values recorded so far (first month: the current value).
The demo account has no withdraw endpoint, so payouts are paper: each payout 'sells' a proportional slice of the book.
pot_after_spending = account value x product(1 - payout_i / value_i), i.e. the account as if the slices had been taken out.
Run once a month (first run in a month records that month's payout; later runs in the month only report)."""
import json, os, sys, time, datetime as dt
STATE = "/mnt/project-files/market-agent/state/heartbeat.json"
LEDGER = "/mnt/project-files/research/spending/demo_ledger.json"
RATE = 0.035

hb = json.load(open(STATE))
age_h = (time.time() - hb["t"]) / 3600
if age_h > 6: sys.exit(f"heartbeat is {age_h:.1f}h old; mirror the hosted state first (hostctl mirror)")
value = float(hb["total_gbp"]); month = hb["ts"][:7]
led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {"rule": "3.5%/yr of 3-yr average, paid monthly, paper", "entries": []}
E = led["entries"]
if not any(e["month"] == month for e in E):
    jan = [e["value"] for e in E if e["month"].endswith("-01")][-3:]
    base = sum(jan) / len(jan) if len(jan) >= 3 else (sum(e["value"] for e in E[-35:]) + value) / (len(E[-35:]) + 1)
    pay = round(RATE * base / 12, 2)
    E.append({"month": month, "ts": hb["ts"], "value": value, "base": round(base, 2), "payout": pay})
    json.dump(led, open(LEDGER, "w"), indent=1)
keep = 1.0
for e in E: keep *= 1 - e["payout"] / e["value"]
print(json.dumps({"month": month, "account_gbp": value, "paid_out_total_gbp": round(sum(e["payout"] for e in E), 2),
                  "this_month_payout_gbp": E[-1]["payout"], "pot_after_spending_gbp": round(value * keep, 2),
                  "months": len(E)}, indent=1))
