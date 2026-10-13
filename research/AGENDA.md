# Research agenda: living backlog

The research routine works through this file top-down: it picks the highest-priority
`OPEN` item, follows [`LOOP.md`](LOOP.md), and updates the item's status and log. New
ideas are appended with a priority and a pre-registration. Status values:
`OPEN`, `IN PROGRESS`, `DONE: rejected`, `DONE: promising → shadow`, `DONE: promoted`, `BLOCKED (reason)`.

**Champion:** `nasdaq3x_trend_sma100_v1` (100% `LQQ3l_EQ` 3x Nasdaq-100 while QQQ > its 100-day SMA, else cash), from the 2026-10-13 reset to £500. Owner-directed override of the promotion gate (E009). Previous champion `momentum_tilt_v1` (50/50 VWRP/IWMO) is now shadow D.
**Trial counter (all hypotheses, all configs, for deflated Sharpe):** 106 (53 round 1 + 18 in E006/E007 + 4 in E008 + 3 in E009 + 2 in E010 + 12 in E011 + 14 in E012, 2026-10-13).

---

## P1: Volatility-managed momentum sleeve
- **Status:** DONE: rejected (2026-10-13, E006)
- **Rationale:** Momentum crashes are predictable from momentum's own recent volatility (Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016). Scaling momentum exposure down when its realised volatility is high has raised the Sharpe ratio in published tests.
- **Implementation:** each month, momentum sleeve weight = clip(target_vol / realised_vol(IWMO − VWRP, 6m), 0.25, 0.75). The rest goes to VWRP. Long-only, no leverage.
- **Data:** Ken French US 10 momentum deciles (1927–2026) and Developed WML (1990–2026) for history; IWFM/IWMO 2014–2026 for the tradeable check.
- **Pre-registered grid:** target_vol ∈ {6%, 8%, 10%} on relative returns; lookback ∈ {6} months. In-sample to 2000, out-of-sample 2001–2026 for US; Developed in-sample 1991–2005, out-of-sample 2006–2026.
- **Status update:** DONE: rejected (2026-10-13, E006, `research/h01_momentum_sleeve.py`)
- **Log:** 2026-10-13: momentum proxy = Ken French large-cap top-30% momentum (BIG HiPRIOR). Out-of-sample vs champion: US dCAGR +0.04% (p=0.45), Developed +0.24% (p=0.19); deflated Sharpe of the active return 0.21 / 0.46. In practice the rule mostly holds 70–75% momentum, i.e. it is a bigger static tilt, not crash timing. Fails: oos_beats, DSR, costs ×3 (US), neighbours (US).

## P2: Momentum sleeve with an absolute trend filter (crash insurance)
- **Status:** DONE: insurance only (2026-10-13, E007)
- **Rationale:** Trend filters halved drawdowns over a century (round 1). Applying one only to the high-beta sleeve might keep most of the premium while cutting crash risk.
- **Rule:** if world equity's 10-month SMA signal is off, the momentum sleeve moves to VWRP. A variant moves it to cash (ERNS).
- **Log:** 2026-10-13 (E007): in-sample pick = to-cash variant in both markets. Out-of-sample CAGR is *lower* than the champion (US -0.15%/yr, Developed -0.90%/yr), so it fails the gate. But max drawdown falls from -49% to -29% (US) and -53% to -38% (Developed), and the bootstrap chance of a ≥50% fall within 10 years drops from 18% to 3% (US). Classified INSURANCE_ONLY: a candidate only if the owner prefers smaller drawdowns over return.

## P3: Cheaper or better momentum vehicle
- **Status:** DONE: no change now (2026-10-13). Revisit on the next full rebalance, or if capital > £1,000.
- **Rationale:** IWMO costs a 0.15% FX fee each way. A GBP/GBX-listed world momentum ETF on Trading 212, or one with lower costs or better tracking, is a pure implementation gain.
- **Task:** search `instruments.json` for momentum UCITS ETFs (e.g. Xtrackers, Invesco, JPM, Amundi), then compare tracking against the MSCI World Momentum index, OCF, spread proxy and currency line.
- **Log:** 2026-10-13: Trading 212 lists the same iShares fund (IE00BP3QZ825) as `IWFM_EQ` (GBX, no FX fee), alongside `IWMOl_EQ` (USD) and `IS3Rd_EQ` (EUR). Xtrackers MSCI World Momentum is listed as `XDEMl_EQ` (GBX). Note: GBX/GBP tickers are not always `…l_EQ`, so search by name and currency, not suffix. A switch from IWMO to IWFM costs about £0.10–0.15 in spread (the exit FX fee is paid either way) and saves the 0.15% fee only on future rebalance trades (≈£0.01/yr at £100), so it breaks even only after more than 10 years. **Decision:** keep IWMO and use `IWFM_EQ` (Yahoo `IWFM.L`) at the next full rebalance. Open follow-up: compare XDEM vs IWFM (different index methodology? OCF and tracking).

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
