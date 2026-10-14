# Research agenda: living backlog

The research routine works through this file top-down: it picks the highest-priority
`OPEN` item, follows [`LOOP.md`](LOOP.md), and updates the item's status and log. New
ideas are appended with a priority and a pre-registration. Status values:
`OPEN`, `IN PROGRESS`, `DONE: rejected`, `DONE: promising → shadow`, `DONE: promoted`, `BLOCKED (reason)`.

**Champion:** `nasdaq3x_trend_sma100_v1` (100% `LQQ3l_EQ` 3x Nasdaq-100 while QQQ > its 100-day SMA, else cash), from the 2026-10-13 reset to £500. Owner-directed override of the promotion gate (E009). Previous champion `momentum_tilt_v1` (50/50 VWRP/IWMO) is now shadow D.
**Trial counter (all hypotheses, all configs, for deflated Sharpe):** 126 (53 round 1 + 18 in E006/E007 + 4 in E008 + 3 in E009 + 2 in E010 + 12 in E011 + 14 in E012, 2026-10-13; + 14 in E013, + 6 in E014, 2026-10-14).

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
- **Status:** DONE: rejected (2026-10-14, E013)
- **Rationale:** Quality is a crash hedge for momentum (negative correlation in drawdowns). Profitability (RMW) is still significant in developed markets after 2010 (t=2.0, round 1).
- **Rule:** sleeve = 50% IWMO + 50% IWQU (or the GBP line), vs the champion.
- **Pre-registration (frozen 2026-10-14, before any out-of-sample result; script `research/h07_quality_momentum.py`):**
  - Data (Ken French, survivorship-free, value-weighted USD): MKT = Mkt-RF+RF; MOM = BIG HiPRIOR (6_Portfolios_ME_Prior_12_2); QUAL = BIG HiOP (6_Portfolios_ME_OP_2x3, robust profitability); Developed equivalents. Tradeable check: VWRL.L / IWFM.L / IWFQ.L (all GBP/GBX) 2014-11..2026-08, month-end signal executed same day and next day.
  - Grid (static weights MKT/MOM/QUAL, monthly rebalance): Q1 50/25/25 (the literal P4 rule), Q2 0/50/50, Q3 34/33/33. Neighbours (knife-edge check only): Q1 50/30/20 and 50/20/30; Q2 0/60/40 and 0/40/60. Pick per market = best in-sample Sharpe among Q1-Q3. 7 configs x 2 markets = 14 trials.
  - Splits: US IS 1963-07..2000-12, OOS 2001-01..2026-08. Developed IS 1991-07..2005-12, OOS 2006-01..2026-08.
  - Benchmarks: (a) **gate benchmark = live champion** `nasdaq3x_trend_sma100_v1`, monthly returns of the synthetic 3x Nasdaq-100 + SMA100 rule from `h03_leveraged_trend.py` (USD, costs included); Stage 2 is applied vs this on the US OOS window, regimes 1986-2000 / 2001-2013 / 2014-2026. (b) design benchmark = previous champion 50 MKT / 50 MOM, full Stage 2 in both markets, reported for information (decides only whether Q is a better *shadow D*).
  - Costs: OCF MKT 0.22%, MOM 0.30%, QUAL 0.25% p.a.; one-way trading MKT 0.10%, MOM 0.35% (incl. 0.15% FX, USD line), QUAL 0.20% (GBX line IWFQ); stress x3.
  - Deflated Sharpe uses the cumulative trial count (106 + 14 = 120) with the variance of this run's active Sharpe ratios.
  - Decision rule: promotable/shadow only if every Stage 2 test passes vs the live champion; otherwise REJECTED (or INSURANCE_ONLY if it cuts max drawdown by 10pp+ while losing on return).
- **Log:** 2026-10-14 (E013, `h07_quality_momentum.py`, `output/h07_gate.csv`): in-sample pick = Q2 0/50/50 in both markets. Vs live champion (US OOS 2001-01..2026-08): CAGR 10.2% vs 14.2% (p=0.73), Sharpe 0.62 vs 0.48 (p=0.24), maxDD -44% vs -56%, DSR 0.04 → fails oos_beats, DSR, costs x3, neighbours. Vs previous champion 50/50: US +0.74%/yr (p=0.04), Sharpe +0.06 (p<0.01); Developed +0.82%/yr (p=0.02), Sharpe +0.06 (p<0.01); but DSR 0.62 / 0.61 at N=120 trials → fails multiple testing. Tradeable GBP ETFs 2014-11..2026-08: Q2 14.0%/yr vs 50/50 13.8% vs live rule on real LQQ3 12.0% (maxDD -63%). One-day lag changes nothing. **Rejected.** Note: quality+momentum is the most consistent improvement of the old 50/50 seen so far; if a future hypothesis reuses the previous-champion benchmark, Q2 is the stronger baseline.

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
- **Status:** RECURRING (every 5th research run). Last run 2026-10-14 (run 10): added P10-P13.
- **Task:** scan recent factor/asset-allocation literature (SSRN, NBER, Alpha Architect, Research Affiliates, AQR) for ideas that are implementable with Trading 212 UCITS ETFs at £100. Add each with a pre-registration. Prefer ideas with an economic rationale and out-of-sample evidence after publication.


