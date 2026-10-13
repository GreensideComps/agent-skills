import numpy as np
import pandas as pd
import pytest

from t212bot.shadow import COST, PriceBook, gem_nav, gem_signal, static_nav

IDX = pd.bdate_range("2024-01-01", "2026-10-13")


def series(annual_growth, currency="GBP"):
    days = np.arange(len(IDX))
    px = 100 * (1 + annual_growth) ** (days / 261)
    df = pd.DataFrame({"close": px, "adjclose": px}, index=IDX)
    df.attrs["currency"] = currency
    return df


def book(us=0.20, intl=0.10, cash=0.04, bond=0.02):
    data = {"VUAG.L": series(us), "VGTSX": series(intl, "USD"), "ERNS.L": series(cash), "VAGS.L": series(bond),
            "VXUS.L": series(intl), "VWRP.L": series(0.12),
            "GBPUSD=X": pd.DataFrame({"close": 1.0, "adjclose": 1.0}, index=IDX)}
    return PriceBook(loader=lambda s: data[s])


def test_gem_signal_picks_winner_or_bonds():
    assert gem_signal(book(us=0.20, intl=0.10), pd.Timestamp("2026-09-30")) == "US"
    assert gem_signal(book(us=0.05, intl=0.15), pd.Timestamp("2026-09-30")) == "INTL"
    assert gem_signal(book(us=0.01, intl=0.00, cash=0.04), pd.Timestamp("2026-09-30")) == "BOND"


def test_static_nav_applies_entry_cost_and_tracks_price():
    b = book()
    nav = static_nav(b, {"VWRPl_EQ": "VWRP.L"}, {"VWRPl_EQ": 1.0}, pd.Timestamp("2026-01-02").date(), 100.0)
    assert nav.iloc[0] == pytest.approx(100 * (1 - COST))
    px = b.gbp_tr("VWRP.L")
    assert nav.iloc[-1] / nav.iloc[0] == pytest.approx(px.iloc[-1] / px.loc[nav.index[0]])


def test_gem_nav_switches_monthly_with_costs():
    b = book(us=0.20, intl=0.10)
    nav, log = gem_nav(b, {"US": "VUAG.L", "INTL": "VXUS.L", "BOND": "VAGS.L"}, pd.Timestamp("2026-06-01").date(), 100.0)
    assert log[0]["hold"] == "US" and len(log) == 1          # constant ranking: no churn
    assert nav.iloc[0] == pytest.approx(100 * (1 - COST))


def test_report_renders(tmp_path, cfg):
    from t212bot import report
    from t212bot.journal import Journal
    j = Journal(root=tmp_path)
    j.save_state({"inception": {"total_value_gbp": 100.0}})
    j.event("order_placed", ticker="VWRPl_EQ", quantity=0.3, order_id=1, reference={"price": 146.4})
    j.snapshot({"totalValue": 100.0, "cash": {"availableToTrade": 1.5}, "investments": {}}, [])
    cfg.shadow_portfolios = {"A_benchmark_vwrp": {"type": "static", "targets": {"VWRPl_EQ": 1.0}}}
    cfg.yahoo_symbols = {"VWRPl_EQ": "VWRP.L", "IWMOl_EQ": "VWRP.L"}
    data = report.build(j, cfg, book=book())
    md = report.render(data)
    assert "Value since inception" in md and "A_benchmark_vwrp" in md and "meaningful" in md
