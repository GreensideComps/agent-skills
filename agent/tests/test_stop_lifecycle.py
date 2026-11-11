"""agent-1.23: a holding with a stop rule is never left without a broker stop for longer than a retry wait.

Each test drives the whole agent against the fake broker and reproduces one way the stop used to lapse for good
(found in the 11 Nov 2026 audit), then shows the stop coming back and the self-check reporting the gap meanwhile.
"""
from __future__ import annotations

import datetime as dt

from test_agent import (ApiErr, T0, _active_book, _jpm_entry, advance, iso, make, no_network, pos)  # noqa: F401

from market_agent import active, execution


def _stops(b, ticker="JPM_US_EQ"):
    return [p for p in b.pending if p["type"] == "STOP" and p["ticker"] == ticker]


def _events(st, clock, kind):
    return [e for e in st.events(iso(clock())[:10]) if e["kind"] == kind]


def _inv(st, code):
    return [v for v in (st.read("invariants.json") or {}).get("violations", []) if v["code"] == code]


def _screen_book(tmp_path, prices=None, picks=("MU_US_EQ", "TDC_US_EQ"), values=(18.0, 18.0)):
    """A book holding stock_screen names bought at 100 and 50 (no stop of their own: the 30% disaster stop applies)."""
    px = {"VWRP.L": 140.0, "GBPUSD=X": 1.25, "MU": 100.0, "TDC": 50.0, **(prices or {})}
    ag, b, st, clock = make(tmp_path, active_on=True, prices=px)
    _active_book(b)
    for k in ("social", "merger"):
        ag.cfg["active"][k]["enabled"] = False
    ag.cfg["active"]["timing"] = {}
    ag.cfg["active"]["stock_screen"].update(enabled=True, picks=list(picks), previous_picks=[])
    ag.cfg["limits"]["buy_whitelist"] += list(picks)
    for tk, v, epx in zip(picks, values, (100.0, 50.0)):
        q = round(v * 1.25 / epx, 4)
        st.intent(id=f"e-{tk}", ticker=tk, quantity=q, value_gbp=v, status="filled",
                  signal={"type": "active_entry", "strategy": "stock_screen", "entry_px": epx, "stop": None,
                          "take_profit": None, "time_stop_s": None, "vwrp_px": 140.0},
                  broker={"fill": {"walletImpact": {"netValue": v, "taxes": []}}})
        b.pos.append(pos(tk, q, q, 0, v, v, px=epx))
    return ag, b, st, clock


def test_a_failed_stop_placement_is_retried_until_it_rests(tmp_path):
    """Before: any refusal other than price-too-far (a 429, a 5xx) was recorded once and never retried; for a
    strategy with no software stop the holding stayed unprotected for good."""
    ag, b, st, clock = _screen_book(tmp_path)
    real, fails = b.place_stop_order, {"n": 0}

    def flaky(ticker, quantity, stop_price):
        if ticker == "MU_US_EQ" and fails["n"] < 2:
            fails["n"] += 1
            raise RuntimeError("/api/v0/equity/orders/stop: HTTP 429: too many requests")
        return real(ticker, quantity, stop_price)
    b.place_stop_order = flaky
    advance(ag, clock, 1, by=30)
    assert not _stops(b, "MU_US_EQ") and _stops(b, "TDC_US_EQ")               # MU refused, TDC protected
    rec = st.read("stops.json")["e-MU_US_EQ"]
    assert rec["failed"].endswith("too many requests") and rec["attempts"] == 1
    assert [v["ticker"] for v in _inv(st, "unprotected")] == ["MU_US_EQ"]       # the self-check sees it at once
    advance(ag, clock, 3, by=301)                                              # inside the 30-minute wait
    assert fails["n"] == 1 and not _stops(b, "MU_US_EQ")
    advance(ag, clock, 4, by=301)                                              # past it: second try, refused again
    assert fails["n"] == 2 and st.read("stops.json")["e-MU_US_EQ"]["attempts"] == 2
    assert [v["severity"] for v in _inv(st, "unprotected")] == ["critical"]    # over 30 open-market minutes bare
    assert any(e["code"] == "invariant:unprotected:MU_US_EQ" and e["level"] == "critical"
               for e in _events(st, clock, "alert"))
    advance(ag, clock, 13, by=301)                                             # the wait doubled to an hour
    assert [p["stopPrice"] for p in _stops(b, "MU_US_EQ")] == [70.0]            # third try rests: 30% under entry
    assert not _inv(st, "unprotected") and st.read("invariants.json")["ok"]


