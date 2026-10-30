"""Offline tests: a fake broker and fake feeds; any real network call fails the test."""
from __future__ import annotations

import datetime as dt
import time
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
                {"ticker": "UBER_US_EQ", "workingScheduleId": 71}, {"ticker": "CROX_US_EQ", "workingScheduleId": 71},
                {"ticker": "VWRPl_EQ", "workingScheduleId": 70}]

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

    def place_stop_order(self, ticker, quantity, stop_price):
        oid = 5000 + len(self.pending) + len(self.history)
        self.pending.append({"id": oid, "ticker": ticker, "type": "STOP", "quantity": quantity, "stopPrice": stop_price})
        return {"id": oid, "status": "NEW"}

    def cancel_order(self, oid):
        self.pending = [p for p in self.pending if p["id"] != oid]
        self.history.insert(0, {"order": {"id": oid, "ticker": "?", "status": "CANCELLED"}})

    def fill_stop(self, oid, net):
        p = next(p for p in self.pending if p["id"] == oid)
        self.pending.remove(p)
        self.pos = [x for x in self.pos if x["instrument"]["ticker"] != p["ticker"]]
        self.cash += net
        self.history.insert(0, {"order": {"id": oid, "ticker": p["ticker"], "status": "FILLED", "side": "SELL",
                                          "createdAt": iso(self.clock())},
                                "fill": {"quantity": -p["quantity"], "price": p["stopPrice"],
                                         "walletImpact": {"netValue": net, "taxes": [{"quantity": -0.03}]}}})

    def history_orders(self, ticker=None, limit=50, max_pages=5):
        return [h for h in self.history if ticker in (None, h["order"]["ticker"]) or h["order"]["ticker"] == "?"]

    def get_order(self, oid):
        raise ApiErr("404")


def fake_get(clock, prices=None, falling=()):
    prices = prices or {}

    def get(url, params):
        if url.startswith("https://query1.finance.yahoo.com/v8/finance/chart/"):
            sym = url.rsplit("/", 1)[-1]
            p = prices.get(sym, 100.0) or 100.0
            n = 260  # a year of daily bars: a steady rise to today's price, or a steady fall for `falling`
            closes = [p * (1.6 - 0.6 * i / (n - 1)) if sym in falling else p * (0.7 + 0.3 * i / (n - 1)) for i in range(n)]
            return {"chart": {"result": [{"indicators": {"quote": [{"close": closes, "volume": [1e6] * n}]}}]}}
        if url.startswith("https://api.nasdaq.com/"):
            return {"data": {"rows": [{"symbol": s} for s in getattr(get, "earnings", {}).get(params["date"], [])]}}
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
        if url.startswith("https://wikimedia.org/") and "Crocs" in url and url.endswith("/20261030"):  # attention takes off
            n = 420
            return {"items": [{"timestamp": "2026010100", "views": 1000 + 40 * (d % 5) if d < n - 28 else 2500 + 40 * (d - n + 28)}
                              for d in range(n)]}
        if url.startswith("https://wikimedia.org/"):
            spike = "Oracle" in url
            return {"items": [{"timestamp": f"202610{d:02d}00", "views": 1000 + 13 * (d % 3) + (9000 if spike and d == 29 else 0)}
                              for d in range(1, 30)]}
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
    ag.cfg["satellite"].update(target_weight=0.20, rebalance_above=0.22)  # the pro rata case (agent-1.1)
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


def test_target_zero_sells_every_passive_pick(tmp_path):
    ag, b, st, clock = make(tmp_path, satellite=True, prices={"VWRP.L": 140.0})
    _book(b)
    for _ in range(12):
        advance(ag, clock, 1, by=30)
        _settle(b)
    assert {p["instrument"]["ticker"] for p in b.pos} == set()
    assert any(o[0] == "VWRPl_EQ" and o[1] > 0 for o in b.orders)


