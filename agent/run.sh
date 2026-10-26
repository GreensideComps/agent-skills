#!/bin/sh
# Supervisor: keeps one market agent running; restarts it after any exit with a capped backoff.
# Usage: agent/run.sh   (state dir from MARKET_AGENT_STATE, default /mnt/project-files/market-agent/state)
cd "$(dirname "$0")" || exit 1
STATE="${MARKET_AGENT_STATE:-/mnt/project-files/market-agent/state}"
mkdir -p "$STATE/logs"
back=10
while :; do
  start=$(date +%s)
  echo "$(date -u +%FT%TZ) supervisor: starting agent" >> "$STATE/logs/supervisor.log"
  python3 -m market_agent --state "$STATE" run >> "$STATE/logs/agent.out" 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) supervisor: agent exited rc=$rc after $(( $(date +%s) - start )) s" >> "$STATE/logs/supervisor.log"
  [ $(( $(date +%s) - start )) -gt 600 ] && back=10
  [ "$rc" -eq 3 ] && back=60
  sleep "$back"
  back=$(( back * 2 )); [ "$back" -gt 300 ] && back=300
done
