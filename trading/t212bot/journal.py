"""Append-only decision/order journal plus small mutable state.

Files (committed to git so they survive ephemeral cloud sessions):
  journal/events.jsonl   one JSON object per line, never rewritten
  journal/snapshots.csv  account value history (one row per run)
  journal/state.json     inception info, learned quantity precision,
                         last rebalance month, shadow portfolio holdings
"""
from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import JOURNAL_DIR

SNAP_FIELDS = ["ts_utc", "total_value_gbp", "cash_gbp", "invested_gbp", "unrealized_pl_gbp",
               "realized_pl_gbp", "positions_json", "run_id"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Journal:
    def __init__(self, root: Path = JOURNAL_DIR, run_id: str | None = None, clock=utcnow):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or utcnow().strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
        self._clock = clock

    # ------------------------------------------------------------ events
    def event(self, kind: str, **data) -> dict:
        rec = {"ts_utc": self._clock().isoformat(timespec="seconds"), "run_id": self.run_id, "kind": kind, **data}
        with open(self.root / "events.jsonl", "a") as f:
            f.write(json.dumps(rec, default=str, sort_keys=True) + "\n")
        return rec

    def events(self, kind: str | None = None) -> list[dict]:
        p = self.root / "events.jsonl"
        if not p.exists():
            return []
        out = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        return [e for e in out if kind is None or e["kind"] == kind]

    # ------------------------------------------------------------ snapshots
    def snapshot(self, summary: dict, positions: list[dict]) -> dict:
        cash = summary.get("cash", {})
        inv = summary.get("investments", {})
        row = {
            "ts_utc": self._clock().isoformat(timespec="seconds"),
            "total_value_gbp": summary.get("totalValue"),
            "cash_gbp": cash.get("availableToTrade"),
            "invested_gbp": inv.get("currentValue"),
            "unrealized_pl_gbp": inv.get("unrealizedProfitLoss"),
            "realized_pl_gbp": inv.get("realizedProfitLoss"),
            "positions_json": json.dumps({p["instrument"]["ticker"]: p["quantity"] for p in positions}, sort_keys=True),
            "run_id": self.run_id,
        }
        p = self.root / "snapshots.csv"
        new = not p.exists()
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SNAP_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
        return row

    def snapshots(self) -> list[dict]:
        p = self.root / "snapshots.csv"
        if not p.exists():
            return []
        with open(p) as f:
            return list(csv.DictReader(f))

    # ------------------------------------------------------------ state
    def load_state(self) -> dict:
        p = self.root / "state.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def save_state(self, state: dict) -> None:
        p = self.root / "state.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True, default=str))
        tmp.replace(p)
