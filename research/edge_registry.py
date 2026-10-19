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
import math
import os
import statistics
import sys
from datetime import date
from pathlib import Path

PATH = Path(__file__).resolve().parent / "edge" / "trials.jsonl"
GENESIS = "0" * 64
MAX_BATCHES = 1  # owner decision D2 (docs/edge/DECISIONS.md): one confirmation batch, ever
KINDS = {"trial", "diagnostic", "inherited", "exposure"}  # exposure: holdout data seen, nothing tested
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
    resulted: set[str] = set()
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
            if e.get("kind") == "exposure" and e.get("counts_for_dsr"):
                problems.append(f"line {n}: exposure {tid} cannot count as a trial")
            if e.get("kind") not in KINDS:
                problems.append(f"line {n}: kind {e.get('kind')!r} not in {sorted(KINDS)}")
            if e.get("phase") not in PHASES:
                problems.append(f"line {n}: phase {e.get('phase')!r} not in {sorted(PHASES)}")
            if e.get("phase") == "exploration" and e.get("touched_holdout") and e.get("kind") != "exposure":
                problems.append(f"line {n}: {tid} is an exploration trial but touched the holdout")
            trials[tid] = e
        elif ev == "result":
            if e.get("id") not in trials:
                problems.append(f"line {n}: result for unregistered trial {e.get('id')}")
            elif e.get("id") in resulted:
                problems.append(f"line {n}: second result for {e.get('id')} (a rerun is a new trial)")
            resulted.add(e.get("id"))
        elif ev == "batch":
            b = e.get("batch")
            if b in batches:
                problems.append(f"line {n}: duplicate batch {b}")
            elif len(batches) >= MAX_BATCHES:
                problems.append(f"line {n}: batch {b} exceeds the {MAX_BATCHES} confirmation batch allowed")
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


STATUS = Path(__file__).resolve().parent / "edge" / "status.json"


def check4_complete(status: Path = STATUS) -> bool:
    """B5 ADDENDUM_1 §6: TTM check 4 (independent source) recorded complete by the owner. Missing counts as open."""
    try:
        return json.loads(status.read_text())["ttm_check4_independent_source"]["complete"] is True
    except (OSError, KeyError, TypeError, ValueError):
        return False


# The two B5 version-3 trials and their robustness runs (edge_b5_run.TRIALS and rob_id; a test keeps the lists
# equal). Owner review 2026-10-19 item 4: no code path may run or record one of these unless the run is open.
# ADDENDUM_3 (D20, D21): version 3 = version 2 + addenda 1-3; P9 is the full-window reverse veto, ROB-WINQ.
B5_RUN_IDS = frozenset(["B5-H1-FCFPS-ACCEL-V3", "B5-S2A-GP-12M-V3"] + [
    f"B5-{t}-V3-ROB-{g}" for t in ("H1", "S2A") for g in ("2XCOST", "MISS100", "NEXTMONTH", "DATAERR", "WINQ")])
# Registered ids that must never run or be recorded. Version 1 and version 2 (both superseded, never run; their
# trial ids stay registered and counted in N) and all of their robustness runs.
B5_RETIRED_IDS = frozenset([f"B5-{t}{v}" for t in ("H1-FCFPS-ACCEL", "S2A-GP-12M") for v in ("", "-V2")] + [
    f"B5-{t}{v}-ROB-{g}" for t in ("H1", "S2A") for v in ("", "-V2")
    for g in ("2XCOST", "MISS100", "NEXTMONTH", "DATAERR", "PITQ")])
B5_LOCK = Path(__file__).resolve().parent / "edge" / "b5_run.lock"
B5_REPO = Path(__file__).resolve().parent.parent
# The manifest a B5 run must be authorised against (edge_b5_run reads these two names; a test keeps them equal).
# B5_RUN_FIX_2 / execution hardening: proposed, not registered, so no run can open until the owner registers it.
B5_MANIFEST_ID = "B5-V3-RUN-MANIFEST-3"
B5_MANIFEST = B5_REPO / "docs" / "edge" / "B5_RUN_MANIFEST_3.json"
# Owner authorisations already used by a run that took the one-run lock. None can open another run, whatever
# status.json says (D27: run 1, authorised by D26 at 09:05Z, stopped with an error; its lock is kept. D32: run 2,
# authorised by D31 at 13:25Z, completed once; its lock is archived). Adding D31 here (owner decision O4, 19 Oct)
# changes this file after MANIFEST-3 was spent, so MANIFEST-3 no longer matches the code and can never run again.
B5_SPENT_AUTHORISATIONS = frozenset({"cmsg_01U4KMvkBYNknqm4HRVie8uvUzn9qQCoyy3U7K3j4iY3kK",  # D26, run 1
                                     "cmsg_01U4KMvkBYNknqm4HRVie8uvNzjD1qcmHEXGwqYmiFikfZ"})  # D31, run 2


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def b5_authorisation(status: Path = STATUS) -> dict:
    """The owner's B5 run authorisation in `status`, or PermissionError. Valid only when `authorised` is True, the
    owner message is a cmsg_ id that no earlier run has spent (`B5_SPENT_AUTHORISATIONS`), and it names the current
    run manifest by id (`B5_MANIFEST_ID`) and by sha256 (`manifest_sha256`), so an approval given for one manifest
    can never authorise a run of different code or inputs."""
    try:
        auth = json.loads(status.read_text())["b5_trial_run"]
    except (OSError, KeyError, TypeError, ValueError):
        auth = None
    if not isinstance(auth, dict) or auth.get("authorised") is not True \
            or not str(auth.get("owner_message", "")).startswith("cmsg_"):
        raise PermissionError("B5 run not authorised by the owner (status.json b5_trial_run)")
    if auth["owner_message"] in B5_SPENT_AUTHORISATIONS:
        raise PermissionError(f"authorisation {auth['owner_message']} was spent by an earlier run; a new run needs "
                              "a new owner authorisation")
    if auth.get("manifest_id") != B5_MANIFEST_ID:
        raise PermissionError(f"the authorisation names manifest {auth.get('manifest_id')!r}, not {B5_MANIFEST_ID}")
    h = auth.get("manifest_sha256")
    if not (isinstance(h, str) and len(h) == 64 and all(c in "0123456789abcdef" for c in h)):
        raise PermissionError("the authorisation does not name the manifest's sha256")
    return auth


