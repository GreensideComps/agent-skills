# This branch is retired (owner decision O10, 20 Oct 2026)

This branch held the Trading 212 demo bot that traded a discretionary intraday strategy (100% LQQ3 at the end).
It is kept unchanged for audit: its history, journal, `config/strategy.json` (sha256 `a08ad34d…`) and research
files are preserved.

Nothing here can trade any more:
- `ops_run.sh` and `monitor_run.sh` exit 5 before any git sync, test run or bot call;
- `python3 -m t212bot <any command>` exits 5 before reading credentials or contacting the broker;
- `Bot.run`, `decide`, `Bot._place`, `Bot._retry_buy_with_fresh_cash` raise `SafetyError`;
- the API client refuses every non-GET request (order placement and cancellation).

The switch is the code constant `BRANCH_RETIRED = True` in `t212bot/retired.py`; it is not driven by any
config file. `tests/test_retired_branch.py` checks each refusal. The five scheduled tasks that ran this branch
were deleted on the owner's instruction; their record is in `docs/office/O10_LEGACY_TASKS_RECORD.json` on the
`claude/retire-lqq3-legacy-loop` branch. The active system lives on `master`.
