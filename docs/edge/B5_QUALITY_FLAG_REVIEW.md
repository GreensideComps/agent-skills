# B5: the share-outlier quality flag and look-ahead (owner question, 2026-10-19 07:25Z)

Input-level analysis only: share counts, prices and flags. No H1 or S2a score, ranking, return, NAV, Sharpe or verdict
was computed. Nothing is registered and no specification is changed. Script:
`research/edge_b5_quality_flag_audit.py` (writes `equity/reports/research/edge/b5_quality_flag_audit.json`).
"Universe" below means the B5 primary universe without the quality rule: large band, `close_raw` ≥ $1,
non-financial, decision months 2015-01 to 2022-11. That is 34,399 company-months, 655 companies and 95 months.

## 1. How the flag enters the primary portfolios

- **Rule.** `quality_ok` is False when `adjclose` ≤ 0 or `close_raw` ≤ 0 (the price flag), or when the share count
  is above 10× or below 1/10 of the company's median (`edge_split.share_outliers`). The share count is
  `shares_out`, falling back to `shares_diluted`. The median is taken over all of the company's rows in the
  exploration frame, 2009-12 to 2022-12, so the median for a 2015 row uses share counts up to 2022.
- **Used in the primary run: yes.** `edge_b5_run.load_inputs` builds it with
  `edge_split.with_quality(edge_split.cut_exploration(xsection.load()))`. The primary panels carry this
  `quality_ok`. Only the P9 panels replace it with `quality_ok_pit`, which uses an expanding median: the company's
  rows up to and including that month.
- **Where it acts.**
  - Engine eligibility (`edge_backtest.eligible`). A flagged row cannot be bought. A held name that is flagged at
    a rebalance has no rank, so it is sold. The flag therefore affects both entries and exits.
  - The S2a score. S2a is a percentile rank within its SIC group among quality-ok names, so a flagged name also
    shifts the percentiles of the other names in its group. H1 scores are raw values with no such effect.
  - Gate P5 compares against an equal-weighted eligible universe, which uses the same flag.
- **Size.**

| Set (universe rows) | Rows | Companies |
|---|---:|---:|
| Flagged by the full-window rule (registered) | 207 | 43 |
| Flagged by the point-in-time rule (P9) | 295 | 49 |
| Flagged by both | 187 | 39 |
| **Full-window only: excluded using later information** | **20** | **6** |
| Point-in-time only | 108 | 11 |
| Price flag (contemporaneous) | 4 | 1 |
| Rows whose `quality_ok` differs between the rules | 128 (0.37%) | in 68 of 95 months, at most 4 per month |

- **Full-window-only rows.** These are AVITA Medical (9 rows), Mobiquity (4), NextTrip (2), Herc Holdings (2),
  Indaptus (2) and Meridian (1). They are early months, before a later share-count change made them look like
  outliers. Rule C already removes 9 of the 20. The 11 that remain are AVITA 2019-11 to 2020-07 (a share-count
  scale error giving a bogus ~$14bn market cap) and Herc Holdings 2015-02 and 2016-07 (before its 2016 separation).
- **Point-in-time-only rows.** These are mostly genuine companies whose early share counts differ from their
  expanding median after a merger, spin-off or early data glitch. Examples: MPLX 19, Fox 19, Linde 12, Cheniere
  Energy Partners 9, Viatris 9, DXC 4, TechnipFMC 3, Amcor 3 and Corteva 2. Some are true errors that rule C also
  removes: Atlas Lithium 14 and Akari 14. Rule C removes 32 of the 108.
- **Flagged under both rules.** Genuine names are wrongly excluded after real 10-for-1 splits. CoStar and The Trade
  Desk are excluded from 2021-07 and 2021-08 through 2022. Others are true scale errors, such as Garmin
  2016-04 to 2019-01, with about 2×10^11 shares.

## 2. Is P9 enough to show a primary result is investable without this look-ahead?

**It is not enough.** It is a useful veto but not a substitute:

1. P9 only requires **net excess > 0** under the point-in-time rule. The strength tests, P1 (t ≥ 3), P2 (DSR),
   P3 (factor alpha), P10 (thirds) and P11 (leave-one-out), are applied only to the primary. A primary pass with
   P9 > 0 does not show that a point-in-time portfolio meets the thresholds.
