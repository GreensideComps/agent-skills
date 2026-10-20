"""pm-1.0: proposal-only portfolio manager (PM_SPEC.md). Every number here is synthetic."""
from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path

from office import pm, sectors

TODAY = dt.date(2026, 10, 20)
REG = [{"event": "register", "id": "T-PASS", "kind": "trial"}, {"event": "result", "id": "T-PASS", "verdict": "pass"},
       {"event": "register", "id": "T-FAIL", "kind": "trial"}, {"event": "result", "id": "T-FAIL", "verdict": "fail"},
       {"event": "register", "id": "D-1", "kind": "diagnostic"}, {"event": "result", "id": "D-1", "verdict": "pass"}]
LOOK = {"as_of": "2026-09-30", "source": "test fixture", "top_holdings": {"AAPL": 0.045},
        "sector_weights": {"Technology": 0.25, "Financials": 0.16, "Industrials": 0.11, "Health Care": 0.10,
                           "Consumer Discretionary": 0.11, "Consumer Staples": 0.06, "Energy": 0.04,
                           "Basic Materials": 0.04, "Telecommunications": 0.03, "Utilities": 0.03,
                           "Real Estate": 0.03}}


def strat(holdings, trials=("T-PASS",), owner="cmsg_x"):
    return {"strategies": [{"id": "S", "owner_decision": owner, "trials": list(trials), "holdings": holdings}]}


def run(cfg, look=LOOK, **kw):
    return pm.propose(eligible_cfg=cfg, trial_events=REG, look_cfg=look, today=TODAY, **kw)


def test_empty_config_is_100pct_vwrp_no_trade():
    r = run({"strategies": []}, look=None)
    assert r["verdict"] == "default" and r["targets"] == [{"ticker": "VWRP", "weight": 1.0,
                                                           "reason": "no strategy has passed the research gates"}]
    assert r["no_trade"] and not r["failed"] and r["review"]["status"] == "not applicable"
    assert any(f.startswith("unverifiable") for f in r["flags"])


def test_shipped_repo_config_gives_default():
    r = pm.from_repo(Path(__file__).resolve().parents[2], TODAY)
    assert r["verdict"] == "default" and r["no_trade"] and r["evidence"]["trials"]


def test_strategy_needs_owner_decision_and_passing_trials():
    h = [{"ticker": "X", "weight": 0.02, "sic": 2834}]
    for cfg, why in ((strat(h, owner="yes"), "owner decision"), (strat(h, trials=()), "cites no trial"),
                     (strat(h, trials=("T-FAIL",)), "verdict is fail"), (strat(h, trials=("NOPE",)), "not in"),
                     (strat(h, trials=("D-1",)), "diagnostic")):
        r = run(cfg)
        assert r["verdict"] == "default" and why in r["refused_strategies"][0]["reason"]


def test_accepted_book_shows_arithmetic():
    r = run(strat([{"ticker": "X", "weight": 0.05, "sic": 2834}, {"ticker": "Y", "weight": 0.05, "sic": 6022}]))
    assert r["verdict"] == "accepted" and not r["no_trade"]
    assert r["targets"][0] == {"ticker": "VWRP", "weight": 0.9, "reason": "core: the remainder"}
    hc = next(c for c in r["constraints"] if c["constraint"] == "sector_active:Health Care")
    assert abs(hc["value"] - (0.9 * 0.10 + 0.05 - 0.10)) < 1e-12 and hc["pass"]
    assert "classification mismatch" in " ".join(r["flags"])


def test_limits_reject_whole_candidate():
    over = [{"ticker": f"T{i}", "weight": 0.05, "sic": 3674} for i in range(5)]       # 25% outside, all tech
    r = run(strat(over))
    assert r["verdict"] == "rejected" and r["targets"][0]["weight"] == 1.0
    assert "outside_core" in r["failed"] and "sector_active:Information Technology" in r["failed"]
    assert "per_company:Z" in run(strat([{"ticker": "Z", "weight": 0.06, "sic": 2834}]))["failed"]


def test_sector_check_unverifiable_rejects():
    h = [{"ticker": "X", "weight": 0.02, "sic": 2834}]
    assert run(strat(h), look=None)["verdict"] == "rejected"
    r = run(strat([{"ticker": "Q", "weight": 0.02, "sic": None}]))
    assert r["verdict"] == "rejected" and any("unknown sector" in f for f in r["flags"])


def test_lookthrough_company_flag_and_stale_data():
    r = run(strat([{"ticker": "AAPL", "weight": 0.01, "sic": 3571}]))
    lt = next(c for c in r["constraints"] if c["constraint"] == "per_company_lookthrough:AAPL")
    assert not lt["enforced"] and lt["value"] > 0.05 and any("AAPL" in f for f in r["flags"])
    stale = dict(LOOK, as_of="2026-01-01", source=None)
    flags = pm.lookthrough(stale, TODAY)[1]
    assert any("days old" in f for f in flags) and any("no source" in f for f in flags)


def test_review_threshold():
    flat = [(f"2026-{m:02d}-28", 100.0, 100.0) for m in range(1, 4)]
    assert pm.review(flat)["status"] == "within threshold"
    bad = [("2025-01-31", 100.0, 100.0)] + [(f"2026-{m:02d}-28", 100.0, 100.0) for m in range(1, 13)] + \
          [("2027-01-31", 80.0, 100.0)]
    r = pm.review(bad)
    assert r["status"] == "review_threshold breached" and set(r["breached"]) == {"trailing_12m", "since_inception"}
    assert abs(r["since_inception"]["relative"] + 0.20) < 1e-12 and r["trailing_12m"]["from"] == "2026-01-28"
    assert pm.review(None)["status"] == "not applicable"


def test_sic_mapping():
    assert sectors.from_sic(2834) == "Health Care" and sectors.from_sic(3674) == "Information Technology"
    assert sectors.from_sic(6798) == "Real Estate" and sectors.from_sic(1311) == "Energy"
    assert sectors.from_sic(None) is None and sectors.from_sic(9999) is None
    assert set(sectors.ICB.values()) == set(sectors.SECTORS)


def test_pm_imports_no_broker_code():
    src = Path(pm.__file__).read_text() + Path(sectors.__file__).read_text()
    mods = {n.module or "" for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in mods if "t212" in m or "trading" in m or "orders" in m or "requests" in m}
