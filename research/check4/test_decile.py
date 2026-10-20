"""The PROPOSED Check 4 decile rule (owner approval pending): decile = 10 - floor((rank - 1) * 10 / n), rank in the
frozen engine's order (`edge_backtest.eligible`: score descending, then CIK ascending). Needs no frozen checkout.

    python3 -m pytest -q research/check4/test_decile.py
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reconstruct_holdings as rh  # noqa: E402

CHECK4 = HERE.parents[1] / "docs" / "edge" / "check4"


def test_deterministic_example_n_23():
    # ranks 1-3 -> 10, 4-5 -> 9, 6-7 -> 8, 8-10 -> 7, 11-12 -> 6, 13-14 -> 5, 15-17 -> 4, 18-19 -> 3, 20-21 -> 2, 22-23 -> 1
    assert [rh.decile(r, 23) for r in range(1, 24)] == [10, 10, 10, 9, 9, 8, 8, 7, 7, 7, 6, 6, 5, 5, 4, 4, 4, 3, 3, 2,
                                                       2, 1, 1]


@pytest.mark.parametrize("n", [10, 11, 99, 161, 250, 397])
def test_every_decile_is_used_and_sizes_differ_by_at_most_one(n):
    sizes = pd.Series([rh.decile(r, n) for r in range(1, n + 1)]).value_counts()
    assert sorted(sizes.index) == list(range(1, 11)) and sizes.max() - sizes.min() <= 1


def test_deciles_are_monotone_in_rank():
    for n in (10, 37, 250):
        d = [rh.decile(r, n) for r in range(1, n + 1)]
        assert all(a >= b for a, b in zip(d, d[1:]))


def test_ties_in_score_are_ordered_by_cik_as_the_engine_ranks_them():
    """Ties cannot share a rank: the engine's sort breaks them by CIK, so the decile of a tied name is fixed by its
    CIK. The frame's ranks must therefore follow (score desc, cik asc) exactly."""
    frame = pd.DataFrame({"cik": [5, 3, 9, 1], "score": [0.5, 0.5, 0.9, 0.1]})
    ranked = frame.sort_values(["score", "cik"], ascending=[False, True])
    assert ranked["cik"].tolist() == [9, 3, 5, 1]


@pytest.mark.parametrize("trial", ["H1", "S2A"])
def test_committed_frames_use_the_rule_on_every_row(trial):
    f = pd.read_csv(CHECK4 / f"frame_{trial}.csv")
    assert (f["decile"] == [rh.decile(r, n) for r, n in zip(f["rank"], f["n_eligible"])]).all()
    for _, g in f.groupby("decision_month"):
        assert sorted(g["rank"]) == list(range(1, len(g) + 1)) and (g["n_eligible"] == len(g)).all()
        g = g.sort_values("rank")
        key = list(zip(-g["score"], g["cik"]))
        assert key == sorted(key)  # rank order is (score desc, cik asc) in every month of both trials
