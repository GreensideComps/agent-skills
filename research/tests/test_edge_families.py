"""Owner decision D-B: the prior ETF family table, the extra multiple-testing count it gives, and the deflated
Sharpe wrapper that applies it (review findings P30-2, P30-3). The edge registry and `edge_registry.py` are only
read and must stay byte-identical."""
import hashlib
import json
import math
import random
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_dsr  # noqa: E402
import edge_families as fam  # noqa: E402
import edge_registry  # noqa: E402

RUN_2_REGISTRY_SHA256 = "de03d38b18a2d80b5c4d20f647c8ff35f5471157aba71fa99da6b550fb1217e6"
EDGE_REGISTRY_PY_SHA256_PREFIX = "129c0e2d2dbab626"
PINNED = {
    "E001": ["ALLOC", "MOM", "TREND"], "E002": ["MOM", "TREND"], "E003": ["MOM", "FACTOR"],
    "E004": ["FACTOR", "MOM"], "E005": ["MEANREV"], "E006": ["MOM", "VOLMGMT"], "E007": ["MOM", "TREND"],
    "E008": ["INTRADAY", "LEVERAGE"], "E009": ["TREND", "LEVERAGE"], "E010": ["INTRADAY", "LEVERAGE"],
    "E011": ["INTRADAY"], "E012": ["INTRADAY"], "E013": ["MOM", "FACTOR"], "E014": ["INTRADAY"],
    "E015": ["TREND", "VOLMGMT", "LEVERAGE"],
}
TABLE_SHA256 = "73bb110423138c3ab8c0a6ffa212578e091ac6d09a17cff5b779606ec265f0a9"


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise NetworkBlocked("network access attempted in an offline test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_table_matches_the_experiment_files():
    assert fam.validate() == []


def test_the_family_tags_and_the_table_are_pinned():
    """Editing a tag fails here until the pin is updated on purpose."""
    assert {e: r["families"] for e, r in fam.load()["experiments"].items()} == PINNED
    assert fam.table_sha256() == TABLE_SHA256


def test_every_experiment_that_names_momentum_carries_mom():
    for p in sorted(fam.EXPERIMENTS.glob("E*.json")):
        d = json.loads(p.read_text())
        text = " ".join(str(d.get(k, "")) for k in ("hypothesis", "data", "decision_detail")).lower()
        if "momentum" in text or "iwfm" in text or "prior_12" in text:
            assert "MOM" in fam.load()["experiments"][p.stem]["families"], p.stem


def test_documented_examples():
    assert fam.extra_n(["MOM"])["count"] == 81
    assert sorted(fam.extra_n(["MOM"])["experiments"]) == ["E001", "E002", "E003", "E004", "E006", "E007", "E013"]
    assert fam.extra_n(["MOM", "FACTOR"])["count"] == 81
    assert fam.extra_n(["FACTOR"])["count"] == 25
    assert fam.extra_n(["ALLOC", "MOM"])["count"] == 81


def test_an_experiment_sharing_several_families_counts_once():
    assert fam.extra_n(["ALLOC", "MOM", "TREND"])["experiments"]["E001"] == 36
    every = fam.extra_n(fam.load()["families"])
    assert every["count"] == 138 and len(every["experiments"]) == 15


def test_unrelated_trials_add_zero():
    assert fam.extra_n(["none"])["count"] == 0


@pytest.mark.parametrize("bad", [[], ["none", "MOM"], ["MOMENTUM"]])
def test_undeclared_or_unknown_families_are_refused(bad):
    with pytest.raises(ValueError):
        fam.extra_n(bad)


def test_a_changed_count_or_missing_basis_is_caught(tmp_path):
    t = fam.load()
    t["experiments"]["E013"]["configurations"] = 1
    t["experiments"]["E005"]["basis"] = ""
    p = tmp_path / "t.json"
    p.write_text(json.dumps(t))
    errs = fam.validate(p)
    assert any("E013" in e for e in errs) and any("E005: no basis" in e for e in errs)


def test_the_registry_and_its_count_are_untouched():
    assert hashlib.sha256(edge_registry.PATH.read_bytes()).hexdigest() == RUN_2_REGISTRY_SHA256
    assert edge_registry.n_trials(edge_registry.load()) == 102
    src = Path(edge_registry.__file__).read_bytes()
    assert hashlib.sha256(src).hexdigest().startswith(EDGE_REGISTRY_PY_SHA256_PREFIX)


# the wrapper (P30-3)
def _b5_v3_stats(events):
    return [(e["sr_monthly"], e["n_months"], e["stat"]) for e in events
            if e.get("event") == "result" and e.get("id", "").endswith("-V3")]


def test_with_no_extra_n_the_wrapper_equals_the_pinned_formula_exactly():
    events, sha = edge_registry.load(), fam.table_sha256()
    rng = random.Random(20261026)
    cases = [(sr, n, 0.0, 3.0, st) for sr, n, st in _b5_v3_stats(events)]
    stats = sorted({edge_registry.result_stat(e) for e in events if edge_registry.result_stat(e)})
    for _ in range(50):
        cases.append((rng.uniform(-0.3, 0.6), rng.randint(24, 240), rng.uniform(-1.5, 1.5), rng.uniform(2.0, 9.0),
                      rng.choice(stats)))
    assert len(cases) == 52
    for sr, n, sk, ku, st in cases:
        a = edge_registry.deflated_sharpe(sr, n, sk, ku, st, events)
        b = edge_dsr.deflated_sharpe_with_prior(sr, n, sk, ku, st, events, 0, sha)
        assert a == {k: b[k] for k in a}


def test_prior_trials_make_the_test_stricter():
    events, sha = edge_registry.load(), fam.table_sha256()
    for sr, n, st in _b5_v3_stats(events):
        base = edge_dsr.deflated_sharpe_with_prior(sr, n, 0.0, 3.0, st, events, 0, sha)
        more = edge_dsr.deflated_sharpe_with_prior(sr, n, 0.0, 3.0, st, events, 81, sha)
        assert more["n_trials"] == 183 and more["sr0"] > base["sr0"]
        if sr > base["sr0"]:
            assert more["dsr"] < base["dsr"]


def test_sr0_at_n_183_matches_a_hand_computation():
    events, sha = edge_registry.load(), fam.table_sha256()
    r = edge_dsr.deflated_sharpe_with_prior(0.2, 120, 0.0, 3.0, "portfolio_excess_vs_vwrp", events, 81, sha)
    n, g, nd = 183, 0.5772156649, __import__("statistics").NormalDist()
    want = math.sqrt(r["var_used"]) * ((1 - g) * nd.inv_cdf(1 - 1 / n) + g * nd.inv_cdf(1 - 1 / (n * math.e)))
    assert abs(r["sr0"] - want) < 1e-12


@pytest.mark.parametrize("bad", [-1, 1.5, True, "81"])
def test_bad_extra_n_is_refused(bad):
    with pytest.raises(ValueError):
        edge_dsr.deflated_sharpe_with_prior(0.2, 120, 0, 3, "x", edge_registry.load(), bad, fam.table_sha256())


def test_a_stale_table_hash_is_refused():
    with pytest.raises(ValueError):
        edge_dsr.deflated_sharpe_with_prior(0.2, 120, 0, 3, "x", edge_registry.load(), 81, "0" * 64)