2. Each robustness run changes one thing from the primary. No run combines point-in-time eligibility with 2×
   costs, −100% missing prices or next-month execution.
3. The reported statistics would come from a universe an investor could not have built in real time.
4. The difference is small on inputs (0.37% of rows, at most 4 a month). But the portfolios hold 20 names, so one
   name is 5% of the portfolio. "Small" is an expectation, not evidence, and the direction of any bias cannot be
   signed in advance. Share-count changes go with issuance, splits and separations, which relate to returns.

Under the registered specification, a primary pass could at most say the result is not driven by this filter in
sign. Treating it as investable would need a further point-in-time trial, a new counted look.

## 3. Choices, with a recommendation

**A. Keep the registered primary and add an explicit limitation.**

- Change: none (no hash change, N = 100).
- Every report would state that primary eligibility used full-window share-count medians.
- A pass could not be called investable without another counted point-in-time trial.

**B. Make point-in-time eligibility the primary, through a reviewed Addendum 3. Recommended.**

- The primary uses `quality_ok_pit` (`edge_split.share_outliers_pit`, already coded and tested; no new rule is
  designed) for engine eligibility, the S2a rank population and the P5 universe.
- P9 becomes the reverse cross-check: net excess > 0 under the registered full-window rule. It stays a veto
  only, so the gate list P1-P11 and every threshold stay the same.
- New uncounted robustness ids would be registered for P9, `B5-{H1,S2A}-V2-ROB-WINQ`. `ROB-PITQ` would stay
  registered but never be run. The run gate and its tests change to match.
- Owner decision D20 would record the change to D5's timing, since D5 kept the exclusions.
- Addendum 3 would be frozen and registered by hash. The run script and manifest would be rebuilt and their new
  hashes reported for review before any registration.
- **Why B.** The gates (t, DSR, alpha) then apply to a portfolio an investor could have run, so a pass answers
  your question directly instead of leading to yet another trial.
- **The cost of B, stated rather than hidden.** The point-in-time rule wrongly excludes some genuine large caps:
  108 rows from 11 companies, or 76 rows from 9 companies after rule C. It also lets AVITA's 9 inflated rows into
  the large universe. These are contemporaneous data errors, not look-ahead, and they would be disclosed in
  `KNOWN_INPUT_LIMITATIONS`.

**Not recommended now: C, design a better point-in-time rule.** For example, a trailing window, or a rule that
checks share count against price consistency. Choosing a new rule after seeing these flags is design on the data,
even at input level, and would need its own review.

## 4. Interactions

- **Price flag.** Contemporaneous: 4 rows from 1 company in the universe. It is unaffected.
- **Rule C.** Point in time (round 6 audit). It overlaps heavily: 136 of the 187 rows flagged by both rules and
  9 of the 20 full-window-only rows are also rule C exclusions. Under option B, rule C still removes 32 of the 108
  point-in-time-only rows.
- **Band, price ≥ $1, T2, H1 and S2a inputs.** Point in time.
- **P8 data-error list.** This also uses later information: 12 company-months picked by auditing the full
  2015-2022 price path in B1. Like P9 it is a veto only, barring purchases. I am disclosing it because it is the
  same kind of issue.
- **SIC codes.** The financial exclusion, the S2a groups and the sector cap use each company's current SIC code,
  from the 2026 SEC submissions snapshot, not a point-in-time classification. This is a pre-existing limitation
  shared with Stage 2. Reclassifications are rare, but they would carry later information.
- **DSR count.** N = 100 already counts Stage 2's 15 `QX-*` and 15 `QX-PIT-*` quality-rule diagnostics, including
  `QX-PIT-S2a`, as prior looks. The `ROB-PITQ` runs are uncounted. Option A leaves N at 100. Option B through an
  addendum also leaves N at 100: Addenda 1 and 2 changed definitions before any B5 output in the same way, and no
  B5 result exists. If you prefer the stricter reading, B can instead re-register the trials as V3 ids, with the
  unrun V2 ids still counted as V1 was, which makes N = 102.

## Standing limitations

- Survivorship bias remains material and unbounded.
- TTM check 4 is open, so no E2 label is possible.
- No exploratory result is proof of a deployable edge.
