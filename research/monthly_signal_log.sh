#!/usr/bin/env bash
# Monthly prospective signal log (used by the "Research: monthly signal log" routine). Research only: no broker
# calls, no orders. Needs SEC_USER_AGENT="<app> <email>". Takes about two hours (SEC bulk files, ~5,400 prices).
#   1. tests  2. rebuild the research dataset  3. score last month (once)  4. evaluate logged months
#   5. commit the report and push
set -uo pipefail
BRANCH="${EQUITY_BRANCH:-master}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
: "${SEC_USER_AGENT:?set SEC_USER_AGENT to '<app name> <contact email>' (SEC requires it)}"
export RESEARCH_DATA="${RESEARCH_DATA:-/mnt/project-files/research-data}"

git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --rebase origin "$BRANCH" || {
  echo "SIGNALS: could not sync $BRANCH"; exit 3; }
(cd research && python3 -m pytest -q tests) || { echo "SIGNALS: tests failed, nothing run"; exit 4; }
(cd equity && python3 -m equity research-data --out "$RESEARCH_DATA" --refresh) || { echo "SIGNALS: data build failed"; exit 5; }
cd research
python3 signal_log.py score || { echo "SIGNALS: scoring failed"; exit 6; }
python3 signal_log.py evaluate ../equity/reports/research/signal_log.md || { echo "SIGNALS: evaluate failed"; exit 7; }
cd "$ROOT"
git add equity/reports/research/signal_log.md
if ! git diff --cached --quiet; then
  git commit -q -m "research: monthly signal log $(date -u +%Y-%m-%d)"
  for i in 1 2 3 4; do git push -q origin "$BRANCH" && break; sleep $((2 ** i)); git pull -q --rebase origin "$BRANCH"; done
fi
echo "SIGNALS: done"