def _jpm_entry(tmp_path):
    prices = {"VWRP.L": 140.0, "GBPUSD=X": 1.25}
    ag, b, st, clock = make(tmp_path, active_on=True, prices=prices)
    _active_book(b)
    get = fake_get(clock, prices)

    def dropped(url, params):
        d = get(url, params)
        if url == feeds.SPARK and "JPM" in d:
            d["JPM"]["close"] = [94.5, 94.5]
            d["JPM"]["previousClose"] = 100.0
        return d
    ag.get = dropped
    advance(ag, clock, 1, by=30)
    q = next(o for o in b.orders if o[0] == "JPM_US_EQ")[1]
    rec = next(r for r in execution.latest_intents(st.intents()).values() if r["ticker"] == "JPM_US_EQ")
    b.pos.append(pos("JPM_US_EQ", q, q, 0, rec["value_gbp"], rec["value_gbp"]))
    b.cash -= rec["value_gbp"]
    advance(ag, clock, 1, by=301)
    return ag, b, st, clock, rec, q


def test_open_trade_gets_a_broker_stop_and_its_fill_closes_the_trade(tmp_path):
    from market_agent import active
    ag, b, st, clock, rec, q = _jpm_entry(tmp_path)
    stops = [p for p in b.pending if p["type"] == "STOP"]
    assert len(stops) == 1 and stops[0]["quantity"] == -q and stops[0]["stopPrice"] == round(94.5 * 0.92, 2)
    advance(ag, clock, 1, by=301)
    assert len([p for p in b.pending if p["type"] == "STOP"]) == 1           # placed once, not repeated
    b.fill_stop(stops[0]["id"], net=rec["value_gbp"] * 0.9)
    advance(ag, clock, 1, by=301)
    t = active.trades(st.intents())
    assert t[0]["exit"] and t[0]["exit"]["signal"]["why"] == "broker_stop"
    assert active.closed_result(t[0])["pnl_gbp"] < 0
    assert not [o for o in b.orders if o[0] == "JPM_US_EQ" and o[1] < 0]     # no market sell on top


def test_agent_exit_cancels_the_broker_stop_first(tmp_path):
    ag, b, st, clock, rec, q = _jpm_entry(tmp_path)
    assert [p for p in b.pending if p["type"] == "STOP"]
    clock.t = T0 + 11 * 86400                                                 # past the 10-day drop_rebound time stop
    advance(ag, clock, 3, by=301)
    assert not [p for p in b.pending if p["type"] == "STOP"]                 # cancelled
    sells = [o for o in b.orders if o[0] == "JPM_US_EQ" and o[1] < 0]
    assert sells == [("JPM_US_EQ", -q)]


def test_attention_spike_is_logged_forward_without_trading(tmp_path):
    ag, b, st, clock = make(tmp_path, active_on=True, prices={"VWRP.L": 140.0, "GBPUSD=X": 1.25})
    _active_book(b)
    advance(ag, clock, 1, by=30)
    ev = st.events(iso(clock())[:10])
    att = next(e for e in ev if e["kind"] == "attention")
    assert len(att["rows"]) == 15 and not [r for r in att["rows"] if "error" in r]
    sig = [e for e in ev if e["kind"] == "attention_signal"]
    assert [e["ticker"] for e in sig] == ["ORCL_US_EQ"] and sig[0]["z"] > 3 and sig[0]["traded"] is False
    assert not [o for o in b.orders if o[0] == "ORCL_US_EQ"]


