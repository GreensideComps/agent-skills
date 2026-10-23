# screen-1.0 and its paper book: status label (owner decision D-C)

Owner decision D-C (2026-10-23 10:19Z, `cmsg_01U4KMvkBYNknqm4HRVie8uv964VkQcqvQbBHhfQQbHd8Z`): "clearly label
screen-1.0 and its paper-book results as unvalidated exploratory research, not investable evidence." The 11:39Z
task added: "without altering historical results".

## 1. The label

> **screen-1.0, paper-1.0 and every result they have produced are unvalidated exploratory research. They are not
> investable evidence and not a recommendation. They may not drive a sleeve target, a position size or an order,
> on paper or real.**

Why it applies [V]:
- `equity/config/evidence.json` gives screen-1.0 tier E1: "Pre-registered backtest failed (mean IC +0.077,
  t = 1.92 vs bar 2.0)". Only E3/E4 may drive decisions (`equity/equity/evidence.py`).
- The M8 screen backtest read 2023–2026 outcomes (`docs/edge/SPLIT_POLICY.md` §3), so screen-1.0 has no clean
  confirmation data left.
- paper-1.0 is USD, price-only, benchmarked to SPY, with fills at decision price plus 25 bps. Its return is not
  comparable with the GBP VWRP core (audit §5).

## 2. How the label is applied without altering history

This file is the label of record. No existing report, ledger or config is edited. The historical files below are
covered as they stand, identified by hash on 2026-10-23 (first 16 hex characters of SHA-256; `unv` counts lines
that already contain "unvalidated"):

| File | sha256 (16) | unv |
|---|---|---|
| `equity/reports/screens/2026-10-14.md` | `7ea51a5d00df26a6` | 2 |
| `equity/reports/screens/2026-10-15.md` | `ad7c723bf112125a` | 2 |
| `equity/reports/screens/2026-10-16.md` | `87d68dcc10b42d14` | 2 |
| `equity/reports/screens/2026-10-19.md` | `af40e7131b2e5917` | 2 |
| `equity/reports/screens/2026-10-20.md` | `a9e305f0b10f6d45` | 2 |
| `equity/reports/screens/2026-10-23.md` | `d6784757c78813c7` | 2 |
| `equity/reports/paper/2026-10-14.md` | `a7f26f8beab1d6c3` | 2 |
| `equity/reports/paper/2026-10-15.md` | `76f94db5ed7a547f` | 2 |
| `equity/reports/paper/2026-10-16.md` | `8c314936ac19f77c` | 2 |
| `equity/reports/paper/2026-10-19.md` | `73239f1c79791a1c` | 2 |
| `equity/reports/paper/2026-10-20.md` | `9071a11bec9440a4` | 2 |
| `equity/reports/paper/2026-10-23.md` | `5322db1d89d4f2a8` | 2 |
| `equity/data/paper_nav.jsonl` (6 lines) | `13c77420a1eec233` | — |
| `equity/data/paper_trades.jsonl` (13 lines) | `b08634e37bbbd7c5` | — |
| `equity/data/recommendations.jsonl` (9 lines) | `50539265c58e01b5` | — |
| `equity/config/paper_portfolio.json` | `7bd9931a478dddfc` | — |

Every historical screen and paper report already carries the E1 "unvalidated: not a recommendation" banner [V].
Reports written after 23 Oct are covered by this label too. The stronger wording for future banners is the
separate proposal `proposals/DC_evidence_labels.patch`, which needs review because it changes daily pipeline output.

**Out of scope:** `research/output/paper_ledger.csv` belongs to the older trading-research paper portfolios
(A_benchmark, B_momentum_tilt), not to screen-1.0.

## 3. What would change the label

Only a new registered trial that reaches E3 under `docs/edge/EVALUATION_SPEC.md`. A screen-1.0 v2 would be a new
trial with its own registration, counted in N. Nothing in Stage 1 or Stage 2 does this.
