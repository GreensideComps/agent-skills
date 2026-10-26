"""Offline tests: a fake broker and fake feeds; any real network call fails the test."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_agent import agent as agent_mod, execution, feeds  # noqa: E402
from market_agent.__main__ import health  # noqa: E402
from market_agent.store import LeaseHeld, Store  # noqa: E402

T0 = dt.datetime(2026, 10, 27, 15, 0, tzinfo=dt.timezone.utc).timestamp()  # Tue: LSE and NASDAQ both open


class Ambiguous(Exception):
    pass


class ApiErr(Exception):
    pass


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


def pos(t, q, avail, pies, value, cost, ccy="USD", px=10.0):
    return {"instrument": {"ticker": t, "currency": ccy}, "quantity": q, "quantityAvailableForTrading": avail,
            "quantityInPies": pies, "currentPrice": px, "walletImpact": {"currentValue": value, "totalCost": cost}}


class FakeBroker:
    def __init__(self, clock):
        self.clock = clock
        self.cash = 0.0
        self.pos = [pos("INTC_US_EQ", 0.2, 0, 0.2, 17.0, 20.0), pos("MSFT_US_EQ", 0.3, 0, 0.3, 150.0, 160.0)]
        self.orders, self.history, self.pending = [], [], []
        self.fail_next = None

    def account_summary(self):
        return {"totalValue": self.cash + sum(p["walletImpact"]["currentValue"] for p in self.pos),
                "cash": {"availableToTrade": self.cash}}

    def positions(self):
        return [dict(p) for p in self.pos]

    def pending_orders(self):
        return list(self.pending)

    def exchanges(self):
        day = dt.datetime.fromtimestamp(self.clock(), dt.timezone.utc).replace(hour=0, minute=0, second=0)
        d = day.timestamp()
        ev = lambda h, k: {"date": iso(d + h * 3600), "type": k}  # noqa: E731
        return [{"name": "LSE", "workingSchedules": [{"id": 70, "timeEvents": [ev(8, "OPEN"), ev(16.5, "CLOSE")]}]},
                {"name": "NASDAQ", "workingSchedules": [{"id": 71, "timeEvents": [ev(13.5, "OPEN"),
                                                                                    ev(20, "AFTER_HOURS_OPEN")]}]}]

    def instruments(self):
        return [{"ticker": "INTC_US_EQ", "workingScheduleId": 71}, {"ticker": "MSFT_US_EQ", "workingScheduleId": 71},
                {"ticker": "JPM_US_EQ", "workingScheduleId": 71},
                {"ticker": "UBER_US_EQ", "workingScheduleId": 71}, {"ticker": "VWRPl_EQ", "workingScheduleId": 70}]

    def place_market_order(self, ticker, quantity):
        if self.fail_next:
            e, self.fail_next = self.fail_next, None
            raise e
        oid = 1000 + len(self.orders)
        self.orders.append((ticker, quantity))
        self.history.insert(0, {"order": {"id": oid, "ticker": ticker, "status": "FILLED",
                                          "side": "BUY" if quantity > 0 else "SELL", "createdAt": iso(self.clock())},
                                "fill": {"quantity": abs(quantity), "price": 10.0}})
        return {"id": oid, "status": "NEW"}

    def history_orders(self, ticker=None, limit=50, max_pages=5):
        return [h for h in self.history if ticker in (None, h["order"]["ticker"])]

    def get_order(self, oid):
        raise ApiErr("404")


def fake_get(clock, prices=None):
    prices = prices or {}

    def get(url, params):
        if url == feeds.SPARK:
            out = {}
            for s in params["symbols"].split(","):
                p = prices.get(s, 100.0)
                if p is not None:
                    out[s] = {"timestamp": [clock() - 120, clock() - 60], "close": [p, p], "previousClose": p}
            return out
        if url == feeds.SEARCH:
            return {"news": [{"uuid": f"n-{params['q']}", "title": "headline", "providerPublishTime": clock() - 60,
                              "relatedTickers": [params["q"]]}]}
        raise AssertionError(url)
    return get


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call in a test")
    monkeypatch.setattr(feeds, "http_get", boom)
    monkeypatch.setattr(feeds.requests, "get", boom)


def make(tmp_path, enabled=True, prices=None, satellite=False, active_on=False):
    clock = Clock()
    st = Store(tmp_path, clock=clock, sleep=lambda s: None)
    if enabled:
        st.set_control(True, "test", "test")
    b = FakeBroker(clock)
    cfg = agent_mod.load_config()
    cfg["satellite"]["enabled"] = satellite  # the older tests hold a 90% single-stock book on purpose
    cfg["active"]["enabled"] = active_on
    ag = agent_mod.Agent(st, b, cfg, ambiguous_exc=Ambiguous, api_exc=ApiErr,
                         get=fake_get(clock, prices), clock=clock, sleep=lambda s: None)
    st.acquire_lease()
    return ag, b, st, clock


def advance(ag, clock, n=1, by=301):
    for _ in range(n):
        clock.t += by
        ag.step()


def test_pie_held_exit_sends_nothing_and_alerts(tmp_path):
    ag, b, st, clock = make(tmp_path)
    advance(ag, clock, 3)
    assert b.orders == []
    ev = st.events(dt.datetime.fromtimestamp(clock.t, dt.timezone.utc).strftime("%Y-%m-%d"))
    assert any(e["kind"] == "alert" and e["code"] == "exit_blocked_pie:INTC_US_EQ" for e in ev)
    assert sum(1 for e in ev if e["kind"] == "alert" and e["code"] == "exit_blocked_pie:INTC_US_EQ") == 1
    assert any(e["kind"] == "decision" and e["no_trade"] for e in ev)


def test_tradeable_exit_sells_once_then_reconciles_to_filled(tmp_path):
    ag, b, st, clock = make(tmp_path)
    b.pos[0] = pos("INTC_US_EQ", 0.2, 0.2, 0, 17.0, 20.0)
    advance(ag, clock, 1)
    assert b.orders == [("INTC_US_EQ", -0.2)]
    b.pos = b.pos[1:]  # the sell filled
    advance(ag, clock, 3)
    assert b.orders == [("INTC_US_EQ", -0.2)]  # never re-sent
    final = execution.latest_intents(st.intents())
    assert [r["status"] for r in final.values()] == ["filled"]
    assert list(final.values())[0]["broker"]["order"]["status"] == "FILLED"


def test_cash_goes_to_vwrp_core_only(tmp_path):
    ag, b, st, clock = make(tmp_path, prices={"VWRP.L": 140.0})
    b.cash = 100.0
    advance(ag, clock, 2)
    assert b.orders == [("VWRPl_EQ", 0.62)]  # floor((100 - 5) / 1.08 / 140, 2 dp): room for the broker's hold


def test_kill_switch_and_missing_control_block_orders(tmp_path):
    ag, b, st, clock = make(tmp_path, enabled=False)
    b.pos[0] = pos("INTC_US_EQ", 0.2, 0.2, 0, 17.0, 20.0)
    advance(ag, clock, 2)
    assert b.orders == []
    assert st.control()["trading_enabled"] is False
    refused = [r for r in st.intents() if r["status"] == "not_sent"]
    assert refused and "kill switch" in refused[0]["refusals"][0]


def test_market_closed_blocks_orders(tmp_path):
    ag, b, st, clock = make(tmp_path)
    clock.t = T0 + 7 * 3600  # 22:00 UTC: both closed
    b.pos[0] = pos("INTC_US_EQ", 0.2, 0.2, 0, 17.0, 20.0)
    advance(ag, clock, 1)
    assert b.orders == []
    day = dt.datetime.fromtimestamp(clock.t, dt.timezone.utc).strftime("%Y-%m-%d")
    assert any("wait for their market" in n for e in st.events(day) if e["kind"] == "decision" for n in e["notes"])


def test_ambiguous_order_is_never_resent_and_blocks_trading(tmp_path):
    ag, b, st, clock = make(tmp_path)
    b.pos[0] = pos("INTC_US_EQ", 0.2, 0.2, 0, 17.0, 20.0)
    b.fail_next = Ambiguous("timeout")
    advance(ag, clock, 1)
    assert b.orders == []
    advance(ag, clock, 3)
    assert b.orders == []  # the ambiguous intent is unresolved, so nothing else is sent
    statuses = [r["status"] for r in execution.latest_intents(st.intents()).values()]
    assert statuses[0] == "ambiguous" and set(statuses[1:]) <= {"not_sent"}


def test_crash_after_intent_resolves_without_resend(tmp_path):
    ag, b, st, clock = make(tmp_path)
    st.intent(id="x1", ticker="INTC_US_EQ", quantity=-0.2, value_gbp=17, status="intended", reason="r")
    clock.t += 200
    ag.ex.reconcile(clock.t, 900)
    assert execution.latest_intents(st.intents())["x1"]["status"] == "not_sent"
    assert b.orders == []


def test_risk_gate_limits():
    lim = agent_mod.load_config()["limits"]
    base = dict(control={"trading_enabled": True}, records=[], pending=[], limits=lim, day="2026-10-27",
                consecutive_errors=0, quote_ok=True, market_open=True,
                positions={"INTC_US_EQ": {"quantityAvailableForTrading": 0.2}})
    ok = {"ticker": "INTC_US_EQ", "quantity": -0.2, "value_gbp": 17}
    assert execution.risk_check(ok, **base) == []
    assert "exceeds" in execution.risk_check({**ok, "quantity": -0.3}, **base)[0]
    assert "whitelist" in execution.risk_check({"ticker": "XYZ_US_EQ", "quantity": 1, "value_gbp": 5}, **base)[0]
    assert "limit" in execution.risk_check({"ticker": "VWRPl_EQ", "quantity": 9, "value_gbp": 900}, **base)[0]
    assert "pending" in execution.risk_check(ok, **{**base, "pending": [{"ticker": "INTC_US_EQ"}]})[0]
    assert "errors" in execution.risk_check(ok, **{**base, "consecutive_errors": 2})[0]
    assert "price" in execution.risk_check(ok, **{**base, "quote_ok": False})[0]


def test_quote_validation():
    f = {"market_open": 600, "market_closed": 345600}
    assert feeds.validate("X", {"price": 10, "t": T0 - 60, "prev_close": 10}, T0, True, f, 0.25, None)[0]
    assert not feeds.validate("X", None, T0, True, f, 0.25, None)[0]
    assert "stale" in feeds.validate("X", {"price": 10, "t": T0 - 900, "prev_close": 10}, T0, True, f, 0.25, None)[1]
    assert "future" in feeds.validate("X", {"price": 10, "t": T0 + 900}, T0, True, f, 0.25, None)[1]
    assert "bad" in feeds.validate("X", {"price": float("nan"), "t": T0}, T0, True, f, 0.25, None)[1]
    q = {"price": 20, "t": T0 - 60, "prev_close": 10}
    assert "abnormal" in feeds.validate("X", q, T0, True, f, 0.25, None)[1]
    assert feeds.validate("X", {**q, "t": T0}, T0, True, f, 0.25, {"price": 20.1, "t": T0 - 60})[0]


def test_london_quotes_get_the_delayed_freshness_limit():
    f = agent_mod.load_config()["freshness_s"]
    q = {"price": 140, "t": T0 - 1000, "prev_close": 140}
    assert feeds.validate("VWRP.L", q, T0, True, f, 0.25, None)[0]
    assert not feeds.validate("SPY", {**q}, T0, True, f, 0.25, None)[0]


def test_stale_price_blocks_core_buy(tmp_path):
    ag, b, st, clock = make(tmp_path, prices={"VWRP.L": None})
    b.cash = 100.0
    advance(ag, clock, 2)
    assert b.orders == []


def test_lease_prevents_a_second_instance(tmp_path):
    clock = Clock()
    a = Store(tmp_path, clock=clock, sleep=lambda s: None)
    a.acquire_lease()
    b = Store(tmp_path, clock=clock, sleep=lambda s: None)
    with pytest.raises(LeaseHeld):
        b.acquire_lease()
    clock.t += 200  # a stopped renewing
    b.acquire_lease()
    with pytest.raises(LeaseHeld):
        a.renew_lease()


def test_session_state_and_health():
    evs = [{"date": iso(T0 - 3600), "type": "OPEN"}, {"date": iso(T0 + 3600), "type": "CLOSE"}]
    assert feeds.session_state(evs, T0)["open"] and not feeds.session_state(evs, T0 + 7200)["open"]
    assert health(None, T0)[0] == 2
    assert health({"t": T0 - 400}, T0)[0] == 2
    assert health({"t": T0 - 30, "duty_age_s": {"prices": 30, "broker": 100}}, T0)[0] == 0
    assert health({"t": T0 - 30, "duty_age_s": {"prices": 900, "broker": 100}}, T0)[0] == 1


def test_records_are_append_only_and_baseline_written_once(tmp_path):
    ag, b, st, clock = make(tmp_path)
    advance(ag, clock, 2)
    base = st.read("baseline.json")
    b.pos[1]["walletImpact"]["currentValue"] = 200.0
    advance(ag, clock, 2)
    assert st.read("baseline.json") == base
    day = dt.datetime.fromtimestamp(clock.t, dt.timezone.utc).strftime("%Y-%m-%d")
    snaps = [e for e in st.events(day) if e["kind"] == "snapshot"]
    assert snaps[-1]["vs_vwrp"]["portfolio_return"] > 0


def test_uptime_counts_gaps(tmp_path):
    from market_agent.__main__ import uptime
    clock = Clock()
    st = Store(tmp_path, clock=clock, sleep=lambda s: None)
    for i in range(60):
        clock.t = T0 + i * 60
        if not 20 <= i < 30:  # a 10-minute outage
            st.event("heartbeat")
    u = uptime(st, T0 + 59 * 60, 1)
    assert len(u["gaps"]) == 1 and u["gaps"][0]["minutes"] == 11.0
    assert 0.80 < u["uptime"] < 0.82


def _book(b, msft=150.0, cash=0.0):
    b.cash = cash
    b.pos = [pos("INTC_US_EQ", 0.2, 0.2, 0, 17.0, 20.0), pos("MSFT_US_EQ", 0.3, 0.3, 0, msft, 160.0),
             pos("UBER_US_EQ", 0.1, 0.1, 0, 6.0, 6.0)]


def _settle(b):
    """Apply the fake broker's sells to its positions and cash, as the real broker would."""
    for t, q in b.orders[len(getattr(b, "_done", [])):]:
        for p in list(b.pos):
            if p["instrument"]["ticker"] == t and q < 0:
                v = p["walletImpact"]["currentValue"]
                frac = -q / p["quantity"]
                b.cash += v * frac
                p["quantity"] += q
                p["quantityAvailableForTrading"] += q
                p["walletImpact"]["currentValue"] = v * (1 - frac)
                if p["quantity"] <= 1e-9:
                    b.pos.remove(p)
    b._done = list(b.orders)