def test_review_scores_and_gates_entries(tmp_path):
    from market_agent import review
    up = review.factors([70 + 0.12 * i for i in range(260)], [1e6] * 260)
    down = review.factors([130 - 0.12 * i for i in range(260)], [1e6] * 260)
    su, sd = review.score(up), review.score(down)
    assert su["long"] > 0.5 and sd["long"] < -0.5 and su["composite"] > 0.25 > sd["composite"]
    cfg = agent_mod.load_config()["active"]["review"]
    now = 1000.0
    ok = {"t": now, "scores": su, "factors": up, "earnings": None}
    assert review.entry_ok("breakout_momentum", ok, cfg, now)[0]
    assert not review.entry_ok("breakout_momentum", {**ok, "scores": sd}, cfg, now)[0]
    assert not review.entry_ok("drop_rebound", {**ok, "scores": sd}, cfg, now)[0]     # no dip-buying in a downtrend
    assert not review.entry_ok("breakout_momentum", {**ok, "earnings": "2026-11-02"}, cfg, now)[0]
    assert not review.entry_ok("breakout_momentum", None, cfg, now)[0]                # no review: no entry
    assert not review.entry_ok("breakout_momentum", ok, cfg, now + cfg["max_age_s"] + 1)[0]


def test_drop_in_a_downtrend_is_not_bought(tmp_path):
    prices = {"VWRP.L": 140.0, "GBPUSD=X": 1.25}
    ag, b, st, clock = make(tmp_path, active_on=True, prices=prices)
    _active_book(b)
    get = fake_get(clock, prices, falling=("JPM",))

    def dropped(url, params):
        d = get(url, params)
        if url == feeds.SPARK and "JPM" in d:
            d["JPM"]["close"] = [94.5, 94.5]
            d["JPM"]["previousClose"] = 100.0
        return d
    ag.get = dropped
    advance(ag, clock, 1, by=30)
    assert not [o for o in b.orders if o[0] == "JPM_US_EQ"]
    dec = [e for e in st.events(iso(clock())[:10]) if e["kind"] == "decision"]
    assert any("review blocks" in n for e in dec for n in e["notes"])


def test_review_turning_against_an_open_trade_exits_it():
    from market_agent import active
    e = {"id": "e1", "ticker": "JPM_US_EQ", "status": "filled", "t": 0.0,
         "signal": {"type": "active_entry", "strategy": "breakout_momentum", "entry_px": 100.0, "stop": 0.05,
                    "take_profit": 0.10, "time_stop_s": 5 * 86400}}
    positions = {"JPM_US_EQ": pos("JPM_US_EQ", 0.2, 0.2, 0, 20.0, 20.0)}
    q = lambda t: {"price": 99.0}  # noqa: E731 - inside the stop and the take-profit
    assert active.exit_orders([e], positions, q, 3600.0, 140.0) == []
    out = active.exit_orders([e], positions, q, 3600.0, 140.0, lambda t, s: "review")
    assert len(out) == 1 and out[0][6]["why"] == "review" and out[0][1] == -0.2


def test_social_attention_and_candidate_rules():
    from market_agent import social
    flat = [("d", 1000 + 40 * (d % 5)) for d in range(392)]
    assert social.attention(flat[:300]) is None                               # not enough history: no signal
    a = social.attention(flat)
    assert abs(a["z"]) < 3
    hot = social.attention(flat[:-28] + [("d", 2500 + 40 * d) for d in range(28)])
    assert hot["z"] > 3 and hot["rising"]
    sc = agent_mod.load_config()["active"]["social"]
    assert social.judge({**hot, "ret20": 0.05}, sc)["candidate"]
    assert not social.judge({**hot, "ret20": 0.20}, sc)["candidate"]           # the crowd got there first
    assert not social.judge({**hot, "rising": False, "ret20": 0.0}, sc)["candidate"]
    assert not social.judge({"error": "pageviews: HTTP 404"}, sc)["candidate"]  # missing data: no trade
    fri = dt.datetime(2026, 10, 30, tzinfo=dt.timezone.utc).timestamp()
    assert social.signal_friday(fri + 20 * 3600) == "2026-10-23"              # before Friday's close
    assert social.signal_friday(fri + 21.5 * 3600) == "2026-10-30"
    assert social.signal_friday(fri + 3 * 86400) == "2026-10-30"              # Monday
    assert social.exit_why({"rows": {"X": {"z": 0.4}}}, "X", sc) == "attention"
    assert social.exit_why({"rows": {"X": {"z": 2.0}}}, "X", sc) is None
    assert social.exit_why(None, "X", sc) is None                             # unknown attention: hold


