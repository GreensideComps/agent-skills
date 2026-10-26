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


_PLAIN = (dict, list, str, int, float, bool, type(None))


def _check_plain(obj, path="$") -> None:
    if not isinstance(obj, _PLAIN):
        raise TypeError(f"{path}: {type(obj).__name__} is not a JSON value; convert it explicitly")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise TypeError(f"{path}: key {k!r} is not a string")
            _check_plain(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_plain(v, f"{path}[{i}]")


def canonical(obj) -> bytes:
    """Canonical JSON bytes. Only plain JSON values are accepted, and NaN or Infinity are refused (P31-3). An int and
    the equal float (1 and 1.0) are different values here and hash differently, on purpose."""
    _check_plain(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def package_versions(names=PACKAGES, version=importlib.metadata.version, modules=None) -> dict:
    """Installed metadata version plus, when the module is already imported, its `__version__` and `__file__`, so a
    shadowing copy on sys.path shows up (P31-6). A metadata error is recorded, not raised."""
    modules = sys.modules if modules is None else modules
    out = {}
    for n in names:
        try:
            out[n] = {"version": version(n)}
        except importlib.metadata.PackageNotFoundError:
            out[n] = {"version": None, "missing_reason": "not_installed"}
        except Exception as e:  # noqa: BLE001 - recorded with its type, never hidden
            out[n] = {"version": None, "missing_reason": f"metadata_error:{type(e).__name__}"}
        mod = modules.get(n)
        if mod is not None:
            out[n]["module_version"] = getattr(mod, "__version__", None)
            out[n]["module_file"] = getattr(mod, "__file__", None)
    return out


def _run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, p.stdout


def _run_git_bytes(args: list[str], cwd: Path) -> tuple[int, bytes]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e).encode()
    return p.returncode, p.stdout


def _porcelain_z(raw: bytes) -> list:
    """`git status --porcelain=v1 -z` entries: plain paths, or {'from', 'to'} for renames and copies (P31-4)."""
    parts, out, i = raw.split(b"\0"), [], 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2].decode(), entry[3:].decode("utf-8", "surrogateescape")
        if code[0] in "RC" or code[1] in "RC":
            out.append({"from": parts[i].decode("utf-8", "surrogateescape"), "to": path})
            i += 1
        else:
            out.append(path)
    return sorted(out, key=lambda p: p if isinstance(p, str) else p["to"])


def git_state(repo: Path = REPO, run=_run_git_bytes) -> dict:
    """Commit, dirty flag and enough to tell two dirty trees apart: the sha256 of `git diff --binary HEAD` and a
    hash for each untracked file (P31-2)."""
    rc, head = run(["rev-parse", "HEAD"], repo)
    if rc != 0:
        return {"commit": None, "dirty": None, "missing_reason": "not_a_git_checkout"}
    head = head.decode().strip()
    rc, status = run(["status", "--porcelain=v1", "-z", "--untracked-files=all"], repo)
    if rc != 0:
        return {"commit": head, "dirty": None, "missing_reason": "git_status_failed"}
    changed = _porcelain_z(status)
    rc, diff = run(["diff", "--binary", "HEAD"], repo)
    if rc != 0:
        return {"commit": head, "dirty": None, "dirty_paths": changed, "missing_reason": "git_diff_failed"}
    rc, others = run(["ls-files", "--others", "--exclude-standard", "-z"], repo)
    if rc != 0:
        return {"commit": head, "dirty": None, "dirty_paths": changed, "missing_reason": "git_ls_files_failed"}
    untracked = []
    for name in sorted(x for x in others.split(b"\0") if x):
        path = name.decode("utf-8", "surrogateescape")
        f = Path(repo) / path
        untracked.append({"path": path, "sha256": sha256_file(f) if f.is_file() else None})
    out = {"commit": head, "dirty": bool(changed), "dirty_paths": changed, "untracked": untracked}
    if diff:
        out["diff_sha256"] = hashlib.sha256(diff).hexdigest()
    else:
        out.update(diff_sha256=None, diff_reason="clean")
    return out


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