def test_satellite_rebalance_trims_pro_rata_then_buys_core(tmp_path):
    ag, b, st, clock = make(tmp_path, satellite=True, prices={"VWRP.L": 140.0})
    _book(b)
    total = 17.0 + 150.0 + 6.0
    for _ in range(12):
        advance(ag, clock, 1, by=30)
        _settle(b)
    sells = [o for o in b.orders if o[1] < 0]
    assert sells[0] == ("INTC_US_EQ", -0.2)                       # the authorised exit goes first
    assert ("UBER_US_EQ", -0.1) in sells                          # under £2 after the trim: sold in full
    msft = next(p for p in b.pos if p["instrument"]["ticker"] == "MSFT_US_EQ")
    assert msft["walletImpact"]["currentValue"] <= 0.05 * total + 0.01   # the 5% single-name cap binds
    assert len([o for o in b.orders if o[0] == "MSFT_US_EQ"]) == 1       # one trim, never repeated
    buys = [o for o in b.orders if o[1] > 0]
    assert buys and all(o[0] == "VWRPl_EQ" for o in buys) and b.orders.index(buys[0]) > b.orders.index(sells[-1])
    plan = st.read("rebalance_plan.json")
    assert plan["status"] == "done" and plan["targets"]["UBER_US_EQ"]["target_qty"] == 0.0


