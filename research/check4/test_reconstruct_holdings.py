"""The reconstruction must select exactly what the frozen run-2 engine would have selected.

Synthetic data only: these tests run the frozen `edge_backtest.run` on made-up worlds (its synthetic NAV is ignored)
and check that `reconstruct_holdings.replay` gives the same names at every rebalance. Real B5 data is never read here.

Needs a clean checkout of run 2's commit a4a07d7, named by the B5_FROZEN environment variable:
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
if not (FROZEN / "research" / "edge_backtest.py").exists():
    raise RuntimeError("set B5_FROZEN to a checkout of a4a07d7 (run 2's commit)")
sys.path.insert(0, str(FROZEN / "research"))

import reconstruct_holdings as rh  # noqa: E402
import edge_backtest as bt  # noqa: E402
import edge_rules  # noqa: E402
import edge_split  # noqa: E402


def world(seed, n_cos=60, n_months=40, p_missing=0.02, p_absent=0.01, p_noscore=0.05, groups=6):
    """A random world with everything the selection reacts to: ties-free scores that persist, missing and invalid
    execution prices (exits and skipped entries), absent rows, unscored rows, quality failures and few groups so
    the sector cap binds."""
    rng = np.random.default_rng(seed)
    months = list(pd.date_range("2015-01-31", periods=n_months, freq="ME"))
    base = rng.standard_normal(n_cos)
    pan, ex = [], []
    px = 50 * np.ones(n_cos)
    for i, m in enumerate(months):
        base = 0.8 * base + 0.6 * rng.standard_normal(n_cos)
        px = px * (1 + 0.05 * rng.standard_normal(n_cos))
        for c in range(n_cos):
            noscore = rng.random() < p_noscore
            pan.append({"cik": c, "month": m, "score": None if noscore else float(base[c]),
                        "band": "large" if rng.random() > 0.03 else "mid", "quality_ok": bool(rng.random() > 0.03),
                        "group": f"g{c % groups}", "close_raw": 50.0 if rng.random() > 0.02 else 0.5})
            r = rng.random()
            if r < p_absent:
                continue
            status = "missing_exec" if r < p_absent + p_missing else ("stale_month_end" if r < 0.06 else "ok")
            ex.append({"cik": c, "ticker": f"T{c}", "month": m.date().isoformat(), "me_date": m.date().isoformat(),
                       "me_adjclose": float(px[c]), "exec_date": (m + pd.offsets.BDay(1)).date().isoformat(),
                       "exec_adjclose": float("nan") if status == "missing_exec" else float(px[c]),
                       "exec_close": float(px[c]), "status": status})
    fx = pd.Series(1.25, index=pd.bdate_range(months[0] - pd.Timedelta(days=10), months[-1] + pd.Timedelta(days=10)))
    return months, pd.DataFrame(pan), pd.DataFrame(ex), fx


def b5_like(rebalance, n=8, cap=2):
    return bt.Config(n=n, weighting="equal", rebalance_every=rebalance, buffer=2.0, sector_cap=cap, bands=("large",),
                     min_price=1.0, cost_mult=1.0, missing_return=edge_rules.DEFAULT_MISSING_RETURN,
                     convention=edge_rules.DEFAULT_CONVENTION, selection="top_n")


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("rebalance,starts", [(3, ("2015-01-31", "2015-02-28", "2015-03-31")),
                                              (12, ("2015-01-31", "2015-06-30"))])
def test_replay_selects_exactly_what_the_frozen_engine_holds(seed, rebalance, starts):
    months, panel, ex, fx = world(seed)
    cfg = b5_like(rebalance)
    for s in starts:
        engine = bt.run(panel, ex, fx, cfg, start=s, end=months[-2])
        rep = rh.replay(bt, edge_rules, edge_split, panel, ex, cfg, s, months[-2])
        assert sorted(rep) == sorted(engine.holdings)
        for m, r in rep.items():
            assert sorted(r["chosen"]) == sorted(engine.holdings[m]), (seed, s, m)
        exits = sorted((e["date"], e["cik"]) for e in engine.log if e["event"] == "exit")
        rexits = sorted((e["date"], e["cik"]) for r in rep.values() for e in r["events"] if e["event"] == "exit")
        # exits after the last rebalance are not attached to a decision in the replay
        last = max(rep[m]["trade_date"] for m in rep)
        assert rexits == [x for x in exits if x[0] <= last]
        for kind in ("skipped_entry", "skipped_cap", "short", "all_cash"):
            a = sorted((str(e["date"]), str(e.get("cik"))) for e in engine.log if e["event"] == kind)
            b = sorted((str(e["date"]), str(e.get("cik"))) for r in rep.values() for e in r["events"] if e["event"] == kind)
            assert a == b, kind


def test_the_worlds_exercise_exits_skips_caps_and_buffers():
    """Guard against a vacuous equivalence test: the synthetic worlds must contain each behaviour."""
    seen = {"exit": 0, "skipped_entry": 0, "skipped_cap": 0, "buffer_kept": 0}
    for seed in range(12):
        months, panel, ex, fx = world(seed)
        cfg = b5_like(3)
        rep = rh.replay(bt, edge_rules, edge_split, panel, ex, cfg, "2015-01-31", months[-2])
        prev = None
        for m in sorted(rep):
            for e in rep[m]["events"]:
                if e["event"] in seen:
                    seen[e["event"]] += 1
            rank = dict(zip(rep[m]["ranked"]["cik"], rep[m]["ranked"]["rank"]))
            if prev is not None:
                seen["buffer_kept"] += sum(1 for c in rep[m]["chosen"] if c in prev and rank[c] > cfg.n)
            prev = set(rep[m]["chosen"])
    assert all(v > 0 for v in seen.values()), seen


def test_price_missing_matches_the_frozen_holding_return_status():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2015-02-02", periods=30, freq="MS")
    for _ in range(300):
        vals = 50 * np.exp(np.cumsum(0.05 * rng.standard_normal(len(idx))))
        s = pd.Series(vals, index=idx)
        for j in rng.choice(len(idx), size=rng.integers(0, 4), replace=False):
            s.iloc[j] = rng.choice([np.nan, 0.0, -1.0])
        s = s.drop(s.index[rng.choice(len(idx), size=rng.integers(0, 3), replace=False)], errors="ignore")
        valid = [t for t in s.index if s[t] > 0]
        if not valid:
            continue
        t0 = valid[rng.integers(0, len(valid))]
        t1 = idx[rng.integers(0, len(idx))]
        if t1 <= t0:
            continue
        assert rh.price_missing(s, t0, t1) == (edge_rules.holding_return(s, t0, t1)[1] == "missing")


def test_decile_top_is_ten_bottom_is_one_and_sizes_differ_by_at_most_one():
    for n in (10, 37, 200, 451):
        d = [rh.decile(r, n) for r in range(1, n + 1)]
        assert d[0] == 10 and d[-1] == 1
        sizes = pd.Series(d).value_counts()
        assert sizes.max() - sizes.min() <= 1


def test_verify_frozen_refuses_another_commit(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "x"], check=True)
    with pytest.raises(SystemExit, match="not run 2's commit"):
        rh.verify_frozen(tmp_path)
