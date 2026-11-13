#!/usr/bin/env bash
# One-command setup of the Trading 212 DEMO market agent on an always-on Linux server (Oracle Cloud Always Free,
# Ubuntu 22.04/24.04, Ampere A1 or E2.1.Micro). Guide for the owner: ops/market-agent-host/vm/ORACLE_GUIDE.md.
#
#   curl -fsSL https://raw.githubusercontent.com/GreensideComps/agent-skills/master/ops/market-agent-host/vm/setup.sh | sudo bash
#
# What it does (safe to run again; it keeps what is already set up):
#   1. installs git + Python, adds a 2 GB swap file on small machines, creates the `marketagent` user;
#   2. clones the repository and installs the agent's Python packages in a private virtualenv;
#   3. makes an SSH deploy key and waits until you have added it to the repository (write access), because the agent
#      keeps its encrypted state on the repository's `market-agent-state` branch;
#   4. asks for the Trading 212 DEMO API key and secret (typed, not shown), checks them against the demo API, and stores
#      them only in /etc/market-agent/env (readable by root and the agent user); a random state key is added there too;
#   5. installs and starts the `market-agent` systemd service (`hostctl run --host-name vm`). It does NOT trade yet:
#      it registers its encryption key and stands by until a Claude session reseals the state and hands over to it.
#
# Nothing secret is printed. Test hooks (used by test_setup.sh, not needed on a real server): MA_REPO_URL, MA_PUSH_URL,
# MA_T212_KEY / MA_T212_SECRET (skip the prompts), MA_SKIP_T212_CHECK=1, MA_SKIP_DEPLOY_KEY=1, MA_NO_SYSTEMD=1, MA_PREFIX.
set -euo pipefail

REPO_URL="${MA_REPO_URL:-https://github.com/GreensideComps/agent-skills.git}"
PUSH_URL="${MA_PUSH_URL:-git@github.com:GreensideComps/agent-skills.git}"
KEYS_PAGE="https://github.com/GreensideComps/agent-skills/settings/keys/new"
PREFIX="${MA_PREFIX:-}"
APP="$PREFIX/opt/market-agent"
DATA="$PREFIX/var/lib/market-agent"
ETC="$PREFIX/etc/market-agent"
USER_NAME=marketagent
# GitHub's published SSH host key (https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
GITHUB_ED25519_FP="SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
ask() {  # ask VAR "prompt" [silent]
  local __v
  if [ "${3:-}" = silent ]; then read -r -s -p "$2" __v </dev/tty; echo; else read -r -p "$2" __v </dev/tty; fi
  printf -v "$1" '%s' "$(printf '%s' "$__v" | tr -d '[:space:]')"
}
as_agent() { if [ "$(id -un)" = "$USER_NAME" ]; then "$@"; else sudo -u "$USER_NAME" -H "$@"; fi; }

[ "$(id -u)" -eq 0 ] || die "run it with sudo: curl -fsSL <url> | sudo bash"

say "1/5 System packages"
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null; then
  apt-get update -qq
  apt-get install -y -qq git python3 python3-venv python3-pip openssh-client curl ca-certificates sudo >/dev/null
elif command -v dnf >/dev/null; then  # Oracle Linux image
  dnf install -y -q git python3 python3-pip openssh-clients curl ca-certificates sudo >/dev/null
else
  die "no apt-get or dnf: use the Ubuntu image (see the guide)"
fi
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 3000 ] && [ -z "$PREFIX" ] && ! swapon --show | grep -q .; then
  say "Small machine (${mem_mb} MB): adding a 2 GB swap file"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
id "$USER_NAME" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$DATA" --shell /usr/sbin/nologin "$USER_NAME"
mkdir -p "$APP" "$DATA/root" "$ETC"
chown "$USER_NAME:" "$APP" "$DATA" "$DATA/root"

say "2/5 Code and Python packages"
if [ ! -d "$APP/repo/.git" ]; then
  as_agent git clone -q --filter=blob:none "$REPO_URL" "$APP/repo"
else
  as_agent git -C "$APP/repo" pull -q --ff-only || echo "   (could not fast-forward the checkout; keeping it)"
fi
as_agent git -C "$APP/repo" config user.name market-agent-host
as_agent git -C "$APP/repo" config user.email market-agent-host@users.noreply.github.com
[ -x "$APP/venv/bin/python" ] || as_agent python3 -m venv "$APP/venv"
as_agent "$APP/venv/bin/pip" install -q --upgrade pip
as_agent "$APP/venv/bin/pip" install -q requests pandas cryptography
AGENT_REF=$(sed -n 's/^ *AGENT_REF: *\([^ #]*\).*/\1/p' "$APP/repo/.github/workflows/market-agent.yml" | head -1)
[ -n "$AGENT_REF" ] || die "could not read AGENT_REF from .github/workflows/market-agent.yml"
echo "   agent branch: $AGENT_REF"

say "3/5 Write access to the repository (deploy key)"
SSH_DIR="$DATA/.ssh"
mkdir -p "$SSH_DIR" && chown "$USER_NAME:" "$SSH_DIR" && chmod 700 "$SSH_DIR"
[ -f "$SSH_DIR/id_ed25519" ] || as_agent ssh-keygen -q -t ed25519 -N "" -C "market-agent-vm" -f "$SSH_DIR/id_ed25519"
if [ -z "${MA_SKIP_DEPLOY_KEY:-}" ]; then
  scan=$(ssh-keyscan -t ed25519 github.com 2>/dev/null)
  fp=$(printf '%s\n' "$scan" | ssh-keygen -lf - | awk '{print $2}')
  [ "$fp" = "$GITHUB_ED25519_FP" ] || die "github.com host key fingerprint $fp does not match GitHub's published one"
  printf '%s\n' "$scan" > "$SSH_DIR/known_hosts"; chown "$USER_NAME:" "$SSH_DIR/known_hosts"
