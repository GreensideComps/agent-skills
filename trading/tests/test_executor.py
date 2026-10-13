"""End-to-end bot runs against the fake demo API."""
import pytest

from conftest import INSTRUMENTS, NOW, FakeQuotes, FakeT212, exchanges_for
from t212bot.config import SafetyError
from t212bot.executor import Bot


@pytest.fixture
def make_bot(make_client, cfg, journal, tmp_path):
    def _make(fake, quotes=None, now=NOW, env=None):
        return Bot(make_client(fake), cfg, journal, quotes=quotes or FakeQuotes(), now=lambda: now,
                   sleep=lambda s: None, instruments=INSTRUMENTS, exchanges=exchanges_for(now),
                   env=env or {}, kill_file=tmp_path / "KILL")
    return _make


def test_dry_run_places_nothing(make_bot, journal):
    fake = FakeT212()
    res = make_bot(fake).run(execute=False)
    assert res["status"] == "dry_run" and fake.posts == []
    assert journal.events("plan")[0]["needs_rebalance"] is True


def test_execute_initial_deploy_and_reconcile(make_bot, journal):
    fake = FakeT212()
    res = make_bot(fake).run(execute=True)
    assert res["status"] == "executed"
    assert {p["ticker"] for p in fake.posts} == {"VWRPl_EQ", "IWMOl_EQ"}
    assert all(p["quantity"] > 0 and p["extendedHours"] is False for p in fake.posts)
    assert 0 < fake.cash < 3.0                              # ~1.5% buffer kept
    rec = journal.events("order_reconciled")
    assert len(rec) == 2 and all(r["status"] == "FILLED" for r in rec)
    assert all(abs(r["slippage_bps_vs_reference"]) < 1e-6 for r in rec)  # fake fills at the reference price
    assert journal.load_state()["last_rebalance_month"] == "2026-10"
    # second run: nothing to do, no new orders
    n = len(fake.posts)
    assert make_bot(fake).run(execute=True)["status"] == "no_action" and len(fake.posts) == n


def test_kill_switch_blocks_orders(make_bot, journal):
    fake = FakeT212()
    res = make_bot(fake, env={"T212BOT_KILL": "1"}).run(execute=True)
    assert res["status"] == "halted" and fake.posts == []
    assert journal.snapshots()  # still records the account


def test_pending_orders_block_new_orders(make_bot):
    fake = FakeT212()
    fake.pending = [{"id": 1, "ticker": "VWRPl_EQ", "status": "NEW", "quantity": 0.1}]
    assert make_bot(fake).run(execute=True)["status"] == "skipped" and fake.posts == []


def test_market_closed_defers(make_bot):
    fake = FakeT212()
    res = make_bot(fake, now=NOW.replace(hour=18)).run(execute=True)
    assert res["status"] == "deferred" and fake.posts == []


def test_stale_quotes_block_execution(make_bot):
    fake = FakeT212()
    with pytest.raises(SafetyError):
        make_bot(fake, quotes=FakeQuotes(as_of=NOW.replace(hour=6))).run(execute=True)
    assert fake.posts == []


def test_price_divergence_vs_t212_blocks(make_bot):
    fake = FakeT212(cash=50.0, positions={"VWRPl_EQ": 0.3})
    q = FakeQuotes(prices={"VWRP.L": (160.0, "GBP"), "IWMO.L": (116.95, "USD")})  # 9% off T212's 146.40
    with pytest.raises(SafetyError):
        make_bot(fake, quotes=q).run(execute=True)
    assert fake.posts == []


def test_precision_fallback_learns_decimals(make_bot, journal):
    fake = FakeT212()
    fake.max_decimals = 2
    res = make_bot(fake).run(execute=True)
    assert res["status"] == "executed"
    ok = [p for p in fake.posts if len(f"{abs(p['quantity']):.10f}".rstrip('0').split('.')[1]) <= 2]
    assert {p["ticker"] for p in ok} == {"VWRPl_EQ", "IWMOl_EQ"}
    learned = journal.load_state()["qty_decimals"]
    assert set(learned) == {"VWRPl_EQ", "IWMOl_EQ"} and all(v < 4 for v in learned.values())
    # every order the server accepted respected its precision limit
    assert all(len(f"{abs(q):.10f}".rstrip("0").split(".")[1]) <= 2 for q in fake.pos.values())
    assert journal.events("order_rejected")