def test_social_trend_scans_on_the_weekend_buys_monday_and_exits_when_attention_fades(tmp_path):
    from market_agent import active
    ag, b, st, clock = make(tmp_path, active_on=True, prices={"VWRP.L": 140.0, "GBPUSD=X": 1.25})
    _active_book(b)
    clock.t = dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.timezone.utc).timestamp()   # Saturday
    advance(ag, clock, 4, by=150)
    scan = st.read("social.json")
    assert scan["friday"] == "2026-10-30" and len(scan["rows"]) == 32
    assert [t for t, r in scan["rows"].items() if r["candidate"]] == ["CROX_US_EQ"]
    assert "unavailable" in scan["confirmation"]
    assert not [o for o in b.orders if o[0] == "CROX_US_EQ"]                 # markets shut at the weekend
    clock.t = dt.datetime(2026, 11, 2, 15, 0, tzinfo=dt.timezone.utc).timestamp()    # Monday, NASDAQ open
    advance(ag, clock, 1, by=30)
    buys = [o for o in b.orders if o[0] == "CROX_US_EQ"]
    assert len(buys) == 1 and buys[0][1] > 0
    rec = next(r for r in execution.latest_intents(st.intents()).values() if r["ticker"] == "CROX_US_EQ")
    sig = rec["signal"]
    assert sig["strategy"] == "social_trend" and sig["stop"] == 0.12 and sig["take_profit"] == 0.25
    assert sig["friday"] == "2026-10-30" and sig["attention"]["z"] > 3
    b.pos.append(pos("CROX_US_EQ", buys[0][1], buys[0][1], 0, rec["value_gbp"], rec["value_gbp"]))
    b.cash -= rec["value_gbp"]
    advance(ag, clock, 1, by=301)
    stop = [p for p in b.pending if p["ticker"] == "CROX_US_EQ"]
    assert len(stop) == 1 and stop[0]["stopPrice"] == 88.0                    # the 12% broker stop
    advance(ag, clock, 2, by=301)
    assert len([o for o in b.orders if o[0] == "CROX_US_EQ"]) == 1            # bought once, held
    st._replace("social.json", {**scan, "rows": {**scan["rows"], "CROX_US_EQ": {**scan["rows"]["CROX_US_EQ"], "z": 0.5}}})
    advance(ag, clock, 3, by=301)
    sells = [o for o in b.orders if o[0] == "CROX_US_EQ" and o[1] < 0]
    assert sells == [("CROX_US_EQ", -buys[0][1])]
    ex = next(r for r in execution.latest_intents(st.intents()).values()
              if (r.get("signal") or {}).get("type") == "active_exit")
    assert ex["signal"]["why"] == "attention" and ex["signal"]["strategy"] == "social_trend"
    assert active.open_trades(st.intents()) == []


DEAL_8K = ("Acme Corp entered into an Agreement and Plan of Merger with Parent. Each share will be converted into the "
           "right to receive $20.00 per share in cash, without interest. The transaction is expected to close in the "
           "first quarter of 2027, subject to customary conditions.")
DEAL_PROXY = ("PROXY. The merger agreement provides that each share of Acme common stock will be converted into the right "
              "to receive $20.00 per share in cash. If Parent receives an unsolicited proposal, the board may recommend "
              "that stockholders reject such tender offer. We expect the merger to be completed in the first quarter "
              "of 2027.")


def _efts(hits):
    return {"hits": {"hits": [{"_id": f"{a}:{f}", "_source": {"form": form, "file_date": d, "file_type": ft,
                                                               "items": items, "display_names": [name]}}
                              for a, f, form, d, ft, items, name in hits]}}


