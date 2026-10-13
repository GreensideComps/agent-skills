# Live demo performance: `momentum_tilt_v1`

_Generated 2026-10-13T09:25:26+00:00 UTC by `python -m t212bot report`. Demo (paper) account only._

Inception: **2026-10-13**, starting capital **£100.00**.

## Value since inception

| Portfolio | Value now | Return | Notes |
|---|---|---|---|
| **B (real demo account)** | £99.88 | -0.12% | real fills, real costs |
| A_benchmark_vwrp | £99.90 | -0.10% | 100% VWRP at daily close |
| C_gem12 | £99.90 | -0.10% | GEM-12 dual momentum at daily close |
| B_live_rules_at_close | £99.83 | -0.17% | same targets, frictionless-ish fills at daily close |

## Execution quality (real fills vs reference quote at order time)

| Order | Ticker | Status | Fill price | Reference | Slippage (bps, + = worse) | Cost vs reference (£) |
|---|---|---|---|---|---|---|
| 56400858289 | IWMOl_EQ | FILLED | 117.02 | 116.88 | 11.98 | 0.132 |
| 56400858303 | VWRPl_EQ | FILLED | 146.42 | 146.3 | 8.2 | 0.0403 |
| 56400858343 | VWRPl_EQ | FILLED | 146.42 | 146.36 | 4.1 | -0.0035 |

## Is any of this meaningful yet?

- Not enough history yet.
