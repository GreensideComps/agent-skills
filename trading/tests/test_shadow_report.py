import numpy as np
import pandas as pd
import pytest

from t212bot.shadow import COST, PriceBook, gem_nav, gem_signal, static_nav

# Runs past today: report.build starts shadows at the first order date, which in test_report_renders is "now".
IDX = pd.bdate_range("2024-01-01", max(pd.Timestamp("2026-10-13"), pd.Timestamp.today().normalize() + pd.Timedelta(days=7)))


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


def test_signal_nav_switches_to_cash_and_back():
    from t212bot.shadow import COST, PriceBook, signal_nav
    idx = pd.bdate_range("2026-01-01", periods=200)
    sig = pd.Series(100.0 + 0.1 * pd.RangeIndex(200).to_numpy(), index=idx)   # gentle uptrend
    sig.iloc[150:170] = 50.0          # trend breaks for 20 days
    etf = pd.Series(10.0, index=idx)
    etf.iloc[150:170] = 8.0           # the leveraged fund falls while the signal is off
    frames = {"QQQ": pd.DataFrame({"close": sig, "adjclose": sig}), "LQQ3.L": pd.DataFrame({"close": etf, "adjclose": etf})}
    for f in frames.values():
        f.attrs["currency"] = "GBP"
    b = PriceBook(loader=lambda s: frames[s])
    spec = {"symbol": "QQQ", "window": 100, "on_targets": {"LQQ3l_EQ": 1.0}, "off_targets": {}}
    nav, log = signal_nav(b, {"LQQ3l_EQ": "LQQ3.L"}, spec, idx[120].date(), 100.0)
    assert [x["hold"] for x in log] == ["on", "off", "on"]
    # the signal acts the day after the break, so the first down day is taken in full (10 -> 8),
    # then the shadow sits in cash and rebuys at 10; three trades pay COST each
    assert log[1]["date"] == idx[151].date().isoformat() and log[2]["date"] == idx[171].date().isoformat()
    assert nav.iloc[-1] == pytest.approx(80 * (1 - COST) ** 3, rel=1e-9)


def test_report_uses_latest_reconcile_record_per_order(tmp_path, cfg):
    from t212bot import report
    from t212bot.journal import Journal
    j = Journal(root=tmp_path)
    j.save_state({"inception": {"total_value_gbp": 100.0}})
    j.event("order_placed", ticker="VWRPl_EQ", quantity=0.3, order_id=1, reference={"price": 146.4})
    j.event("order_reconciled", order_id=1, ticker="VWRPl_EQ", status="FILLED", slippage_bps_vs_reference=986397.28)
    j.event("order_reconciled", order_id=1, ticker="VWRPl_EQ", status="FILLED", slippage_bps_vs_reference=-36.03)
    j.snapshot({"totalValue": 100.0, "cash": {"availableToTrade": 1.5}, "investments": {}}, [])
    cfg.shadow_portfolios = {}
    cfg.yahoo_symbols = {"VWRPl_EQ": "VWRP.L", "IWMOl_EQ": "VWRP.L"}
    md = report.render(report.build(j, cfg, book=book()))
    assert "-36.03" in md and "986397" not in md
