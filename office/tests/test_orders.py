"""Order state machine against a fake broker. No real broker exists in this package."""
import itertools

import pytest

from office import events as ev
from office.orders import BrokerRejected, BrokerUnknown, OrderManager, order_id, orders, paused


class FakeBroker:
    """Fills market orders at once unless told otherwise; can lose responses, reject, hang or misreport."""

    def __init__(self, clock):
        self.clock, self.ids = clock, itertools.count(1000)
        self.orders, self.pos = {}, {"VWRP": 0.0}
        self.lose_response = self.reject = self.lookup_fails = self.cancel_unknown = False
        self.fake_drift = 0.0
        self.hang = False
        self.submits = 0

    def submit_market(self, ticker, quantity):
        self.submits += 1
        if self.reject:
            raise BrokerRejected("quantity below minimum")
        if self.lose_response == "before":
            raise BrokerUnknown("connection reset before the request was sent")
        bid = next(self.ids)
        o = {"id": bid, "ticker": ticker, "quantity": quantity, "created": self.clock(), "status": "working",
             "filled": 0.0}
        self.orders[bid] = o
        if not self.hang:
            self._fill(o)
        if self.lose_response == "after":
            raise BrokerUnknown("read timed out")
        return {"id": bid, "status": o["status"]}

    def _fill(self, o):
        o.update(status="filled", filled=o["quantity"])
        self.pos[o["ticker"]] = self.pos.get(o["ticker"], 0.0) + o["quantity"]

    def get_order(self, bid):
        return dict(self.orders[bid]) if bid in self.orders else None

    def find_orders(self, ticker, since):
        if self.lookup_fails:
            raise BrokerUnknown("history endpoint 503")
        return [dict(o) for o in self.orders.values() if o["ticker"] == ticker and o["created"] >= since]

    def cancel(self, bid):
        if self.cancel_unknown:
            raise BrokerUnknown("cancel timed out")
        if self.orders[bid]["status"] == "working":
            self.orders[bid]["status"] = "cancelled"

    def position(self, ticker):
        return self.pos.get(ticker, 0.0) + self.fake_drift


@pytest.fixture
def om(make_store, clock):
    b = FakeBroker(clock)
    m = OrderManager(make_store("om"), b, clock=clock, sleep=clock.sleep, settle_s=120, poll_s=5, max_working_s=60)
    return m, b


def log(m):
    return ev.parse(m.s.sync())


def kinds(m, oid):
    return [e["kind"] for e in log(m) if e.get("order") == oid]


def test_normal_fill_records_intent_before_submission_and_reconciles(om):
    m, b = om
    assert m.place("dec-1", "VWRP", 0.05) == "filled"
    oid = order_id("dec-1")
    assert kinds(m, oid) == ["order_intent", "order_submitted", "order_filled", "order_reconciled"]
    assert b.pos["VWRP"] == pytest.approx(0.05)


def test_intent_is_on_the_remote_before_the_broker_is_called(om):
    m, b = om
    seen = []
    real = b.submit_market

    def spy(t, qty):
        seen.append([e["kind"] for e in ev.parse(m.s.sync())])
        return real(t, qty)
    b.submit_market = spy
    m.place("dec-x", "VWRP", 0.01)
    assert seen == [["order_intent"]]


def test_a_decision_key_is_used_once(om):
    m, b = om
    m.place("dec-1", "VWRP", 0.05)
    assert m.place("dec-1", "VWRP", 0.05).startswith("refused: decision key already used")
    assert b.submits == 1


def test_definite_rejection_is_terminal_and_not_retried(om):
    m, b = om
    b.reject = True
    assert m.place("dec-r", "VWRP", 0.00001) == "rejected"
    assert b.submits == 1 and b.pos["VWRP"] == 0.0


def test_lost_response_after_send_is_found_and_adopted_not_resubmitted(om):
    m, b = om
    b.lose_response = "after"
    assert m.place("dec-u", "VWRP", 0.05) == "filled"
    assert b.submits == 1  # never resubmitted
    assert "order_unknown" in kinds(m, order_id("dec-u")) and "order_adopted" in kinds(m, order_id("dec-u"))


def test_unknown_outcome_with_no_broker_record_pauses_and_alerts(om):
    m, b = om
    b.lose_response = "before"
    assert m.place("dec-n", "VWRP", 0.05) == "paused"
    assert b.submits == 1
    events = log(m)
    assert paused(events) and any(e["kind"] == "alert" and e["severity"] == "critical" for e in events)
    assert m.place("dec-next", "VWRP", 0.01).startswith("refused: trading paused")  # everything is blocked
    assert b.submits == 1


def test_two_matching_broker_orders_pause_rather_than_guess(om, clock):
    m, b = om
    b.orders[1] = {"id": 1, "ticker": "VWRP", "quantity": 0.05, "created": clock() + 1, "status": "filled",
                   "filled": 0.05}
    clock.t += 2
    b.lose_response = "before"
    b.orders[2] = {"id": 2, "ticker": "VWRP", "quantity": 0.05, "created": clock(), "status": "filled",
                   "filled": 0.05}
    assert m.place("dec-d", "VWRP", 0.05) == "paused"
    assert "match" in paused(log(m))


def test_failed_lookup_pauses(om):
    m, b = om
    b.lose_response, b.lookup_fails = "before", True
    assert m.place("dec-l", "VWRP", 0.05) == "paused"


def test_working_order_is_cancelled_after_the_limit(om):
    m, b = om
    b.hang = True
    assert m.place("dec-h", "VWRP", 0.05) == "cancelled"
    assert "order_cancel_requested" in kinds(m, order_id("dec-h")) and b.pos["VWRP"] == 0.0


def test_cancel_with_unknown_outcome_pauses(om):
    m, b = om
    b.hang, b.cancel_unknown = True, True
    assert m.place("dec-c", "VWRP", 0.05) == "paused"


def test_reconciliation_mismatch_pauses(om):
    m, b = om
    orig = b.position
    calls = []

    def drifting(t):
        calls.append(t)
        return orig(t) + (0.5 if len(calls) > 1 else 0.0)
    b.position = drifting
    assert m.place("dec-m", "VWRP", 0.05) == "paused"
    assert "reconciliation mismatch" in paused(log(m))


def test_one_unfinished_order_per_ticker(om, clock):
    m, b = om
    m.s.transact(lambda e: [{"kind": "order_intent", "order": "o-x", "decision_key": "k", "ticker": "VWRP",
                             "quantity": 1.0, "position_before": 0.0, "intent_at": clock()}])
    assert m.place("dec-2", "VWRP", 0.05).startswith("refused: another VWRP order")


def test_crash_after_intent_is_recovered_on_restart_without_resubmitting(om, clock):
    m, b = om
    # the process wrote the intent, the order reached the broker, then the process died
    bid = b.submit_market("VWRP", 0.05)["id"]
    b.submits = 0
    m.s.transact(lambda e: [{"kind": "order_intent", "order": "o-crash", "decision_key": "k2", "ticker": "VWRP",
                             "quantity": 0.05, "position_before": 0.0, "intent_at": clock() - 1}])
    assert m.recover_all() == {"o-crash": "filled"}
    assert b.submits == 0
    assert orders(log(m))["o-crash"]["broker_id"] == bid


def test_resume_needs_an_owner_message(om):
    m, b = om
    b.lose_response = "before"
    m.place("dec-p", "VWRP", 0.05)
    with pytest.raises(PermissionError):
        m.resume("please")
    assert m.recover_all() == {"*": "paused: " + paused(log(m))}
    m.resume("cmsg_owner")
    assert paused(log(m)) is None
