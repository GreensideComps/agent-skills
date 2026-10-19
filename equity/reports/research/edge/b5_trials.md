# B5 exploratory trials

**Standing limitations (not solved by anything in this report):**

1. **Survivorship bias (material, unbounded).** Companies that stopped trading before the 2026 price download have no
   free prices, so they are missing from the universe entirely, even in the years they traded. The bias is of unknown
   size and is usually assumed to flatter results. The -30% and -100% missing-price rules apply only to companies
   that are in the data and later lose a price; **they do not address companies missing from the universe, and are
   not evidence that survivorship bias is bounded.** Accepted for exploration only (D13).
2. **Missing prices are indistinguishable.** Delistings, acquisitions and ticker changes all get the same
   conservative mark-down.
3. **The 2023-2026 holdout is partly seen**, so a holdout pass is weaker than a clean out-of-sample test.
4. **One ticker per company, today's SIC codes, unofficial free prices (Yahoo).**
5. **Benchmark:** actual VWRP only from 2019-08 (first full monthly return; first price 25 July 2019); VWRL (its distributing twin) before that.

# B5 exploratory trials: H1 and S2a

**Exploratory evidence only (2015-2022, survivorship-biased free data). A passing result is not proof of a deployable edge, authorises no confirmation test, holdout access or demo allocation, and changes nothing in any account.**

Authorised by owner message cmsg_01U4KMvkBYNknqm4HRVie8uvNzjD1qcmHEXGwqYmiFikfZ; manifest sha256 f3f4fd71bae5ddf4932211c1983edac7dcb1d6d152d8d087c73550409a4b9671; N = 102; TTM check 4 complete: False.

**Known input-rule limitations (ADDENDUM_2 §1, §3; stated in every B5 report):**

- Revenue tests: General Dynamics 2017-18 loses 18 fallback rows to a mis-tagged alternate concept (false
  positive); Abbott 2015-01 (about 10.6% basis mixing) is not caught (missed case); EQT and ConocoPhillips rows are
  flagged for derivative-inclusive `Revenues` (a basis difference, conservative).
- Identity rule C: rows between 25x and 100x market cap to assets stay in, where errors and genuine values overlap
  (Curis 97x, BeOne 97x, Larimar 85x after a CIK reuse); Scinai is unscorable for lack of total assets.
- T2 uses only filings known at each decision date; restatements filed later are not used (diagnostic only).
- TTM check 4 (independent source) is open: no result carries the E2 label.
- Quality rule (ADDENDUM_3): eligibility uses the point-in-time share-outlier rule. Against the Phase A full-window
  rule it wrongly excludes about 108 universe company-months of 11 genuine companies after mergers or spin-offs
  (76 rows, 9 companies after rule C; e.g. MPLX, Fox, Linde, Viatris) and admits AVITA Medical's 9 inflated rows
  (2019-11 to 2020-07). Both rules wrongly exclude CoStar and The Trade Desk after their 2021 10-for-1 splits.
- P8's 12 data-error company-months were chosen by auditing the whole 2015-2022 price path (later information; a
  veto only). SIC codes (financial exclusion, S2a groups, sector cap) are a 2026 snapshot, not point in time.


**P7 evaluation window (owner decision D29, option A; `docs/edge/B5_EXECUTION_HARDENING.md` §3):**

- P7 (next-month-close execution) has **94 valuation dates and 93 monthly returns** (2015-02-28 to 2022-11-30). The
  primary and the next-day-close variants (P4, P5, P6, P8, P9, P11) have **95 valuation dates and 94 monthly
  returns** (2015-02-02 to 2022-12-01).
- Under P7 the 2015-01 decision first trades at the 2015-02 month-end, and the 2022-11 decision cannot trade because
  the registered execution file (decisions to 2022-11) holds no 2022-12 month-end close.
- P7 is assessed against the benchmark on its own dates. Its result is **not directly comparable** with variants
  measured over a different window. The registered data, definition and gate are unchanged.

- B5-H1-FCFPS-ACCEL-V3: primary 94 monthly returns; P7 93 monthly returns.
- B5-S2A-GP-12M-V3: primary 94 monthly returns; P7 93 monthly returns.

## B5-H1-FCFPS-ACCEL-V3

Verdict: **fail**

| Gate | Pass |
|---|---|
| P1 | False |
| P2 | False |
| P3 | False |
| P4 | True |
| P5 | True |
| P6 | True |
| P7 | True |
| P8 | True |
| P9 | True |
| P10 | True |
| P11 | True |

