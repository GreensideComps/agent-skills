"""Owner decision D-B (2026-10-23): prior ETF experiments E001-E015 count towards a new trial's multiple-testing N
only when they share a declared family with it (docs/minifund/MULTIPLE_TESTING_PRIOR_ETF.md). This module reads the
fixed family table and computes the extra count. It never writes to the edge registry: the extra N is passed to
the deflated Sharpe explicitly at evaluation time."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE / "edge" / "prior_etf_families.json"
EXPERIMENTS = HERE / "experiments"
NONE = "none"


def load(path: Path = PATH) -> dict:
    return json.loads(Path(path).read_text())


def table_sha256(path: Path = PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(path: Path = PATH, experiments: Path = EXPERIMENTS) -> list[str]:
    """Problems with the table: unknown families, or configuration counts that differ from the experiment files."""
    t, errs = load(path), []
    vocab = set(t["families"])
    files = {p.stem: p for p in Path(experiments).glob("E*.json")}
    if set(files) != set(t["experiments"]):
        errs.append(f"experiments differ: table {sorted(t['experiments'])} vs files {sorted(files)}")
    for e, row in t["experiments"].items():
        if not row["families"] or set(row["families"]) - vocab:
            errs.append(f"{e}: families {row['families']} not in the vocabulary")
        if not str(row.get("basis", "")).strip():
            errs.append(f"{e}: no basis recorded for its families")
        if e in files and json.loads(files[e].read_text())["trials"] != row["configurations"]:
            errs.append(f"{e}: {row['configurations']} configurations, file says otherwise")
    return errs


def extra_n(families: list[str], path: Path = PATH) -> dict:
    """{'count', 'experiments'}: configurations of every experiment sharing a family, each experiment once.
    A trial must declare its families; ['none'] declares that it shares none."""
    t = load(path)
    declared = set(families)
    if not declared:
        raise ValueError("families must be declared; use ['none'] for a trial that shares none")
    if NONE in declared:
        if declared != {NONE}:
            raise ValueError("'none' cannot be combined with other families")
        return {"count": 0, "experiments": {}, "table_sha256": table_sha256(path)}
    unknown = declared - set(t["families"])
    if unknown:
        raise ValueError(f"unknown families {sorted(unknown)}")
    hit = {e: r["configurations"] for e, r in sorted(t["experiments"].items()) if declared & set(r["families"])}
    return {"count": sum(hit.values()), "experiments": hit, "table_sha256": table_sha256(path)}


if __name__ == "__main__":
    problems = validate()
    print("valid" if not problems else "\n".join(problems))
