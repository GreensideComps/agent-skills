"""Synthetic inputs for the sample daily report (EXAMPLE DATA - not the real account).

The account, orders, journal and market figures below are invented to exercise
every report section (deposits, a withdrawal, a sell, fees, a dividend, a
rejected order attempt). The research section uses the real experiment
registry because it is historical research, not account data.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .intel import Src


def sample_inputs(now: datetime) -> dict:
    t = lambda d, h=9: (now - timedelta(days=d)).replace(hour=h, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    at = now.isoformat(timespec="seconds")
    summary = {"id": 0, "currency": "GBP", "totalValue": 140.99,
               "cash": {"availableToTrade": 1.55, "reservedForOrders": 0, "inPies": 0},
               "investments": {"currentValue": 139.44, "totalCost": 129.40, "realizedProfitLoss": 0.72, "unrealizedProfitLoss": 10.04}}
    positions = [
        {"instrument": {"ticker": "VWRPl_EQ", "name": "Vanguard FTSE All-World (Acc)", "currency": "GBP"}, "quantity": 0.4612,
         "currentPrice": 151.20, "quantityAvailableForTrading": 0.4612,
         "walletImpact": {"currency": "GBP", "totalCost": 65.10, "currentValue": 69.73, "unrealizedProfitLoss": 4.63}},
        {"instrument": {"ticker": "IWMOl_EQ", "name": "iShares Edge MSCI World Momentum (Acc)", "currency": "USD"}, "quantity": 0.7350,
         "currentPrice": 125.60, "quantityAvailableForTrading": 0.7350,
         "walletImpact": {"currency": "GBP", "totalCost": 64.30, "currentValue": 69.71, "unrealizedProfitLoss": 5.41}},
    ]
    orders = [
        {"order": {"id": 9001, "ticker": "VWRPl_EQ", "side": "BUY", "type": "MARKET", "status": "FILLED", "quantity": 0.3400, "filledQuantity": 0.3400,
                   "createdAt": t(120), "initiatedFrom": "API"},
         "fill": {"quantity": 0.3400, "price": 140.00, "filledAt": t(120), "walletImpact": {"netValue": 47.60, "taxes": []}}},
        {"order": {"id": 9002, "ticker": "IWMOl_EQ", "side": "BUY", "type": "MARKET", "status": "FILLED", "quantity": 0.5600, "filledQuantity": 0.5600,
                   "createdAt": t(120), "initiatedFrom": "API"},
         "fill": {"quantity": 0.5600, "price": 112.00, "filledAt": t(120),
                  "walletImpact": {"netValue": 48.17, "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": -0.07}]}}},
        {"order": {"id": 9003, "ticker": "VWRPl_EQ", "side": "BUY", "type": "MARKET", "status": "FILLED", "quantity": 0.1212, "filledQuantity": 0.1212,
                   "createdAt": t(40), "initiatedFrom": "API"},
         "fill": {"quantity": 0.1212, "price": 145.00, "filledAt": t(40), "walletImpact": {"netValue": 17.57, "taxes": []}}},
        {"order": {"id": 9004, "ticker": "IWMOl_EQ", "side": "BUY", "type": "MARKET", "status": "FILLED", "quantity": 0.2750, "filledQuantity": 0.2750,
                   "createdAt": t(40), "initiatedFrom": "API"},
         "fill": {"quantity": 0.2750, "price": 120.00, "filledAt": t(40),
                  "walletImpact": {"netValue": 24.94, "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": -0.04}]}}},
        {"order": {"id": 9005, "ticker": "IWMOl_EQ", "side": "SELL", "type": "MARKET", "status": "FILLED", "quantity": -0.1000, "filledQuantity": -0.1000,
                   "createdAt": t(0, 8), "initiatedFrom": "API"},
         "fill": {"quantity": -0.1000, "price": 125.10, "filledAt": t(0, 8),
                  "walletImpact": {"netValue": 9.48, "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": -0.01}]}}},
    ]
    transactions = [
        {"type": "DEPOSIT", "amount": 100.0, "currency": "GBP", "dateTime": t(121), "reference": "ex-1"},
        {"type": "DEPOSIT", "amount": 50.0, "currency": "GBP", "dateTime": t(41), "reference": "ex-2"},
        {"type": "WITHDRAW", "amount": -20.0, "currency": "GBP", "dateTime": t(10), "reference": "ex-3"},
    ]
    dividends = [{"type": "ORDINARY", "amount": 0.35, "ticker": "VWRPl_EQ", "paidOn": t(30)}]
    acct = {k: Src(True, v, None, at) for k, v in
            {"summary": summary, "positions": positions, "pending": [], "orders": orders, "transactions": transactions, "dividends": dividends}.items()}
    snaps = []
    vals = [(121, 100.0), (90, 103.4), (60, 98.9), (41, 151.2), (20, 158.0), (10, 141.0), (1, 141.9)]
    for d, v in vals:
        snaps.append({"ts_utc": t(d, 10).replace("Z", "+00:00"), "total_value_gbp": str(v)})
    events = [
        {"ts_utc": t(0, 8).replace("Z", "+00:00"), "run_id": "ex-run", "kind": "run_start"},
        {"ts_utc": t(0, 8).replace("Z", "+00:00"), "run_id": "ex-run", "kind": "plan", "reasons": ["IWMOl_EQ drift +5.6% beyond ±5% band"]},
        {"ts_utc": t(0, 8).replace("Z", "+00:00"), "run_id": "ex-run", "kind": "order_rejected", "ticker": "VWRPl_EQ", "quantity": 0.07,
         "body": "insufficient-free-for-stocks-buy (retried with fresh cash)"},
        {"ts_utc": t(0, 8).replace("Z", "+00:00"), "run_id": "ex-run", "kind": "order_placed", "ticker": "IWMOl_EQ", "quantity": -0.1, "reason": "reduce to target"},
        {"ts_utc": t(0, 8).replace("Z", "+00:00"), "run_id": "ex-run", "kind": "run_end"},
    ]
    market = {"shadow": {"inception": (now - timedelta(days=121)).date().isoformat(), "capital": 100.0,
                         "portfolios": {"A_benchmark_vwrp": {"value": 108.10, "return": 0.081, "as_of": (now - timedelta(days=1)).date().isoformat()},
                                        "C_gem12": {"value": 106.70, "return": 0.067, "as_of": (now - timedelta(days=1)).date().isoformat()},
                                        "B_live_rules_at_close": {"value": 109.30, "return": 0.093, "as_of": (now - timedelta(days=1)).date().isoformat()}}},
              "price_data_last_date": (now - timedelta(days=1)).date().isoformat(),
              "risk": {"est_annual_vol": 0.142, "est_daily_vol": 0.0089, "est_var95_1d_pct": 0.0147, "vol_window_days": 252,
                       "estimate_basis": "EXAMPLE values"}}
    prev = {"meta": {"report_date": (now - timedelta(days=1)).date().isoformat()}, "reconciliation_ok": True,
            "account": {"total_value": 141.90, "holdings": [{"ticker": "VWRPl_EQ", "weight": 0.47}, {"ticker": "IWMOl_EQ", "weight": 0.51}]}}
    delivery = {"report_date": (now - timedelta(days=1)).date().isoformat(), "status": "sent", "provider": "resend", "detail": "accepted by provider"}
    return {"acct": acct, "snaps": snaps, "events": events, "market": market, "prev": prev, "delivery": delivery}
