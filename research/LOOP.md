# RETIRED (2026-10-19): this research loop must not run

Owner decision O10 (owner message `cmsg_01U4KMvkBYNknqm4HRVie8uv5WhbXFRm6KFGKqgHWHri4W`, 2026-10-19 14:36Z) retired the
legacy ETF research loop together with the stale `discretionary_intraday_v1` strategy (100% LQQ3).

- The loop allowed a research run to add shadow strategies and promote a challenger into
  `trading/config/strategy.json`. Research must never write trading configuration, so the loop is retired.
- The full previous procedure is kept unchanged at [`archive/LOOP_retired_2026-10-19.md`](archive/LOOP_retired_2026-10-19.md),
  and its results stay in `research/LOG.md`, `research/AGENDA.md` and `research/REPORT.md` (unchanged).
- `research/STOP` exists, so any session that still follows the old precondition ("if research/STOP exists, log and
  end") stops at once.
- Its scheduled task ("T212 demo: research loop", `trig_019cbvFKHAnfuPE24Bqexu9L`) is disabled and must stay disabled.

Research now runs only under the research office's standing permission (docs/office/), which has no write path to
trading configuration.
