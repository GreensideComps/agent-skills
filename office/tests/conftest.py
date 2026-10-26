"""Fixtures: a throwaway local bare repository holding an empty event log, and stores pointed at it."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from office.store import GitStore  # noqa: E402

BRANCH = "office-state-test"


@pytest.fixture
def remote(tmp_path) -> str:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    GitStore.create_branch(tmp_path / "seed", str(bare), BRANCH)
    return str(bare)


@pytest.fixture
def make_store(remote, tmp_path):
    n = [0]

    def make(actor: str | None = None) -> GitStore:
        n[0] += 1
        return GitStore(tmp_path / f"w{n[0]}", BRANCH, remote, actor=actor or f"w{n[0]}")
    return make


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


@pytest.fixture
def clock() -> Clock:
    return Clock()
