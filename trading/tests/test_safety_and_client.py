import pytest

from conftest import FakeT212
from t212bot.client import AmbiguousOrderError, ApiError, NotFound, Response, T212Client
from t212bot.config import Credentials, SafetyError, StrategyConfig, kill_switch_engaged, load_credentials


# ---------------------------------------------------------------- config / safety
@pytest.mark.parametrize("env_value", ["live", "", "DEMO", "production"])
def test_credentials_refuse_anything_but_demo(env_value):
    with pytest.raises(SafetyError):
        load_credentials({"T212_ENV": env_value, "T212_API_KEY": "k", "T212_API_SECRET": "s"})


def test_credentials_require_both_and_no_whitespace():
    with pytest.raises(SafetyError):
        load_credentials({"T212_ENV": "demo", "T212_API_KEY": "k"})
    with pytest.raises(SafetyError):
        load_credentials({"T212_ENV": "demo", "T212_API_KEY": "k ", "T212_API_SECRET": "s"})
    c = load_credentials({"T212_ENV": "demo", "T212_API_KEY": "k", "T212_API_SECRET": "s"})
    assert c.key == "k" and "k" not in repr(c) and "s" not in repr(c).replace("Credentials", "")


def test_kill_switch(tmp_path):
    kf = tmp_path / "KILL"
    assert kill_switch_engaged({}, kf) is None
    assert kill_switch_engaged({"T212BOT_KILL": "0"}, kf) is None
    assert "T212BOT_KILL" in kill_switch_engaged({"T212BOT_KILL": "1"}, kf)
    kf.write_text("stop")
    assert "kill file" in kill_switch_engaged({}, kf)


def test_strategy_config_validation():
    base = dict(name="x", yahoo_symbols={"A": "a", "B": "b"})
    with pytest.raises(SafetyError):
        StrategyConfig(targets={"A": 0.7, "B": 0.5}, **base)       # leverage
    with pytest.raises(SafetyError):
        StrategyConfig(targets={"A": 1.2, "B": -0.2}, **base)      # shorting
    with pytest.raises(SafetyError):
        StrategyConfig(targets={"C": 1.0}, **base)                 # no price symbol
    StrategyConfig(targets={"A": 0.5, "B": 0.5}, **base)


def test_shipped_strategy_config_is_valid():
    from t212bot.config import load_strategy
    cfg = load_strategy()
    # O10 (2026-10-19): the shipped strategy is retired, so it must hold no targets at all
    assert cfg.mode == "retired" and cfg.targets == {} and cfg.signal is None


def test_live_url_absent_from_package():
    from pathlib import Path
    src = "".join(p.read_text() for p in (Path(__file__).parent.parent / "t212bot").glob("*.py"))
    assert "live.trading212.com" not in src


# ---------------------------------------------------------------- client
def test_client_refuses_non_demo_base_url(creds):
    with pytest.raises(SafetyError):
        T212Client(creds, base_url="https://live.trading212.com")


def test_client_never_leaks_secret(make_client, creds):
    fake = FakeT212()
    fake.get_status = [401]
    c = make_client(fake)
    assert creds.secret not in repr(c) and creds.key not in repr(c)
    with pytest.raises(ApiError) as e:
        c.account_summary()
    assert creds.secret not in str(e.value)


def test_throttle_spaces_calls_per_endpoint(make_client):
    c = make_client(FakeT212())
    c.account_summary()
    c.account_summary()
    assert any(s >= 5.0 for s in c.sleeps), c.sleeps


def test_get_retries_on_429_and_5xx(make_client):
    fake = FakeT212()
    fake.get_status = [429, 503]
    c = make_client(fake)
    assert c.account_summary()["totalValue"] == 100.0


def test_post_429_is_retried_but_5xx_and_timeouts_are_ambiguous(make_client):
    fake = FakeT212()
    fake.post_status = [429]
    c = make_client(fake)
    o = c.place_market_order("VWRPl_EQ", 0.1)
    assert o["id"] and len(fake.posts) == 1          # rejected 429 never reached the book

    fake.post_status = [500]
    with pytest.raises(AmbiguousOrderError):
        c.place_market_order("VWRPl_EQ", 0.1)
    assert len(fake.posts) == 1                       # not re-sent

    fake.raise_on_post = True
    with pytest.raises(AmbiguousOrderError):
        c.place_market_order("VWRPl_EQ", 0.1)


def test_404_maps_to_notfound(make_client):
    c = make_client(FakeT212())
    with pytest.raises(NotFound):
        c.get_order(999999)


def test_invalid_order_rejected_client_side(make_client):
    c = make_client(FakeT212())
    with pytest.raises(SafetyError):
        c.place_market_order("VWRPl_EQ", 0)


def test_history_pagination(creds):
    pages = {
        "/api/v0/equity/history/orders?limit=50": {"items": [{"order": {"id": 1}}], "nextPagePath": "/api/v0/equity/history/orders?limit=50&cursor=2"},
        "/api/v0/equity/history/orders?limit=50&cursor=2": {"items": [{"order": {"id": 2}}], "nextPagePath": None},
    }

    def transport(method, url, headers, body, timeout):
        import json
        return Response(200, {}, json.dumps(pages[url.split(".com", 1)[1]]).encode())

    c = T212Client(creds, transport=transport, sleep=lambda s: None)
    assert [i["order"]["id"] for i in c.history_orders()] == [1, 2]


def test_request_outside_api_prefix_refused(make_client):
    c = make_client(FakeT212())
    with pytest.raises(SafetyError):
        c._request("GET", "/../evil", "x")
