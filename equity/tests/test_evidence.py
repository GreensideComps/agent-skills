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


def test_d_c_screen_and_paper_books_are_labelled_exploratory_not_investable():
    """Owner decision D-C (2026-10-23): screen-1.0 and its paper books are unvalidated exploratory research."""
    cfg = evidence.load()
    for m in ("screen-1.0", "paper-1.0", "paper-1.1"):
        assert not evidence.may_drive_decisions(m, cfg)
        assert "not investable evidence" in cfg["methods"][m]["allowed_use"]
        b = evidence.banner(m, cfg=cfg)
        assert "unvalidated exploratory research: not investable evidence" in b and "not a recommendation" in b


def test_d_c_leaves_other_banners_byte_identical():
    """Review finding P30-7: val-1.0 and unknown methods keep the old wording exactly."""
    cfg = evidence.load()
    e = cfg["methods"]["val-1.0"]
    assert evidence.banner("val-1.0", cfg=cfg) == (
        f"> Evidence tier **E0** for `val-1.0` (**unvalidated: not a recommendation**). Allowed use: "
        f"{e['allowed_use']}. {e['evidence']}")
    assert evidence.banner("unknown-9.9", cfg=cfg) == (
        "> Evidence tier **E0** for `unknown-9.9` (**unvalidated: not a recommendation**). Allowed use: none recorded. ")
