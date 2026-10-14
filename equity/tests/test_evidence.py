"""Stage 0 (STRATEGY_V2): evidence tiers label unvalidated outputs."""
from equity import evidence


def test_current_methods_cannot_drive_decisions():
    cfg = evidence.load()
    for m in ("screen-1.0", "val-1.0", "paper-1.0"):
        assert not evidence.may_drive_decisions(m, cfg)
    assert evidence.tier("unknown-9.9", cfg) == "E0"


def test_banner_says_not_a_recommendation():
    b = evidence.banner("screen-1.0", "val-1.0")
    assert "E1" in b and "E0" in b and b.count("not a recommendation") == 2


def test_config_tiers_are_defined():
    cfg = evidence.load()
    for m, e in cfg["methods"].items():
        assert e["tier"] in cfg["tiers"], m
        assert e["evidence"] and e["allowed_use"], m
