"""Evidence tiers for method versions (docs/STRATEGY_V2.md, Part 3.4).

Every report that shows a score, valuation or pick states the tier of the method behind it, so an
unvalidated output is never read as a recommendation.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "evidence.json"
DECISION_TIERS = {"E3", "E4"}  # tiers allowed to drive rankings or sizing


def load(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def tier(method_version: str, cfg: dict | None = None) -> str:
    """Tier of a method version; anything not listed is E0."""
    return ((cfg or load())["methods"].get(method_version) or {}).get("tier", "E0")


def may_drive_decisions(method_version: str, cfg: dict | None = None) -> bool:
    return tier(method_version, cfg) in DECISION_TIERS


def banner(*method_versions: str, cfg: dict | None = None) -> str:
    """One markdown line per method, for the top of a report."""
    cfg = cfg or load()
    out = []
    for m in method_versions:
        e = cfg["methods"].get(m) or {}
        t = e.get("tier", "E0")
        state = "may drive decisions" if t in DECISION_TIERS else "**unvalidated: not a recommendation**"
        out.append(f"> Evidence tier **{t}** for `{m}` ({state}). Allowed use: {e.get('allowed_use', 'none recorded')}. "
                   f"{e.get('evidence', '')}")
    return "\n>\n".join(out)