def b5_manifest_ok(manifest_sha256: str, registry: Path, manifest: Path, repo: Path, files: bool) -> None:
    """PermissionError unless `manifest` has `manifest_sha256`, the registry registers B5_MANIFEST_ID at that sha256,
    and (with `files`) every input and code file it lists still has its recorded sha256."""
    try:
        actual = _sha(manifest)
        reg = registered(load(registry)).get(B5_MANIFEST_ID)
        listed = json.loads(manifest.read_text()) if files else {}
    except (OSError, ValueError) as e:
        raise PermissionError(f"B5 run manifest unreadable: {e}") from None
    if actual != manifest_sha256:
        raise PermissionError("the run manifest file does not match the authorised sha256")
    if reg is None or reg.get("spec_sha256") != manifest_sha256:
        raise PermissionError(f"{B5_MANIFEST_ID} is not registered at the authorised sha256")
    for group in ("inputs", "code"):
        for path, h in listed.get(group, {}).items() if files else ():
            p = Path(path) if Path(path).is_absolute() else repo / path
            try:
                ok = _sha(p) == h
            except OSError:
                ok = False
            if not ok:
                raise PermissionError(f"{group} file {path} does not match the run manifest")


def b5_run_open(verify_files: bool = False) -> str:
    """The owner message id of the open B5 run, else PermissionError. Open means all of:

    * the real status.json holds a valid, unspent authorisation for the current manifest (`b5_authorisation`);
    * the one-run lock, which only `edge_b5_run.preflight` creates after every other control has passed, exists
      and names that same owner message and manifest sha256;
    * the manifest file has that sha256 and the real registry registers it (`b5_manifest_ok`); with
      `verify_files` (the run's entry points: load_inputs, run_one, finish), every listed file is re-hashed too.

    It reads the module paths (STATUS, B5_LOCK, PATH, B5_MANIFEST, B5_REPO), never arguments, so no caller can point
    it at a copied registry, status file, manifest or lock."""
    auth = b5_authorisation(STATUS)
    try:
        lock = json.loads(B5_LOCK.read_text())
        same = lock["owner_message"] == auth["owner_message"] and lock["manifest"] == auth["manifest_sha256"]
    except (OSError, KeyError, TypeError, ValueError):
        same = False
    if not same:
        raise PermissionError("B5 run not open: needs the one-run lock taken by edge_b5_run.preflight for this "
                              "authorisation and manifest")
    b5_manifest_ok(auth["manifest_sha256"], PATH, B5_MANIFEST, B5_REPO, verify_files)
    return auth["owner_message"]


def append(event: dict, path: Path = PATH, status: Path = STATUS) -> dict:
    """Append one event, chaining it to the last line. Refuses if the file is already invalid or the result
    would be invalid; the file is left untouched in that case. Refuses a confirmation batch while TTM check 4 is
    open (B5 ADDENDUM_1 §6)."""
    if event.get("event") == "batch" and not check4_complete(status):
        raise ValueError("confirmation pre-registration refused: TTM check 4 (independent source) is open")
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


def stage(events: list[dict], path: Path = PATH) -> tuple[Path, bytes]:
    """Write the registry plus `events` (chained, dated today) to a staged copy beside it and return the copy and the
    registry's current bytes; the registry itself is not touched. Refuses (and removes the copy) unless the registry
    is valid before, the copy is valid, every earlier byte is unchanged and exactly these events were added. A
    confirmation batch is never staged. `commit` makes the copy the registry in one rename."""
    if any(e.get("event") == "batch" for e in events):
        raise ValueError("a confirmation batch is appended only through append")
    problems = validate(path)
    if problems:
        raise ValueError(f"registry invalid before staging: {problems}")
    old = path.read_bytes()
    lines = [l for l in old.decode().splitlines() if l.strip()]
    prev = line_hash(lines[-1]) if lines else GENESIS
    new = []
    for event in events:
        raw = json.dumps({"prev": prev, "date": date.today().isoformat(), **event}, sort_keys=True)
        new.append(raw)
        prev = line_hash(raw)
    text = ("\n".join(lines + new) + "\n").encode()
    staged = path.with_suffix(".staged")
    staged.write_bytes(text)
    after = validate(staged)
    if after or not text.startswith(old) or len(load(staged)) != len(load(path)) + len(events):
        staged.unlink()
        raise ValueError(f"staged events rejected, registry unchanged: {after or 'history or count mismatch'}")
    return staged, old


