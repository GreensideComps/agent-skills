# Research log

| Date (UTC) | Item | What ran | Key result | Decision | Trials total |
|---|---|---|---|---|---|
| 2026-10-13 | Round 1 | 36 allocation configs, factor premia, factor ETFs, mean reversion, risk, power analysis | No strategy beats world equity significantly OOS. Momentum ETF +2.6%/yr (p=0.09). | Champion = momentum_tilt_v1 (50/50 VWRP/IWMO). GEM-12 → shadow. | 53 |
| 2026-10-13 | P1 + P2 (re-run of E006/E007) | `h01_momentum_sleeve.py`: 3 vol-managed + 6 trend-filter configs × US 1927–2026 and Developed 1991–2026, costs, ×3 stress, regimes, drawdown bootstrap, next-day ETF check | P1: dCAGR +0.04% US / +0.24% Dev, not significant. P2: CAGR -0.15% / -0.90%, maxDD -29% vs -49% (US) | E006 REJECTED; E007 INSURANCE_ONLY. Champion unchanged. | 71 |
| 2026-10-13 | Owner request: day trading (E008) | `h02_intraday_orb.py`: US-open breakout on 3x Nasdaq ETPs, 4 variants, ~40 trading days | Total return -22.2% to -9.3%; holding LQQ3 +11.9% | REJECTED | 75 |
| 2026-10-13 | Owner request: leveraged trend (E009) | `h03_leveraged_trend.py`: 3x Nasdaq-100 + SMA{100,150,200} filter, 1986-2026, costs, validated vs QQQ3.L | OOS CAGR 20.7% vs 16.0% (1x); maxDD -59%; IS maxDD -92% | PROMOTED by owner override (fails gate on Sharpe and drawdown) | 78 |
| 2026-10-13 | Owner request: flat at close (E010) | `h04_intraday_vs_overnight.py`: LQQ3 open->close vs overnight, 2013-2026 | Open->close daily -53.8%/yr after spread; overnight only +38.9%/yr | REJECTED; owner keeps overnight holding | 80 |
