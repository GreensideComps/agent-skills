"""Research-run provenance (mini fund Stage 2 §3, owner approval U2 of 2026-10-23).

A run manifest records what a research run used: the Python and package versions, the git commit and whether the
tree was dirty, a SHA-256 for every input file and for the parameters. It records the environment; it does not
reproduce it. Nothing here makes a network request, and a manifest is never overwritten.

Missing or unknown values are recorded as null with a reason, never filled in (owner review point 5).

    python3 research/provenance.py --check-data-manifest /mnt/project-files/research-data/edge/manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "run_manifest"
SCHEMA_VERSION = "provenance-0.1"
REPO = Path(__file__).resolve().parent.parent
PACKAGES = ("numpy", "pandas", "scipy", "statsmodels", "pytest")
TIME_FIELDS = ("started_at", "finished_at")
LIMITATIONS = (
    "Records the environment; it does not reproduce it.",
    "OS-level libraries (BLAS, libc) and hardware are not captured.",
    "Input hashes prove which bytes were read, not that the data is correct, survivorship-free or licensed.",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def package_versions(names=PACKAGES, version=importlib.metadata.version) -> dict:
    out = {}
    for n in names:
        try:
            out[n] = {"version": version(n)}
        except importlib.metadata.PackageNotFoundError:
            out[n] = {"version": None, "missing_reason": "not_installed"}
    return out


def _run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, p.stdout


def git_state(repo: Path = REPO, run=_run_git) -> dict:
    rc, head = run(["rev-parse", "HEAD"], repo)
    if rc != 0:
        return {"commit": None, "dirty": None, "missing_reason": "not_a_git_checkout"}
    rc, status = run(["status", "--porcelain"], repo)
    if rc != 0:
        return {"commit": head.strip(), "dirty": None, "missing_reason": "git_status_failed"}
    changed = sorted(line[3:] for line in status.splitlines() if line.strip())
    return {"commit": head.strip(), "dirty": bool(changed), "dirty_paths": changed}


def _display_path(p: Path, repo: Path) -> str:
    try:
        return str(p.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(p.resolve())


def input_record(path, repo: Path = REPO) -> dict:
    p = Path(path)
    rec = {"path": _display_path(p, repo)}
    if not p.is_file():
        rec.update(bytes=None, sha256=None, missing_reason="not_found" if not p.exists() else "not_a_file")
        return rec
    rec.update(bytes=p.stat().st_size, sha256=sha256_file(p))
    return rec


def content_sha256(manifest: dict) -> str:
    """Hash of everything except the run times, so two runs on the same inputs and params agree."""
    body = {k: v for k, v in manifest.items() if k not in TIME_FIELDS and k != "content_sha256"}
    return hashlib.sha256(canonical(body)).hexdigest()


def run_manifest(inputs, params: dict, *, purpose: str, repo: Path = REPO, started_at: str | None = None,
                 finished_at: str | None = None, versions=package_versions, git=git_state) -> dict:
    m = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "purpose": purpose,
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "packages": versions(),
        "git": git(repo),
        "inputs": sorted((input_record(p, repo) for p in inputs), key=lambda r: r["path"]),
        "params": params,
        "params_sha256": hashlib.sha256(canonical(params)).hexdigest(),
        "limitations": list(LIMITATIONS),
        "started_at": started_at or utc_now(),
        "finished_at": finished_at,
    }
    m["content_sha256"] = content_sha256(m)
    return m


def write(manifest: dict, out_dir, name: str = "run_manifest.json") -> Path:
    """Write once, atomically. An existing manifest is never replaced."""
    out = Path(out_dir) / name
    if out.exists():
        raise FileExistsError(f"{out} exists; a run manifest is never overwritten")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.link(tmp, out)  # fails if `out` appeared meanwhile, so nothing is overwritten
    tmp.unlink()
    return out


def compare_with_data_manifest(manifest: dict, data_manifest: dict) -> dict:
    """Check run inputs against a dataset manifest's recorded hashes (e.g. research-data/edge/manifest.json).
    Only files named in both are compared; files present in only one are listed, not guessed."""
    recorded = {name: f.get("sha256") for name, f in data_manifest.get("files", {}).items()}
    by_name = {Path(r["path"]).name: r for r in manifest["inputs"]}
    shared = sorted(set(recorded) & set(by_name))
    return {
        "matched": [n for n in shared if by_name[n]["sha256"] and by_name[n]["sha256"] == recorded[n]],
        "mismatched": [n for n in shared if by_name[n]["sha256"] and by_name[n]["sha256"] != recorded[n]],
        "unreadable": [n for n in shared if by_name[n]["sha256"] is None],
        "only_in_data_manifest": sorted(set(recorded) - set(by_name)),
        "only_in_run": sorted(set(by_name) - set(recorded)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check-data-manifest", type=Path, required=True,
                    help="dataset manifest.json; its files are hashed from the same folder")
    ap.add_argument("--out", type=Path, help="folder to write run_manifest.json into (optional)")
    a = ap.parse_args(argv)
    dm = json.loads(a.check_data_manifest.read_text())
    folder = a.check_data_manifest.parent
    m = run_manifest([folder / n for n in dm.get("files", {})], {"check": "data_manifest_hashes"},
                     purpose="dry run: compare stored dataset files with their manifest hashes (no outcomes)")
    m["finished_at"] = utc_now()
    result = compare_with_data_manifest(m, dm)
    print(json.dumps({"run_manifest": m, "comparison": result}, indent=1, sort_keys=True))
    if a.out:
        print(f"written: {write(m, a.out)}", file=sys.stderr)
    return 0 if not result["mismatched"] and not result["unreadable"] else 1


if __name__ == "__main__":
    sys.exit(main())