def test_merger_filings_parse_and_deal_filters():
    from market_agent import merger
    p = merger.parse(DEAL_PROXY, "DEFM14A")
    assert p["price"] == 20.0 and p["agreement"] and not p["mixed"] and not p["hostile"]   # boilerplate is not hostile
    assert time.gmtime(p["close"])[:3] == (2027, 3, 31)
    mixed = merger.parse("Agreement and Plan of Merger: $10.00 per share in cash and 0.5 shares of Parent stock.")
    assert mixed["mixed"]
    rej = merger.parse("The Board unanimously recommends that stockholders reject the Offer. Agreement", "SC 14D9")
    assert rej["hostile"]
    name = "Acme Corp  (ACME)  (CIK 0000000123)"
    hits = merger.search(lambda u, p: _efts([("0001-26-1", "p.htm", "DEFM14A", "2026-10-01", "DEFM14A", [], name),
                                             ("0001-26-2", "k.htm", "8-K", "2026-09-01", "8-K", ["1.01"], name)]),
                         "2026-05-01", "2026-10-30")
    assert hits[0]["target"] == {"ticker": "ACME", "cik": "0000000123", "name": "Acme Corp"}
    docs = {hits[0]["id"]: p, hits[1]["id"]: merger.parse(DEAL_8K, "8-K")}
    d = merger.build_deals(hits, docs, lambda tk: tk + "_US_EQ")["ACME_US_EQ"]
    assert d["eligible"] and d["offer"] == 20.0
    only_8k = merger.build_deals(hits[1:], docs, lambda tk: tk + "_US_EQ")
    assert only_8k == {}                                                        # an 8-K alone may be the acquirer's
    one = merger.build_deals(hits[:1], docs, lambda tk: tk + "_US_EQ")["ACME_US_EQ"]
    assert not one["eligible"] and "two filings" in one["why"]
    cfg = agent_mod.load_config()
    now = dt.datetime(2026, 11, 2, 15, tzinfo=dt.timezone.utc).timestamp()
    st = {"deals": {"ACME_US_EQ": d}}
    q = lambda px: (lambda t: {"price": px})  # noqa: E731
    args = (cfg, [], {}, None, 1.25, 1000.0, 100.0, "2026-11-02", now, 140.0, {})
    o, _ = merger.entry_orders(*args[:3], q(19.0), *args[4:], st)
    assert len(o) == 1 and o[0][6]["strategy"] == "merger_arb" and o[0][6]["stop"] == 0.10   # 5.3% to March: ok
    assert merger.entry_orders(*args[:3], q(19.9), *args[4:], st)[0] == []     # 0.5% spread: too thin
    assert merger.entry_orders(*args[:3], q(15.0), *args[4:], st)[0] == []     # 33%: the market doubts it
    assert merger.entry_orders(*args[:3], q(19.0), *args[4:], {**st, "terminated": {"ACME_US_EQ": {}}})[0] == []


