"""Shared fixtures for the research tests.

The registry (research/edge/trials.jsonl) is append-only and hash-chained. The B5 test modules were written when it
ended at run 2 (line 252, commit a4a07d7) and assert facts about that state: its exact bytes, a count of 102 trials,
which results exist. The always-on research loop has since appended hundreds of trials to the same file, which is
what an append-only registry is for, and those assertions then failed for twelve days without anyone seeing it
(the repository had no CI).

The fix keeps every guarantee and adds one:

* the B5 modules read the registry AS OF RUN 2: the first 252 lines of the live file, refused unless they hash to
  the pinned value. So the historical bytes are still verified on every run, and the B5 facts are checked against
  the state they describe;
* test_registry_history.py checks that the live registry is an append-only extension of that prefix whose hash
  chain validates from the first line to the last.

Some B5 tests also re-check the run's input data on /mnt/project-files/research-data. Those files are outside the
repository and are rebuilt weekly since 6 Nov 2026, so the bytes run 2 used are gone from that folder.
`b5_inputs_intact()` says whether this machine still has them; tests that need them skip with that reason, and tests
that only need the run to be refused accept a refusal at the inputs check.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1]
REPO = RESEARCH.parent
sys.path.insert(0, str(RESEARCH))

LIVE_REGISTRY = RESEARCH / "edge" / "trials.jsonl"
RUN_2_LINES = 252
RUN_2_REGISTRY_SHA256 = "de03d38b18a2d80b5c4d20f647c8ff35f5471157aba71fa99da6b550fb1217e6"
B5_ERA_MODULES = {"test_edge_b5_run", "test_edge_families", "test_edge_rules", "test_edge_verdict_annotation"}
PATCHED_MODULES = ("edge_registry", "edge_b5_run", "edge_b5_addendum3", "edge_verdicts", "stage2_diagnostics",
                   "edge_b5_handcheck")


def run_2_registry_bytes() -> bytes:
    """The registry as run 2 left it: the live file's first 252 lines, refused unless they match the pinned hash."""
    data = b"".join(LIVE_REGISTRY.read_bytes().splitlines(keepends=True)[:RUN_2_LINES])
    got = hashlib.sha256(data).hexdigest()
    assert got == RUN_2_REGISTRY_SHA256, f"the registry's first {RUN_2_LINES} lines changed: {got}"
    return data


@pytest.fixture(scope="session")
def run_2_registry(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("registry_at_run_2") / "trials.jsonl"
    p.write_bytes(run_2_registry_bytes())
    return p


def b5_inputs_intact() -> bool:
    """True when every shared-data input MANIFEST-3 names is on this machine with the bytes run 2 used."""
    m = json.loads((REPO / "docs" / "edge" / "B5_RUN_MANIFEST_3.json").read_text())
    for path, h in m["inputs"].items():
        p = Path(path)
        if p.is_absolute() and not (p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == h):
            return False
    return True


@pytest.fixture(scope="session")
def b5_inputs() -> bool:
    return b5_inputs_intact()


NO_B5_INPUTS = ("the shared research data run 2 used is not on this machine (it is outside the repository and has "
                "been rebuilt weekly since 6 Nov 2026)")


@pytest.fixture(autouse=True)
def _b5_modules_read_the_registry_as_of_run_2(request, monkeypatch):
    """For the B5-era modules only: every default registry path points at the run-2 snapshot (a temporary copy), so
    their assertions describe the state they were written for and nothing they do can touch the live registry."""
    if request.module.__name__ not in B5_ERA_MODULES:
        yield
        return
    snap = request.getfixturevalue("run_2_registry")
    snap.write_bytes(run_2_registry_bytes())  # a fresh copy for every test
    import importlib
    for name in PATCHED_MODULES:
        try:
            mod = importlib.import_module(name)
        except Exception:  # noqa: BLE001 - optional modules (heavy imports) are simply not patched
            continue
        for _, fn in inspect.getmembers(mod, inspect.isfunction):
            d = fn.__defaults__
            if fn.__module__ == mod.__name__ and d and any(isinstance(x, Path) and x == LIVE_REGISTRY for x in d):
                monkeypatch.setattr(fn, "__defaults__", tuple(snap if isinstance(x, Path) and x == LIVE_REGISTRY else x
                                                              for x in d))
        if getattr(mod, "PATH", None) == LIVE_REGISTRY:
            monkeypatch.setattr(mod, "PATH", snap)
    yield
