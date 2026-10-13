# Research loop: standing procedure for each unattended research run

This file is the "brain" of the self-improving loop. A scheduled routine starts a
fresh cloud session that follows these steps exactly. It runs unattended, so it
must be conservative, reproducible and honest.

## 0. Preconditions
1. `git fetch origin claude/trading212-agent-skills-r71zy3 && git checkout claude/trading212-agent-skills-r71zy3 && git pull --rebase`
2. If `research/STOP` exists: write one line to `research/LOG.md` ("stopped by STOP file"), commit, push and end.
3. `pip3 install -q pandas numpy scipy statsmodels pytest`
4. Read `research/REPORT.md` (round 1 findings), `research/PROMOTION_GATE.md`, `research/AGENDA.md`, the tail of `research/LOG.md`, and `trading/PERFORMANCE.md`.

## 1. Pick work
- If the run number (count of entries in LOG.md, plus 1) is divisible by 5, do agenda item P8 (generate new hypotheses) first.
- Otherwise take the highest-priority `OPEN` item. Mark it `IN PROGRESS` with today's date.
- A `BLOCKED` item gets one cheap unblock attempt per week at most.

## 2. Do the research properly
- Reuse `research/` code (`dataset.py`, `engine.py`, `strategies.py`). Add new code as `research/hNN_<slug>.py`, writing outputs to `research/output/hNN_*.csv`.
- Freeze the pre-registered grid **before** computing out-of-sample results. Increment the agenda's trial counter by the number of configurations run.
- Include costs (spread by asset, 0.15% FX on non-GBP lines), a one-day lag robustness check, a bootstrap against the champion, and a deflated Sharpe ratio.
- Never invent numbers. Every figure in the write-up must come from a script committed in this run.
- If a data source fails, try a legitimate alternative. Otherwise mark the item `BLOCKED` with the exact error.

## 3. Decide using the promotion gate
- Fails a Stage 2 test → `DONE: rejected`, recording which test failed.
- Passes Stage 2 → add the challenger to `trading/config/strategy.json` → `shadow_portfolios` (the shadow engine must support its type; add the type in `trading/t212bot/shadow.py` with a unit test), then mark `DONE: promising → shadow`.
- A shadow challenger with at least 20 trading days of clean tracking, passing every stage, and with no promotion yet this quarter → promote per Stage 4. Run `cd trading && python3 -m pytest -q` before committing. **Never place orders from the research loop**; the ops routine trades the new targets at its next run.

## 4. Record
- Append to `research/LOG.md`: date, item, what was run, the key numbers, the decision, and the trial count.
- Update the item in `AGENDA.md`. Update `REPORT.md` only when something changes the overall conclusion.
- Commit with the message `research: <item> - <decision>` and push (rebase on conflict, retry up to 4 times).
- Check that no credentials are staged: `git diff --cached | grep -F "$T212_API_KEY"` must find nothing.

## Hard rules
- Demo account only. Never contact `live.trading212.com`. Never place, modify or cancel orders from the research loop.
- No leverage or shorting in any recommended strategy.
- Do not tune parameters on out-of-sample data. If you peeked, say so and count it as a new trial.
- Prefer "no change" when in doubt. Most ideas should fail; that's the point of the gate.
