"""Order state machine and recovery for broker execution (M1: specification and tests only).

Nothing in this module talks to a real broker. It drives an object implementing `Broker`; M1 ships no adapter for
Trading 212, so there is no path from here to any account. A demo adapter is a later, separately approved step.

States of one order (each transition is an event in the log, written before the next broker call):

    intent ──submit──> submitted ──poll──> working ──poll──> filled | cancelled | rejected
       │                  │                   └─(too long)─> cancel_requested ──poll──> cancelled | filled
       │                  └─ rejected (definite broker refusal, terminal)
       └─ unknown (no definite answer: timeout, connection error, 5xx, or a crash after the intent was recorded)
              └─recover──> exactly one matching broker order found ──> adopted, then polled as above
                         └─ none found after the settle window, several found, or lookups failing ──> PAUSED

Rules:
* The intent (decision key, ticker, signed quantity, position before) is recorded and pushed before submission. A
  decision key can be used once; a second intent with the same key is refused.
* An order with an unknown outcome is never resubmitted. It is resolved only by finding the broker's own record of
  it. If that cannot be done safely, trading is paused for everything and an alert event is written.
* While paused, every new intent is refused. Only an owner's resume event (with the owner's message id) un-pauses.
* After a terminal state, the broker position must equal position before + filled quantity (within tolerance);
  otherwise trading is paused (reconciliation mismatch).
* At most one non-terminal order per ticker.
"""
from __future__ import annotations

import hashlib
import time
from typing import Protocol

from .store import GitStore

TERMINAL = {"filled", "cancelled", "rejected"}
FINAL = TERMINAL | {"reconciled"}


class BrokerRejected(Exception):
    """The broker definitely refused the order (it was never live)."""


class BrokerUnknown(Exception):
    """No definite answer: the order may or may not exist."""


class Broker(Protocol):
    def submit_market(self, ticker: str, quantity: float) -> dict: ...  # {"id", "status"}; raises above
    def get_order(self, broker_id) -> dict | None: ...                  # {"id", "status", "filled"} or None
    def find_orders(self, ticker: str, since: float) -> list[dict]: ... # pending + history since `since`
    def cancel(self, broker_id) -> None: ...
    def position(self, ticker: str) -> float: ...


def order_id(decision_key: str) -> str:
    return "o-" + hashlib.sha256(decision_key.encode()).hexdigest()[:20]