## P9: TJR / ICT "smart money" intraday model (owner request 2026-10-14)
- **Status:** DONE: rejected (2026-10-14, E014)
- **Rationale claimed by its proponents:** stop-loss liquidity above/below obvious levels gets swept by larger players, then price reverses; entering after the reversal is confirmed (break of structure) on a retrace into the imbalance (fair-value gap) gives a small stop and a large target. No audited track record or peer-reviewed test is known; rules below follow third-party TradingView implementations (TJR's own rulebook not public).
- **Pre-registration (frozen 2026-10-14 before running; script `research/h08_tjr_smc.py`):**
  - Signal data: NQ=F 5-minute bars (Yahoo, ~60 days, 24h). Execution: LQQ3.L 5-minute closes (the real 3x Nasdaq fund, GBP), cost 0.15% per side (stress 0.30%).
  - Levels (New York time): Asia range 20:00-00:00, London range 02:00-05:00, previous regular-session high/low.
  - Long setup: in 09:30-11:00 ET a bar's low trades below any level (sweep); within the next 12 bars a bar closes above the highest high of the 5 bars up to the sweep (break of structure). Stop = lowest low since the sweep. One trade per day. Exit at stop (checked first), target, or the last LQQ3 bar before 16:25 London.
  - Grid: entry {next = LQQ3 close of the BOS bar, fvg50 = limit at the midpoint of the last bullish 3-bar fair-value gap of the BOS leg, valid to 11:30 ET} x target {1.5R, 2R, 3R} = 6 configs. Informational only (not tradable, needs shorting): the same rules both directions on NQ at 3x.
  - Split: first half of the trading days in-sample (pick = best Sharpe), second half out-of-sample. Benchmarks: holding LQQ3 over the same days; cash.
  - Decision rule: cannot pass the gate's 20-year history test, so the best outcome is AWAITING_EVIDENCE (paper-track live); REJECTED if the out-of-sample pick loses money after base costs.
- **Log:** 2026-10-14 (E014, `h08_tjr_smc.py`, `output/h08_tjr_summary.csv`): 49 trading days 2026-08-05..2026-10-14. All 6 long-only configs lost over the whole sample after 0.15%/side: 'next' entries -8.3% to -9.2% on 35 trades (win rate 34%), FVG entries -1.4% on 6 trades. In-sample pick fvg50 1.5R: OOS 4 trades, -1.2% (-2.4% at 0.30%/side) while holding LQQ3 made +14.9%. Even the untradable both-directions version lost (-0.2% to -13.6%). **Rejected.**


## P10: Volatility-managed leverage on the Nasdaq trend rule (priority 1)
- **Status:** OPEN (added 2026-10-14 by P8)
- **Rationale:** Volatility clusters while expected returns barely rise with it, so scaling exposure down when recent volatility is high raises Sharpe (Moreira & Muir 2017, "Volatility-Managed Portfolios", JF). For a daily-reset 3x product the volatility drag is about 3x(3-1)/2 = 3 times the index variance, so cutting leverage in high-vol spells should help most where the drag is worst. Who is on the other side: investors who hold constant leverage through turbulence.
- **Rule to pre-register before running:** while QQQ > SMA100 (as now), weight in LQQ3 = clip(target_vol / realised_vol_20d(3x), 0, 1), remainder in EQQQ (1x) or cash; off-signal = cash. Grid: target_vol in {30%, 45%, 60%} x remainder {EQQQ, cash} = 6 configs. Data: `h03_leveraged_trend.py` synthetic 3x on ^NDX/QQQ 1986-2026, IS 1986-2005 / OOS 2006-2026, champion = current rule.

## P11: Trend sleeve rotates to gold instead of cash (priority 2)
- **Status:** OPEN (added 2026-10-14 by P8)
- **Rationale:** When the Nasdaq trend is off the account sits in cash. Gold has had low or negative correlation to equities in equity bear markets (2000-02, 2008, 2022 partially). Rule: off-signal -> SGLN if gold > its own SMA100, else cash. Grid: gold SMA {100, 200} = 2 configs. Data: GC=F/gold from 2000 (Yahoo), so ~26 years; IS 2000-2012 / OOS 2013-2026.

## P12: Turn-of-the-month leverage tilt (priority 3)
- **Status:** OPEN (added 2026-10-14 by P8)
- **Rationale:** US equity returns concentrate in the last trading day and first three trading days of each month (Lakonishok & Smidt 1988; McConnell & Xu 2008, FAJ), linked to month-end pension and payroll flows. Rule: inside the trend-on state, hold 3x during the turn-of-month window and 1x (EQQQ) otherwise; variant 1x outside -> cash. 2 configs. Post-publication decay must be checked: OOS 2006-2026 only counts.

## P13: Pre-FOMC drift (priority 4)
- **Status:** OPEN (added 2026-10-14 by P8)
- **Rationale:** US equities rose on average in the 24 hours before scheduled FOMC announcements (Lucca & Moench 2015, JF); later studies report the effect weakened after publication. Rule: hold 3x from the close two days before a scheduled FOMC decision to the announcement day close even when the trend is off. Needs a point-in-time list of scheduled FOMC dates (federalreserve.gov calendars). 1 config. Expect decay; most likely outcome is rejection.

---

## Closed (round 1, see REPORT.md)
- Trend following / time-series momentum as a return enhancer: **rejected** (insurance only).
- Cross-asset rotation, risk parity, volatility targeting: **rejected** out-of-sample.
- Value and minimum-volatility factor ETFs: **rejected**.
- Short-term mean reversion (RSI-2, down-day streaks): **rejected**.
- GEM-12 dual momentum: **shadow** (portfolio C), not promoted (p=0.15).
