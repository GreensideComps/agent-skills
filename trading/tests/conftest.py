"""Shared fixtures: an in-memory fake of the Trading 212 demo API."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "retired_guard: run with the branch retirement in force")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from t212bot.client import Response, T212Client  # noqa: E402
from t212bot.config import Credentials, StrategyConfig  # noqa: E402
from t212bot.journal import Journal  # noqa: E402
from t212bot.market import Quote  # noqa: E402

NOW = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _legacy_behaviour_unless_testing_the_retirement(request, monkeypatch):
    """The branch is retired (t212bot/retired.py). The legacy tests keep checking the
    old logic in-process against the fake broker; tests marked `retired_guard` run
    with the real, retired setting."""
    if request.node.get_closest_marker("retired_guard") is None:
        import t212bot.retired
        monkeypatch.setattr(t212bot.retired, "BRANCH_RETIRED", False)

INSTRUMENTS = [
    {"ticker": "VWRPl_EQ", "currencyCode": "GBP", "workingScheduleId": 70, "type": "ETF", "name": "Vanguard FTSE All-World (Acc)"},
    {"ticker": "IWMOl_EQ", "currencyCode": "USD", "workingScheduleId": 154, "type": "ETF", "name": "iShares MSCI World Momentum"},
    {"ticker": "SGLNl_EQ", "currencyCode": "GBX", "workingScheduleId": 70, "type": "ETF", "name": "iShares Physical Gold"},
]


def exchanges_for(day: datetime):
    d = day.strftime("%Y-%m-%d")
    evs = [{"type": "OPEN", "date": f"{d}T07:00:00.000Z"}, {"type": "CLOSE", "date": f"{d}T15:30:00.000Z"}]
    return [{"id": 42, "name": "London Stock Exchange",
             "workingSchedules": [{"id": 70, "timeEvents": evs}, {"id": 154, "timeEvents": evs}]}]


class FakeT212:
    """Stateful fake. Market orders fill instantly at `fill_px` (instrument ccy)."""

    def __init__(self, cash=100.0, positions=None, fill_px=None, gbpusd=1.3237):
        self.cash = cash
        self.pos = dict(positions or {})          # ticker -> qty
        self.fill_px = fill_px or {"VWRPl_EQ": 146.40, "IWMOl_EQ": 116.95, "SGLNl_EQ": 61.40}
        self.ccy = {i["ticker"]: i["currencyCode"] for i in INSTRUMENTS}
        self.gbpusd = gbpusd
        self.cost = {t: q * self.px_gbp(t) for t, q in self.pos.items()}   # ticker -> GBP cost basis (excl. FX fee)
        self.pending: list[dict] = []
        self.history: list[dict] = []
        self.posts: list[dict] = []
        self.next_id = 1000
        self.max_decimals: int | None = None      # reject quantities with more decimals
        self.post_status: list[int] = []          # queued forced statuses for POSTs
        self.get_status: list[int] = []
        self.raise_on_post = False
        self.buy_reserve = 0.0                    # extra cash held on market buys
        self.transactions = [{"type": "DEPOSIT", "amount": cash, "currency": "GBP",
                              "dateTime": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z"), "reference": "dep-1"}]
        self.dividends: list[dict] = []
        self.get_calls: list[str] = []

    def px_gbp(self, t):
        p = self.fill_px[t]
        c = self.ccy[t]
        return p / self.gbpusd if c == "USD" else (p / 100 if c == "GBX" else p)

    def value(self):
        return sum(q * self.px_gbp(t) for t, q in self.pos.items())

    def __call__(self, method, url, headers, body, timeout):
        assert url.startswith("https://demo.trading212.com/api/v0/"), url
        assert headers["Authorization"].startswith("Basic ")
        path = url.split("demo.trading212.com", 1)[1]
        if method == "POST":
            if self.raise_on_post:
                raise TimeoutError("simulated timeout")
            if self.post_status:
                st = self.post_status.pop(0)
                return Response(st, {"x-ratelimit-reset": "0"}, b'{"code":"x"}')
            return self._post(path, json.loads(body))
        if self.get_status:
            return Response(self.get_status.pop(0), {"x-ratelimit-reset": "0"}, b"")
        return self._get(path)

    def _ok(self, obj):
        return Response(200, {}, json.dumps(obj).encode())

    def _get(self, path):
        self.get_calls.append(path)
        if "/equity/history/transactions" in path:
            return self._ok({"items": self.transactions, "nextPagePath": None})
        if "/equity/history/dividends" in path:
            return self._ok({"items": self.dividends, "nextPagePath": None})
        if path.endswith("/equity/account/summary"):
            v = self.value()
            return self._ok({"id": 1, "currency": "GBP", "totalValue": round(self.cash + v, 2),
                             "cash": {"availableToTrade": round(self.cash, 2), "reservedForOrders": 0, "inPies": 0},
                             "investments": {"currentValue": round(v, 2), "totalCost": round(sum(self.cost.values()), 2),
                                             "realizedProfitLoss": 0, "unrealizedProfitLoss": round(v - sum(self.cost.values()), 2)}})
        if path.endswith("/equity/positions"):
            out = []
            for t, q in self.pos.items():
                cp = self.fill_px[t] * (100 if self.ccy[t] == "GBX" else 1)
                out.append({"instrument": {"ticker": t, "currency": self.ccy[t]}, "quantity": q,
                            "quantityAvailableForTrading": q, "currentPrice": cp,
                            "walletImpact": {"currency": "GBP", "currentValue": round(q * self.px_gbp(t), 2),
                                             "totalCost": round(self.cost.get(t, 0), 2),
                                             "unrealizedProfitLoss": round(q * self.px_gbp(t) - self.cost.get(t, 0), 2)}})
            return self._ok(out)
        if path.endswith("/equity/orders"):
            return self._ok(self.pending)
        if "/equity/orders/" in path:
            oid = int(path.rsplit("/", 1)[1])
            for o in self.pending:
                if o["id"] == oid:
                    return self._ok(o)
            return Response(404, {}, b"")
        if "/equity/history/orders" in path:
            t = None
            if "ticker=" in path:
                t = path.split("ticker=")[1].split("&")[0]
            items = [h for h in self.history if t is None or h["order"]["ticker"] == t]
            return self._ok({"items": items[::-1], "nextPagePath": None})
        if path.endswith("/metadata/instruments"):
            return self._ok(INSTRUMENTS)
        if path.endswith("/metadata/exchanges"):
            return self._ok(exchanges_for(NOW))
        return Response(404, {}, b"")

    def _post(self, path, payload):
        assert path.endswith("/equity/orders/market"), path
        self.posts.append(payload)
        t, q = payload["ticker"], payload["quantity"]
        if self.max_decimals is not None:
            s = f"{abs(q):.10f}".rstrip("0").split(".")
            if len(s) > 1 and len(s[1]) > self.max_decimals:
                return Response(400, {}, b'{"code":"InvalidQuantityPrecision","message":"quantity precision"}')
        if q < 0 and self.pos.get(t, 0) + 1e-12 < -q:
            return Response(400, {}, b'{"code":"SellingEquityNotOwned"}')
        fee = 0.0015 if self.ccy[t] == "USD" else 0
        gross = abs(q) * self.px_gbp(t)
        if q > 0 and gross * (1 + fee) * (1 + self.buy_reserve) > self.cash + 1e-9:
            return Response(400, {}, b'{"code":"InsufficientFreeForStocksBuy"}')
        self.cash += -gross * (1 + fee) if q > 0 else gross * (1 - fee)
        before = self.pos.get(t, 0)
        self.cost[t] = self.cost.get(t, 0) + gross if q > 0 else self.cost.get(t, 0) * (1 + q / before)   # cost excludes FX fee, like T212
        self.pos[t] = self.pos.get(t, 0) + q
        if abs(self.pos[t]) < 1e-12:
            del self.pos[t]
            self.cost.pop(t, None)
        oid = self.next_id
        self.next_id += 1
        order = {"id": oid, "ticker": t, "quantity": q, "filledQuantity": q, "status": "FILLED", "type": "MARKET",
                 "side": "BUY" if q > 0 else "SELL", "strategy": "QUANTITY", "initiatedFrom": "API",
                 "createdAt": NOW.isoformat()}
        self.history.append({"order": order, "fill": {"id": oid * 10, "price": self.fill_px[t], "quantity": q,
                             "filledAt": NOW.isoformat(), "type": "TRADE",
                             "walletImpact": {"currency": "GBP", "fxRate": 1 / self.gbpusd if self.ccy[t] == "USD" else 1,
                                              "netValue": gross * (1 + fee) if q > 0 else gross * (1 - fee), "realisedProfitLoss": 0,
                                              "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": -gross * fee}] if fee else []}}})
        return Response(200, {}, json.dumps({**order, "status": "NEW", "filledQuantity": 0}).encode())


class FakeQuotes:
    def __init__(self, prices=None, gbpusd=1.3237, as_of=NOW - timedelta(minutes=16)):
        self.prices = prices or {"VWRP.L": (146.40, "GBP"), "IWMO.L": (116.95, "USD"), "SGLN.L": (61.40, "GBP")}
        self.fx, self.as_of = gbpusd, as_of

    def quote(self, sym):
        p, c = self.prices[sym]
        return Quote(sym, p, c, self.as_of, "fake")

    def gbpusd(self):
        return Quote("GBPUSD=X", self.fx, "USD", self.as_of, "fake")


@pytest.fixture
def cfg():
    return StrategyConfig(name="test", targets={"VWRPl_EQ": 0.5, "IWMOl_EQ": 0.5},
                          yahoo_symbols={"VWRPl_EQ": "VWRP.L", "IWMOl_EQ": "IWMO.L", "SGLNl_EQ": "SGLN.L"})


@pytest.fixture
def creds():
    return Credentials("KEY_abc123", "SECRET_xyz789")


@pytest.fixture
def make_client(creds):
    def _make(fake, **kw):
        sleeps = []
        c = T212Client(creds, transport=fake, sleep=sleeps.append, clock=lambda: 0.0, wall=lambda: 0.0, **kw)
        c.sleeps = sleeps
        return c
    return _make


@pytest.fixture
def journal(tmp_path):
    return Journal(root=tmp_path / "journal", clock=lambda: NOW)
