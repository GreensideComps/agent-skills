# Multiple-testing rule for prior ETF experiments E001–E015 (owner decision D-B)

Owner decision D-B (2026-10-23 10:19Z, `cmsg_01U4KMvkBYNknqm4HRVie8uv964VkQcqvQbBHhfQQbHd8Z`): "YES, selectively:
document and apply a pre-defined multiple-testing rule for relevant prior ETF experiments E001–E015 when researching
related momentum/factor strategies. Do not indiscriminately count unrelated experiments for every strategy."

Status: **rule defined here, before any new trial is registered.** It is applied at registration time by the Stage 3
registry change (audit plan 3.3). No registry entry or deflated-Sharpe count changes now: `n_trials` stays 102 [V].

## 1. What the experiments are

The legacy ETF registry `research/experiments/E*.json` records each experiment's own count of configurations
tested (`trials` field) [V]. Together they hold 138 configurations. The edge registry records them only as one
holdout-exposure entry, `ETF-RESEARCH-E001-E015`, with `counts_for_dsr: false` [V].

## 2. Family vocabulary and assignment (fixed)

| Family | Meaning |
|---|---|
| `MOM` | cross-sectional or time-series momentum and relative strength, including dual momentum |
| `TREND` | trend filters and trend following on an index or fund (moving-average or breakout rules) |
| `FACTOR` | value, profitability, quality, low volatility and factor-ETF tilts |
| `VOLMGMT` | volatility targeting or volatility-managed exposure |
| `LEVERAGE` | leveraged ETPs or leverage overlays |
| `ALLOC` | asset-allocation timing and rotation between funds, sectors or regions |
| `MEANREV` | short-term mean reversion |
| `INTRADAY` | intraday or session-based trading |

| Exp. | Configs (`trials`) | Decision | Families |
|---|---|---|---|
| E001 Asset-allocation timing: trend, dual momentum, rotation, risk parity | 36 | REJECTED | ALLOC, MOM, TREND |
| E002 Trend following on the US market, 1928–2026 | 2 | INSURANCE_ONLY | TREND |
| E003 Persistence of factor premia (momentum, value, profitability) | 6 | MOMENTUM_SUPPORTED | MOM, FACTOR |
| E004 Tradeable MSCI World factor UCITS ETFs vs MSCI World | 5 | PROMOTED | FACTOR |
| E005 Short-term mean reversion (RSI-2, down-day streaks) | 10 | REJECTED | MEANREV |
| E006 Volatility-managed momentum sleeve | 6 | REJECTED | MOM, VOLMGMT |
| E007 Momentum sleeve with trend filter | 12 | INSURANCE_ONLY | MOM, TREND |
| E008 US-open breakout day trading, 3x Nasdaq-100 ETPs | 4 | REJECTED | INTRADAY, LEVERAGE |
| E009 3x Nasdaq-100 with a trend filter (LQQ3) | 3 | PROMOTED (now retired) | TREND, LEVERAGE |
| E010 LQQ3 London-session vs overnight returns | 2 | REJECTED | INTRADAY, LEVERAGE |
| E011 Day-trading gold on the LSE | 12 | REJECTED | INTRADAY |
| E012 CFD-style round-the-clock day trading | 14 | REJECTED | INTRADAY |
| E013 Quality + momentum sleeve | 14 | REJECTED | MOM, FACTOR |
| E014 TJR / ICT smart-money intraday model | 6 | REJECTED | INTRADAY |
| E015 Volatility-managed leverage on the Nasdaq trend rule | 6 | REJECTED | TREND, VOLMGMT, LEVERAGE |

Titles, counts and decisions are copied from the JSON files at master `b8cccb4` [V]. The family column is this
rule's assignment and is the part for owner review.

## 3. The rule

1. **Declare.** Every new trial declares its families from §2 when it is registered. If its signal uses any input
   in a family's meaning (for example a 12-month return), that family must be declared. When in doubt, the reviewer
   adds the family (conservative).
2. **Count.** The trial's deflated-Sharpe N is
   `N = n_trials(registry) + Σ trials(E) over every E sharing at least one family with the trial`,
   with each experiment counted once even if it shares several families.
3. **Configurations, not experiments.** An experiment adds its recorded configuration count, not 1. This is the
   stricter reading and matches D4, which counts correlated variants separately.
4. **N only, not the variance.** The E experiments' results are not on the trial's statistic, so they enter N but
   not the cross-trial Sharpe variance. This is the same pooling rule as `edge_registry.deflated_sharpe` (D4).
5. **Unrelated means zero.** A trial with no shared family adds nothing. For example, the SEC 8-K category
   baselines (D-D) declare no §2 family and add 0.
6. **Frozen per trial.** A trial's families and N are fixed at registration and recorded in its registration event
   (`families`, `experiment_count` with its breakdown). Neither may change after any result exists.
7. **Changing this table** creates a new version of this document. It applies only to trials registered afterwards
   and is never applied retroactively.

## 4. Effect on typical Stage 3 trials (illustrative)

| Trial type | Families | Added from E | N |
|---|---|---|---|
| Stock 12-1 momentum baseline | MOM | E001, E003, E006, E007, E013 = 74 | 176 |
| Quality + momentum composite | MOM, FACTOR | the above + E004 = 79 | 181 |
| Value or quality tilt alone | FACTOR | E003, E004, E013 = 25 | 127 |
| Sector or region rotation | ALLOC, MOM | E001, E003, E006, E007, E013 = 74 | 176 |
| SEC 8-K category baseline | none | 0 | 102 |

`N` assumes today's registry count of 102 and grows as new trials are registered. For scale: with the variance floor
of 1/94 months, the deflated-Sharpe hurdle on the monthly Sharpe (`sr0`) moves from 0.262 at N = 102 to 0.281 at
N = 176 (0.91 to 0.97 annualised) [V: computed with the `deflated_sharpe` formula].

## 5. Implementation (later, Stage 3)

- The §2 table becomes a data file, `research/edge/prior_etf_families.json`, whose sha256 is recorded at registration.
- `edge_registry` registration requires `families` and `experiment_count` for new trials (audit plan 3.3). The
  extra N is passed to `deflated_sharpe` explicitly rather than added to the registry.
- A test checks that the configuration counts in the data file equal the `trials` fields in `research/experiments/`.
