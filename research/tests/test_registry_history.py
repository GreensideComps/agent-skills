"""The live registry is an append-only, hash-chained extension of the registry as B5 run 2 left it."""
from __future__ import annotations

import hashlib
import json

import conftest
import edge_registry


def test_the_run_2_prefix_is_byte_identical_and_the_whole_chain_validates():
    lines = conftest.LIVE_REGISTRY.read_bytes().splitlines(keepends=True)
    assert len(lines) >= conftest.RUN_2_LINES
    assert hashlib.sha256(b"".join(lines[:conftest.RUN_2_LINES])).hexdigest() == conftest.RUN_2_REGISTRY_SHA256
    assert edge_registry.validate(conftest.LIVE_REGISTRY) == []           # every `prev` hash links to the line before


def test_trials_are_only_ever_added():
    then = edge_registry.load_bytes(conftest.run_2_registry_bytes()) if hasattr(edge_registry, "load_bytes") else \
        [json.loads(x) for x in conftest.run_2_registry_bytes().splitlines()]
    now = edge_registry.load(conftest.LIVE_REGISTRY)
    assert now[:len(then)] == then
    assert edge_registry.n_trials(then) == 102 and edge_registry.n_trials(now) >= 102
    ids_then = {e["id"] for e in then if e.get("event") == "register"}
    assert ids_then <= {e["id"] for e in now if e.get("event") == "register"}


def test_an_edit_inside_the_history_is_detected(tmp_path):
    lines = conftest.LIVE_REGISTRY.read_bytes().splitlines(keepends=True)
    e = json.loads(lines[300])
    e["verdict"] = "pass"
    lines[300] = (json.dumps(e, sort_keys=True) + "\n").encode()
    p = tmp_path / "trials.jsonl"
    p.write_bytes(b"".join(lines))
    assert edge_registry.validate(p)                                      # the chain breaks at the edited line
