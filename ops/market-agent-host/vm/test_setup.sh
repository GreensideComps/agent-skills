#!/usr/bin/env bash
# End-to-end test of setup.sh on a throwaway Ubuntu machine (run as root; it creates the `marketagent` user and
# installs git/python packages). Uses a local bare repo instead of GitHub, a fake agent instead of the real one, and no
# systemd: proves the script installs, stores the key safely, registers the server's encryption key, waits for the
# reseal, then claims the branch and runs the agent once a session hands over to the vm.
#   sudo bash ops/market-agent-host/vm/test_setup.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../../.." && pwd)
T=$(mktemp -d /tmp/ma-vm-test.XXXX); chmod 755 "$T"
trap 'rm -rf "$T"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
git config --system --add safe.directory '*'   # the test repo is root-owned, the agent user reads it

# a "GitHub": bare repo with master (controller + workflow) and agent-branch (fake agent)
bare="$T/remote.git"; work="$T/work"
git init -q --bare "$bare"; git clone -q "$bare" "$work" 2>/dev/null
mkdir -p "$work/ops/market-agent-host" "$work/.github/workflows"
cp "$SRC/ops/market-agent-host/hostctl.py" "$work/ops/market-agent-host/"
sed 's/^  AGENT_REF: .*/  AGENT_REF: agent-branch   # test/' "$SRC/.github/workflows/market-agent.yml" > "$work/.github/workflows/market-agent.yml"
git -C "$work" add -A && git -C "$work" -c user.name=t -c user.email=t@t commit -qm controller && git -C "$work" push -q origin HEAD:refs/heads/master
git -C "$work" checkout -q --orphan agent && git -C "$work" rm -rq --cached . && rm -rf "$work/ops" "$work/.github"
mkdir -p "$work/agent"
cat > "$work/agent/fake_agent.py" <<'PY'
#!/usr/bin/env python3
import json, os, signal, time
from pathlib import Path
st = Path(os.environ["MARKET_AGENT_STATE"]); stop = []
signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
assert os.environ["T212_ENV"] == "demo"
while not stop:
    (st / "heartbeat.json").write_text(json.dumps({"t": time.time(), "version": "fake-vm",
                                                  "host": os.environ["MARKET_AGENT_HOST"]}))
    time.sleep(0.2)
PY
chmod +x "$work/agent/fake_agent.py"
git -C "$work" add -A && git -C "$work" -c user.name=t -c user.email=t@t commit -qm agent && git -C "$work" push -q origin HEAD:refs/heads/agent-branch
git -C "$work" checkout -q master
chmod -R a+rwX "$bare"

# a "session": seeds the state, then hands over to the vm
proj="$T/proj"; mkdir -p "$proj/market-agent/state/events" "$proj/research/stock-screener"
echo '{"trading_enabled": true}' > "$proj/market-agent/state/control.json"
echo "pick" > "$proj/research/stock-screener/picks_2026-11.csv"
S=(env T212_API_KEY=k T212_API_SECRET=session-secret python3 "$work/ops/market-agent-host/hostctl.py" --repo "$work")
"${S[@]}" seed --root "$proj" >/dev/null
"${S[@]}" handover --to vm --reason test >/dev/null

common=(MA_REPO_URL="$bare" MA_PUSH_URL="$bare" MA_PREFIX="$T/pfx" MA_SKIP_DEPLOY_KEY=1 MA_SKIP_T212_CHECK=1
        MA_T212_KEY=demo-key-xyz MA_T212_SECRET=vm-secret-xyz MA_NO_SYSTEMD=1 MA_UNIT_DIR="$T/unit")
out=$(env "${common[@]}" MA_TEST_ARGS="--budget-min 0.2" bash "$HERE/setup.sh" 2>&1) || fail "setup run 1: $out"
grep -q "registered this host's key" <<<"$out" || fail "no key registration: $out"
grep -q "hostctl reseal" <<<"$out" || fail "did not wait for a reseal: $out"
grep -q -e vm-secret-xyz -e demo-key-xyz <<<"$out" && fail "a secret was printed"
envf="$T/pfx/etc/market-agent/env"
[ "$(stat -c '%a %U %G' "$envf")" = "640 root marketagent" ] || fail "env file perms $(stat -c '%a %U %G' "$envf")"
grep -q '^MA_STATE_KEY=[0-9a-f]\{64\}$' "$envf" || fail "no random state key"
grep -q '^AGENT_REF=agent-branch$' "$envf" || fail "AGENT_REF not stored"
grep -q "^ExecStart=.*hostctl.py --repo $T/pfx/opt/market-agent/repo run --host-name vm .*--agent-ref \${AGENT_REF} .*--budget-min 0$" "$T/unit/market-agent.service" \
  || fail "unit ExecStart: $(grep ExecStart= "$T/unit/market-agent.service")"
key1=$(sed -n 's/^MA_STATE_KEY=//p' "$envf")

"${S[@]}" reseal >/dev/null
out=$(env "${common[@]}" MA_TEST_ARGS="--budget-min 0.3 --tick-s 0.5 --sync-s 3 --agent-cmd ./fake_agent.py" bash "$HERE/setup.sh" 2>&1) || fail "setup run 2: $out"
grep -q "keeping the key already stored" <<<"$out" || fail "rerun did not keep the stored key"
[ "$(sed -n 's/^MA_STATE_KEY=//p' "$envf")" = "$key1" ] || fail "rerun changed the state key"
grep -q "agent started" <<<"$out" || fail "agent did not start after the reseal: $out"
grep -q "final snapshot pushed" <<<"$out" || fail "no final snapshot: $out"
st=$("${S[@]}" status || true)
python3 - "$st" <<'PY' || fail "status after the vm run: $st"
import json, sys
s = json.loads(sys.argv[1])
assert s["owner"]["host"] == "vm" and s["hosted"]["run_id"].startswith("vm-") and s["hosted"]["phase"] == "stopped", s
assert s["hosted"]["version"] == "fake-vm", s
PY
[ -f "$T/pfx/var/lib/market-agent/root/research/stock-screener/picks_2026-11.csv" ] || fail "research inputs not restored"
echo "ok: setup.sh installs, keeps secrets private, registers, waits for reseal, then runs the agent as host=vm"
