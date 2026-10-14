#!/usr/bin/env bash
# Daily equity research pipeline (used by the "Equity: daily research pipeline" routine).
# Research only: no broker calls, no orders. Needs SEC_USER_AGENT="<app> <email>" in the environment.
#   1. tests  2. grow the universe (NEW companies)  3. rolling re-check of old snapshots
#   4. prices  5. screen + valuation + alerts  6. paper portfolio  7. portfolio monitor  8. reliability
#   9. commit and push
# Exit code: the reliability check's (0 ok, 1 warn, 2 critical), or 3+ if a step failed.
set -uo pipefail
BRANCH="${EQUITY_BRANCH:-master}"
NEW="${EQUITY_NEW_PER_DAY:-200}"
REFRESH="${EQUITY_REFRESH_PER_DAY:-300}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
: "${SEC_USER_AGENT:?set SEC_USER_AGENT to '<app name> <contact email>' (SEC requires it)}"

git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --rebase origin "$BRANCH" || {
  echo "EQUITY: could not sync $BRANCH"; exit 3; }

cd equity
python3 -m pytest -q tests || { echo "EQUITY: tests failed, nothing run"; exit 4; }
FAILED=""
# Per-company ingest failures (e.g. SEC has no companyfacts) are expected and recorded in the job ledger.
python3 -m equity ingest --all-sec --new-only --limit "$NEW" | tail -n 1
python3 -m equity ingest --all-sec --refresh "$REFRESH" | tail -n 1
python3 -m equity prices >/dev/null || FAILED="$FAILED prices"
python3 -m equity screen --top 25 >/dev/null || FAILED="$FAILED screen"
python3 -m equity paper >/dev/null || FAILED="$FAILED paper"
# Read-only portfolio monitor (needs the T212 read-only variables; skipped without them).
if [ -n "${T212_API_KEY:-}" ]; then
  python3 -m equity portfolio --ingest-missing >/dev/null || FAILED="$FAILED portfolio"
fi
python3 -m equity reliability; RC=$?
[ -n "$FAILED" ] && echo "EQUITY: steps with failures:$FAILED (see equity/data/jobs/)"

cd "$ROOT"
git add equity/data equity/reports
if ! git diff --cached --quiet; then
  git commit -q -m "equity: daily pipeline $(date -u +%Y-%m-%d) (rc=$RC${FAILED:+, failed:$FAILED})"
  for i in 1 2 3 4; do
    git push -q origin "$BRANCH" && break
    git pull -q --rebase origin "$BRANCH"; sleep $((2**i))
  done
fi
[ -n "$FAILED" ] && [ "$RC" -lt 3 ] && RC=3
exit "$RC"
