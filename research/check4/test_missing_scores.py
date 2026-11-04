"""The missing-score classifier must agree with the frozen scores: every unscored row gets a named reason and every
scored row gets none ("unexplained" is the classifier's 'no step fails'). Synthetic data only.

    B5_FROZEN=/path/to/a4a07d7-checkout python3 -m pytest -q research/check4
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
FROZEN = Path(os.environ.get("B5_FROZEN", ""))
if not (FROZEN / "research" / "edge_b5.py").exists():
    raise RuntimeError("set B5_FROZEN to a checkout of a4a07d7 (run 2's commit)")
sys.path.insert(0, str(FROZEN / "research"))

import edge_b5 as b5  # noqa: E402
import missing_scores as ms  # noqa: E402


def panel(seed, n_cos=25, n_months=48, p=0.06):
    """Random company-months with every input the two scores read, each knocked out or flagged with probability p,
    period ends that drift, share jumps, absent months and one identity-rule company."""
    rng = np.random.default_rng(seed)
    rows = []
    months = pd.date_range("2013-01-31", periods=n_months, freq="ME")
    for c in range(n_cos):
        sh = 1e8
        for m in months:
            if rng.random() < p / 2:
                continue  # absent month
            end = (m - pd.offsets.MonthEnd(int(rng.integers(0, 4)) if rng.random() > p else 8)).normalize()
            sh *= 4.0 if rng.random() < p / 3 else 1.0
            gap = lambda: rng.random() < p
            flag = lambda: (None if rng.random() < p / 3 else True) if rng.random() < p else False
            ta = float(rng.uniform(5e9, 5e10)) if not gap() else (np.nan if rng.random() < .5 else -1.0)
            rev = float(rng.uniform(1e9, 2e10))
            rows.append({
                "cik": 1635327 if c == 0 else 1000 + c, "month": m,
                "ocf": np.nan if gap() else float(rng.uniform(1e8, 5e9)),
                "capex": np.nan if gap() else float(rng.uniform(1e7, 1e9)),
                "fcf_end": None if gap() else end.date().isoformat(),
                "shares_out": np.nan if gap() else sh, "shares_diluted": sh,
                "total_assets": ta, "close_raw": 50.0 if not gap() else np.nan, "adjclose": 50.0,
                "ocf_restated": flag(), "capex_restated": flag(),
                "gross_profit": np.nan if gap() else rev * 0.4, "gp_end": end.date().isoformat(),
                "gp_restated": flag(), "revenue": np.nan if gap() else rev,
                "cost_of_revenue": np.nan if gap() else rev * 0.6,
                "rev_end": end.date().isoformat(),
                "cor_end": end.date().isoformat() if not gap() else (end - pd.offsets.MonthEnd(3)).date().isoformat(),
                "rev_conflict": flag(), "cor_restated": flag(),
                "mcap": 5e9 if not gap() else 1e13, "financial": False,
                "group": None if gap() else f"g{c % 4}"})
    return pd.DataFrame(rows).reset_index(drop=True)


@pytest.mark.parametrize("seed", range(6))
def test_h1_every_unscored_row_has_a_reason_and_no_scored_row_has_one(seed):
    df = panel(seed)
    score = b5.h1_score(df)
    reason, inherited = ms.h1_reasons(b5, df)
    assert (reason[score.isna()] != "unexplained").all()
    assert (reason[score.notna()] == "unexplained").all()
    assert inherited.notna().equals(reason.isin(["fcf_12m_earlier_unavailable", "no_row_24m_earlier_or_G_12m_earlier"]))
    assert score.isna().sum() > 50 and reason.nunique() >= 8  # the worlds exercise most steps


@pytest.mark.parametrize("seed", range(6))
def test_s2a_every_unscored_row_has_a_reason_and_no_scored_row_has_one(seed):
    df = panel(seed)
    gpa = b5.s2a_profitability(df)
    scored = gpa.notna() & df["group"].notna()  # s2a_scores ranks within group: no group, no rank
    reason, _ = ms.s2a_reasons(b5, df)
    assert (reason[~scored] != "unexplained").all()
    assert (reason[scored] == "unexplained").all()
    assert reason.nunique() >= 6


def test_first_reason_takes_the_first_failing_step_in_order():
    idx = pd.RangeIndex(3)
    steps = [("a", "", ""), ("b", "", ""), ("unexplained", "", "")]
    conds = [pd.Series([False, True, False]), pd.Series([True, True, False]), pd.Series(True, index=idx)]
    assert ms.first_reason(conds, steps, idx).tolist() == ["b", "a", "unexplained"]


def test_steps_are_labelled_and_kinds_are_known():
    for steps in (ms.H1_STEPS, ms.S2A_STEPS):
        assert steps[-1][0] == "unexplained" and len({s[0] for s in steps}) == len(steps)
        assert {s[1] for s in steps} <= {"rule", "data", "inherits"}
