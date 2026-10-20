"""Git-backed store for the event log.

A state change is one commit that appends events, pushed without force. Git refuses a push that is not a
fast-forward, so the push is an atomic compare-and-swap on the whole log: if another worker appended first, this
push is rejected, nothing of it becomes visible, and the caller rebuilds from the new log and decides again.

A push that fails for any other reason (network, proxy, killed process) has an unknown outcome: the commit may or
may not have reached the remote. `append` resolves that by fetching and checking whether its commit is now part of
the remote branch, and raises `StoreUnavailable` if it cannot find out.
"""
from __future__ import annotations

import os
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import events as ev

LOG = "events.jsonl"
REJECTED = ("[rejected]", "fetch first", "non-fast-forward", "stale info", "[remote rejected]")


class StoreUnavailable(Exception):
    """The remote could not be reached or the outcome of a push could not be determined."""


class Contention(Exception):
    """A transaction lost the race to other writers more times than allowed."""


class GitStore:
    def __init__(self, workdir: str | Path, branch: str, remote_url: str | None = None, actor: str = "worker",
                 timeout: float = 60.0, clock: Callable[[], float] | None = None):
        self.dir, self.branch, self.actor, self.timeout = Path(workdir), branch, actor, timeout
        self.clock = clock  # event timestamps; None = the real clock (tests pass a fake one)
        if not (self.dir / ".git").exists():
            if remote_url is None:
                raise ValueError("a new workdir needs remote_url")
            self.dir.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q")
            self._git("remote", "add", "origin", remote_url)
        self._git("config", "user.email", f"{actor}@office.invalid")
        self._git("config", "user.name", f"office {actor}")
        self.stats = {"commits": 0, "rejected": 0, "ambiguous_resolved": 0}
        self.last_seen = ""  # the log as of this worker's last sync; the remote may only ever extend it

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            r = subprocess.run(["git", "-C", str(self.dir), *args], capture_output=True, text=True, env=env,
                               timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            raise StoreUnavailable(f"git {args[0]} timed out") from e
        if check and r.returncode:
            raise StoreUnavailable(f"git {' '.join(args[:2])}: {r.stderr.strip()[-300:]}")
        return r

    @staticmethod
    def create_branch(workdir: str | Path, remote_url: str, branch: str) -> None:
        """Push a new branch holding an empty log. Refuses if the branch already exists."""
        s = GitStore(workdir, branch, remote_url, actor="init")
        if s._git("ls-remote", "--heads", "origin", branch).stdout.strip():
            raise ValueError(f"branch {branch} already exists")
        s._git("checkout", "-q", "--orphan", branch)
        (s.dir / LOG).write_text("")
        s._git("add", LOG)
        s._git("commit", "-q", "-m", "office: empty event log")
        s._git("push", "-q", "origin", f"HEAD:refs/heads/{branch}")

    def sync(self) -> str:
        """Make the workdir exactly the remote branch; returns the log text (validated)."""
        self._git("fetch", "-q", "origin", f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}")
        self._git("checkout", "-q", "-B", self.branch, f"origin/{self.branch}")
        self._git("reset", "-q", "--hard", f"origin/{self.branch}")
        text = self.read()
        problems = ev.validate(text)
        if problems:
            raise ev.CorruptLog(problems)
        if not text.startswith(self.last_seen):
            raise ev.CorruptLog(["the remote log no longer extends what this worker saw: history was rewritten"])
        self.last_seen = text
        return text

    def audit_history(self) -> list[str]:
        """Walk every commit of the branch (oldest first) and check each one only appended to the log. The chain
        alone cannot detect an edit to the newest line or a rewrite of the whole file; this check can."""
        self.sync()
        shas = self._git("rev-list", "--reverse", f"origin/{self.branch}").stdout.split()
        problems, prev = [], ""
        for sha in shas:
            r = self._git("show", f"{sha}:{LOG}", check=False)
            text = r.stdout if r.returncode == 0 else ""
            if not text.startswith(prev):
                problems.append(f"commit {sha[:10]} changed earlier log lines")
            problems += [f"commit {sha[:10]}: {p}" for p in ev.validate(text)]
            prev = text
        return problems

    def read(self) -> str:
        p = self.dir / LOG
        return p.read_text() if p.exists() else ""

    def append(self, base: str, new: list[dict], message: str) -> bool:
        """Append `new` to `base` (the text returned by the last sync). True if it is now on the remote branch,
        False if another writer got there first. Raises StoreUnavailable if the outcome cannot be determined."""
        if self.read() != base:
            raise RuntimeError("workdir changed since sync")
        now = None if self.clock is None else datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(
            timespec="seconds")
        (self.dir / LOG).write_text(ev.extend(base, new, self.actor, now))
        self._git("add", LOG)
        self._git("commit", "-q", "-m", message[:200])
        mine = self._git("rev-parse", "HEAD").stdout.strip()
        self.stats["commits"] += 1
        r = self._git("push", "-q", "origin", f"HEAD:refs/heads/{self.branch}", check=False)
        if r.returncode == 0:
            return True
        if any(s in r.stderr for s in REJECTED):
            self.stats["rejected"] += 1
            return False
        # Unknown outcome: did the commit reach the remote?
        for wait in (1, 2, 4):
            f = self._git("fetch", "-q", "origin", f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}",
                          check=False)
            if f.returncode == 0:
                landed = self._git("merge-base", "--is-ancestor", mine, f"origin/{self.branch}",
                                   check=False).returncode == 0
                self.stats["ambiguous_resolved"] += 1
                return landed
            time.sleep(wait)
        raise StoreUnavailable(f"push outcome unknown: {r.stderr.strip()[-300:]}")

    def transact(self, decide: Callable[[list[dict]], list[dict] | None], tries: int = 30,
                 sleep: Callable[[float], None] = time.sleep) -> list[dict] | None:
        """Run `decide` on the current events and append what it returns, atomically. None if it returns nothing.
        On a lost race, re-sync and decide again (jittered backoff), up to `tries` times."""
        for i in range(tries):
            base = self.sync()
            new = decide(ev.parse(base))
            if not new:
                return None
            n = len(ev.parse(base))
            if self.append(base, new, " ".join(e["kind"] for e in new)):
                return [{**e, "seq": n + k} for k, e in enumerate(new)]
            sleep(min(2.0, 0.05 * 2 ** min(i, 5)) * random.uniform(0.5, 1.5))
        raise Contention(f"lost the race {tries} times")
