"""Order execution behind an independent risk gate, with an intent journal that makes duplicates impossible.

Flow for every order: the risk gate checks it -> an `intended` record is written -> the order is sent -> its
acknowledgement (or error) is written -> `reconcile` follows it to filled / cancelled / rejected from the broker's own
records. While any intent is unresolved, or the broker shows a pending order for that ticker, no new order is sent.
An order whose outcome is unknown (timeout, 5xx) is `ambiguous`: it is never re-sent, and it blocks all trading until
the broker's records explain it.
"""
from __future__ import annotations

import datetime as dt
import math
import uuid

TERMINAL = {"filled", "cancelled", "rejected", "not_sent"}


def latest_intents(records: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in records:
        if r.get("id"):
            out[r["id"]] = {**out.get(r["id"], {}), **r}
    return out


def unresolved(records: list[dict]) -> list[dict]:
    return [r for r in latest_intents(records).values() if r.get("status") not in TERMINAL]


def today_orders(records: list[dict], day: str) -> list[dict]:
    return [r for r in latest_intents(records).values()
            if r.get("ts", "").startswith(day) and r.get("status") in ("placed", "ambiguous", "filled")]


def risk_check(order: dict, *, control: dict, records: list[dict], pending: list[dict], positions: dict,
               limits: dict, day: str, consecutive_errors: int, quote_ok: bool, market_open: bool) -> list[str]:
    """Reasons to refuse; an empty list means the order may be sent. This gate never reads the strategy's reasons."""
    why = []
    if control.get("trading_enabled") is not True:
        why.append(f"kill switch: trading disabled ({control.get('reason', 'no reason given')})")
    if unresolved(records):
        why.append("an earlier order intent is unresolved")
    if any(_pending_ticker(p) == order["ticker"] for p in pending):
        why.append("the broker shows a pending order for this ticker")
    if not quote_ok:
        why.append("no fresh, validated price")
    if not market_open:
        why.append("market closed")
    if consecutive_errors >= limits["max_consecutive_order_errors"]:
        why.append(f"{consecutive_errors} consecutive order errors")
    q = order["quantity"]
    if not isinstance(q, (int, float)) or not math.isfinite(q) or q == 0:
        why.append("invalid quantity")
    elif q > 0 and order["ticker"] not in limits["buy_whitelist"]:
        why.append(f"{order['ticker']} is not on the buy whitelist")
    elif q > 0 and order["ticker"] not in limits.get("cap_exempt", []) and \
            float(order.get("post_weight", 1.0)) > limits.get("max_name_weight", 1.0):
        why.append(f"{order['ticker']} would be {float(order.get('post_weight', 1.0)):.1%} of the book "
                   f"(single-name cap {limits['max_name_weight']:.0%})")
    elif q < 0:
        avail = float((positions.get(order["ticker"]) or {}).get("quantityAvailableForTrading") or 0)
        if -q > avail + 1e-9:
            why.append(f"sell of {-q} exceeds the {avail} available to trade")
    if order["value_gbp"] > limits["max_order_gbp"]:
        why.append(f"order value £{order['value_gbp']:.2f} is over the £{limits['max_order_gbp']:.0f} limit")
    done = today_orders(records, day)
    if len(done) >= limits["max_orders_per_day"]:
        why.append(f"{len(done)} orders today (limit {limits['max_orders_per_day']})")
    turnover = sum(abs(float(r.get("value_gbp", 0))) for r in done)
    if turnover + order["value_gbp"] > limits["max_turnover_gbp_per_day"]:
        why.append(f"daily turnover would reach £{turnover + order['value_gbp']:.2f}")
    return why


def _pending_ticker(p: dict) -> str | None:
    return p.get("ticker") or (p.get("instrument") or {}).get("ticker")


class Executor:
    def __init__(self, store, client, ambiguous_exc: type[Exception], api_exc: type[Exception]):
        self.store, self.client = store, client
        self.Ambiguous, self.ApiError = ambiguous_exc, api_exc
        self.consecutive_errors = 0

    def submit(self, order: dict, refusals: list[str]) -> dict:
        iid = uuid.uuid4().hex
        base = {"id": iid, "ticker": order["ticker"], "quantity": order["quantity"], "value_gbp": order["value_gbp"],
                "price": order.get("price"), "reason": order["reason"], "signal": order.get("signal")}
        if refusals:
            return self.store.intent(**base, status="not_sent", refusals=refusals)
        self.store.intent(**base, status="intended")
        try:
            ack = self.client.place_market_order(order["ticker"], order["quantity"])
        except self.Ambiguous as e:
            self.consecutive_errors += 1
            return self.store.intent(id=iid, status="ambiguous", error=str(e))
        except self.ApiError as e:
            self.consecutive_errors += 1
            return self.store.intent(id=iid, status="rejected", error=str(e)[:400])
        self.consecutive_errors = 0
        return self.store.intent(id=iid, status="placed", order_id=(ack or {}).get("id"), ack=ack)

    def reconcile(self, now: float, timeout_s: float) -> list[dict]:
        """Follow every unresolved intent to its outcome from the broker's records. Returns the records written."""
        written = []
        for it in unresolved(self.store.intents()):
            oid = it.get("order_id")
            hist = self.client.history_orders(ticker=it["ticker"], limit=20, max_pages=1)
            h = next((x for x in hist if _hid(x) == oid), None) if oid else None
            if h is None and not oid:
                # ambiguous or never acknowledged: match on ticker, side and time after the intent
                h = next((x for x in hist if _after(x, it["t"] - 5) and _same_side(x, it["quantity"])), None)
            if h is not None:
                status = _hist_status(h)
                if status:
                    written.append(self.store.intent(id=it["id"], status=status, order_id=_hid(h), broker=h))
                    continue
            if oid:
                try:
                    live = self.client.get_order(oid)
                    if live and now - it["t"] < timeout_s:
                        continue  # still working at the broker
                except Exception:  # noqa: BLE001 - a 404 means it has left the pending book; history decides
                    pass
            if it.get("status") == "intended" and now - it["t"] > 120:
                # crashed between writing the intent and sending: only the broker's records can say it was sent
                if not any(_after(x, it["t"] - 5) and _same_side(x, it["quantity"]) for x in hist):
                    written.append(self.store.intent(id=it["id"], status="not_sent",
                                                     refusals=["no broker record after a restart"]))
        return written


def _hid(x: dict):
    return x.get("id") or (x.get("order") or {}).get("id")


def _hist_status(x: dict) -> str | None:
    s = str(x.get("status") or (x.get("order") or {}).get("status") or "").upper()
    if s == "FILLED":
        return "filled"
    if s in ("CANCELLED", "REJECTED"):
        return s.lower()
    return None


def _after(x: dict, t: float) -> bool:
    s = x.get("dateCreated") or (x.get("order") or {}).get("createdAt") or x.get("createdAt")
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() >= t
    except ValueError:
        return False


def _same_side(x: dict, q: float) -> bool:
    o = x.get("order") or x
    hq = o.get("quantity") or o.get("orderedQuantity") or o.get("filledQuantity") or 0
    side = str(o.get("side") or "").upper()
    if side:
        return (side == "BUY") == (q > 0)
    return (float(hq) > 0) == (q > 0)
