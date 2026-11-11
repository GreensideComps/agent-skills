"""Research gate v3 (research/gate.py, GATE_V3.md): rules, error rates by simulation, and power."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gate  # noqa: E402
import stats  # noqa: E402

B = gate.Batch("G-TEST", ("a", "b", "c"), ("1963-07", "1999-12"), ("2000-01", "2022-12"))


def months(a="1963-07", b="2022-12"):
    y, m, out = int(a[:4]), int(a[5:]), []
    while f"{y}-{m:02d}" <= b:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def series(ann, te=0.10, seed=0, a="1963-07", b="2022-12"):
    r = random.Random(seed)
    mu, sd = ann / 12, te / 12 ** 0.5
    ex = {m: r.gauss(mu, sd) for m in months(a, b)}
    return {"excess": ex, "costs_x2": {m: v - 0.0005 for m, v in ex.items()}, "lag1": dict(ex)}


def test_batch_rules():
    assert B.problems() == []
    bad = [gate.Batch("x", tuple("abcdefghijk"), B.discovery, B.confirmation),                # 11 configs
           gate.Batch("x", ("a", "a"), B.discovery, B.confirmation),
           gate.Batch("x", ("a",), ("2000-01", "2010-12"), ("2011-01", "2023-06")),               # holdout
           gate.Batch("x", ("a",), ("2000-01", "2012-12"), ("2010-01", "2022-12")),               # overlap
           gate.Batch("x", ("a",), ("2000-01", "2001-12"), ("2011-01", "2022-12")),               # too short
           gate.Batch("x", ("a",), ("2000-13", "2010-12"), ("2011-01", "2022-12")),
           gate.Batch("x", ("a",), B.discovery, B.confirmation, q=0.5)]
    for b in bad:
        assert b.problems(), b
    with pytest.raises(ValueError, match="holdout"):
        gate.verdict(bad[2], {"a": series(0.0)})


def test_windows_accept_both_month_spellings_and_slice_exactly():
    s = {"2000-01": 1.0, "200002": 2.0, "2000-03": 3.0}
    assert gate.window(s, ("2000-02", "2000-03")) == [2.0, 3.0]
    assert gate.months_between("1963-07", "1999-12") == 438


def test_every_declared_configuration_must_be_scored():
    with pytest.raises(ValueError, match="every declared configuration"):
        gate.discovery(B, {"a": 0.01, "b": 0.2})
    with pytest.raises(ValueError, match="undeclared"):
        gate.discovery(B, {"a": 0.01, "b": 0.2, "c": 0.3, "d": 0.0})


def test_a_strong_edge_passes_and_noise_does_not():
    v = gate.verdict(B, {"a": series(0.09, seed=1), "b": series(0.0, seed=2), "c": series(0.0, seed=3)})
    assert v["passed"] == ["a"] and v["results"]["a"]["checks"]["confirmed"]
    assert not v["results"]["b"]["pass"] and not v["results"]["c"]["pass"]


def test_stage_two_never_reads_a_configuration_stage_one_dropped():
    s = series(0.0, seed=4)
    s["excess"] = {m: (-0.01 if m < "2000-01" else 0.05) for m in s["excess"]}   # bad then brilliant
    v = gate.verdict(gate.Batch("x", ("a",), B.discovery, B.confirmation), {"a": s})
    assert v["discovered"] == [] and v["results"]["a"]["pass"] is False and "checks" not in v["results"]["a"]


def test_stress_checks_can_veto_a_confirmed_result():
    s = series(0.09, seed=1)
    s["costs_x2"] = {m: v - 0.02 for m, v in s["excess"].items()}
    v = gate.verdict(gate.Batch("x", ("a",), B.discovery, B.confirmation), {"a": s})
    r = v["results"]["a"]
    assert r["checks"]["confirmed"] and not r["checks"]["costs_x2"] and not r["pass"]


def test_false_pass_rate_under_no_edge_is_within_the_bound():
    """2,000 batches of three pure-noise configurations: the share of configurations passing must sit near or below
    q/k x alpha, far below what the old t >= 2 screen let through."""
    r, passed, total = random.Random(7), 0, 0
    for i in range(2000):
        cfg = {c: series(0.0, seed=r.randrange(10 ** 9), a="1990-01", b="2022-12") for c in ("a", "b", "c")}
        v = gate.verdict(gate.Batch("n", ("a", "b", "c"), ("1990-01", "2006-12"), ("2007-01", "2022-12")), cfg)
        passed += len(v["passed"])
        total += 3
    rate = passed / total
    bound = gate.power(0, 0.1, 1, 1, k=3)["false_pass_per_config"]           # 0.10/3 x 0.05 = 0.17%
    assert rate <= 3 * bound                                                  # sampling noise allowance
    assert rate < 0.01


def test_power_formula_matches_simulation_for_a_real_edge():
    """One real 5%/yr configuration among three noise ones, 1963-1999 discovery, 2000-2022 confirmation."""
    r, hits, n = random.Random(11), 0, 400
    for _ in range(n):
        cfg = {"a": series(0.05, seed=r.randrange(10 ** 9))}
        cfg.update({c: series(0.0, seed=r.randrange(10 ** 9)) for c in ("b", "c")})
        hits += "a" in gate.verdict(B, cfg)["passed"]
    p = gate.power(0.05, 0.10, 438, 276, k=3)["p_pass"]
    assert abs(hits / n - p) < 0.12 and hits / n >= p - 0.12                  # the formula is the conservative case


def test_power_is_far_above_the_old_gate_for_the_same_edge():
    old = stats.power(0.05 / 0.10 * 30 ** 0.5, stats.dsr_bar_t(486))          # 5%/yr on 30 years, old bar
    new = gate.power(0.05, 0.10, 240, 120, k=1)["p_pass"]                     # same 30 years split 20 + 10
    assert old < 0.03 and new > 0.3
    assert "RUN" in gate.power_line(0.05, 0.10, 438, 276, k=3)
    assert "REDESIGN" in gate.power_line(0.03, 0.10, 60, 36, k=3)