def _check_utc(name: str, value: str | None) -> None:
    if value is None:
        return
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.utcoffset() is None or t.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must be a UTC time, got {value}")


def run_manifest(inputs, params: dict, *, purpose: str, repo: Path = REPO, started_at: str | None = None,
                 finished_at: str | None = None, versions=package_versions, git=git_state,
                 require_clean: bool = False) -> dict:
    """`require_clean=True` refuses a dirty or unknown tree, for runs whose results must map to a commit."""
    _check_utc("started_at", started_at)
    _check_utc("finished_at", finished_at)
    g = git(repo)
    if require_clean and g.get("dirty") is not False:
        raise ValueError(f"require_clean: working tree is not clean ({g.get('dirty_paths') or g.get('missing_reason')})")
    m = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "purpose": purpose,
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation(),
                   "executable": sys.executable},
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "packages": versions(),
        "git": g,
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
    """Write once. The file is created exclusively (`open(..., "xb")`), so an existing manifest is never replaced
    and two writers cannot both win; this works on mounts without hard links, unlike `os.link` (P31-1). A failed
    write removes only the file this call created, and no temporary file is used."""
    out = Path(out_dir) / name
    data = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        f = open(out, "xb")
    except FileExistsError:
        raise FileExistsError(f"{out} exists; a run manifest is never overwritten") from None
    try:
        with f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    return out


MEANING = "byte match only; not correctness, PIT safety or licence"


def compare_with_data_manifest(manifest: dict, data_manifest: dict, folder=None, repo: Path = REPO) -> dict:
    """Check run inputs against a dataset manifest's recorded hashes (e.g. research-data/edge/manifest.json).

    Inputs are matched by their path relative to `folder` (the manifest's folder) when given, otherwise by name;
    two inputs with the same name are refused rather than one silently winning (P31-5). Only files named in both
    are compared; files present in only one are listed, not guessed. A match means the bytes are the recorded
    bytes, nothing more (`meaning`)."""
    recorded = {name: f.get("sha256") for name, f in data_manifest.get("files", {}).items()}
    by_name = {}
    for r in manifest["inputs"]:
        key = Path(r["path"]).name
        if folder is not None:
            full = Path(r["path"]) if Path(r["path"]).is_absolute() else Path(repo) / r["path"]
            try:
                key = full.resolve().relative_to(Path(folder).resolve()).as_posix()
            except ValueError:
                key = r["path"]
        if key in by_name:
            raise ValueError(f"two run inputs share the name {key}; matching would be ambiguous")
        by_name[key] = r
    shared = sorted(set(recorded) & set(by_name))
    return {
        "meaning": MEANING,
        "matched": [n for n in shared if by_name[n]["sha256"] and by_name[n]["sha256"] == recorded[n]],
        "mismatched": [n for n in shared if by_name[n]["sha256"] and by_name[n]["sha256"] != recorded[n]],
        "unreadable": [n for n in shared if by_name[n]["sha256"] is None],
        "only_in_data_manifest": sorted(set(recorded) - set(by_name)),
        "only_in_run": sorted(set(by_name) - set(recorded)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 epilog=f"Exit 0 means every listed file's bytes match the manifest ({MEANING}).")
    ap.add_argument("--check-data-manifest", type=Path, required=True,
                    help="dataset manifest.json; its files are hashed from the same folder")
    ap.add_argument("--out", type=Path, help="folder to write run_manifest.json into (optional)")
    a = ap.parse_args(argv)
    dm = json.loads(a.check_data_manifest.read_text())
    folder = a.check_data_manifest.parent
    m = run_manifest([folder / n for n in dm.get("files", {})], {"check": "data_manifest_hashes"},
                     purpose="dry run: compare stored dataset files with their manifest hashes (no outcomes)")
    m["finished_at"] = utc_now()
    result = compare_with_data_manifest(m, dm, folder)
    print(json.dumps({"run_manifest": m, "comparison": result}, indent=1, sort_keys=True))
    if a.out:
        print(f"written: {write(m, a.out)}", file=sys.stderr)
    return 0 if not result["mismatched"] and not result["unreadable"] else 1


if __name__ == "__main__":
    sys.exit(main())
