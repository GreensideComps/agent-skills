#!/usr/bin/env bash
# Scheduled trading run (used by the "T212 demo: trading ops" routine).
# Safe to run any time: outside market hours it snapshots and defers.
#   1. sync the branch   2. run tests   3. bot run --execute   4. report
#   5. commit journal + report and push (rebasing on conflicts)
set -uo pipefail
BRANCH="${T212BOT_BRANCH:-claude/trading212-agent-skills-r71zy3}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --rebase origin "$BRANCH" || {
  echo "OPS: could not sync $BRANCH"; exit 3; }

python3 -c "import pandas, numpy, pytest" 2>/dev/null || pip3 install -q pandas numpy pytest >/dev/null 2>&1

cd trading
if ! python3 -m pytest -q >/tmp/t212bot_tests.log 2>&1; then
  echo "OPS: tests FAILED - not trading"; tail -20 /tmp/t212bot_tests.log
  python3 -m t212bot status || true
  TRADE_RC=99
else
  python3 -m t212bot run --execute; TRADE_RC=$?
fi
python3 -m t212bot report >/dev/null 2>&1 || echo "OPS: report failed (non-fatal)"

cd "$ROOT"
git add trading/journal trading/PERFORMANCE.md
if ! git diff --cached --quiet; then
  if git diff --cached | grep -qF "${T212_API_KEY:-__none__}" || git diff --cached | grep -qF "${T212_API_SECRET:-__none__}"; then
    echo "OPS: credential detected in staged diff - aborting commit"; git reset -q; exit 4
  fi
  git commit -q -m "ops: trading run $(date -u +%Y-%m-%dT%H:%MZ) (rc=$TRADE_RC)"
  for i in 1 2 3 4; do
    git push -q origin "$BRANCH" && break
    git pull -q --rebase origin "$BRANCH"; sleep $((2**i))
  done
fi
echo "OPS: done (trade rc=$TRADE_RC)"
exit "$TRADE_RC"
