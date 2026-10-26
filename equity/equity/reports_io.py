"""Write-once report files (mini fund work package WP-H, review finding P30-5).

A report under `equity/reports/` is a historical record: once written it is never replaced. Writing a report whose
file already exists with different bytes creates `<name>.rerun-<n>.md` (the next free n) beside it; identical bytes
write nothing. Files are created exclusively (`open(..., "x")`), so two writers racing for one name cannot both
win, and a failed write leaves no partial file.

`PINNED` lists the screen-1.0 and paper-1.0 reports covered by the label of record (docs/minifund/SCREEN_1_0_LABEL.md
on PR #30, owner decision D-C) by full SHA-256. A pinned report that is missing or no longer has its hash is an
error: it is never re-created or written over, because that would alter a historical result.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

PINNED = {
    "screens/2026-10-14.md": "7ea51a5d00df26a62d6d7ee4ac1de8a68b717f89360f42feeec954a36b7b1da1",
    "screens/2026-10-15.md": "ad7c723bf112125aff048e06afcc5ea23ee3310d67fe4d84167f477849289a62",
    "screens/2026-10-16.md": "87d68dcc10b42d14d5b379d558c4d8d2bf0faeae1c84365b58eaf44e6b6235b0",
    "screens/2026-10-19.md": "af40e7131b2e59177121923d4fd34301446cbbfb250cc63a6dcc79e7055ca2ac",
    "screens/2026-10-20.md": "a9e305f0b10f6d453ada2313bbf9d1d8a89195008988da741fd7749c9a27545b",
    "screens/2026-10-23.md": "c298a067749b7340e8e135c6562569156ab671c3ff51a96705795408ffcfdd6b",  # see OVERWRITTEN
    "paper/2026-10-14.md": "a7f26f8beab1d6c38dccdc497854b6ab030fc7fe3846178b3796400d6decd644",
    "paper/2026-10-15.md": "76f94db5ed7a547f04a57566f0b0f0da4c22d3953f805964f6d044a70cadce6c",
    "paper/2026-10-16.md": "8c314936ac19f77c0b4a090482bcba23c4c022ed681e6a5e95128698533858c8",
    "paper/2026-10-19.md": "73239f1c79791a1c769e5b6d138c17ce07d7e36c45dfeb47ee483e9dc4185e8e",
    "paper/2026-10-20.md": "9071a11bec9440a4436a7c797e79d2cf5053e70edf6df7da1466d2d2dcdd9b94",
    "paper/2026-10-23.md": "5322db1d89d4f2a8b92d48cb6642b36b9dd6bc0e1460444cdeb41300ffb1546e",
}


# Reports replaced before this guard existed. The label of record pinned the first version; the scheduled pipeline
# run of 2026-10-23 21:55Z (commit ef9004a) rewrote the file. Both versions stay in git history; the current file is
# pinned above (proposed, pending owner decision) and the original is recorded here, never restored over it.
OVERWRITTEN = {
    "screens/2026-10-23.md": {"label_sha256": "d6784757c78813c7116c6937f6fdb7161191256be03a4202ee36c38ca7ac41e0",
                              "original_commit": "b8cccb4", "overwritten_by_commit": "ef9004a"},
}

class ReportError(RuntimeError):
    pass


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pinned_problems(root: Path | None = None) -> list[str]:
    """Pinned reports that are missing or whose bytes changed (empty = all intact)."""
    root = REPORTS_DIR if root is None else root
    out = []
    for rel, h in sorted(PINNED.items()):
        p = Path(root) / rel
        if not p.is_file():
            out.append(f"{rel}: missing")
        elif _sha(p.read_bytes()) != h:
            out.append(f"{rel}: sha256 changed")
    return out


def _check_pinned(path: Path, root: Path) -> None:
    try:
        rel = path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return
    h = PINNED.get(rel)
    if h is None:
        return
    if not path.is_file():
        raise ReportError(f"pinned historical report {rel} is missing; it is never re-created")
    if _sha(path.read_bytes()) != h:
        raise ReportError(f"pinned historical report {rel} no longer has its recorded sha256")


def _create(path: Path, data: bytes) -> bool:
    """Create `path` with `data` exclusively. False if it already exists. A failed write removes the partial file."""
    try:
        f = open(path, "xb")
    except FileExistsError:
        return False
    try:
        with f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return True


def write_report_once(path, text: str, root: Path | None = None) -> Path:
    """Write `text` to `path` unless a report is already there; return the file that holds `text`.

    Existing file with the same bytes: nothing is written. With different bytes: the text goes to
    `<stem>.rerun-<n><suffix>`, the first n whose file is absent (or already holds the same bytes)."""
    path = Path(path)
    data = text.encode()
    _check_pinned(path, REPORTS_DIR if root is None else root)
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate, n = path, 0
    while True:
        if _create(candidate, data):
            return candidate
        if candidate.read_bytes() == data:
            return candidate
        n += 1
        candidate = path.with_name(f"{path.stem}.rerun-{n}{path.suffix}")
