#!/usr/bin/env python3
"""Host the Trading 212 DEMO market agent outside Claude sessions (GitHub Actions), with its state kept on a git branch.

Why: the agent used to run inside a Claude session container, which stops whenever the session sleeps (INCIDENTS.md
lists ~12 h overnight gaps and several 3 h stalls). A GitHub Actions job runs for up to 6 h whether or not any session
is awake; the workflow `.github/workflows/market-agent.yml` chains jobs through the market day.

State branch `market-agent-state` (one orphan commit, force-pushed with a lease, so history never grows):
  snapshot.tar.gz.enc  hosted -> everyone. market-agent/state/** (events: last KEEP_EVENT_DAYS days) and the agent's
                       forward log research/always-on/forward/Q205.csv. Encrypted (the repo is public).
  inputs.tar.gz.enc    session -> hosted. Research files the agent reads (forward/ picks, stock-screener picks).
  owner.json           plaintext. {"host": "github-actions" | "session"}: the ONLY place that decides who may trade.
  control.json         plaintext kill switch, copied into the hosted agent's state on every sync.
  hosted.json          plaintext runner status: run id, phase, last sync time, agent commit, health verdict.

Encryption key = sha256("market-agent-state-v1" + T212_API_SECRET), so no extra secret is needed: anyone who can run the
agent can read its state and nobody else can. Nothing secret is ever printed (Actions logs on a public repo are public).

One trader at a time:
  * the hosted runner starts the agent only while owner.json says github-actions, and stops within one sync interval
    (SYNC_S) after it changes;
  * the runner waits for a previous run's hosted.json to be stopped or stale before it claims the branch, and claims it
    with a compare-and-swap push;
  * a Claude session must not start its own agent while owner.json says github-actions; `handover --to session` waits
    for the hosted run to stop and mirrors its state first. `seed` refuses while a local agent holds its lease.

Commands (run from any clone of the repo with push rights):
  seed     --root /mnt/project-files [--force]   first cutover: pack local state + inputs, set host=github-actions
  status                                         owner, hosted run, last sync age (exit 0 ok, 1 stale, 2 not seeded)
  mirror   --root /mnt/project-files             copy the hosted snapshot over local files (read-only replica)
  push-inputs --root /mnt/project-files          send fresh research inputs to the hosted agent
  handover --to session|github-actions --reason TEXT [--root DIR]
  halt REASON | resume REASON                    kill switch, applied by the hosted agent within SYNC_S
  run      --root DIR --agent-ref BRANCH ...     the hosted runner (used by the workflow)
"""
from __future__ import annotations

import argparse
import calendar
import fnmatch
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

BRANCH = "market-agent-state"
REF = f"refs/heads/{BRANCH}"
REMOTE_REF = f"refs/remotes/origin/{BRANCH}"
STATE_REL = "market-agent/state"
KEEP_EVENT_DAYS = 10
SYNC_S = 120            # snapshot + owner/control check
CODE_CHECK_S = 300      # new agent commit -> graceful restart
INPUTS_CHECK_S = 600
STALE_S = 300           # a hosted.json not refreshed for this long belongs to a dead run
LOCAL_LEASE_TTL_S = 180  # store.LEASE_TTL_S in the agent
# Paths (relative to the project root) that travel in each direction.
SNAPSHOT_GLOBS = [f"{STATE_REL}/*", "research/always-on/forward/Q205.csv"]
INPUT_GLOBS = ["research/always-on/forward/*", "research/stock-screener/picks_*.csv"]
INPUT_EXCLUDE = ["research/always-on/forward/Q205.csv"]
SNAPSHOT_EXCLUDE = [f"{STATE_REL}/.*", f"{STATE_REL}/*/.*"]


def utc(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if t is None else t))


def log(msg: str) -> None:
    print(f"{utc()} {msg}", flush=True)


# ------------------------------------------------------------------ crypto
def state_key(env=os.environ) -> str:
    secret = env.get("T212_API_SECRET", "")
    if not secret:
        raise SystemExit("T212_API_SECRET is not set: cannot derive the state key")
    return hashlib.sha256(b"market-agent-state-v1\0" + secret.encode()).hexdigest()