def test_a_stop_the_broker_rejects_is_placed_again(tmp_path):
    """Before: a REJECTED stop was written off as {rejected: ts} and never looked at again."""
    ag, b, st, clock, rec, q = _jpm_entry(tmp_path)
    s0 = _stops(b)[0]
    b.pending.remove(s0)
    b.history.insert(0, {"order": {"id": s0["id"], "ticker": "JPM_US_EQ", "status": "REJECTED"}})
    advance(ag, clock, 2, by=301)
    assert _events(st, clock, "stop_rejected")
    new = _stops(b)
    assert len(new) == 1 and new[0]["id"] != s0["id"] and new[0]["stopPrice"] == s0["stopPrice"]
    assert st.read("stops.json")[rec["id"]]["order_id"] == new[0]["id"]


def test_a_stop_the_broker_no_longer_knows_is_placed_again(tmp_path):
    """Before: an order missing from both the pending book and the history left stops.json claiming a live stop
    for ever."""
    ag, b, st, clock, rec, q = _jpm_entry(tmp_path)
    s0 = _stops(b)[0]
    b.pending.remove(s0)                                                       # vanished: no history record either
    advance(ag, clock, 2, by=301)
    assert not _stops(b) and st.read("stops.json")[rec["id"]]["order_id"] == s0["id"]   # two passes: still believed
    assert [v["ticker"] for v in _inv(st, "unprotected")] == ["JPM_US_EQ"]      # but the self-check trusts the broker
    advance(ag, clock, 2, by=301)                                              # third miss: asked by id, 404 -> lost
    assert _events(st, clock, "stop_lost")
    assert len(_stops(b)) == 1 and len(_events(st, clock, "stop_placed")) == 2  # a new order, placed again


def test_the_stop_is_kept_while_the_risk_gate_would_refuse_the_exit(tmp_path):
    """Before: the agent cancelled the stop ahead of its own exit without asking whether the exit could go."""
    ag, b, st, clock, rec, q = _jpm_entry(tmp_path)
    ag.cfg["limits"]["max_turnover_gbp_per_day"] = 0.0                         # the risk gate will refuse the exit
    clock.t = T0 + 11 * 86400                                                  # past the 10-day time stop
    advance(ag, clock, 14, by=301)
    assert len(_stops(b)) == 1 and not _events(st, clock, "stop_cancelled")    # protection never dropped
    assert not [o for o in b.orders if o[0] == "JPM_US_EQ" and o[1] < 0]
    assert any(e["code"] == "sell_blocked:JPM_US_EQ" for e in _events(st, clock, "alert"))
    assert [v["severity"] for v in _inv(st, "overdue_exit")] == ["warn"]       # and the self-check says so


def test_a_stop_cancelled_for_an_exit_that_never_happens_is_put_back(tmp_path):
    """Before: if the exit did not go out after the cancel, the trade stayed open with no stop and the record's
    "why" marker stopped it ever being re-placed."""
    ag, b, st, clock, rec, q = _jpm_entry(tmp_path)
    clock.t = T0 + 11 * 86400                                                  # past the 10-day time stop
    advance(ag, clock, 1, by=301)
    assert not _stops(b) and st.read("stops.json")[rec["id"]]["why"] == "time"  # cancelled for the exit
    ag.cfg["limits"]["max_turnover_gbp_per_day"] = 0.0                         # ...which the gate now refuses
    advance(ag, clock, 5, by=301)
    assert not _stops(b) and not [o for o in b.orders if o[0] == "JPM_US_EQ" and o[1] < 0]
    advance(ag, clock, 4, by=301)                                              # 30-minute grace over
    assert len(_stops(b)) == 1                                                 # protection is back, and stays
    advance(ag, clock, 4, by=301)
    assert len(_stops(b)) == 1


