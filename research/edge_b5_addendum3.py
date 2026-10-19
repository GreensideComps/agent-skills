"""The registry events ADDENDUM_3 needs (version 3, owner decisions D20 and D21), prepared for the owner's review and
NOT appended.

`register` appends them only when called with the owner's message id; nothing in the repository calls it. Events:

* `B5-V3-ADDENDUM-3`: the addendum itself by sha256 (a specification record, not counted);
* `B5-H1-FCFPS-ACCEL-V3`, `B5-S2A-GP-12M-V3`: the two amended trials, **counted**, so N goes from 100 to 102;
* `B5-{H1,S2A}-V3-ROB-{2XCOST,MISS100,NEXTMONTH,DATAERR,WINQ}`: their ten robustness runs (not counted).

Nothing already in the registry is edited: the version-1 and version-2 entries stay as written, stay counted, and are
refused by `edge_registry.require` (B5_RETIRED_IDS).

`register` is all or nothing: the 13 lines are chained, written to a temporary file, checked (valid registry, every
earlier byte unchanged, exactly these 13 ids added, N up by exactly 2) and only then moved over the registry in one
rename. Any failure leaves the registry as it was.
"""
import hashlib
import json
import os
from datetime import date
from pathlib import Path

import edge_registry

REPO = Path(__file__).resolve().parent.parent
ADDENDUM = "docs/edge/B5_PREREGISTRATION_ADDENDUM_3.md"
PROPOSAL = REPO / "docs" / "edge" / "B5_V3_PROPOSED_REGISTRY_EVENTS.json"  # the file the owner reviewed
WINDOW = {"decisions": ["2015-01", "2022-11"], "outcomes_to": "2022-12-31"}
UNIVERSE = ("large band (>= $10bn), close_raw >= $1, point-in-time quality rule (ADDENDUM_3), ex financials; each "
            "TTM input's own period end <= 183 days old")
TRIALS = {"H1": ("B5-H1-FCFPS-ACCEL-V3", "B5-H1-FCFPS-ACCEL-V2", 3,
                 "H1: investors underreact when per-share free cash flow growth accelerates"),
          "S2A": ("B5-S2A-GP-12M-V3", "B5-S2A-GP-12M-V2", 12, "S2a: gross profitability predicts returns over 12 months")}
ROB = {"2XCOST": "2x costs; gate P4", "MISS100": "missing prices at -100%; gate P6",
       "NEXTMONTH": "next-month-close execution; gate P7",
       "DATAERR": "the 12 registered data-error company-months barred from purchase; gate P8",
       "WINQ": "eligibility and the S2a rank population under the Phase A full-window quality rule "
               "(edge_split.share_outliers); gate P9, reverse veto"}


def events(repo: Path = REPO) -> list[dict]:
    sha = hashlib.sha256((repo / ADDENDUM).read_bytes()).hexdigest()
    base = {"event": "register", "phase": "exploration", "touched_holdout": False, "window": WINDOW,
            "spec_sha256": sha}
    out = [{**base, "id": "B5-V3-ADDENDUM-3", "kind": "diagnostic", "counts_for_dsr": False, "horizon_months": 0,
            "hypothesis": "none (specification record for version 3, not a trial)", "universe": "as version 3",
            "definition": "docs/edge/B5_PREREGISTRATION_ADDENDUM_3.md: version 3 = version 2 + addenda 1-3; "
                          "point-in-time quality rule primary, full-window rule as P9 reverse veto; new counted "
                          "trial ids, N = 102 (owner decisions D20, D21).",
            "amends": ["B5-H1-FCFPS-ACCEL-V2", "B5-S2A-GP-12M-V2", "B5-V2-ADDENDUM-1", "B5-V2-ADDENDUM-2"]}]
    for t, (tid, old, horizon, hyp) in TRIALS.items():
        out.append({**base, "id": tid, "kind": "trial", "counts_for_dsr": True, "horizon_months": horizon,
                    "hypothesis": hyp, "universe": UNIVERSE, "supersedes": old,
                    "definition": f"{old} as registered (docs/edge/B5_PREREGISTRATION.md v2), amended by addenda 1, 2 "
                                  "and 3: the quality rule for eligibility, the S2a rank population and the P5 "
                                  "universe is edge_split.share_outliers_pit; P9 is the full-window reverse veto; "
                                  "gates P1-P11 and thresholds unchanged; verdict edge_b5.verdict"})
        for g, what in ROB.items():
            out.append({**base, "id": f"B5-{t}-V3-ROB-{g}", "kind": "diagnostic", "counts_for_dsr": False,
                        "horizon_months": horizon, "universe": UNIVERSE,
                        "hypothesis": f"robustness of {tid} (veto only, never a substitute result)",
                        "definition": f"{tid} exactly as registered, except: {what}. ADDENDUM_3 §3."})
    return out


def register(owner_message: str, registry: Path = edge_registry.PATH, repo: Path = REPO,
             proposal: Path = PROPOSAL) -> list[dict]:
    """Append the 13 events in one atomic step. Refuses without an owner message id, if the events differ from the
    reviewed proposal file, if the registry is invalid, or if any id is already registered."""
    if not str(owner_message).startswith("cmsg_"):
        raise PermissionError("registering ADDENDUM_3 (version 3) needs the owner's message id")
    proposed = events(repo)
    if proposed != json.loads(proposal.read_text()):
        raise ValueError(f"events differ from the reviewed proposal {proposal}")
    problems = edge_registry.validate(registry)
    if problems:
        raise ValueError(f"registry invalid before registration: {problems}")
    old = registry.read_bytes()
    before = edge_registry.load(registry)
    have = edge_registry.registered(before)
    clash = [e["id"] for e in proposed if e["id"] in have]
    if clash:
        raise ValueError(f"already registered: {clash}")
    lines = [l for l in old.decode().splitlines() if l.strip()]
    prev = edge_registry.line_hash(lines[-1]) if lines else edge_registry.GENESIS
    out, new = [], []
    for e in proposed:
        full = {"prev": prev, "date": date.today().isoformat(), **e, "owner_message": owner_message}
        raw = json.dumps(full, sort_keys=True)
        out.append(full)
        new.append(raw)
        prev = edge_registry.line_hash(raw)
    text = "\n".join(lines + new) + "\n"
    if not text.encode().startswith(old):
        raise ValueError("registry is not in canonical form; refusing rather than rewrite any existing byte")
    tmp = registry.with_suffix(".v3.tmp")
    tmp.write_text(text)
    try:
        after = edge_registry.load(tmp)
        added = set(edge_registry.registered(after)) - set(have)
        checks = {"valid": not edge_registry.validate(tmp),
                  "prefix unchanged": tmp.read_bytes()[:len(old)] == old,
                  "13 ids added": added == {e["id"] for e in proposed} and len(after) == len(before) + 13,
                  "N + 2": edge_registry.n_trials(after) == edge_registry.n_trials(before) + 2}
        if not all(checks.values()):
            raise ValueError(f"registration rejected, registry unchanged: {checks}")
        os.replace(tmp, registry)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out
