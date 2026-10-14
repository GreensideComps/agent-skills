#!/usr/bin/env bash
# Hourly read-only check (used by the "T212 demo: monitor" routine). Never trades.
#   1. sync   2. t212bot monitor   3. commit the journal's monitor event and push
# Exit code is the monitor's: 0 ok, 1 warning, 2 critical.
set -uo pipefail
BRANCH="${T212BOT_BRANCH:-claude/trading212-agent-skills-r71zy3}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --rebase origin "$BRANCH" || {
  echo "MONITOR: could not sync $BRANCH"; exit 3; }
python3 -c "import pandas, numpy" 2>/dev/null || pip3 install -q pandas numpy >/dev/null 2>&1

cd trading
python3 -m t212bot monitor; RC=$?

cd "$ROOT"
git add trading/journal
if ! git diff --cached --quiet; then
  if git diff --cached | grep -qF "${T212_API_KEY:-__none__}" || git diff --cached | grep -qF "${T212_API_SECRET:-__none__}"; then
    echo "MONITOR: credential detected in staged diff - aborting commit"; git reset -q; exit 4
  fi
  git commit -q -m "monitor: $(date -u +%Y-%m-%dT%H:%MZ) (rc=$RC)"
  for i in 1 2 3 4; do
    git push -q origin "$BRANCH" && break
    git pull -q --rebase origin "$BRANCH"; sleep $((2**i))
  done
fi
exit "$RC"