def test_the_stop_follows_the_position_when_its_size_changes(tmp_path):
    """Before: the stop kept its first quantity; a top-up left the new shares uncovered."""
    ag, b, st, clock, rec, q = _jpm_entry(tmp_path)
    p = next(x for x in b.pos if x["instrument"]["ticker"] == "JPM_US_EQ")
    p["quantity"] = round(q * 1.5, 4)
    advance(ag, clock, 1, by=301)
    assert _events(st, clock, "stop_resized") and not _stops(b)                # old stop cancelled first
    assert [v["ticker"] for v in _inv(st, "unprotected")] == ["JPM_US_EQ"]
    advance(ag, clock, 1, by=30)
    assert [x["quantity"] for x in _stops(b)] == [-round(q * 1.5, 4)]           # then the right size


def test_the_agent_sells_at_the_disaster_level_when_no_broker_stop_rests(tmp_path):
    """Before: the four no-stop strategies relied on the broker stop alone. If the broker refused it, nothing sold."""
    ag, b, st, clock = _screen_book(tmp_path)
    b.place_stop_order = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 500: stop orders unavailable"))
    advance(ag, clock, 2, by=301)
    assert not b.pending and not [o for o in b.orders if o[1] < 0]             # no stop, and no reason to sell yet
    get = ag.get

    def crashed(url, params):
        d = get(url, params)
        if isinstance(d, dict) and "MU" in d and "close" in d["MU"]:
            d["MU"]["close"] = [69.0, 69.0]                                    # -31% from the 100 entry
            d["MU"]["previousClose"] = 80.0
        return d
    ag.get = crashed
    for x in b.pos:
        if x["instrument"]["ticker"] == "MU_US_EQ":
            x["currentPrice"] = 69.0
    advance(ag, clock, 2, by=301)
    sells = [o for o in b.orders if o[1] < 0]
    assert [o[0] for o in sells] == ["MU_US_EQ"]
    ex = next(r for r in execution.latest_intents(st.intents()).values()
              if (r.get("signal") or {}).get("type") == "active_exit")
    assert ex["signal"]["why"] == "disaster_stop" and ex["signal"]["strategy"] == "stock_screen"


def test_no_software_disaster_sale_while_the_broker_stop_rests(tmp_path):
    ag, b, st, clock = _screen_book(tmp_path)
    advance(ag, clock, 2, by=301)
    assert len(b.pending) == 2
    recs, stops = st.intents(), st.read("stops.json")
    posn = {p["instrument"]["ticker"]: p for p in b.pos}
    q = lambda t: {"price": 60.0 if t == "MU_US_EQ" else 30.0}  # noqa: E731 - far below the 70 and 35 stops
    dis = ag.cfg["active"]["disaster_stop"]
    live = {k for k, v in stops.items() if v.get("order_id")}
    assert active.exit_orders(recs, posn, q, clock(), 140.0, None, dis, live) == []          # the broker's job
    assert [o[6]["why"] for o in active.exit_orders(recs, posn, q, clock(), 140.0, None, dis, set())] == \
        ["disaster_stop", "disaster_stop"]
    assert active.exit_orders(recs, posn, q, clock(), 140.0, None, None, set()) == []        # switch off: as before


