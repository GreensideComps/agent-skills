# Research log

| Date (UTC) | Item | What ran | Key result | Decision | Trials total |
|---|---|---|---|---|---|
| 2026-10-13 | Round 1 | 36 allocation configs, factor premia, factor ETFs, mean reversion, risk, power analysis | No strategy beats world equity significantly OOS. Momentum ETF +2.6%/yr (p=0.09). | Champion = momentum_tilt_v1 (50/50 VWRP/IWMO). GEM-12 → shadow. | 53 |
| 2026-10-13 | P1 + P2 (re-run of E006/E007) | `h01_momentum_sleeve.py`: 3 vol-managed + 6 trend-filter configs × US 1927–2026 and Developed 1991–2026, costs, ×3 stress, regimes, drawdown bootstrap, next-day ETF check | P1: dCAGR +0.04% US / +0.24% Dev, not significant. P2: CAGR -0.15% / -0.90%, maxDD -29% vs -49% (US) | E006 REJECTED; E007 INSURANCE_ONLY. Champion unchanged. | 71 |
