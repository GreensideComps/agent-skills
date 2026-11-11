"""Minimal, safety-first Trading 212 API client (demo only).

Design rules
------------
* Only DEMO_BASE_URL is reachable; any other host raises SafetyError.
* Official per-endpoint rate limits (docs.trading212.com OpenAPI, 2026-10)
  are enforced client-side with a minimum interval per endpoint.
* GET requests retry on 429/5xx/network errors.
* Order POSTs are NOT idempotent (official docs). They are retried only on
  HTTP 429, where the server rejected the request before processing it.
  Timeouts, 5xx and network errors raise AmbiguousOrderError so the caller
  reconciles against pending orders/history instead of re-sending.
* Credentials never appear in logs, exceptions or reprs.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .config import DEMO_BASE_URL, Credentials, SafetyError

# endpoint key -> minimum seconds between calls (official limit + margin)
RATE_LIMITS = {
    "account_summary": 5.2,
    "positions": 1.1,
    "orders_list": 5.2,
    "order_get": 1.1,
    "order_market": 1.3,       # 50 / min
    "order_limit": 2.1,        # 1 / 2s
    "order_stop": 2.1,         # 1 / 2s
    "order_cancel": 1.3,       # 50 / min
    "history_orders": 3.1,     # 20 / min
    "history_dividends": 3.1,
    "history_transactions": 3.1,
    "exchanges": 30.5,
    "instruments": 50.5,
}


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str, endpoint: str):
        super().__init__(f"{endpoint}: HTTP {status}: {body[:300]}")
        self.status, self.body, self.endpoint = status, body, endpoint


class AmbiguousOrderError(RuntimeError):
    """The order request may or may not have been accepted. Reconcile; do not resend."""


class NotFound(ApiError):
    pass


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes


Transport = Callable[[str, str, dict, bytes | None, float], Response]


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> Response:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
    except urllib.error.HTTPError as e:
        return Response(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b"")


class T212Client:
    def __init__(self, creds: Credentials, transport: Transport = urllib_transport,
                 base_url: str = DEMO_BASE_URL, sleep=time.sleep, clock=time.monotonic,
                 wall=time.time, timeout: float = 30.0):
        if base_url != DEMO_BASE_URL:
            raise SafetyError(f"refusing non-demo base URL {base_url!r}")
        self._auth = "Basic " + base64.b64encode(f"{creds.key}:{creds.secret}".encode()).decode()
        self._t = transport
        self._base = base_url
        self._sleep, self._clock, self._wall = sleep, clock, wall
        self._timeout = timeout
        self._last: dict[str, float] = {}
        self.calls: list[tuple[str, str]] = []  # (method, path) audit trail, no secrets

    def __repr__(self) -> str:
        return f"T212Client(base={self._base!r}, auth=<redacted>)"

    # ------------------------------------------------------------ plumbing
    def _throttle(self, key: str) -> None:
        gap = RATE_LIMITS.get(key, 1.1)
        last = self._last.get(key)
        if last is not None:
            wait = gap - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[key] = self._clock()

    def _wait_reset(self, headers: dict) -> None:
        reset = headers.get("x-ratelimit-reset")
        try:
            wait = float(reset) - self._wall() + 0.5 if reset else 5.0
        except ValueError:
            wait = 5.0
        self._sleep(min(max(wait, 1.0), 65.0))

    def _request(self, method: str, path: str, key: str, payload: dict | None = None,
                 is_order: bool = False, max_tries: int = 4):
        url = self._base + path
        if not url.startswith(DEMO_BASE_URL + "/api/v0/"):
            raise SafetyError(f"refusing request outside demo API: {path!r}")
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Authorization": self._auth, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(1, max_tries + 1):
            self._throttle(key)
            self.calls.append((method, path))
            try:
                r = self._t(method, url, headers, body, self._timeout)
            except Exception as e:  # network/timeout
                if is_order:
                    raise AmbiguousOrderError(f"{method} {path}: transport error {type(e).__name__}") from None
                if attempt == max_tries:
                    raise
                self._sleep(2 ** attempt)
                continue
            text = r.body.decode("utf-8", "replace")
            if r.status == 429:
                if attempt == max_tries:
                    raise ApiError(429, text, path)
                self._wait_reset(r.headers)
                continue
            if r.status >= 500 or r.status == 408:
                if is_order:
                    raise AmbiguousOrderError(f"{method} {path}: HTTP {r.status}")
                if attempt == max_tries:
                    raise ApiError(r.status, text, path)
                self._sleep(2 ** attempt)
                continue
            if r.status == 404:
                raise NotFound(404, text, path)
            if r.status >= 400:
                raise ApiError(r.status, text, path)
            return json.loads(text) if text.strip() else None
        raise RuntimeError("unreachable")

    # ------------------------------------------------------------ endpoints
    def account_summary(self) -> dict:
        return self._request("GET", "/api/v0/equity/account/summary", "account_summary")

    def positions(self) -> list[dict]:
        return self._request("GET", "/api/v0/equity/positions", "positions")

    def pending_orders(self) -> list[dict]:
        return self._request("GET", "/api/v0/equity/orders", "orders_list")

    def get_order(self, order_id: int) -> dict:
        return self._request("GET", f"/api/v0/equity/orders/{int(order_id)}", "order_get")

    def place_market_order(self, ticker: str, quantity: float, extended_hours: bool = False) -> dict:
        if not isinstance(ticker, str) or not ticker or quantity == 0:
            raise SafetyError("invalid market order")
        return self._request("POST", "/api/v0/equity/orders/market", "order_market",
                             {"ticker": ticker, "quantity": quantity, "extendedHours": extended_hours},
                             is_order=True)

    def place_stop_order(self, ticker: str, quantity: float, stop_price: float,
                         time_validity: str = "GOOD_TILL_CANCEL") -> dict:
        """A resting stop order at the broker (negative quantity sells). It fills at market once the price trades
        at or through `stop_price`, in the instrument's currency, whether or not anything here is running."""
        if not isinstance(ticker, str) or not ticker or quantity == 0 or not stop_price or stop_price <= 0:
            raise SafetyError("invalid stop order")
        return self._request("POST", "/api/v0/equity/orders/stop", "order_stop",
                             {"ticker": ticker, "quantity": quantity, "stopPrice": stop_price,
                              "timeValidity": time_validity}, is_order=True)

    def cancel_order(self, order_id: int) -> None:
        self._request("DELETE", f"/api/v0/equity/orders/{int(order_id)}", "order_cancel", is_order=True)

    def history_orders(self, ticker: str | None = None, limit: int = 50, max_pages: int = 5) -> list[dict]:
        path = f"/api/v0/equity/history/orders?limit={int(limit)}" + (f"&ticker={ticker}" if ticker else "")
        items: list[dict] = []
        for _ in range(max_pages):
            page = self._request("GET", path, "history_orders") or {}
            items.extend(page.get("items", []))
            nxt = page.get("nextPagePath")
            if not nxt:
                break
            path = nxt
        return items

    def _paged(self, path: str, key: str, max_pages: int) -> list[dict]:
        items: list[dict] = []
        for _ in range(max_pages):
            page = self._request("GET", path, key) or {}
            items.extend(page.get("items", []))
            nxt = page.get("nextPagePath")
            if not nxt:
                break
            path = nxt
        return items

    def history_transactions(self, limit: int = 50, max_pages: int = 20) -> list[dict]:
        """Deposits, withdrawals, fees, transfers (account currency)."""
        return self._paged(f"/api/v0/equity/history/transactions?limit={int(limit)}", "history_transactions", max_pages)

    def history_dividends(self, limit: int = 50, max_pages: int = 20) -> list[dict]:
        return self._paged(f"/api/v0/equity/history/dividends?limit={int(limit)}", "history_dividends", max_pages)

    def exchanges(self) -> list[dict]:
        return self._request("GET", "/api/v0/equity/metadata/exchanges", "exchanges")

    def instruments(self) -> list[dict]:
        return self._request("GET", "/api/v0/equity/metadata/instruments", "instruments")