def test_ambiguous_order_stops_run_without_resend(make_bot, journal):
    fake = FakeT212()
    fake.post_status = [500]
    with pytest.raises(SafetyError):
        make_bot(fake).run(execute=True)
    assert len(fake.posts) == 0 or len(fake.posts) == 1
    assert journal.events("order_ambiguous") and journal.events("order_ambiguous_resolution")


def test_rebalance_sells_before_buys(make_bot):
    # start overweight VWRP after a rally
    fake = FakeT212(cash=1.0, positions={"VWRPl_EQ": 0.5, "IWMOl_EQ": 0.2})
    res = make_bot(fake).run(execute=True)
    assert res["status"] == "executed"
    sides = ["SELL" if p["quantity"] < 0 else "BUY" for p in fake.posts]
    assert sides[0] == "SELL" and "BUY" in sides
    total = fake.cash + fake.value()
    w = fake.pos["VWRPl_EQ"] * fake.px_gbp("VWRPl_EQ") / total
    assert abs(w - 0.4925) < 0.02


def test_unknown_ticker_refused(make_bot, cfg):
    cfg.targets = {"NOPE_EQ": 1.0}
    cfg.yahoo_symbols["NOPE_EQ"] = "NOPE"
    with pytest.raises(SafetyError):
        make_bot(FakeT212()).run(execute=False)


def test_insufficient_funds_right_after_fill_is_retried_with_fresh_cash(make_bot, journal):
    fake = FakeT212()
    orig = fake._post
    calls = {"n": 0}

    def flaky(path, payload):
        calls["n"] += 1
        if calls["n"] == 2:   # second order hits a transient funds hold
            from t212bot.client import Response
            return Response(400, {}, b'{"type":"/api-errors/insufficient-free-for-stocks-buy","detail":"Insufficient funds"}')
        return orig(path, payload)
    fake._post = flaky
    res = make_bot(fake).run(execute=True)
    assert res["status"] == "executed"
    assert set(fake.pos) == {"VWRPl_EQ", "IWMOl_EQ"}
    assert any(e.get("will_retry_with_fresh_cash") for e in journal.events("order_rejected"))


def test_insufficient_funds_gives_up_cleanly(make_bot, journal):
    from t212bot.client import ApiError, Response
    fake = FakeT212()
    orig = fake._post
    fake._post = lambda path, payload: (Response(400, {}, b'{"type":"/api-errors/insufficient-free-for-stocks-buy"}')
                                        if payload["ticker"] == "VWRPl_EQ" else orig(path, payload))
    with pytest.raises(ApiError):
        make_bot(fake).run(execute=True)
    assert "VWRPl_EQ" not in fake.pos


def test_learns_trading212_buy_reserve_and_stays_invested(make_bot, journal):
    fake = FakeT212()
    fake.buy_reserve = 0.05
    res = make_bot(fake).run(execute=True)
    assert res["status"] == "executed" and set(fake.pos) == {"VWRPl_EQ", "IWMOl_EQ"}
    r = journal.load_state()["buy_reserve"]
    assert r.get("upper", 1) >= 0.05 - 1e-9          # every accepted buy left >= 5% headroom
    assert fake.cash / (fake.cash + fake.value()) < 0.10


def test_reserve_bisection(make_bot):
    bot = make_bot(FakeT212())
    st = {"buy_reserve": {"lower": 0.04, "upper": 0.08}}
    assert abs(bot._reserve(st) - 0.06) < 1e-12
    bot._learn_reserve(st, cash=106.0, value=100.0, accepted=True)    # 6% headroom worked
    assert st["buy_reserve"]["upper"] == 0.06
    bot._learn_reserve(st, cash=104.5, value=100.0, accepted=False)   # 4.5% failed
    assert st["buy_reserve"]["lower"] == 0.045


def test_loose_upper_bound_does_not_starve_later_buys(make_bot):
    bot = make_bot(FakeT212())
    st = {}
    bot._learn_reserve(st, cash=100.0, value=49.0, accepted=True)     # 104% headroom: uninformative
    assert bot._reserve(st) == bot.DEFAULT_RESERVE
