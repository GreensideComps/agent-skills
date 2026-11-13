# Promotion gate: how a research idea can change live (demo) trading

> **Retired 2026-10-19 (owner decision O10).** Stage 4 promotion into `trading/config/strategy.json` no longer applies;
> research never changes trading configuration. Kept for the record of past decisions.

The research loop runs unattended. This gate keeps it from turning noise into
trades. Every condition must hold, and the evidence must be committed, before
`trading/config/strategy.json` changes.

## Stage 1: pre-registration (before looking at out-of-sample data)

The hypothesis gets an entry in [`AGENDA.md`](AGENDA.md) stating:
- the economic rationale (why the effect should exist and persist, and who is on the other side);
- the exact rule and parameter grid, which is frozen;
- the in-sample and out-of-sample split, and the benchmark (the current live strategy, the "champion");
- the data sources, and the reasons they are point-in-time and free of survivorship bias.

## Stage 2: evidence (all required)

| Test | Pass condition |
|---|---|
| History | At least 20 years of data, or the longest survivorship-free history available. Costs, spreads, FX fees and a one-day execution lag are included. |
| Out-of-sample vs champion | Out-of-sample CAGR higher **and** out-of-sample Sharpe higher, with paired block-bootstrap p < 0.10 on at least one of them |
| Multiple testing | Deflated Sharpe ratio ≥ 0.90, counting **every** configuration ever tried for the hypothesis (log the count in AGENDA) |
| Robustness | Still beats the champion with costs ×3, and with neighbouring parameter values (no knife-edge optimum) |
| Risk | Max drawdown no more than 5 percentage points worse than the champion's. Bootstrap P(≥50% drawdown within 10 years) not higher. |
| Regimes | Not reliant on a single regime: the result should hold in at least 2 of the 3 sub-periods |
| Implementable at £100 | Uses instruments available on Trading 212, ideally GBP/GBX lines. Turnover cost under 0.5%/yr. No leverage, no shorting. |

## Stage 3: shadow period

The challenger is added to `shadow_portfolios` in `trading/config/strategy.json`
and tracked for **at least 20 trading days**. It must show no data or signal
failures, and it must produce trades that match the backtest logic. This step checks
the plumbing, not the edge, because no short period can prove an edge.

## Stage 4: promotion

- A single commit changes `targets`/`name` in `strategy.json`. The message links the evidence (output CSVs and the REPORT section).
- **At most one strategy change per calendar quarter.** Frequent switching is itself overfitting.
- The old champion stays on as a shadow portfolio for comparison.
- Never: leverage, shorting, the live environment, or more than 10 orders per run.

## Demotion

The research loop reverts to the previous champion (subject to the same once-per-quarter
limit) if any of these happen:
- the live strategy underperforms its own same-rules-at-close shadow by more than
  1.5% in total, which means the implementation is broken;
- a data source behind the signal stops being reliable;
- new evidence makes the champion fail Stage 2 against a simpler benchmark.
