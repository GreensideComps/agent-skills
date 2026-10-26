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
| E002 Trend following on the US market, 1928–2026 | 2 | INSURANCE_ONLY | TREND, MOM (12-month absolute momentum) |
| E003 Persistence of factor premia (momentum, value, profitability) | 6 | MOMENTUM_SUPPORTED | MOM, FACTOR |
| E004 Tradeable MSCI World factor UCITS ETFs vs MSCI World | 5 | PROMOTED | FACTOR, MOM (IWFM; momentum chosen as the tilt) |
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
| Stock 12-1 momentum baseline | MOM | E001, E002, E003, E004, E006, E007, E013 = 81 | 183 |
| Quality + momentum composite | MOM, FACTOR | the same seven = 81 | 183 |
| Value or quality tilt alone | FACTOR | E003, E004, E013 = 25 | 127 |
| Sector or region rotation | ALLOC, MOM | the MOM seven = 81 | 183 |
| SEC 8-K category baseline | none | 0 | 102 |

`N` assumes today's registry count of 102 and grows as new trials are registered. For scale: with the variance floor
of 1/94 months, the deflated-Sharpe hurdle on the monthly Sharpe (`sr0`) moves from 0.262 at N = 102 to 0.281 at
N = 176 (0.91 to 0.97 annualised) [V: computed with the `deflated_sharpe` formula].

## 5. Implementation (later, Stage 3)

- The §2 table becomes a data file, `research/edge/prior_etf_families.json`, whose sha256 is recorded at registration.
- `edge_registry` registration requires `families` and `experiment_count` for new trials (audit plan 3.3). The
  extra N is passed to `deflated_sharpe` explicitly rather than added to the registry.
- A test checks that the configuration counts in the data file equal the `trials` fields in `research/experiments/`.

## 6. Rationale for each family, other prior trials, and the 8-K baselines (owner review point 3)

### 6.1 Why a family is counted or not

A prior experiment enters a new trial's N when a researcher who had seen its results could plausibly have chosen
the new trial's rule *because of* them. Sharing an input or a mechanism is the test. Sharing an asset class is not.

| Family | Counted for a new trial when the trial … | Not counted when … | Why |
|---|---|---|---|
| `MOM` | uses past returns, relative strength or momentum ranks in any form | the trial uses no past-return input | E001/E003/E006/E007/E013 all searched momentum lookbacks and filters; any momentum rule now benefits from that search |
| `TREND` | uses a moving average, breakout or time-series trend filter | no trend filter | E001/E002/E007/E009/E015 searched trend filter settings |
| `FACTOR` | tilts on value, profitability, quality, low volatility or factor ETFs | no fundamental or factor input | E003/E004/E013 compared factor premia, including in 2023–26 |
| `VOLMGMT` | scales exposure by volatility | fixed exposure | E006/E015 searched volatility targets |
| `LEVERAGE` | uses leveraged products or overlays | unlevered | E008/E009/E010/E015 searched leveraged rules |
| `ALLOC` | rotates between funds, sectors or regions | single-asset or stock-level event rules | E001 searched rotation schemes |
| `MEANREV` | buys short-term losers or sells winners over days | holding periods follow an event, not a price move | E005 searched RSI and down-day rules |
| `INTRADAY` | trades within a session or on session splits | trades only at closes | E008/E010/E011/E012/E014 searched intraday rules |

When a trial's inputs are ambiguous, the family is included (rule 1, conservative).

### 6.2 Other relevant prior trials (not E001–E015)

| Prior work | Where | How it is counted | Why |
|---|---|---|---|
| Stage 2 signals S2-S1a … S2-S9 (15), including S2-S4 standardised unexpected EPS and S2-S7a/b insider buying | registry, `counts_for_dsr: true` | **Already in N for every new trial** | D4 counts every registered trial in full, whatever its family. This is stricter than D-B, so D-B adds nothing on top. |
| DIAG (45) and QX (30) Stage 2 diagnostic horizons | registry, counts | Already in N | Same reason |
| B5 trials (6 ids) | registry, counts | Already in N | Same reason |
| M8 screen-1.0 looks (6) | registry, counts | Already in N | Same reason |
| Exposure-only entries: ETF E001–E015, STAGE1, PORTFOLIO, PROGRAMME, REVIEW | registry, `counts_for_dsr: false` | E001–E015 by family under this rule; the others **not counted** | The others are looks at returns (a market average, the demo holdings, factor means) with no rule searched. They are disclosed in each trial's `touched_holdout` note instead. |
| B1, B3, B5 diagnostics marked `counts_for_dsr: false` | registry | Not counted | They re-ran registered trials under changed settings (cost, reproduction checks) after the fact. They are recorded, and DSR uses the trials they belong to. |
| `research/h01`–`h09`, `run_*.py` scripts | repository | Not counted separately | They are the code behind the ETF research recorded as E001–E015 [A: matched by title, not line by line], so counting them again would double-count. |

### 6.3 Applied to the draft 8-K category baselines (not registered)

| Family | Shared? | Reason |
|---|---|---|
| `MOM`, `TREND`, `MEANREV` | No | The rules use only the filing's item codes and fixed horizons. No past-return input decides anything (the $1 floor is an eligibility rule, not a signal). |
| `FACTOR` | No | No fundamental, valuation or quality input. Band membership only sets the universe and cost. |
| `VOLMGMT`, `LEVERAGE`, `ALLOC` | No | Equal weight, unlevered, single-stock events. |
| `INTRADAY` | No | Entry and exit are at closes only. |

So D-B adds **0** configurations from E001–E015, and N = registry n_trials + 12 (102 + 12 = 114 if nothing else is
registered first).

**Closest prior work.** The closest prior work is S2-S4 (earnings surprise), which relates to item 2.02, and S2-S7
(insiders), which relates weakly to 5.02. Both are already counted in the 102. They are disclosed in the
pre-registration's prior-knowledge section.

**Status.** Nothing is registered; the 12 trials stay unregistered until U1 and U5 are approved.


**Re-audit 2026-10-26 (review finding P30-2).** Every row was re-checked against the experiment's hypothesis, data and decision, not its title. E004 (IWFM momentum ETF, momentum chosen as the tilt) and E002 (12-month absolute-momentum filter) gain MOM, so a momentum trial's extra N is 81, not 74. Each tag's basis is recorded in `research/edge/prior_etf_families.json` (version 1.1), and the table's sha256 is pinned by `research/tests/test_edge_families.py`.