def _openssl(data: bytes, decrypt: bool) -> bytes:
    env = {**os.environ, "MA_STATE_PASS": state_key()}
    cmd = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256", "-pass", "env:MA_STATE_PASS"]
    cmd += ["-d"] if decrypt else ["-salt"]
    r = subprocess.run(cmd, input=data, capture_output=True, env=env)
    if r.returncode != 0:
        raise RuntimeError("decryption failed (wrong T212_API_SECRET?)" if decrypt else "encryption failed")
    return r.stdout


# ------------------------------------------------------------------ packing
def _matches(rel: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, g) for g in globs)


def collect(root: Path, globs: list[str], exclude: list[str], now: float | None = None) -> list[str]:
    """Relative file paths under root matched by globs (fnmatch, '*' crosses '/'); old event days are dropped."""
    now = time.time() if now is None else now
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(now - KEEP_EVENT_DAYS * 86400))
    out = []
    for g in globs:
        base = root / g.split("*")[0]
        cands = [base] if base.is_file() else (p for p in (base if base.is_dir() else base.parent).rglob("*"))
        for p in cands:
            if not p.is_file() or p.is_symlink():
                continue
            rel = p.relative_to(root).as_posix()
            if not _matches(rel, [g]) or _matches(rel, exclude):
                continue
            if rel.startswith(f"{STATE_REL}/events/") and p.name[:10] < cutoff:
                continue
            out.append(rel)
    return sorted(set(out))