def test_merger_arb_buys_an_agreed_deal_and_exits_on_termination(tmp_path):
    from market_agent import merger
    ag, b, st, clock = make(tmp_path, active_on=True, prices={"VWRP.L": 140.0, "GBPUSD=X": 1.25, "ACME": 19.0})
    _active_book(b)
    b.instruments_extra = True
    name = "Acme Corp  (ACME)  (CIK 0000000123)"
    term = []

    def sec(url, params):
        if url == merger.EFTS and params.get("forms") == "8-K":
            return _efts(term)
        if url == merger.EFTS:
            return _efts([("0001-26-1", "p.htm", "DEFM14A", "2026-10-01", "DEFM14A", [], name),
                          ("0001-26-2", "k.htm", "8-K", "2026-09-01", "8-K", ["1.01"], name)])
        return DEAL_PROXY if url.endswith("p.htm") else DEAL_8K
    ag.sec_get = sec
    ag.schedule_of["ACME_US_EQ"] = 71
    orig = b.instruments
    b.instruments = lambda: orig() + [{"ticker": "ACME_US_EQ", "workingScheduleId": 71}]
    advance(ag, clock, 3, by=301)
    assert st.read("merger.json")["deals"]["ACME_US_EQ"]["eligible"]
    buys = [o for o in b.orders if o[0] == "ACME_US_EQ"]
    assert len(buys) == 1 and buys[0][1] > 0
    rec = next(r for r in execution.latest_intents(st.intents()).values() if r["ticker"] == "ACME_US_EQ")
    b.pos.append(pos("ACME_US_EQ", buys[0][1], buys[0][1], 0, rec["value_gbp"], rec["value_gbp"]))
    b.cash -= rec["value_gbp"]
    advance(ag, clock, 1, by=301)
    assert [p for p in b.pending if p["ticker"] == "ACME_US_EQ"][0]["stopPrice"] == 17.1   # the 10% broker stop
    term.append(("0001-26-9", "t.htm", "8-K", iso(clock())[:10], "8-K", ["1.02", "9.01"], name))
    clock.t = T0 + 86400                                                              # next day: a new deal scan, market open
    advance(ag, clock, 3, by=301)
    ex = next(r for r in execution.latest_intents(st.intents()).values()
              if (r.get("signal") or {}).get("type") == "active_exit")
    assert ex["signal"]["why"] == "deal_terminated"


def _bars(c, h=None, l=None, v=None, t=None, o=None):
    n = len(c)
    return {"t": t or [None] * n, "o": o or list(c), "h": h or list(c), "l": l or list(c), "c": list(c),
            "v": v or [1e6] * n}


def test_vol_squeeze_and_gap_go_rules():
    from market_agent import swing
    sc = agent_mod.load_config()["active"]["swing"]["squeeze"]
    gc = agent_mod.load_config()["active"]["swing"]["gap"]
    c = [100 + 0.02 * i + (4 if i % 2 else -4) for i in range(270)] + [106 + 0.02 * i + (0.2 if i % 2 else -0.2)
                                                                       for i in range(29)]
    v = [1e6] * len(c)
    quiet = _bars(c, v=v)
    assert not swing.squeeze(quiet, sc)["signal"]                                   # no breakout yet
    brk = _bars(c + [109.0], v=v + [3e6])
    r = swing.squeeze(brk, sc)
    assert r["signal"] and r["pct"] <= 0.10 and r["vol_x"] >= 1.5, r
    assert not swing.squeeze(_bars(c + [109.0], v=v + [1.2e6]), sc)["signal"]       # weak volume
    assert not swing.squeeze(_bars(c[-200:] + [109.0], v=v[-200:] + [3e6]), sc)["signal"]   # too little history
    tb = _bars([100.0] * 20, h=[100.0] * 19 + [111.0], l=[99.0] * 10 + [104.0] * 10, t=[float(i) for i in range(20)])
    assert swing.squeeze_trailing(tb, 0.0, 100.0, 103.0, sc)                        # was up 11%, now under the 10-day low
    assert not swing.squeeze_trailing(tb, 0.0, 100.0, 105.0, sc)
    assert not swing.squeeze_trailing(_bars([100.0] * 20, t=[float(i) for i in range(20)]), 0.0, 100.0, 95.0, sc)
    o = 1_000_000.0
    mins = [o + 60 * i for i in range(40)]
    g = _bars([104.0 + 0.02 * i for i in range(40)], t=mins, o=[104.0] * 40,
              h=[104.1 + 0.02 * i for i in range(40)], l=[103.6] + [103.9 + 0.02 * i for i in range(39)])
    ok = swing.gap_check(g, 100.0, o, o + 2100, gc)
    assert ok["signal"] and ok["low30"] == 103.6 and 0.039 < ok["gap"] < 0.041
    assert not swing.gap_check(g, 100.0, o, o + 1200, gc)["signal"]                 # before the check window
    assert not swing.gap_check(g, 90.0, o, o + 2100, gc)["signal"]                  # a 15% gap is too big
    fade = _bars([104.0] + [100.5] * 39, t=mins, o=[104.0] * 40)
    assert "held" in swing.gap_check(fade, 100.0, o, o + 2100, gc)["why"]


