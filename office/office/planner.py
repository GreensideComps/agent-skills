"""Research planner (owner decision D-T15): drafts at most one research proposal per ISO week for owner approval.

Drafting only. This module never registers a trial, writes a manifest, sets an authorisation or runs anything:
it reads the trial registry and writes one markdown file. The existing gates (registration, owner authorisation,
manifest and lock checks in research/edge_b5_run.py) stay the only way an experiment can start.

The candidate (hypothesis, rationale, data, method, costs, risks, windows) is written by whoever proposes it. The
planner refuses an incomplete candidate and adds what it can check itself: overlap with every registered trial,
the multiple-testing count, and whether the proposed windows touch data already seen.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

REQUIRED = ("title", "hypothesis", "rationale", "data_requirements", "methodology", "costs", "risks", "windows")
# DECISIONS.md: confirmation data Jan 2023 - Sep 2026 is PARTLY SEEN; one confirmation batch ever.
SEEN = ("2023-01", "2026-09")
EXPLORATION_END = "2022-12"


class PlannerError(ValueError):
    pass


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}


def overlap(candidate: dict, events: list[dict], top: int = 5) -> list[dict]:
    """Registered entries most similar to the candidate (word overlap of hypothesis and definitions), with verdicts."""
    mine = _words(candidate["hypothesis"] + " " + candidate["methodology"])
    reg, verdict = {}, {}
    for e in events:
        if e.get("event") == "register":
            reg[e["id"]] = e
        elif e.get("event") == "result" and e.get("verdict"):
            verdict[e["id"]] = e["verdict"]
    scored = []
    for tid, e in reg.items():
        theirs = _words(f"{e.get('hypothesis', '')} {e.get('definition', '')}")
        if mine and theirs:
            j = len(mine & theirs) / len(mine | theirs)
            if j > 0:
                scored.append({"id": tid, "similarity": round(j, 3), "kind": e.get("kind"),
                               "verdict": verdict.get(tid, "none recorded"), "definition": e.get("definition", "")[:120]})
    return sorted(scored, key=lambda x: -x["similarity"])[:top]


def _months_overlap(a: tuple[str, str], b: tuple[str, str]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def contamination(windows: dict) -> list[str]:
    """Plain statements of which proposed windows touch seen data; a confirmation window inside it is refused."""
    out = []
    for name, w in windows.items():
        if not (isinstance(w, (list, tuple)) and len(w) == 2 and all(re.fullmatch(r"\d{4}-\d{2}", x) for x in w)):
            raise PlannerError(f"window {name!r} must be [YYYY-MM, YYYY-MM]")
        w = tuple(w)
        if _months_overlap(w, SEEN):
            if name == "confirmation":
                raise PlannerError(f"confirmation window {w} overlaps the partly seen {SEEN} holdout; it cannot be "
                                   "used as untouched confirmation (DECISIONS.md)")
            out.append(f"{name} {w[0]} to {w[1]} overlaps the partly seen {SEEN[0]} to {SEEN[1]} period: exploratory "
                       "evidence only, never confirmation.")
        else:
            out.append(f"{name} {w[0]} to {w[1]} does not touch the partly seen period.")
    if "confirmation" not in windows:
        out.append("No confirmation window: any result is exploratory. The single confirmation batch stays unspent.")
    return out


def week_of(day: dt.date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def draft(candidate: dict, events: list[dict], today: dt.date, out_dir: Path) -> Path:
    """Write one proposal draft; refuse if incomplete or if this ISO week already has one."""
    missing = [k for k in REQUIRED if not candidate.get(k)]
    if missing:
        raise PlannerError(f"candidate is missing {missing}")
    wk = week_of(today)
    out_dir.mkdir(parents=True, exist_ok=True)
    if list(out_dir.glob(f"{wk}-*.md")):
        raise PlannerError(f"a proposal for {wk} already exists (one per week, D-T15)")
    n_dsr = len({e["id"] for e in events if e.get("event") == "register" and e.get("counts_for_dsr")})
    ov = overlap(candidate, events)
    cont = contamination(candidate["windows"])
    costs = candidate["costs"]
    slug = re.sub(r"[^a-z0-9]+", "-", candidate["title"].lower()).strip("-")[:50]
    path = out_dir / f"{wk}-{slug}.md"
    lines = [f"# Research proposal {wk}: {candidate['title']}", "",
             "**Status: DRAFT, awaiting owner approval.** Drafting does not register, authorise or run anything "
             "(D-T15). Registration, owner authorisation and the manifest gates stay mandatory.", "",
             f"Drafted {today.isoformat()} by the research planner.", "",
             "## Hypothesis", "", candidate["hypothesis"], "", "## Rationale", "", candidate["rationale"], "",
             "## Data requirements", "", candidate["data_requirements"], "", "## Methodology", "",
             candidate["methodology"], "", "## Costs", "",
             (costs if isinstance(costs, str) else json.dumps(costs)), ""]
    if isinstance(costs, dict) and costs.get("paid"):
        lines += ["**This needs paid data or services: owner approval for the spend is required first.**", ""]
    lines += ["## Risks", "", candidate["risks"], "", "## Prior-trial overlap (computed from the registry)", "",
              f"{n_dsr} registered entries count towards the deflated Sharpe ratio; this proposal would add at least "
              "one more.", "", "| Registered id | Similarity | Kind | Verdict | Definition |", "|---|---|---|---|---|"]
    lines += [f"| {o['id']} | {o['similarity']:.2f} | {o['kind']} | {o['verdict']} | {o['definition']} |" for o in ov] \
        or ["| none | | | | |"]
    lines += ["", "Similarity is word overlap only; a reviewer must judge whether a close match is the same idea.",
              "", "## Holdout-contamination assessment (computed)", ""] + [f"- {c}" for c in cont] + [""]
    path.write_text("\n".join(lines))
    return path
