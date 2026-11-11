# Where things are (11 Nov 2026)

Most files here are records: pre-registrations, incident reports and plans that were true when written. Records are
never edited or deleted (the research rules forbid rewriting past results). Use this page to tell what is CURRENT.

## Current: read these first

| Topic | File |
|---|---|
| What the demo agent does, version by version | `docs/agent/MARKET_AGENT.md` |
| The agent's rules, generated from config (CI fails if stale) | `docs/agent/RULES.md` |
| How a research idea passes (from 12 Nov 2026) | `research/GATE_V3.md`, code `research/gate.py` |
| Statistics every script must import | `research/stats.py` |
| Why the old pass bar went, what the registry shows | `research/METHOD_AUDIT.md` |
| Survivorship bias in the stock panel, and its bound | `research/SURVIVORSHIP.md` |
| Which demo strategies run as designed, and when each can be judged | `research/STRATEGY_REVIEW_2026-11.md` |
| Real-money go-live rule and the demo scoreboard | `research/always_on/GO_LIVE_RULE.md` (shared copy in `/mnt/project-files/research/always-on/`), `research/always_on/scoreboard.py` |
| The research loop's procedure and queue | `/mnt/project-files/research/always-on/LOOP.md`, `QUEUE.md` |
| The improvement track's backlog | `/mnt/project-files/research/improve/BACKLOG.md`, `TRACK.md` |
| Trade log | `/mnt/project-files/market-agent/TRADES.md` |

## Records: historical, do not act on them

- `docs/edge/`: the B1-B5 edge programme (closed). Its pre-registrations, manifests and incidents are evidence for the
  registry's early lines.
- `docs/minifund/`: the mini-fund stages 1-4 (data purchase comparisons, Sharadar plans). Paid data is not used.
- `docs/office/`: office decisions; `DECISION_REGISTER.md` is the running list of owner decisions.
- `docs/AUDIT_AND_PLAN.md`, `docs/STRATEGY_V2.md`: October plans, superseded by the files above.
- `research/h01_*.py` to `research/h09_*.py`, `research/run_*.py`, `research/edge_*.py`: the scripts behind recorded
  results. Kept so those results can be reproduced.
- `/mnt/project-files/archive/`: retired material (for example the Signal Room dashboard, switched off 4 Nov).

## Code that runs

| Folder | What it is | Runs where |
|---|---|---|
| `agent/` | the demo market agent | GitHub Actions, 24/7 (never start `agent/run.sh` locally) |
| `ops/market-agent-host/` | hosting control (`hostctl`) and the encrypted state branch | GitHub Actions |
| `trading/t212bot/` | the Trading 212 API client the agent and pipelines import | library |
| `equity/` | the equity research pipeline and weekly data rebuild | scheduled routine |
| `office/` | the office worker | scheduled routine |
| `research/` | research code, tests and the scoreboard | research loop and CI |
| `index.ts`, `plugins/`, `clawdbot.plugin.json` | the upstream Trading 212 skills plugin this repository was forked from | not used by the system |