fi
as_agent git -C "$APP/repo" config core.sshCommand "ssh -i $SSH_DIR/id_ed25519 -o UserKnownHostsFile=$SSH_DIR/known_hosts -o IdentitiesOnly=yes"
as_agent git -C "$APP/repo" remote set-url --push origin "$PUSH_URL"
if [ -z "${MA_SKIP_DEPLOY_KEY:-}" ]; then
  until as_agent git -C "$APP/repo" push -q --dry-run origin HEAD:refs/heads/market-agent-vm-write-check 2>/dev/null; do
    echo
    echo "   Add this key in GitHub, then press Enter:"
    echo "     1. open $KEYS_PAGE"
    echo "     2. Title: oracle-vm     Key: the line below     tick 'Allow write access'     Add key"
    echo
    cat "$SSH_DIR/id_ed25519.pub"
    echo
    read -r -p "   Press Enter once the key is added..." _ </dev/tty
  done
  echo "   write access OK"
fi

say "4/5 Trading 212 DEMO API key"
if [ -f "$ETC/env" ] && grep -q '^T212_API_KEY=.' "$ETC/env" && [ -z "${MA_RESET_KEYS:-}" ]; then
  echo "   keeping the key already stored in $ETC/env (run with MA_RESET_KEYS=1 to replace it)"
else
  key="${MA_T212_KEY:-}"; secret="${MA_T212_SECRET:-}"
  [ -n "$key" ] || ask key "   Trading 212 DEMO API key: " silent
  [ -n "$secret" ] || ask secret "   Trading 212 DEMO API secret: " silent
  [ -n "$key" ] && [ -n "$secret" ] || die "key and secret are both needed"
  if [ -z "${MA_SKIP_T212_CHECK:-}" ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' -u "$key:$secret" https://demo.trading212.com/api/v0/equity/account/cash || true)
    [ "$code" = 200 ] || die "the demo API refused this key (HTTP $code). Use a key made in Trading 212 while in Practice (demo) mode."
    echo "   demo API accepted the key"
  fi
  umask 077
  state_key=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  if [ -f "$ETC/env" ] && grep -q '^MA_STATE_KEY=.' "$ETC/env"; then state_key=$(sed -n 's/^MA_STATE_KEY=//p' "$ETC/env"); fi
  printf 'T212_ENV=demo\nT212_API_KEY=%s\nT212_API_SECRET=%s\nMA_STATE_KEY=%s\nAGENT_REF=%s\n' \
    "$key" "$secret" "$state_key" "$AGENT_REF" > "$ETC/env.new"
  mv "$ETC/env.new" "$ETC/env"
  unset key secret state_key
fi
sed -i "s/^AGENT_REF=.*/AGENT_REF=$AGENT_REF/" "$ETC/env"
chown "root:$USER_NAME" "$ETC/env" && chmod 640 "$ETC/env"

say "5/5 Service"
run_cmd() {  # run_cmd AGENT_REF_VALUE
  echo "$APP/venv/bin/python $APP/repo/ops/market-agent-host/hostctl.py --repo $APP/repo run --host-name vm" \
       "--root $DATA/root --agent-ref $1 --code-dir $DATA/code --budget-min 0"
}
UNIT_DIR="${MA_UNIT_DIR:-/etc/systemd/system}"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/market-agent.service" <<UNIT
[Unit]
Description=Trading 212 DEMO market agent (hostctl run --host-name vm)
Documentation=https://github.com/GreensideComps/agent-skills/tree/master/ops/market-agent-host
Wants=network-online.target
After=network-online.target

[Service]
User=$USER_NAME
EnvironmentFile=$ETC/env
WorkingDirectory=$APP/repo
# keep the controller itself current; the agent code follows AGENT_REF inside hostctl
ExecStartPre=-/usr/bin/git -C $APP/repo pull -q --ff-only
ExecStart=$(run_cmd '${AGENT_REF}')
Restart=always
RestartSec=60
KillSignal=SIGTERM
TimeoutStopSec=150
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
if [ -n "${MA_NO_SYSTEMD:-}" ]; then
  echo "   MA_NO_SYSTEMD set: one short pass in the foreground instead of a service"
  set -a; . "$ETC/env"; set +a
  # shellcheck disable=SC2046
  as_agent env T212_ENV="$T212_ENV" T212_API_KEY="$T212_API_KEY" T212_API_SECRET="$T212_API_SECRET" \
    MA_STATE_KEY="$MA_STATE_KEY" $(run_cmd "$AGENT_REF") ${MA_TEST_ARGS:---budget-min 0.2}
  exit 0
fi
systemctl daemon-reload
systemctl enable -q market-agent.service
systemctl restart market-agent.service
echo "   waiting for the first check-in..."
for _ in $(seq 1 36); do
  if journalctl -u market-agent -n 50 --no-pager -q 2>/dev/null | grep -Eq "registered this host's key|standby|awaiting|hostctl reseal|agent started"; then break; fi
  sleep 5
done
journalctl -u market-agent -n 8 --no-pager -q -o cat | grep -v -i secret || true
cat <<DONE

Done. The server is set up and standing by: it is NOT trading yet.
Last step: tell Claude "the server is ready". A Claude session will then re-encrypt the agent's state for this
server and hand trading over to it; the GitHub runner stops by itself within 2 minutes.

Useful commands on this server:
  sudo systemctl status market-agent        is it running?
  sudo journalctl -u market-agent -f        live log (no positions or keys are printed)
  sudo systemctl stop market-agent          stop it (the state is saved first)
DONE
