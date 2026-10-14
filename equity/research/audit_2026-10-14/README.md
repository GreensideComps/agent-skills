# Pre-trade validation audit, 14 October 2026

Inputs and scripts behind `equity/reports/portfolio/2026-10-14-validation.md`. Read-only work: no orders, no pie
or account changes. Scripts were run from a scratch directory and write to `/mnt/project-files/portfolio/audit/`;
adjust the paths to re-run.

- `rerun.py`: full re-run of the M8 screen backtest (600 companies, seed 7) from fresh SEC and Yahoo downloads.
- `bt_audit.py ROWS OUT`: reproduces the t-statistic and adds bootstrap, leave-one-out, binomial, size, sector,
  regime and sub-score breakdowns.
- `evidence.py`: per-holding fundamentals, screen and valuation evidence joined to the live API snapshot.
- `prices5y.py`, `risk.py`: 5-year daily prices (Yahoo) and the keep / hard-risk exits / proposed / VWRP comparison.
- `api_snapshot.json`: demo-account read at 2026-10-14T15:05:38Z (account id removed).

The 5-year price file (1.5 MB) and the re-run rows (identical to the original rows) are kept in the project files,
not committed.
