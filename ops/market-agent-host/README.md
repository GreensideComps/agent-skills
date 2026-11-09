# Hosted market agent (GitHub Actions)

The Trading 212 **demo** market agent used to run inside a Claude session container, which stops whenever the session
sleeps (see `market-agent/INCIDENTS.md`: ~12 h overnight gaps, several 3 h stalls). It now runs on GitHub Actions,
which is free for this public repository and does not depend on any session being awake.

## Pieces

| Piece | What it does |
|---|---|
| `.github/workflows/market-agent.yml` | Around the clock. Each run (~5.5 h) queues its successor as soon as it starts; the `market-agent` concurrency group keeps one running and one waiting, so the next takes over about a minute after a run ends. GitHub's cron is hours late in practice, so a twice-hourly cron is only a backstop that restarts a broken chain. |
| `ops/market-agent-host/hostctl.py run` | Restores state, checks out the agent from `AGENT_REF` (the office thread's deploy branch), runs `python -m market_agent run`, restarts it on exit with a backoff, syncs state every 2 min, restarts on a new agent commit within 5 min, and pushes a final snapshot when it stops. |
| branch `market-agent-state` | One orphan commit, force-pushed with a lease (history never grows). `snapshot.tar.gz.enc` (state, encrypted), `inputs.tar.gz.enc` (research picks the agent reads, encrypted), `owner.json`, `control.json`, `hosted.json` (plaintext, nothing secret). |

The repository is public, so the state is encrypted (AES-256, key derived from `T212_API_SECRET`), and the runner
prints nothing about positions, orders or keys. Agent output stays in the encrypted `logs/agent.out`.

## One trader at a time

* `owner.json` `host` decides who may trade: `github-actions` or `session`.
* The hosted runner trades only while it says `github-actions`, and stops within 2 min after it changes.
* A new run waits until the previous run's `hosted.json` is `stopped` or 5 min stale, then claims the branch with a
  compare-and-swap push.
* A Claude session **must not** start `agent/run.sh` while `host` is `github-actions`. `seed` and `mirror` refuse
  while a local agent holds its lease.

## Owner setup (once)

Add two repository secrets at <https://github.com/GreensideComps/agent-skills/settings/secrets/actions/new>:
`T212_API_KEY` and `T212_API_SECRET`, the **demo** key pair already used by the agent. Nothing else is needed.

## Commands (from a Claude session with the repo and the demo key in its environment)

```sh
H=ops/market-agent-host/hostctl.py
python3 $H status                        # who is host, last hosted sync, agent version (exit 1 = hosted run stale)
python3 $H seed --root /mnt/project-files     # first cutover, after the local agent is stopped
python3 $H mirror --root /mnt/project-files   # refresh the read-only replica for research and the dashboard
python3 $H push-inputs --root /mnt/project-files  # after research writes new picks (forward/, stock-screener/)
python3 $H halt "reason" / resume "reason"    # kill switch, applied by the hosted agent within 2 min
python3 $H handover --to session --reason "..." --root /mnt/project-files   # take it back into a session
python3 $H handover --to github-actions --reason "..." --root /mnt/project-files
```

## Cutover

1. Owner adds the two secrets. Runs then log "state branch not seeded" instead of the missing-secrets warning.
2. Office thread stops its agent (`agent/run.sh` and `python3 -m market_agent run`) and disables the restart in its
   watchdog.
3. `hostctl seed --root /mnt/project-files`, then trigger the workflow ("Run workflow") or wait up to 20 min.
4. The office watchdog switches to `hostctl status` (alert when exit 1 during the window) plus `hostctl mirror`.

## Not shipped to the hosted copy

* `research/always-on/scoreboard.py`: the agent skips it when the file is absent; run it in a session after `mirror`.

## Caveat

GitHub's terms say Actions is for building, testing and deploying a repository's software, and long-running service use
can be throttled or disabled. If GitHub objects, the same
`hostctl.py run` works unchanged on an always-free cloud VM (for example Oracle Cloud's free tier) under systemd.