def test_sells_wait_for_their_market_and_block_the_core_buy(tmp_path):
    ag, b, st, clock = make(tmp_path, satellite=True, prices={"VWRP.L": 140.0})
    clock.t = T0 - 4 * 3600  # 11:00 UTC: LSE open, NASDAQ closed
    _book(b, cash=100.0)
    advance(ag, clock, 2, by=30)
    assert b.orders == []  # US sells wait; the core buy waits for them
    assert not [r for r in st.intents() if r.get("status") == "not_sent"]  # no refusal spam while waiting


def test_single_name_cap_in_the_risk_gate():
    lim = {**agent_mod.load_config()["limits"], "buy_whitelist": ["VWRPl_EQ", "MSFT_US_EQ"]}
    base = dict(control={"trading_enabled": True}, records=[], pending=[], limits=lim, day="2026-10-27",
                consecutive_errors=0, quote_ok=True, market_open=True, positions={})
    assert "cap" in execution.risk_check({"ticker": "MSFT_US_EQ", "quantity": 1, "value_gbp": 5, "post_weight": 0.06},
                                         **base)[0]
    assert "cap" in execution.risk_check({"ticker": "MSFT_US_EQ", "quantity": 1, "value_gbp": 5}, **base)[0]  # unknown: refused
    assert execution.risk_check({"ticker": "MSFT_US_EQ", "quantity": 1, "value_gbp": 5, "post_weight": 0.04}, **base) == []
    assert execution.risk_check({"ticker": "VWRPl_EQ", "quantity": 1, "value_gbp": 5, "post_weight": 0.9}, **base) == []


