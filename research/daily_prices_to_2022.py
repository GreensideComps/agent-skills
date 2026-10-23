"""Build the daily price file to 2022 from already-stored chart responses (mini fund Stage 2 §2).

    python3 research/daily_prices_to_2022.py --raw-index index.json --out-dir <folder with manifest.json>

`index.json` lists stored responses: [{"symbol", "raw_path", "url", "retrieved_at"}]. This script reads local
files only; it fetches nothing (a live pull is a separate, unapproved step, U3-style). It writes
`daily_prices_to_2022.csv.gz` and adds it to the folder's `manifest.json` as a **new** entry with its hash and a
history line. Existing manifest entries are never changed, and an existing entry of the same name is never replaced.
Nothing dated after 2022-12-31 can enter the file (`edge_exec_prices.assert_cut`).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import edge_exec_prices
import price_provenance as pp

OUT_NAME = "daily_prices_to_2022.csv.gz"
COLUMNS = ["symbol", "session_date", "close", "adjclose", "close_unadjusted", "split_basis", "available_at",
           "missing_reasons", "raw_sha256"]


class ManifestError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fmt(v):
    return "" if v is None else v


def build_rows(index: list[dict], sessions: dict | None = None) -> list[dict]:
    rows = []
    for item in index:
        body = Path(item["raw_path"]).read_bytes()
        parsed = pp.parse_chart(body, symbol=item["symbol"], url=item["url"], retrieved_at=item["retrieved_at"],
                                sessions=sessions)
        for r in parsed["records"]:
            rows.append({"symbol": r["symbol"], "session_date": r["session_date"], "close": r["close"],
                         "adjclose": r["adjclose"], "close_unadjusted": r["close_unadjusted"],
                         "split_basis": r["split_basis"], "available_at": r["available_at"],
                         "missing_reasons": "|".join(r["missing_reasons"]), "raw_sha256": r["source"]["raw_sha256"]})
    edge_exec_prices.assert_cut([r["session_date"] for r in rows], "daily prices")
    rows.sort(key=lambda r: (r["symbol"], r["session_date"]))
    return rows


def encode(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: _fmt(r[k]) for k in COLUMNS})
    return gzip.compress(buf.getvalue().encode(), mtime=0)  # mtime 0: same rows give the same bytes


def add_to_manifest(manifest_path: Path, name: str, blob: bytes, rows: int, provenance: str, clock=utc_now) -> dict:
    """Add one new file entry and one history line; every existing key and entry stays exactly as it was."""
    old_text = manifest_path.read_text()
    m = json.loads(old_text)
    if name in m.get("files", {}):
        raise ManifestError(f"{name} is already in the manifest; entries are never replaced")
    before = json.loads(old_text)
    m.setdefault("files", {})[name] = {"rows": rows, "sha256": hashlib.sha256(blob).hexdigest(), "added_utc": clock()}
    m.setdefault("provenance", {})[name] = provenance
    m.setdefault("history", []).append({"utc": clock(), "action": f"add {name} (mini fund Stage 2 §2); "
                                        "existing entries unchanged"})
    m.setdefault("limitations", {})[name] = list(pp.LIMITATIONS)
    for k, v in before.items():
        if k in ("files", "provenance", "history", "limitations"):
            continue
        if m[k] != v:
            raise ManifestError(f"manifest key {k} would change")
    for k, v in before.get("files", {}).items():
        if m["files"][k] != v:
            raise ManifestError(f"manifest entry {k} would change")
    if m["history"][:len(before.get("history", []))] != before.get("history", []):
        raise ManifestError("manifest history would change")
    if any(m["provenance"].get(k) != v for k, v in before.get("provenance", {}).items()):
        raise ManifestError("manifest provenance would change")
    tmp = manifest_path.with_name(manifest_path.name + ".tmp")
    tmp.write_text(json.dumps(m, indent=1) + "\n")
    tmp.replace(manifest_path)
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw-index", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--sessions", type=Path, help="sourced session calendar CSV (optional; none exists yet)")
    a = ap.parse_args(argv)
    sessions = pp.load_sessions(a.sessions) if a.sessions else None
    rows = build_rows(json.loads(a.raw_index.read_text()), sessions)
    out = a.out_dir / OUT_NAME
    if out.exists():
        raise ManifestError(f"{out} exists; it is never overwritten")
    blob = encode(rows)
    out.write_bytes(blob)  # data first: a manifest entry never points at a file that was not written
    try:
        add_to_manifest(a.out_dir / "manifest.json", OUT_NAME, blob, len(rows),
                        "Yahoo chart v8 responses stored as raw bytes (sha256 per row); built offline by "
                        "research/daily_prices_to_2022.py")
    except Exception:
        out.unlink()
        raise
    print(f"{OUT_NAME}: {len(rows)} rows, sha256 {hashlib.sha256(blob).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
