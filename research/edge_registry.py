"""Trial registry for the edge-discovery programme (Phase A). Separate from Stage 2's `TRIALS` and from the ETF
research registry in `research/experiments/`; neither of those is changed.

The registry is an append-only JSON-lines file, `research/edge/trials.jsonl`. Each line is one event:

* `register`: a trial (or an inherited earlier look at the data) exists, with its definition. Written before
  the trial runs. Ids are unique.
* `result`: a registered trial has run; carries the numbers the deflated Sharpe needs and where they came from.
* `batch`: a confirmation batch is pre-registered (trial ids, pre-registration commit).
* `holdout_run`: a batch used the holdout. At most one per batch, ever.

Every line stores `prev`, the SHA-256 of the line before it, so an edited or deleted line breaks the chain and
`validate` reports it even without git. `n_trials` is what the deflated Sharpe counts: every registered trial
with `counts_for_dsr`, whether or not it was reported.

    python3 edge_registry.py            # validate and summarise
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

PATH = Path(__file__).resolve().parent / "edge" / "trials.jsonl"
GENESIS = "0" * 64
KINDS = {"trial", "diagnostic", "inherited"}
PHASES = {"exploration", "confirmation", "prospective", "pre-programme"}
REQUIRED = {
    "register": {"id", "date", "kind", "phase", "hypothesis", "definition", "universe", "horizon_months", "window",
                 "counts_for_dsr", "touched_holdout"},
    "result": {"id", "date", "evidence"},
    "batch": {"batch", "date", "trials", "prereg_commit"},
    "holdout_run": {"batch", "date", "evidence"},
}


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()


def load(path: Path = PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def validate(path: Path = PATH) -> list[str]:
    """Problems found (empty list = valid): broken hash chain, missing fields, duplicate ids, results or
    batches naming unknown trials, a result before its registration, a second holdout run for a batch, a
    holdout run without a batch, or a trial in two batches."""
    problems: list[str] = []
    if not path.exists():
        return [f"{path} missing"]
    prev = GENESIS
    trials: dict[str, dict] = {}
    batches: dict[str, dict] = {}
    runs: set[str] = set()
    in_batch: dict[str, str] = {}
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError as x:
            problems.append(f"line {n}: not JSON ({x})")
            prev = line_hash(raw)
            continue
        if e.get("prev") != prev:
            problems.append(f"line {n}: hash chain broken (a line was edited, removed or reordered)")
        prev = line_hash(raw)
        ev = e.get("event")
        if ev not in REQUIRED:
            problems.append(f"line {n}: unknown event {ev!r}")
            continue
        missing = REQUIRED[ev] - e.keys()
        if missing:
            problems.append(f"line {n}: {ev} missing {sorted(missing)}")
        if ev == "register":
            tid = e.get("id")
            if tid in trials:
                problems.append(f"line {n}: duplicate trial id {tid}")
            if e.get("kind") not in KINDS:
                problems.append(f"line {n}: kind {e.get('kind')!r} not in {sorted(KINDS)}")
            if e.get("phase") not in PHASES:
                problems.append(f"line {n}: phase {e.get('phase')!r} not in {sorted(PHASES)}")
            if e.get("phase") == "exploration" and e.get("touched_holdout"):
                problems.append(f"line {n}: {tid} is an exploration trial but touched the holdout")
            trials[tid] = e
        elif ev == "result":
            if e.get("id") not in trials:
                problems.append(f"line {n}: result for unregistered trial {e.get('id')}")
        elif ev == "batch":
            b = e.get("batch")
            if b in batches:
                problems.append(f"line {n}: duplicate batch {b}")
            for t in e.get("trials", []):
                if t not in trials:
                    problems.append(f"line {n}: batch {b} names unregistered trial {t}")
                elif trials[t].get("phase") != "exploration":
                    problems.append(f"line {n}: batch {b} confirms {t}, which is not an exploration trial")
                if t in in_batch:
                    problems.append(f"line {n}: trial {t} already confirmed in batch {in_batch[t]}")
                in_batch[t] = b
            batches[b] = e
        elif ev == "holdout_run":
            b = e.get("batch")
            if b not in batches:
                problems.append(f"line {n}: holdout run for unregistered batch {b}")
            if b in runs:
                problems.append(f"line {n}: batch {b} used the holdout twice")
            runs.add(b)
    return problems


def append(event: dict, path: Path = PATH) -> dict:
    """Append one event, chaining it to the last line. Refuses if the file is already invalid or the result
    would be invalid; the file is left untouched in that case."""
    problems = validate(path) if path.exists() else []
    if problems:
        raise ValueError(f"registry invalid before append: {problems}")
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [l for l in lines if l.strip()]
    e = {"prev": line_hash(lines[-1]) if lines else GENESIS, "date": date.today().isoformat(), **event}
    new = "\n".join(lines + [json.dumps(e, sort_keys=True)]) + "\n"
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(new)
    after = validate(tmp)
    if after:
        tmp.unlink()
        raise ValueError(f"event rejected: {after}")
    tmp.replace(path)
    return e


def registered(events: list[dict]) -> dict[str, dict]:
    return {e["id"]: e for e in events if e.get("event") == "register"}


def n_trials(events: list[dict]) -> int:
    """The trial count the deflated Sharpe uses: every registered trial marked counts_for_dsr."""
    return sum(1 for e in registered(events).values() if e.get("counts_for_dsr"))


def sharpe_list(events: list[dict]) -> list[float]:
    """Monthly Sharpe ratios recorded in results for trials that count, for the DSR's cross-trial variance."""
    reg = registered(events)
    out = {}
    for e in events:
        if e.get("event") == "result" and reg.get(e["id"], {}).get("counts_for_dsr") and e.get("sr_monthly") is not None:
            out[e["id"]] = float(e["sr_monthly"])  # a later result for the same trial replaces the earlier one
    return list(out.values())


def holdout_runs(events: list[dict]) -> set[str]:
    return {e["batch"] for e in events if e.get("event") == "holdout_run"}


def summary(events: list[dict]) -> str:
    reg = registered(events)
    by = {}
    for e in reg.values():
        by.setdefault((e["phase"], e["kind"]), 0)
        by[(e["phase"], e["kind"])] += 1
    lines = [f"trials registered: {len(reg)}; counted for deflated Sharpe: {n_trials(events)}; "
             f"touched holdout: {sum(1 for e in reg.values() if e.get('touched_holdout'))}; "
             f"holdout runs: {len(holdout_runs(events))}"]
    lines += [f"  {p} / {k}: {c}" for (p, k), c in sorted(by.items())]
    return "\n".join(lines)


if __name__ == "__main__":
    probs = validate()
    print(summary(load()))
    if probs:
        print("INVALID:\n  " + "\n  ".join(probs))
        sys.exit(1)
    print("valid")