def _active_book(b):
    b.cash = 60.0  # 5% of the book is kept for the sleeve, so the core buys nothing
    b.pos = [pos("VWRPl_EQ", 6.0, 6.0, 0, 840.0, 840.0, ccy="GBP")]


def test_active_entry_on_a_5pct_drop_then_stop_loss_exit(tmp_path):
    prices = {"VWRP.L": 140.0, "GBPUSD=X": 1.25}
    ag, b, st, clock = make(tmp_path, active_on=True, prices=prices)
    _active_book(b)
    get = fake_get(clock, prices)

    def dropped(url, params):  # JPM 5.5% below its previous close
        d = get(url, params)
        if url == feeds.SPARK and "JPM" in d:
            d["JPM"]["close"] = [94.5, 94.5]
            d["JPM"]["previousClose"] = 100.0
        return d
    ag.get = dropped
    advance(ag, clock, 1, by=30)
    buys = [o for o in b.orders if o[0] == "JPM_US_EQ"]
    assert len(buys) == 1 and buys[0][1] > 0
    rec = next(r for r in execution.latest_intents(st.intents()).values() if r["ticker"] == "JPM_US_EQ")
    assert rec["signal"]["strategy"] == "drop_rebound" and rec["signal"]["stop"] == 0.08
    assert 0.019 < rec["value_gbp"] / 900.0 < 0.021                     # 2% of the book
    # the fill lands, then the price falls through the 8% stop
    b.pos.append(pos("JPM_US_EQ", buys[0][1], buys[0][1], 0, rec["value_gbp"], rec["value_gbp"]))
    b.cash -= rec["value_gbp"]

    def crashed(url, params):
        d = dropped(url, params)
        if url == feeds.SPARK and "JPM" in d:
            d["JPM"]["close"] = [86.0, 86.0]
            d["JPM"]["previousClose"] = 86.5
        return d
    ag.get = crashed
    advance(ag, clock, 2, by=301)
    sells = [o for o in b.orders if o[0] == "JPM_US_EQ" and o[1] < 0]
    assert len(sells) == 1
    ex = next(r for r in execution.latest_intents(st.intents()).values()
              if (r.get("signal") or {}).get("type") == "active_exit")
    assert ex["signal"]["why"] == "stop" and ex["signal"]["entry_id"] == rec["id"]


