from datetime import datetime, timedelta, timezone

import pytest

from conftest import NOW, exchanges_for
from t212bot.config import SafetyError
from t212bot.journal import Journal
from t212bot.market import Quote, YahooQuotes, check_against_t212, check_fresh, session_window, to_gbp, tradable_now


def test_session_window_and_buffers():
    ex = exchanges_for(NOW)
    assert session_window(ex, 70, NOW)[0].hour == 7
    assert tradable_now(ex, 70, NOW, 15, 15)[0]
    assert not tradable_now(ex, 70, NOW.replace(hour=7, minute=5), 15, 15)[0]      # just opened
    assert not tradable_now(ex, 70, NOW.replace(hour=15, minute=20), 15, 15)[0]    # about to close
    assert tradable_now(ex, 70, NOW.replace(hour=18), 15, 15) == (False, "market closed")
    with pytest.raises(SafetyError):
        session_window(ex, 999, NOW)


def test_quote_checks():
    q = Quote("X", 100.0, "GBP", NOW - timedelta(hours=3), "t")
    with pytest.raises(SafetyError):
        check_fresh(q, NOW)
    check_fresh(Quote("X", 100.0, "GBP", NOW - timedelta(minutes=20), "t"), NOW)
    check_against_t212(q, 101.0, 0.03)
    with pytest.raises(SafetyError):
        check_against_t212(q, 110.0, 0.03)
    assert to_gbp(132.37, "USD", 1.3237) == pytest.approx(100.0)
    with pytest.raises(SafetyError):
        to_gbp(1, "EUR", 1.0)


def test_yahoo_parser_converts_pence():
    payload = {"chart": {"result": [{"meta": {"regularMarketPrice": 6140.0, "currency": "GBp",
                                              "regularMarketTime": int(NOW.timestamp())}}]}}
    q = YahooQuotes(fetch=lambda url: payload).quote("SGLN.L")
    assert q.price == 61.40 and q.currency == "GBP" and q.as_of == NOW


def test_journal_roundtrip(tmp_path):
    j = Journal(root=tmp_path, clock=lambda: NOW)
    j.event("plan", x=1)
    j.event("order_placed", order_id=5)
    assert [e["kind"] for e in j.events()] == ["plan", "order_placed"]
    assert j.events("order_placed")[0]["order_id"] == 5
    j.snapshot({"totalValue": 100, "cash": {"availableToTrade": 100}, "investments": {}}, [])
    j.snapshot({"totalValue": 101, "cash": {"availableToTrade": 1}, "investments": {"currentValue": 100}},
               [{"instrument": {"ticker": "VWRPl_EQ"}, "quantity": 0.5}])
    rows = j.snapshots()
    assert len(rows) == 2 and rows[1]["total_value_gbp"] == "101"
    j.save_state({"a": 1})
    assert j.load_state() == {"a": 1}