def test_equal_weight_trims_and_top_ups_work_with_stops_resting(tmp_path):
    """Before: a resting stop holds the shares, so the trim quantity was min(qty, 0) = 0 and the month was marked
    done with nothing traded; a top-up was refused as "pending order for this ticker" and still marked done."""
    ag, b, st, clock = _screen_book(tmp_path, values=(24.0, 12.0))
    b.cash = 200.0
    ag.cfg["core"]["invest_cash_above_gbp"] = 10_000.0                         # keep the core buy out of the way
    ag.cfg["active"]["stock_screen"]["ew_rebalance"].update(**{"from": "2026-10"})
    ag.cfg["active"]["stock_screen"]["ew_rebalance"]["enabled"] = False
    advance(ag, clock, 1, by=30)
    assert len(b.pending) == 2                                                 # both names protected
    for x in b.pos:                                                            # the broker locks shares under a stop
        if x["instrument"]["ticker"] in ("MU_US_EQ", "TDC_US_EQ"):
            x["quantityAvailableForTrading"] = 0
    ag.cfg["active"]["stock_screen"]["ew_rebalance"]["enabled"] = True
    advance(ag, clock, 1, by=301)
    assert [e["for_exit"] for e in _events(st, clock, "stop_cancelled")] == ["active_trim"]  # MU's stop goes first
    assert not [o for o in b.orders if o[0] == "MU_US_EQ"]
    for x in b.pos:
        if x["instrument"]["ticker"] == "MU_US_EQ":
            x["quantityAvailableForTrading"] = x["quantity"]
    advance(ag, clock, 1, by=30)
    trim = [o for o in b.orders if o[0] == "MU_US_EQ"]
    assert len(trim) == 1 and trim[0][1] < 0                                   # the trim really goes out
    for x in b.pos:                                                            # apply the fill
        if x["instrument"]["ticker"] == "MU_US_EQ":
            x["quantity"] = round(x["quantity"] + trim[0][1], 4)
            x["quantityAvailableForTrading"] = x["quantity"]
            x["walletImpact"]["currentValue"] = 18.0
    advance(ag, clock, 2, by=30)
    top = [o for o in b.orders if o[0] == "TDC_US_EQ"]
    assert len(top) == 1 and top[0][1] > 0                                     # the top-up is not blocked by its stop
    assert st.read("stock_screen.json")["ew_done"]
    for x in b.pos:
        if x["instrument"]["ticker"] == "TDC_US_EQ":
            x["quantity"] = round(x["quantity"] + top[0][1], 4)
            x["walletImpact"]["currentValue"] = 18.0
    advance(ag, clock, 3, by=301)
    held = {x["instrument"]["ticker"]: x["quantity"] for x in b.pos}
    assert {p["ticker"]: -p["quantity"] for p in b.pending} == {t: held[t] for t in ("MU_US_EQ", "TDC_US_EQ")}
    assert not _inv(st, "unprotected")


def test_a_refused_trim_or_top_up_is_not_marked_done(tmp_path):
    ag, b, st, clock = _screen_book(tmp_path, values=(24.0, 12.0))
    b.place_stop_order = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 500"))  # no stops: trims go direct
    ag.cfg["core"]["invest_cash_above_gbp"] = 10_000.0
    ag.cfg["active"]["stock_screen"]["ew_rebalance"].update(**{"from": "2026-10"})
    ag.cfg["limits"]["max_turnover_gbp_per_day"] = 0.0
    advance(ag, clock, 2, by=301)
    assert not b.orders and not (st.read("stock_screen.json") or {}).get("ew_done")


def test_stop_action_states():
    now = 1_800_000_000.0
    iso_ = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    sa = active.stop_action
    assert sa(None, 1.0, now) == "place"
    assert sa({"order_id": 5, "qty": 1.0}, 1.0, now) == "live"
    assert sa({"order_id": 5}, 1.0, now) == "live"                             # legacy record without a quantity
    assert sa({"order_id": 5, "qty": 1.0}, 1.5, now) == "resize"
    assert sa({"order_id": None, "filled": "x"}, 1.0, now) == "done"
    assert sa({"order_id": None, "qty": 1.0, "cancelled": iso_(now - 60), "why": "time"}, 1.0, now) == "wait"
    assert sa({"order_id": None, "qty": 1.0, "cancelled": iso_(now - 1801), "why": "time"}, 1.0, now) == "replace"
    assert sa({"order_id": None, "qty": 1.0, "cancelled": iso_(now - 60), "why": "active_trim"}, 0.8, now) == "replace"
    assert sa({"order_id": None, "cancelled": iso_(now - 5), "resized": True}, 1.0, now) == "replace"
    for k in ("cancelled", "rejected", "lost"):
        assert sa({"order_id": None, k: iso_(now - 5)}, 1.0, now) == "replace"                  # first loss: at once
        again = {"order_id": None, k: iso_(now - 5), "attempts": 2, "t": now - 600}
        assert sa(again, 1.0, now) == "wait"                                                    # a repeat: backs off
        assert sa({**again, k: iso_(now - 3601)}, 1.0, now) == "replace"
        assert sa({**again, "t": now - 90000}, 1.0, now) == "replace"                           # rested a day: fresh
    f = {"order_id": None, "failed": "HTTP 429", "clamp_tried": True, "attempts": 1, "t": now - 600}
    assert sa(f, 1.0, now) == "wait" and sa({**f, "t": now - 1800}, 1.0, now) == "place"
    assert sa({**f, "attempts": 9, "t": now - 6 * 3600}, 1.0, now) == "place"                   # capped at 6 hours
    assert sa({"order_id": None, "failed": "price-too-far"}, 1.0, now) == "place"               # ladder not tried yet
