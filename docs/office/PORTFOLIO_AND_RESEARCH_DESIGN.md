# Design: VWRP paper book, portfolio manager, research planner

Status: **decided 20 Oct 2026** (D-T14 A, D-T16 approved with changes, D-T15 allow; DECISION_REGISTER.md §7).
Built on a draft PR: paper-1.1 (T14), pm-1.0 per `PM_SPEC.md` (T20), the research planner (T15). The text below is
the proposal as it was put to the owner; where the owner changed it (the −15% rule is a review threshold, not a stop;
the sector limit uses look-through), `PM_SPEC.md` governs.

## 1. VWRP benchmark for the paper book (T14)

**Today [V: `equity/config/paper_portfolio.json`, `paper.py`]:**
- `paper-1.0` buys the top 10 screened companies, equal weight, rebalanced monthly. It runs in USD with 0.25%
  round-trip costs.
- It benchmarks against SPY, using price-only Yahoo closes for both the book and the benchmark.
- The config says that any mandate change needs owner approval and a new `method_version`.

**Problems:**
- SPY is not the strategy's benchmark. VWRP is (strategy V2).
- VWRP is accumulating, so its price includes reinvested dividends, while the book's prices exclude them. A naive
  swap would bias the comparison against the book by roughly the stocks' dividend yield, about 1–1.5% a year [A].
- VWRP is priced in GBP on the LSE, while the book is in USD.

**Proposal: `paper-1.1`, additive.**
- Keep the SPY benchmark and its history unchanged.
- Add a second benchmark book, `BENCH:VWRP.L`. It is funded with the same cash on the same day, converted at that day's
  GBPUSD close, and marked in USD at each mark.
- Report excess return against both benchmarks. Label VWRP "total return (accumulating)" and the book "price only,
  dividends excluded", so the bias is stated beside the number rather than hidden.
- History before the change stays `paper-1.0`. Nothing is restated.

**Decision D-T14:**
- (a) add VWRP alongside SPY, as above (recommended);
- (b) replace SPY from a new start date;
- (c) leave as is.

## 2. Portfolio manager (T16, R0 until a separate execution mandate)

**Purpose:** a deterministic component that turns evidence into a target portfolio and records why, or records "no
trade". It proposes; it never executes. Orders stay outside its reach (the office has no order path).

**Rules, enforced in code (proposed defaults):**
- **The default target is 100% VWRP.** A satellite position needs a signal that has passed the research gates. None
  has (Stage 2 and B5 both failed), so today the manager can only ever output the VWRP core: the documented no-trade
  outcome.
- **Limits:**
  - satellite total at most 20% of the book;
  - any single name at most 5%;
  - any sector at most 10%;
  - a satellite drawdown stop at −15% versus VWRP, which returns that sleeve to the core.
- **Each decision record holds:** the evidence ids (trial ids and gate verdicts), the inputs' hashes, the target
  weights, the reason for each weight, and the limits checked. A decision is reproducible from the log.
- **Book:** the office's own paper book, using `orders.py` against a simulated broker with persisted intent and
  reconciliation. It is separate from the equity paper book and the demo account.

**Decision D-T16:** approve these limits and the "VWRP unless gated evidence" rule as the manager's mandate (version
`pm-1.0`), or change them.

## 3. Research planner (T15)

**Purpose:** pick the next question without prompting. Under the D-series governance it may **only draft**. It writes a
proposal and a draft manifest, then stops for the owner. It never registers, authorises or runs anything.

**Proposed behaviour:**
- Weekly, it reads the registry, failed trials, open limitations (survivorship, Check 4 coverage, the partly seen
  holdout) and the data actually available.
- It ranks candidate work by expected information per unit of risk. Candidates that would reuse the seen 2023–26
  holdout as confirmation are excluded, and its DSR budget counts all 102 prior trials.
- It writes one proposal to `docs/edge/proposals/`. A new `research_proposal` task appears in the digest as "awaiting
  owner".

**Decision D-T15:** allow the planner to draft proposals weekly (it never runs them), or keep research planning manual.

## Not covered here

Live execution (T18) needs its own explicit authorisation and is not designed here.