def test_gap_go_buys_after_the_open_and_is_flat_by_the_close(tmp_path):
    prices = {"VWRP.L": 140.0, "GBPUSD=X": 1.25}
    ag, b, st, clock = make(tmp_path, active_on=True, prices=prices)
    _active_book(b)
    day0 = dt.datetime(2026, 10, 27, tzinfo=dt.timezone.utc).timestamp()
    open_t = day0 + 13.5 * 3600
    clock.t = open_t + 35 * 60
    base = fake_get(clock, prices)

    def get(url, params):
        if "JPM" in url and params.get("interval") == "1m":
            n = int((clock() - open_t) // 60)
            return {"chart": {"result": [{"timestamp": [open_t + 60 * i for i in range(n)], "indicators": {"quote": [{
                "open": [104.0] * n, "high": [104.2 + 0.01 * i for i in range(n)],
                "low": [103.5] + [103.9] * (n - 1), "close": [104.0 + 0.015 * i for i in range(n)],
                "volume": [1e4] * n}]}}]}}
        d = base(url, params)
        if url == feeds.SPARK and "JPM" in d:
            d["JPM"]["close"] = [104.5, 104.5]
            d["JPM"]["previousClose"] = 100.0
        return d
    ag.get = get
    advance(ag, clock, 2, by=30)
    chk = [e for e in st.events("2026-10-27") if e["kind"] == "gap_check"]
    assert [e["ticker"] for e in chk] == ["JPM_US_EQ"] and chk[0]["signal"]
    buys = [o for o in b.orders if o[0] == "JPM_US_EQ"]
    assert len(buys) == 1
    rec = next(r for r in execution.latest_intents(st.intents()).values() if r["ticker"] == "JPM_US_EQ")
    assert rec["signal"]["strategy"] == "gap_go" and rec["signal"]["take_profit"] == 0.06
    assert abs(104.5 * (1 - rec["signal"]["stop"]) - 103.5) < 0.01               # stop at the first-30-minute low
    b.pos.append(pos("JPM_US_EQ", buys[0][1], buys[0][1], 0, rec["value_gbp"], rec["value_gbp"]))
    b.cash -= rec["value_gbp"]
    advance(ag, clock, 2, by=301)
    assert len([o for o in b.orders if o[0] == "JPM_US_EQ"]) == 1                 # held through the day
    clock.t = day0 + 19.8 * 3600                                                  # 12 minutes before the close
    advance(ag, clock, 3, by=30)
    sells = [o for o in b.orders if o[0] == "JPM_US_EQ" and o[1] < 0]
    assert sells == [("JPM_US_EQ", -buys[0][1])]
    ex = next(r for r in execution.latest_intents(st.intents()).values()
              if (r.get("signal") or {}).get("type") == "active_exit")
    assert ex["signal"]["why"] == "flat_by_close"


def test_gap_check_slept_through_is_missed_not_traded(tmp_path):
    ag, b, st, clock = make(tmp_path, active_on=True, prices={"VWRP.L": 140.0, "GBPUSD=X": 1.25})
    _active_book(b)
    advance(ag, clock, 1, by=30)                                                  # T0 is 90 minutes after the open
    missed = [e["ticker"] for e in st.events("2026-10-27") if e["kind"] == "gap_go_missed"]
    assert sorted(missed) == ["JPM_US_EQ", "UBER_US_EQ"]                         # the names with a known calendar
    advance(ag, clock, 2, by=30)
    assert len([e for e in st.events("2026-10-27") if e["kind"] == "gap_go_missed"]) == 2   # logged once a day
    assert not [e for e in st.events("2026-10-27") if e["kind"] == "gap_check"]