| Statistic | Value |
|---|---|
| months | 94 |
| cagr | 0.14853346481705998 |
| vol | 0.1690682221023935 |
| sharpe | 0.9080878131926636 |
| max_drawdown | -0.20646416153173863 |
| excess_months | 94 |
| te | 0.083185385137448 |
| ir | 0.5410147667687305 |
| sr_excess_monthly | 0.15617751061474458 |
| share_months_ahead | 0.5638297872340425 |
| relative_drawdown | -0.12987782951241067 |
| benchmark_labels | {'VWRL-based': 54, 'actual VWRP': 40} |
| first_actual_vwrp_period | 2019-09-03 |
| excess_skew | 0.0586710212977584 |
| excess_kurt | 2.9645860426628103 |
| t_nw | 1.6621551814729447 |
| t_nonoverlap | None |
| alpha | {'alpha': -0.0002743847067176759, 'alpha_t': -0.12041323385842176, 'betas': {'Mkt-RF': 1.0540224317844882, 'SMB': 0.17355754417314556, 'HML': -0.009931870958360907, 'RMW': 0.06447248728355634, 'CMA': 0.00930071880048966, 'Mom': 0.07980749463079553}, 'months': 94} |
| dsr | {'dsr': 0.15470123031914174, 'n_trials': 102, 'n_comparable': 2, 'var_used': 0.010638297872340425, 'floor_used': True, 'sr0': 0.26172956829197197, 'stat': 'portfolio_excess_vs_vwrp'} |
| top_contributor | 2488 |
| net excess P4 | 0.0027243424430073155 |
| net excess P5 | 0.0005466863994966764 |
| net excess P6 | 0.0037503768115586212 |
| net excess P7 | 0.0027067924268005116 |
| net excess P8 | 0.0037503768115586212 |
| net excess P9 | 0.0037503768115586212 |
| net excess P11 | 0.003581601700298321 |
| thirds | [0.002023746372113472, 0.0041082494823263, 0.005174832336347226] |

## B5-S2A-GP-12M-V3

Verdict: **fail**

| Gate | Pass |
|---|---|
| P1 | False |
| P2 | False |
| P3 | False |
| P4 | True |
| P5 | True |
| P6 | True |
| P7 | True |
| P8 | True |
| P9 | True |
| P10 | True |
| P11 | True |

| Statistic | Value |
|---|---|
| months | 94 |
| cagr | 0.15748650132200281 |
| vol | 0.1606015484580813 |
| sharpe | 0.9953687046101678 |
| max_drawdown | -0.16905669586139793 |
| excess_months | 94 |
| te | 0.07409878458860851 |
| ir | 0.6927709432951833 |
| sr_excess_monthly | 0.19998574529911248 |
| share_months_ahead | 0.5425531914893617 |
| relative_drawdown | -0.10139153659896949 |
| benchmark_labels | {'VWRL-based': 54, 'actual VWRP': 40} |
| first_actual_vwrp_period | 2019-09-03 |
| excess_skew | 0.5394186012360062 |
| excess_kurt | 3.2679809852445416 |
| t_nw | 2.0983607266676 |
| t_nonoverlap | 2.1970841261295635 |
| alpha | {'alpha': 0.00041035970736772083, 'alpha_t': 0.306452898761554, 'betas': {'Mkt-RF': 0.9537279003931418, 'SMB': 0.25404590031880053, 'HML': -0.14718947452126302, 'RMW': 0.344587564797595, 'CMA': -0.10020201513034147, 'Mom': 0.007703782364901615}, 'months': 94} |
| dsr | {'dsr': 0.2667912949062855, 'n_trials': 102, 'n_comparable': 2, 'var_used': 0.010638297872340425, 'floor_used': True, 'sr0': 0.26172956829197197, 'stat': 'portfolio_excess_vs_vwrp'} |
| top_contributor | 97476 |
| net excess P4 | 0.004105808918937573 |
| net excess P5 | 0.0007283817496831172 |
| net excess P6 | 0.004277790408039742 |
| net excess P7 | 0.004289291268088462 |
| net excess P8 | 0.004277790408039742 |
| net excess P9 | 0.004340953251630254 |
| net excess P11 | 0.003803938999801036 |
| thirds | [0.0006855212268224893, 0.006631126633717522, 0.00563260301458622] |
