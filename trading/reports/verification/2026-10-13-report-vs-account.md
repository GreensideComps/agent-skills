# Report verification: 2026-10-13

Stored report generated 2026-10-13T13:20:39+00:00; raw API re-fetched 2026-10-13T13:33:52+00:00 (read-only client).
Independent code path: `t212bot/verify.py` does not use the report's calculation modules.

**Result: ALL CHECKS PASS** (37 pass, 0 fail, 2 informational)

| Check | Report | Independent (raw API) | Status | Note |
|---|---|---|---|---|
| Cash available | 1.52 | 1.52 | PASS |  |
| Cash reserved for orders | 0.0 | 0.0 | PASS |  |
| Cash in pies | 0.0 | 0.0 | PASS |  |
| Holdings: same instruments | ["IWMOl_EQ", "VWRPl_EQ"] | ["IWMOl_EQ", "VWRPl_EQ"] | PASS |  |
| IWMOl_EQ: quantity | 0.5568 | 0.5568 | PASS |  |
| IWMOl_EQ: cost basis £ | 49.23 | 49.23 | PASS |  |
| IWMOl_EQ: value £ (report time vs now) | 48.76 | 48.6 | PASS | price 116.05 -> 115.69; report value x price ratio = £48.61 (±0.3% allowed for FX) |
| IWMOl_EQ: report value = cost + unrealised | 48.76 | 48.76 | PASS |  |
| VWRPl_EQ: quantity | 0.3359 | 0.3359 | PASS |  |
| VWRPl_EQ: cost basis £ | 49.18 | 49.18 | PASS |  |
| VWRPl_EQ: value £ (report time vs now) | 49.01 | 49.03 | PASS | price 145.901 -> 145.979; report value x price ratio = £49.04 |
| VWRPl_EQ: report value = cost + unrealised | 49.01 | 49.01 | PASS |  |
| Report: invested = Σ holding values | 97.77 | 97.77 | PASS |  |
| Report: total = cash + invested | 99.29 | 99.29 | PASS |  |
| Report: gain = total − net contributions | -0.71 | -0.71 | PASS |  |
| Report: Σ unrealised = unrealised P&L | -0.64 | -0.64 | PASS |  |
| Total value now (informational) | 99.29 | 99.15 | INFO | differs only by market moves since the report |
| Total cost basis | 98.41 | 98.41 | PASS |  |
| Realised P&L | 0.0 | 0.0 | PASS |  |
| Deposits | 100.0 | 100.0 | PASS |  |
| Withdrawals | 0.0 | 0.0 | PASS |  |
| Dividends | 0.0 | 0.0 | PASS |  |
| Interest / cashback | 0.0 | 0.0 | PASS |  |
| Transactions of other types | 0 | 0 | PASS | none |
| Orders: same set | 3 | 3 | PASS |  |
| Order 56400858289 (IWMOl_EQ BUY) | "FILLED 0.5568 @ 117.02, net £49.3, fees £0.07" | "FILLED 0.5568 @ 117.02, net £49.3, fees £0.07" | PASS |  |
| Order 56400858303 (VWRPl_EQ BUY) | "FILLED 0.319 @ 146.42, net £46.71, fees £0.0" | "FILLED 0.319 @ 146.42, net £46.71, fees £0" | PASS |  |
| Order 56400858343 (VWRPl_EQ BUY) | "FILLED 0.0169 @ 146.42, net £2.47, fees £0.0" | "FILLED 0.0169 @ 146.42, net £2.47, fees £0" | PASS |  |
| Pending orders | 0 | 0 | INFO | live state now; may legitimately differ |
| Trading fees total | 0.07 | 0.07 | PASS |  |
| Fees by type | {"CURRENCY_CONVERSION_FEE": 0.07} | {"CURRENCY_CONVERSION_FEE": 0.07} | PASS |  |
| VWRPl_EQ: quantity = Σ fills | 0.3359 | 0.3359 | PASS |  |
| IWMOl_EQ: quantity = Σ fills | 0.5568 | 0.5568 | PASS |  |
| Cash ledger: deposits − buys + sells + income | 1.52 | 1.52 | PASS | £100.00 − £98.48 + £0.00 + £0.00; fill netValue already includes FX fees |
| Time-weighted return | -0.0071 | -0.0071 | PASS | chain-linked over 11 journal snapshots; flows from raw transactions |
| Max drawdown | -0.0072 | -0.0072 | PASS |  |
| Adviser code has no client, order or network calls | "none" | "none" | PASS |  |
| Read-only client allowlist contains no order methods | ["account_summary", "exchanges", "history_dividends", "history_orders", "history_transactions", "instruments", "pending_orders", "positions"] | "none" | PASS |  |
| Trading 212 API has no money-movement endpoint | "17 paths in spec" | "none" | PASS | source: t212_openapi.yaml |