def orders(events: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for e in events:
        o = e.get("order")
        if e["kind"] == "order_intent":
            out[o] = {"key": e["decision_key"], "ticker": e["ticker"], "quantity": e["quantity"],
                      "before": e["position_before"], "at": e["intent_at"], "state": "intent", "broker_id": None,
                      "filled": 0.0}
        elif o in out and e["kind"].startswith("order_"):
            s = out[o]
            s["state"] = e.get("state", s["state"])
            s["broker_id"] = e.get("broker_id", s["broker_id"])
            s["filled"] = e.get("filled", s["filled"])
    return out


def paused(events: list[dict]) -> str | None:
    reason = None
    for e in events:
        if e["kind"] == "trading_paused":
            reason = e["reason"]
        elif e["kind"] == "trading_resumed":
            reason = None
    return reason


class OrderManager:
    def __init__(self, store: GitStore, broker: Broker, clock=time.time, sleep=time.sleep, settle_s: float = 120.0,
                 poll_s: float = 5.0, max_working_s: float = 60.0, tolerance: float = 1e-6):
        self.s, self.b, self.clock, self.sleep = store, broker, clock, sleep
        self.settle_s, self.poll_s, self.max_working_s, self.tol = settle_s, poll_s, max_working_s, tolerance

    # ---------- log helpers ----------
    def _record(self, order: str, state: str, **kw) -> None:
        self.s.transact(lambda ev: [{"kind": "order_" + state, "order": order, "state": state, **kw}])

    def pause(self, reason: str, order: str | None = None) -> str:
        self.s.transact(lambda ev: [{"kind": "trading_paused", "reason": reason, "order": order},
                                    {"kind": "alert", "severity": "critical", "message": reason, "order": order}])
        return "paused"

    def resume(self, owner_message: str) -> None:
        if not owner_message.startswith("cmsg_"):
            raise PermissionError("resuming needs the owner's message id")
        self.s.transact(lambda ev: [{"kind": "trading_resumed", "owner_message": owner_message}])

    # ---------- the state machine ----------
    def place(self, decision_key: str, ticker: str, quantity: float) -> str:
        """Run one order to a final answer. Returns its terminal state, 'refused: ...', or 'paused'."""
        oid, refused = order_id(decision_key), []
        before = self.b.position(ticker)

        def intent(ev):
            why = paused(ev)
            st = orders(ev)
            if why:
                refused.append(f"trading paused: {why}")
            elif oid in st:
                refused.append("decision key already used")
            elif any(o["ticker"] == ticker and o["state"] not in FINAL for o in st.values()):
                refused.append(f"another {ticker} order is not finished")
            if refused:
                return None
            return [{"kind": "order_intent", "order": oid, "decision_key": decision_key, "ticker": ticker,
                     "quantity": quantity, "position_before": before, "intent_at": self.clock()}]

        self.s.transact(intent)
        if refused:
            return "refused: " + refused[0]
        try:
            ack = self.b.submit_market(ticker, quantity)
        except BrokerRejected as e:
            self._record(oid, "rejected", error=str(e)[:300])
            return self._reconcile(oid)
        except BrokerUnknown as e:
            self._record(oid, "unknown", error=str(e)[:300])
            return self.recover(oid)
        self._record(oid, "submitted", broker_id=ack["id"])
        return self._drive(oid, ack["id"])

    def _drive(self, oid: str, bid) -> str:
        start, cancel_sent = self.clock(), False
        while True:
            try:
                o = self.b.get_order(bid)
            except BrokerUnknown as e:
                return self.pause(f"order {bid} status unreadable: {e}", oid)
            if o is None:
                return self.pause(f"order {bid} not found at the broker after submission", oid)
            if o["status"] in TERMINAL:
                self._record(oid, o["status"], broker_id=bid, filled=float(o.get("filled", 0.0)))
                return self._reconcile(oid)
            if not cancel_sent and self.clock() - start > self.max_working_s:
                try:
                    self.b.cancel(bid)
                except BrokerUnknown as e:
                    return self.pause(f"cancel of {bid} has an unknown outcome: {e}", oid)
                self._record(oid, "cancel_requested", broker_id=bid)
                cancel_sent, start = True, self.clock()
            elif cancel_sent and self.clock() - start > self.max_working_s:
                return self.pause(f"order {bid} still not final after cancel", oid)
            self.sleep(self.poll_s)

    def recover(self, oid: str) -> str:
        """Resolve an order whose outcome is unknown, without ever resubmitting it."""
        o = orders(_events(self.s))[oid]
        deadline = self.clock() + self.settle_s
        while True:
            try:
                found = [m for m in self.b.find_orders(o["ticker"], o["at"] - 5)
                         if abs(float(m["quantity"]) - o["quantity"]) <= self.tol]
            except BrokerUnknown as e:
                return self.pause(f"order lookup failed for {oid}: {e}", oid)
            if len(found) == 1:
                self._record(oid, "adopted", broker_id=found[0]["id"])
                return self._drive(oid, found[0]["id"])
            if len(found) > 1:
                return self.pause(f"{len(found)} broker orders match {oid}; cannot tell which is ours", oid)
            if self.clock() >= deadline:
                return self.pause(f"no broker record of {oid} after {self.settle_s:.0f}s; outcome cannot be "
                                  "determined safely, not resubmitting", oid)
            self.sleep(self.poll_s)

    def recover_all(self) -> dict[str, str]:
        """On start: every order left non-terminal by a crash is resolved by `recover` (never resubmitted)."""
        out, ev = {}, _events(self.s)
        if paused(ev):
            return {"*": "paused: " + paused(ev)}
        for oid, o in orders(ev).items():
            if o["state"] not in FINAL:
                out[oid] = self._drive(oid, o["broker_id"]) if o["broker_id"] else self.recover(oid)
        return out

    def _reconcile(self, oid: str) -> str:
        o = orders(_events(self.s))[oid]
        try:
            after = self.b.position(o["ticker"])
        except BrokerUnknown as e:
            return self.pause(f"position unreadable after {oid}: {e}", oid)
        expected = o["before"] + o["filled"]
        if abs(after - expected) > self.tol:
            return self.pause(f"reconciliation mismatch on {o['ticker']}: broker {after}, expected {expected}", oid)
        self.s.transact(lambda ev: [{"kind": "order_reconciled", "order": oid, "state": "reconciled",
                                     "final": o["state"], "position_after": after}])
        return o["state"]


def _events(store: GitStore) -> list[dict]:
    from .events import parse
    return parse(store.sync())
