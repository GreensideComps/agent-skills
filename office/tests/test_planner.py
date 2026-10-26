"""Research planner (D-T15): drafts only, one per ISO week, required fields, computed overlap and contamination."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from office import planner

REPO = Path(__file__).resolve().parents[2]
EVENTS = [json.loads(x) for x in (REPO / "research/edge/trials.jsonl").read_text().splitlines() if x.strip()]
CAND = {"title": "Gross profitability in mid caps", "hypothesis": "Gross profit / assets predicts returns in mid caps",
        "rationale": "r", "data_requirements": "SEC companyfacts, Yahoo prices", "methodology": "monthly IC, within "
        "SIC group, ex financials", "costs": {"data": "free sources only", "paid": False}, "risks": "survivorship",
        "windows": {"exploration": ["2010-01", "2022-12"]}}
DAY = dt.date(2026, 10, 20)


def test_draft_has_every_section_and_computed_parts(tmp_path):
    p = planner.draft(CAND, EVENTS, DAY, tmp_path)
    md = p.read_text()
    assert p.name.startswith("2026-W43-") and "DRAFT, awaiting owner approval" in md
    for h in ("Hypothesis", "Rationale", "Data requirements", "Methodology", "Costs", "Risks",
              "Prior-trial overlap", "Holdout-contamination assessment"):
        assert f"## {h}" in md
    assert "S2-S2a" in md                       # the Stage 2 gross-profitability trial is found as overlap
    assert "single confirmation batch stays unspent" in md


def test_one_per_week_and_required_fields(tmp_path):
    planner.draft(CAND, EVENTS, DAY, tmp_path)
    with pytest.raises(planner.PlannerError, match="already exists"):
        planner.draft(dict(CAND, title="other"), EVENTS, DAY + dt.timedelta(days=1), tmp_path)
    planner.draft(dict(CAND, title="next"), EVENTS, DAY + dt.timedelta(days=7), tmp_path)
    with pytest.raises(planner.PlannerError, match="missing"):
        planner.draft(dict(CAND, risks=""), EVENTS, DAY + dt.timedelta(days=14), tmp_path)


def test_seen_holdout_cannot_be_confirmation(tmp_path):
    with pytest.raises(planner.PlannerError, match="partly seen"):
        planner.draft(dict(CAND, windows={"confirmation": ["2024-01", "2025-12"]}), EVENTS, DAY, tmp_path)
    notes = planner.contamination({"exploration": ["2020-01", "2024-06"]})
    assert "exploratory evidence only" in notes[0]
    md = planner.draft(dict(CAND, costs={"data": "EODHD", "paid": True}), EVENTS, DAY, tmp_path).read_text()
    assert "owner approval for the spend" in md


def test_planner_never_touches_registry_or_runs(tmp_path):
    before = hashlib.sha256((REPO / "research/edge/trials.jsonl").read_bytes()).hexdigest()
    planner.draft(CAND, EVENTS, DAY, tmp_path)
    assert hashlib.sha256((REPO / "research/edge/trials.jsonl").read_bytes()).hexdigest() == before
    tree = ast.parse(Path(planner.__file__).read_text())
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in mods if "edge" in m or "subprocess" in m or "research" in m}


def test_review_findings_windows_and_week_limit(tmp_path):
    for w in ({"confirmation": ["2026-12", "2023-02"]}, {"exploration": ["2026-10", "2026-13"]},
              {"Confirmation": ["2024-01", "2024-06"]}, {"holdout": ["2010-01", "2011-01"]}, ["2010-01", "2011-01"]):
        with pytest.raises(planner.PlannerError):
            planner.draft(dict(CAND, windows=w), EVENTS, DAY, tmp_path / "a")
    assert not (tmp_path / "a").exists()                      # nothing written on refusal
    planner.draft(CAND, EVENTS, DAY, tmp_path / "main")
    with pytest.raises(planner.PlannerError, match="already exists"):
        planner.draft(CAND, EVENTS, DAY, tmp_path / "other", also_check=(tmp_path / "main",))
    with pytest.raises(planner.PlannerError, match="must be text"):
        planner.draft(dict(CAND, hypothesis=["x"]), EVENTS, DAY + dt.timedelta(days=7), tmp_path / "x")
