"""SEC EDGAR client (public XBRL APIs; no key, no licence fee).

SEC fair-access rules: a User-Agent with a contact email is mandatory (requests
without one get HTTP 403, checked 2026-10-14) and at most 10 requests/second. We
stay at <= 5/s. The contact comes from the SEC_USER_AGENT environment variable,
never from code.

Responses are cached under equity/cache/sec (gitignored). Filings are immutable and
companyfacts keeps every historically filed value with its accession number, so
any past state can be re-derived from the source; the cache is only an optimisation.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "sec"
TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


class SecError(RuntimeError):
    pass


def user_agent(env: dict | None = None) -> str:
    ua = (env if env is not None else os.environ).get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        raise SecError("SEC_USER_AGENT must be set to '<app name> <contact email>' (SEC fair-access policy)")
    return ua


def _urllib_get(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""


class SecClient:
    def __init__(self, ua: str | None = None, transport=_urllib_get, cache_dir: Path = CACHE_DIR,
                 min_interval: float = 0.2, sleep=time.sleep, clock=time.monotonic, max_attempts: int = 4):
        self.ua = ua or user_agent()
        self.transport = transport
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self.sleep, self.clock = sleep, clock
        self.max_attempts = max_attempts
        self._last = None
        self.requests_made = 0

    def _get_json(self, url: str, cache_name: str, max_age_s: float) -> dict:
        path = self.cache_dir / cache_name
        if path.exists() and time.time() - path.stat().st_mtime < max_age_s:
            return json.loads(path.read_text())
        delay = 1.0
        for attempt in range(1, self.max_attempts + 1):
            if self._last is not None:
                wait = self.min_interval - (self.clock() - self._last)
                if wait > 0:
                    self.sleep(wait)
            self._last = self.clock()
            self.requests_made += 1
            status, body = self.transport(url, {"User-Agent": self.ua, "Accept-Encoding": "identity"}, 30)
            if status == 200:
                data = json.loads(body)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
                return data
            if status == 404:
                raise SecError(f"404 not found: {url}")
            if status in (429, 500, 502, 503, 504) and attempt < self.max_attempts:
                self.sleep(delay)
                delay *= 2
                continue
            raise SecError(f"HTTP {status} from {url}")
        raise SecError(f"gave up on {url}")

    def get_raw(self, url: str) -> dict:
        """One paced request with no caching or retries: {'url', 'status', 'body', 'error', 'retrieved_at'}. A
        connection failure, timeout or OSError gives status None and `error` set to the exception's type name, so the
        caller labels it instead of crashing (review finding P32-6). For filing events, whose raw bytes are kept by
        hash elsewhere (equity.filings_store). Added for mini fund Stage 2 §1; existing callers are unchanged."""
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()
        self.requests_made += 1
        error = None
        try:
            status, body = self.transport(url, {"User-Agent": self.ua, "Accept-Encoding": "identity"}, 30)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            status, body, error = None, None, type(e).__name__
        return {"url": url, "status": status, "body": body, "error": error,
                "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}

    def tickers(self, max_age_s: float = 86400) -> list[dict]:
        """[{cik, name, ticker, exchange}] for every SEC registrant with a listed ticker."""
        d = self._get_json(TICKERS_URL, "company_tickers_exchange.json", max_age_s)
        cols = d["fields"]
        return [dict(zip(cols, row)) for row in d["data"]]

    def company_facts(self, cik: int, max_age_s: float = 86400) -> dict:
        return self._get_json(FACTS_URL.format(cik=int(cik)), f"facts/CIK{int(cik):010d}.json", max_age_s)

    def submissions(self, cik: int, max_age_s: float = 7 * 86400) -> dict:
        """Registrant profile: SIC code and description, fiscal year end, former names, filings."""
        return self._get_json(SUBMISSIONS_URL.format(cik=int(cik)), f"submissions/CIK{int(cik):010d}.json",
                              max_age_s)