def test_core_keeps_cash_for_the_active_sleeve(tmp_path):
    ag, b, st, clock = make(tmp_path, active_on=True, prices={"VWRP.L": 140.0, "GBPUSD=X": 1.25})
    _active_book(b)
    b.cash = 40.0  # below 5% of a £880 book plus the £20 threshold
    advance(ag, clock, 2)
    assert b.orders == []


def test_kill_rule_disables_a_strategy_that_trails_vwrp():
    from market_agent import active
    cfg = agent_mod.load_config()
    recs = []
    for i in range(30):
        e = {"id": f"e{i}", "ticker": "JPM_US_EQ", "status": "filled", "t": i, "value_gbp": 20,
             "signal": {"type": "active_entry", "strategy": "drop_rebound", "vwrp_px": 100.0},
             "broker": {"fill": {"walletImpact": {"netValue": 20.0, "taxes": [{"quantity": -0.03}]}}}}
        x = {"id": f"x{i}", "ticker": "JPM_US_EQ", "status": "filled", "t": i + 0.5, "value_gbp": 20,
             "signal": {"type": "active_exit", "entry_id": f"e{i}", "vwrp_px": 101.0},
             "broker": {"fill": {"walletImpact": {"netValue": 20.1, "taxes": [{"quantity": -0.03}]}}}}
        recs += [e, x]
    sc = active.strategy_scores(recs)
    assert sc["drop_rebound"]["n"] == 30 and sc["drop_rebound"]["avg_ret"] < sc["drop_rebound"]["avg_vwrp_ret"]
    new = active.kill_check(sc, cfg, {}, "2026-11-01T00:00:00Z")
    assert "drop_rebound" in new
    assert active.kill_check(sc, cfg, new, "t") == {}                      # disabled once
    assert active.kill_check({"x": {**sc["drop_rebound"], "n": 29}}, cfg, {}, "t") == {}
