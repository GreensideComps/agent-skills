"""The registry events ADDENDUM_3 needs, prepared for the owner's review and NOT appended.

`register` appends them only when called with the owner's message id; nothing in the repository calls it. The
events: the addendum itself by sha256 (a diagnostic record, not counted) and the two new P9 robustness runs
`B5-{H1,S2A}-V2-ROB-WINQ` (diagnostics, not counted). No trial is added, so N stays 100. The version-2 trial ids,
version 2's ROB-PITQ ids and version 1's ids stay registered unchanged; the retired ones are refused by
`edge_registry.require` (B5_RETIRED_IDS).
"""
import hashlib
from pathlib import Path

import edge_registry

REPO = Path(__file__).resolve().parent.parent
ADDENDUM = "docs/edge/B5_PREREGISTRATION_ADDENDUM_3.md"
BASE = {"event": "register", "kind": "diagnostic", "phase": "exploration", "counts_for_dsr": False,
        "touched_holdout": False, "window": {"decisions": ["2015-01", "2022-11"], "outcomes_to": "2022-12-31"},
        "universe": "large band (>= $10bn), close_raw >= $1, ex financials; quality rule per ADDENDUM_3"}


def events(repo: Path = REPO) -> list[dict]:
    sha = hashlib.sha256((repo / ADDENDUM).read_bytes()).hexdigest()
    out = [{**BASE, "id": "B5-V2-ADDENDUM-3", "hypothesis": "none (specification amendment)", "horizon_months": 0,
            "definition": "ADDENDUM_3: point-in-time share-outlier quality rule is primary; the full-window rule is "
                          "the P9 reverse veto (ROB-WINQ); ROB-PITQ retired. Owner decision D20.",
            "spec_sha256": sha, "amends": ["B5-H1-FCFPS-ACCEL-V2", "B5-S2A-GP-12M-V2", "B5-V2-ADDENDUM-1",
                                           "B5-V2-ADDENDUM-2"],
            "retires": ["B5-H1-V2-ROB-PITQ", "B5-S2A-V2-ROB-PITQ"]}]
    for t, trial in (("H1", "B5-H1-FCFPS-ACCEL-V2"), ("S2A", "B5-S2A-GP-12M-V2")):
        out.append({**BASE, "id": f"B5-{t}-V2-ROB-WINQ", "hypothesis": f"robustness of {trial} (P9, veto only)",
                    "horizon_months": 3 if t == "H1" else 12, "spec_sha256": sha,
                    "definition": f"{trial} exactly as registered and amended, except: eligibility and the S2a rank "
                                  "population use the Phase A full-window quality rule "
                                  "(edge_split.share_outliers); gate P9 (reverse veto); ADDENDUM_3 §3. Replaces "
                                  "ROB-PITQ for P9."})
    return out


def register(owner_message: str, registry: Path = edge_registry.PATH, repo: Path = REPO) -> list[dict]:
    """Append the events. Refuses without an owner message id or if any id is already registered."""
    if not str(owner_message).startswith("cmsg_"):
        raise PermissionError("registering ADDENDUM_3 needs the owner's message id")
    have = edge_registry.registered(edge_registry.load(registry))
    evs = [{**e, "owner_message": owner_message} for e in events(repo)]
    clash = [e["id"] for e in evs if e["id"] in have]
    if clash:
        raise ValueError(f"already registered: {clash}")
    return [edge_registry.append(e, registry) for e in evs]