def pack(root: Path, globs: list[str], exclude: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for rel in collect(root, globs, exclude):
            data = (root / rel).read_bytes()  # read once: a file being appended to stays self-consistent
            info = tarfile.TarInfo(rel)
            info.size, info.mtime, info.mode = len(data), int((root / rel).stat().st_mtime), 0o644
            tar.addfile(info, io.BytesIO(data))
    return _openssl(buf.getvalue(), decrypt=False)


def unpack(blob: bytes, root: Path, only: list[str] | None = None, skip: list[str] | None = None) -> list[str]:
    raw = _openssl(blob, decrypt=True)
    written = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for m in tar.getmembers():
            rel = m.name
            if not m.isfile() or rel.startswith("/") or ".." in Path(rel).parts:
                continue
            if (only is not None and not _matches(rel, only)) or (skip and _matches(rel, skip)):
                continue
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.hostctl.tmp")
            tmp.write_bytes(tar.extractfile(m).read())
            os.replace(tmp, dst)
            written.append(rel)
    return written


# ------------------------------------------------------------------ git plumbing on the state branch
class Branch:
    def __init__(self, repo: Path, remote: str = "origin"):
        self.repo, self.remote = repo, remote

    def git(self, *args: str, data: bytes | None = None, check: bool = True) -> bytes:
        env = {**os.environ, "GIT_AUTHOR_NAME": "market-agent-host", "GIT_AUTHOR_EMAIL": "market-agent-host@users.noreply.github.com",
               "GIT_COMMITTER_NAME": "market-agent-host", "GIT_COMMITTER_EMAIL": "market-agent-host@users.noreply.github.com"}
        r = subprocess.run(["git", "-C", str(self.repo), *args], input=data, capture_output=True, env=env)
        if check and r.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {r.stderr.decode(errors='replace')[-300:]}")
        return r.stdout

    def fetch(self) -> str | None:
        """Head of the remote branch after a fetch, or None if it does not exist."""
        out = self.git("ls-remote", self.remote, REF).decode().split()
        if not out:
            return None
        self.git("fetch", "-q", "--no-tags", self.remote, f"+{REF}:{REMOTE_REF}")
        return self.git("rev-parse", REMOTE_REF).decode().strip()

    def read(self, sha: str | None, name: str) -> bytes | None:
        if not sha:
            return None
        r = subprocess.run(["git", "-C", str(self.repo), "cat-file", "blob", f"{sha}:{name}"], capture_output=True)
        return r.stdout if r.returncode == 0 else None

    def read_json(self, sha: str | None, name: str) -> dict:
        b = self.read(sha, name)
        try:
            return json.loads(b) if b else {}
        except json.JSONDecodeError:
            return {}

    def blob_id(self, sha: str | None, name: str) -> str | None:
        if not sha:
            return None
        r = subprocess.run(["git", "-C", str(self.repo), "rev-parse", f"{sha}:{name}"], capture_output=True)
        return r.stdout.decode().strip() if r.returncode == 0 else None

    def write(self, parent: str | None, files: dict[str, bytes], message: str) -> bool:
        """Replace `files` in the branch (keeping the others) as a single orphan commit. Compare-and-swap: False when
        the branch moved since `parent` was fetched (the caller fetches again and retries)."""
        entries = {}
        if parent:
            for line in self.git("ls-tree", parent).decode().splitlines():
                meta, name = line.split("\t", 1)
                entries[name] = meta
        for name, data in files.items():
            blob = self.git("hash-object", "-w", "--stdin", data=data).decode().strip()
            entries[name] = f"100644 blob {blob}"
        tree_in = "".join(f"{meta}\t{name}\n" for name, meta in sorted(entries.items())).encode()
        tree = self.git("mktree", data=tree_in).decode().strip()
        commit = self.git("commit-tree", tree, "-m", message).decode().strip()
        r = subprocess.run(["git", "-C", str(self.repo), "push", "-q", f"--force-with-lease={REF}:{parent or ''}",
                            self.remote, f"{commit}:{REF}"], capture_output=True)
        if r.returncode != 0:
            err = r.stderr.decode(errors="replace")
            if "stale info" in err or "rejected" in err or "fetch first" in err:
                return False
            raise RuntimeError(f"push failed: {err[-300:]}")
        return True


def jdump(obj: dict) -> bytes:
    return (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode()


# ------------------------------------------------------------------ local agent checks (session side)
def local_lease_live(root: Path, now: float | None = None) -> str | None:
    p = root / STATE_REL / "lease.json"
    try:
        cur = json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    now = time.time() if now is None else now
    if cur.get("instance") and now - float(cur.get("t", 0)) < LOCAL_LEASE_TTL_S:
        return f"{cur['instance']} renewed {now - float(cur['t']):.0f} s ago"
    return None


# ------------------------------------------------------------------ session-side commands
def cmd_seed(b: Branch, a) -> int:
    root = Path(a.root)
    head = b.fetch()
    if head and not a.force:
        print("the state branch already exists; use --force to overwrite it with this copy", file=sys.stderr)
        return 1
    held = local_lease_live(root)
    if held:
        print(f"a local agent still holds its lease ({held}); stop it first", file=sys.stderr)
        return 1
    control = json.loads((root / STATE_REL / "control.json").read_text())
    files = {"snapshot.tar.gz.enc": pack(root, SNAPSHOT_GLOBS, SNAPSHOT_EXCLUDE),
             "inputs.tar.gz.enc": pack(root, INPUT_GLOBS, INPUT_EXCLUDE),
             "control.json": jdump(control),
             "owner.json": jdump({"host": "github-actions", "ts": utc(), "by": "seed", "reason": a.reason}),
             "hosted.json": jdump({"phase": "seeded", "ts": utc(), "t": time.time()})}
    if not b.write(head, files, f"seed {utc()}"):
        print("the branch moved during the seed; run it again", file=sys.stderr)
        return 1
    n = len(collect(root, SNAPSHOT_GLOBS, SNAPSHOT_EXCLUDE))
    print(json.dumps({"seeded": True, "files": n, "host": "github-actions"}))
    return 0


def _status(b: Branch) -> tuple[int, dict]:
    head = b.fetch()
    if not head:
        return 2, {"seeded": False}
    hosted = b.read_json(head, "hosted.json")
    age = time.time() - float(hosted.get("t", 0) or 0)
    out = {"owner": b.read_json(head, "owner.json"), "control": b.read_json(head, "control.json"),
           "hosted": hosted, "hosted_age_s": round(age)}
    running = hosted.get("phase") in ("starting", "running")
    out["hosted_live"] = running and age < STALE_S
    code = 0 if (out["hosted_live"] or out["owner"].get("host") != "github-actions") else 1
    return code, out


def cmd_status(b: Branch, a) -> int:
    code, out = _status(b)
    print(json.dumps(out, indent=1))
    return code


def cmd_mirror(b: Branch, a) -> int:
    root = Path(a.root)
    held = local_lease_live(root)
    if held:
        print(f"refusing: a local agent is running on this state ({held})", file=sys.stderr)
        return 1
    head = b.fetch()
    blob = b.read(head, "snapshot.tar.gz.enc")
    if not blob:
        print("no snapshot on the state branch", file=sys.stderr)
        return 2
    written = unpack(blob, root, only=SNAPSHOT_GLOBS, skip=[f"{STATE_REL}/lease.json"])
    lease = root / STATE_REL / "lease.json"  # never leave a replica looking like it holds a live lease
    if lease.exists():
        lease.write_text(json.dumps({"instance": None, "t": 0, "ts": utc(), "released_by": "hostctl-mirror"}))
    print(json.dumps({"mirrored": len(written), "hosted": b.read_json(head, "hosted.json")}))
    return 0


def cmd_push_inputs(b: Branch, a) -> int:
    root = Path(a.root)
    for _ in range(3):
        head = b.fetch()
        if not head:
            print("not seeded", file=sys.stderr)
            return 2
        if b.write(head, {"inputs.tar.gz.enc": pack(root, INPUT_GLOBS, INPUT_EXCLUDE)}, f"inputs {utc()}"):
            print(json.dumps({"inputs": len(collect(root, INPUT_GLOBS, INPUT_EXCLUDE))}))
            return 0
    return 1


def _update(b: Branch, name: str, obj: dict, msg: str) -> int:
    for _ in range(5):
        head = b.fetch()
        if not head:
            print("not seeded", file=sys.stderr)
            return 2
        if b.write(head, {name: jdump(obj)}, msg):
            print(json.dumps({name: obj}))
            return 0
        time.sleep(2)
    return 1


def cmd_control(b: Branch, a) -> int:
    enabled = a.cmd == "resume"
    return _update(b, "control.json", {"trading_enabled": enabled, "reason": a.reason, "by": "hostctl", "ts": utc()},
                   f"{a.cmd} {utc()}")


def cmd_handover(b: Branch, a) -> int:
    if a.to == "github-actions" and a.root:
        held = local_lease_live(Path(a.root))
        if held:
            print(f"stop the local agent first ({held})", file=sys.stderr)
            return 1
    rc = _update(b, "owner.json", {"host": a.to, "ts": utc(), "by": "handover", "reason": a.reason}, f"handover {a.to}")
    if rc or a.to != "session":
        return rc
    deadline = time.time() + a.wait_s
    while time.time() < deadline:
        code, st = _status(b)
        if not st.get("hosted_live"):
            break
        time.sleep(15)
    else:
        print("the hosted run has not stopped yet; do not start a local agent", file=sys.stderr)
        return 1
    if a.root:
        return cmd_mirror(b, a)
    return 0


# ------------------------------------------------------------------ the hosted runner
class Runner:
    def __init__(self, b: Branch, a):
        self.b, self.a = b, a
        self.root = Path(a.root)
        self.state = self.root / STATE_REL
        self.code = Path(a.code_dir).resolve()
        self.run_id = os.environ.get("GITHUB_RUN_ID", f"local-{os.getpid()}")
        self.proc: subprocess.Popen | None = None
        self.agent_sha: str | None = None
        self.control_applied: bytes | None = None
        self.inputs_blob: str | None = None
        self.restarts = 0
        self.next_start = 0.0
        self.started_at = 0.0
        self.backoff = 10
        self.stopping = False
        self.phase = "starting"

    # ---- helpers
    def hosted(self, extra: dict | None = None) -> bytes:
        hb = {}
        try:
            hb = json.loads((self.state / "heartbeat.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        age = round(time.time() - float(hb.get("t", 0) or 0)) if hb else None
        return jdump({"run_id": self.run_id, "phase": self.phase, "ts": utc(), "t": time.time(),
                      "agent_ref": self.a.agent_ref, "agent_sha": self.agent_sha, "restarts": self.restarts,
                      "agent_running": bool(self.proc and self.proc.poll() is None),
                      "heartbeat_age_s": age, "version": hb.get("version"), "loops": hb.get("loops"),
                      "duty_failures": sorted((hb.get("duty_failures") or {}).keys()), **(extra or {})})

    def sync(self, final: bool = False) -> dict:
        """Push the snapshot + status; read owner/control/inputs. Returns the branch's owner.json."""
        for attempt in range(4):
            head = self.b.fetch()
            owner = self.b.read_json(head, "owner.json")
            ctl = self.b.read(head, "control.json")
            if ctl and ctl != self.control_applied:
                (self.state / "control.json").write_bytes(ctl)
                self.control_applied = ctl
                log(f"control.json applied: trading_enabled={json.loads(ctl).get('trading_enabled')}")
            files = {"hosted.json": self.hosted()}
            if self.phase != "starting":
                files["snapshot.tar.gz.enc"] = pack(self.root, SNAPSHOT_GLOBS, SNAPSHOT_EXCLUDE)
            if self.b.write(head, files, f"{'final' if final else 'sync'} {self.run_id} {utc()}"):
                return owner
            time.sleep(3 + attempt * 3)
        log("sync: lost 4 compare-and-swap races; will retry next interval")
        return owner

    def fetch_code(self) -> str:
        self.b.git("fetch", "-q", "--no-tags", self.b.remote, f"+refs/heads/{self.a.agent_ref}:refs/remotes/origin/ma-agent")
        sha = self.b.git("rev-parse", "refs/remotes/origin/ma-agent").decode().strip()
        if not self.code.exists():
            self.b.git("worktree", "add", "-q", "--detach", str(self.code), sha)
        else:
            subprocess.run(["git", "-C", str(self.code), "checkout", "-q", "--detach", sha], check=True)
        return sha

    def remote_code_sha(self) -> str | None:
        out = self.b.git("ls-remote", self.b.remote, f"refs/heads/{self.a.agent_ref}", check=False).decode().split()
        return out[0] if out else None

    def start_agent(self) -> None:
        cmd = self.a.agent_cmd.split() if self.a.agent_cmd else [sys.executable, "-m", "market_agent", "--state",
                                                                 str(self.state), "run"]
        (self.state / "logs").mkdir(parents=True, exist_ok=True)
        with open(self.state / "logs" / "supervisor.log", "a") as f:
            f.write(f"{utc()} hosted runner {self.run_id}: starting agent {self.agent_sha[:7]}\n")
        out = open(self.state / "logs" / "agent.out", "a")
        env = {**os.environ, "MARKET_AGENT_STATE": str(self.state), "MARKET_AGENT_HOST": f"github-actions:{self.run_id}"}
        self.proc = subprocess.Popen(cmd, cwd=self.code / "agent", stdout=out, stderr=subprocess.STDOUT, env=env)
        log(f"agent started at {self.agent_sha[:7]} (pid {self.proc.pid})")

    def stop_agent(self, why: str) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        log(f"stopping agent: {why}")
        self.proc.terminate()  # the agent turns SIGTERM into a recorded stop and releases its lease
        try:
            self.proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        log(f"agent stopped rc={self.proc.returncode}")

    def _on_term(self, signum, frame):  # noqa: ARG002 - job cancelled or timed out
        self.stopping = True

    # ---- main
    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._on_term)
        signal.signal(signal.SIGINT, self._on_term)
        t0 = time.time()
        deadline = t0 + self.a.budget_min * 60
        if self.a.until:
            hh, mm = map(int, self.a.until.split(":"))
            g = time.gmtime(t0)
            until = calendar.timegm((g.tm_year, g.tm_mon, g.tm_mday, hh, mm, 0, 0, 0, 0))
            if until - t0 < 600:
                log(f"outside the trading window (ends {self.a.until}Z); nothing to do")
                return 0
            deadline = min(deadline, until)
        if not os.environ.get("T212_API_KEY") or not os.environ.get("T212_API_SECRET"):
            log("::warning::T212_API_KEY / T212_API_SECRET repository secrets are not set; the hosted agent cannot run")
            return 0
        # wait for the previous run to hand over, then claim the branch
        while True:
            head = self.b.fetch()
            if not head:
                log("state branch not seeded yet (hostctl seed); nothing to do")
                return 0
            owner = self.b.read_json(head, "owner.json")
            if owner.get("host") != "github-actions":
                log(f"standby: owner.json says host={owner.get('host')!r}")
                return 0
            prev = self.b.read_json(head, "hosted.json")
            age = time.time() - float(prev.get("t", 0) or 0)
            if prev.get("phase") in ("starting", "running") and prev.get("run_id") != self.run_id and age < STALE_S:
                if time.time() - t0 > STALE_S + 120:
                    log(f"run {prev.get('run_id')} is still live; exiting")
                    return 0
                log(f"waiting for run {prev.get('run_id')} to stop (last sync {age:.0f} s ago)")
                time.sleep(20)
                continue
            if self.b.write(head, {"hosted.json": self.hosted()}, f"claim {self.run_id} {utc()}"):
                break
        snap = self.b.read(head, "snapshot.tar.gz.enc")
        n = len(unpack(snap, self.root)) if snap else 0
        inp = self.b.read(head, "inputs.tar.gz.enc")
        if inp:
            unpack(inp, self.root)
            self.inputs_blob = self.b.blob_id(head, "inputs.tar.gz.enc")
        ctl = self.b.read(head, "control.json")
        if ctl:
            (self.state / "control.json").write_bytes(ctl)
            self.control_applied = ctl
        for d in ("events", "intents", "logs"):
            (self.state / d).mkdir(parents=True, exist_ok=True)
        (self.state / "lease.json").unlink(missing_ok=True)  # the previous holder is verified stopped or stale
        log(f"state restored: {n} files")
        self.agent_sha = self.fetch_code()
        self.phase = "running"
        last_sync = last_code = last_inputs = 0.0
        try:
            while not self.stopping and time.time() < deadline:
                now = time.time()
                if self.proc is None or self.proc.poll() is not None:
                    if self.proc is not None:
                        if now - self.started_at > 600:
                            self.backoff = 10  # it had been healthy for a while: restart quickly
                        log(f"agent exited rc={self.proc.returncode}; restart in {self.backoff} s")
                        self.next_start = now + self.backoff
                        self.backoff = min(self.backoff * 2, 300)
                        self.restarts += 1
                        self.proc = None
                    if now >= self.next_start:
                        self.start_agent()
                        self.started_at = now
                if now - last_sync >= self.a.sync_s:
                    last_sync = now
                    owner = self.sync()
                    if owner.get("host") != "github-actions":
                        log(f"handover: owner.json now says host={owner.get('host')!r}")
                        break
                if now - last_code >= CODE_CHECK_S:
                    last_code = now
                    sha = self.remote_code_sha()
                    if sha and sha != self.agent_sha:
                        self.stop_agent(f"new agent commit {sha[:7]}")
                        self.agent_sha = self.fetch_code()
                        self.proc = None
                        self.next_start = 0
                if now - last_inputs >= INPUTS_CHECK_S:
                    last_inputs = now
                    head = self.b.fetch()
                    bid = self.b.blob_id(head, "inputs.tar.gz.enc")
                    if bid and bid != self.inputs_blob:
                        unpack(self.b.read(head, "inputs.tar.gz.enc"), self.root)
                        self.inputs_blob = bid
                        log("research inputs updated")
                time.sleep(self.a.tick_s)
        finally:
            self.stop_agent("end of run" if not self.stopping else "job cancelled")
            self.phase = "stopped"
            self.sync(final=True)
            log("final snapshot pushed; run stopped")
        return 0


def cmd_run(b: Branch, a) -> int:
    return Runner(b, a).run()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hostctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]), help="a clone with push rights")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--root", default="/mnt/project-files")
    s.add_argument("--force", action="store_true")
    s.add_argument("--reason", default="cutover to hosted runner")
    sub.add_parser("status")
    for c in ("mirror", "push-inputs"):
        sub.add_parser(c).add_argument("--root", default="/mnt/project-files")
    h = sub.add_parser("handover")
    h.add_argument("--to", required=True, choices=["session", "github-actions"])
    h.add_argument("--reason", required=True)
    h.add_argument("--root", default=None, help="session: mirror into this root after the hosted run stops")
    h.add_argument("--wait-s", type=int, default=SYNC_S * 3 + 120)
    for c in ("halt", "resume"):
        sub.add_parser(c).add_argument("reason")
    r = sub.add_parser("run")
    r.add_argument("--root", default="/mnt/project-files")
    r.add_argument("--agent-ref", required=True)
    r.add_argument("--code-dir", default="ma-code")
    r.add_argument("--budget-min", type=float, default=330)
    r.add_argument("--until", default=None, help="HH:MM UTC: stop at this time today")
    r.add_argument("--tick-s", type=float, default=10)
    r.add_argument("--sync-s", type=float, default=SYNC_S)
    r.add_argument("--agent-cmd", default=None, help="tests only: replace the agent command")
    a = ap.parse_args(argv)
    b = Branch(Path(a.repo))
    fn = {"seed": cmd_seed, "status": cmd_status, "mirror": cmd_mirror, "push-inputs": cmd_push_inputs,
          "handover": cmd_handover, "halt": cmd_control, "resume": cmd_control, "run": cmd_run}[a.cmd]
    return fn(b, a)


if __name__ == "__main__":
    sys.exit(main())
