# Research agenda: living backlog

The research routine works through this file top-down: it picks the highest-priority
`OPEN` item, follows [`LOOP.md`](LOOP.md), and updates the item's status and log. New
ideas are appended with a priority and a pre-registration. Status values:
`OPEN`, `IN PROGRESS`, `DONE: rejected`, `DONE: promising → shadow`, `DONE: promoted`, `BLOCKED (reason)`.

**Champion:** `momentum_tilt_v1` (50% VWRPl_EQ / 50% IWMOl_EQ), live since 2026-10-13.
**Trial counter (all hypotheses, all configs, for deflated Sharpe):** 53 as of round 1.

---

## P1: Volatility-managed momentum sleeve
- **Status:** OPEN
- **Rationale:** Momentum crashes are predictable from momentum's own recent volatility (Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016). Scaling momentum exposure down when its realised volatility is high has raised the Sharpe ratio in published tests.
- **Implementation:** each month, momentum sleeve weight = clip(target_vol / realised_vol(IWMO − VWRP, 6m), 0.25, 0.75). The rest goes to VWRP. Long-only, no leverage.
- **Data:** Ken French US 10 momentum deciles (1927–2026) and Developed WML (1990–2026) for history; IWFM/IWMO 2014–2026 for the tradeable check.
- **Pre-registered grid:** target_vol ∈ {6%, 8%, 10%} on relative returns; lookback ∈ {6} months. In-sample to 2000, out-of-sample 2001–2026 for US; Developed in-sample 1991–2005, out-of-sample 2006–2026.
- **Log:** (none yet)

## P2: Momentum sleeve with an absolute trend filter (crash insurance)
- **Status:** OPEN
- **Rationale:** Trend filters halved drawdowns over a century (round 1). Applying one only to the high-beta sleeve might keep most of the premium while cutting crash risk.
- **Rule:** if world equity's 10-month SMA signal is off, the momentum sleeve moves to VWRP. A variant moves it to cash (ERNS).
- **Log:** (none yet)

## P3: Cheaper or better momentum vehicle
- **Status:** OPEN
- **Rationale:** IWMO costs a 0.15% FX fee each way. A GBP/GBX-listed world momentum ETF on Trading 212, or one with lower costs or better tracking, is a pure implementation gain.
- **Task:** search `instruments.json` for momentum UCITS ETFs (e.g. Xtrackers, Invesco, JPM, Amundi), then compare tracking against the MSCI World Momentum index, OCF, spread proxy and currency line.
- **Log:** (none yet)

## P4: Quality + momentum combination
- **Status:** OPEN
- **Rationale:** Quality is a crash hedge for momentum (negative correlation in drawdowns). Profitability (RMW) is still significant in developed markets after 2010 (t=2.0, round 1).
- **Rule:** sleeve = 50% IWMO + 50% IWQU (or the GBP line), vs the champion.
- **Log:** (none yet)

## P5: Fill-quality and timing study (operations)
- **Status:** OPEN (needs ≥ 20 fills)
- **Question:** do fills at 10:00 London beat 14:00, when the US is open? Do slippage and the cash hold vary by time?
- **Data:** `trading/journal/events.jsonl` `order_reconciled` records.
- **Log:** (none yet)

## P6: Post-earnings-announcement drift
- **Status:** BLOCKED (needs point-in-time earnings surprises: LSEG/Daloopa connectors unauthorised, SEC EDGAR returned 403 to plain requests). Retry EDGAR with a compliant `User-Agent` including contact details. Use XBRL `frames` to build a seasonal-random-walk SUE.
- **Prior:** large decay after 2000 in large caps (Martineau 2022). Low expected value at £100 scale because of FX fees on US single stocks.

## P7: Longer MSCI factor-index history
- **Status:** OPEN
- **Task:** find a free, legitimate source for MSCI World Momentum/Quality index levels back to 1994–1999 (MSCI end-of-day index search, iShares factsheet data). That would give an independent long test of the champion.

## P8: Generate new hypotheses (recurring)
- **Status:** RECURRING (every 5th research run)
- **Task:** scan recent factor/asset-allocation literature (SSRN, NBER, Alpha Architect, Research Affiliates, AQR) for ideas that are implementable with Trading 212 UCITS ETFs at £100. Add each with a pre-registration. Prefer ideas with an economic rationale and out-of-sample evidence after publication.

---

## Closed (round 1, see REPORT.md)
- Trend following / time-series momentum as a return enhancer: **rejected** (insurance only).
- Cross-asset rotation, risk parity, volatility targeting: **rejected** out-of-sample.
- Value and minimum-volatility factor ETFs: **rejected**.
- Short-term mean reversion (RSI-2, down-day streaks): **rejected**.
- GEM-12 dual momentum: **shadow** (portfolio C), not promoted (p=0.15).