def commit(staged: Path, old: bytes, path: Path = PATH) -> None:
    """Replace the registry with a `stage`d copy in one rename, refusing if the registry changed since staging."""
    if path.read_bytes() != old:
        raise ValueError("registry changed since staging; nothing committed")
    if validate(staged) or not staged.read_bytes().startswith(old):
        raise ValueError("staged copy no longer valid; nothing committed")
    os.replace(staged, path)


def require(trial_id: str, path: Path = PATH) -> dict:
    """The registration of `trial_id`, or an error if it is not registered or already has a result. Research
    code calls this before computing anything, so an unregistered or repeated look cannot run. A B5 trial or
    robustness id also needs the B5 run to be open (`b5_run_open`), whichever script asks."""
    if trial_id in B5_RETIRED_IDS:
        raise ValueError(f"{trial_id} is retired (superseded) and can never be run or recorded")
    if trial_id in B5_RUN_IDS:
        b5_run_open()
    events = load(path)
    reg = registered(events).get(trial_id)
    if reg is None:
        raise KeyError(f"{trial_id} is not registered: append a register event before running it")
    if any(e.get("event") == "result" and e.get("id") == trial_id for e in events):
        raise ValueError(f"{trial_id} already has a result; register a new trial to look again")
    return reg


def registered(events: list[dict]) -> dict[str, dict]:
    return {e["id"]: e for e in events if e.get("event") == "register"}


def n_trials(events: list[dict]) -> int:
    """The trial count the deflated Sharpe uses: every registered trial marked counts_for_dsr."""
    return sum(1 for e in registered(events).values() if e.get("counts_for_dsr"))


# Stage 2's results (seeded from stage2_signals.json) carry `sr_monthly` without a `stat` field: it is the monthly
# Sharpe of the large-cap top quintile's return net of costs minus the universe (stage2.run, `q5_net`).
LEGACY_STAT = "xsection_q5_net_vs_universe"


def result_stat(e: dict) -> str | None:
    """Which statistic a result's `sr_monthly` measures. Results without a Sharpe (IC-only) return None."""
    if e.get("sr_monthly") is None:
        return None
    return e.get("stat") or LEGACY_STAT


def sharpe_list(events: list[dict], stat: str | None = None) -> list[float]:
    """Monthly Sharpe ratios recorded in results of counted trials, for the DSR's cross-trial variance. With
    `stat`, only results measuring that same statistic: a top-quintile spread's Sharpe and a concentrated
    portfolio's excess-over-VWRP Sharpe are different quantities and are never pooled. Missing or non-finite
    values are left out (the trial still counts in `n_trials`)."""
    reg = registered(events)
    out = {}
    for e in events:
        if e.get("event") != "result" or not reg.get(e["id"], {}).get("counts_for_dsr"):
            continue
        st = result_stat(e)
        if st is None or (stat is not None and st != stat):
            continue
        v = float(e["sr_monthly"])
        if math.isfinite(v):
            out[e["id"]] = v
    return list(out.values())


def deflated_sharpe(sr: float, n_months: int, skew: float, kurt: float, stat: str, events: list[dict]) -> dict:
    """Deflated Sharpe ratio (Bailey and Lopez de Prado 2014) for a monthly Sharpe `sr` measuring `stat`.

    N, the number of trials, is `n_trials(events)`: every counted look, whatever statistic it reported (owner
    decision D4). Correlated variants are counted as separate trials, which overstates the effective N and makes
    the test stricter. The cross-trial variance of Sharpe ratios comes only from results of the same `stat`, and is
    floored at 1/n_months, the variance of a Sharpe estimate under the null; with fewer than two comparable
    results the floor is used. `kurt` is raw (normal = 3)."""
    n = n_trials(events)
    comp = sharpe_list(events, stat)
    floor = 1.0 / n_months
    emp = statistics.variance(comp) if len(comp) >= 2 else 0.0
    var = max(emp, floor)
    g = 0.5772156649
    nd = statistics.NormalDist()
    sr0 = math.sqrt(var) * ((1 - g) * nd.inv_cdf(1 - 1 / n) + g * nd.inv_cdf(1 - 1 / (n * math.e))) if n > 1 else 0.0
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return {"dsr": nd.cdf((sr - sr0) * math.sqrt(n_months - 1) / den), "n_trials": n, "n_comparable": len(comp),
            "var_used": var, "floor_used": var == floor, "sr0": sr0, "stat": stat}


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
