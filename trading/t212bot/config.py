"""Configuration, paths and the demo-only safety lock.

The live server URL deliberately does not appear anywhere in this package.
DEMO_BASE_URL is the only host the client will talk to; switching to live
would require editing code, not configuration.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEMO_BASE_URL = "https://demo.trading212.com"
ROOT = Path(__file__).resolve().parent.parent          # trading/
JOURNAL_DIR = ROOT / "journal"
CONFIG_PATH = ROOT / "config" / "strategy.json"
KILL_FILE = ROOT / "KILL"


class SafetyError(RuntimeError):
    """Raised when a safety rule would be violated. Never caught silently."""


@dataclass(frozen=True)
class Credentials:
    key: str
    secret: str

    def __repr__(self) -> str:  # never leak secrets into logs/tracebacks
        return "Credentials(<redacted>)"


def load_credentials(env: dict | None = None) -> Credentials:
    env = os.environ if env is None else env
    target = env.get("T212_ENV", "")
    if target != "demo":
        raise SafetyError(f"T212_ENV must be 'demo' (got {target!r}); this bot is demo-only")
    key, secret = env.get("T212_API_KEY", ""), env.get("T212_API_SECRET", "")
    if not key or not secret:
        raise SafetyError("T212_API_KEY and T212_API_SECRET must be set")
    if key.strip() != key or secret.strip() != secret:
        raise SafetyError("credentials contain leading/trailing whitespace")
    return Credentials(key, secret)


def kill_switch_engaged(env: dict | None = None, kill_file: Path = KILL_FILE) -> str | None:
    env = os.environ if env is None else env
    if env.get("T212BOT_KILL", "").strip() not in ("", "0", "false", "False"):
        return "environment variable T212BOT_KILL is set"
    if kill_file.exists():
        return f"kill file present: {kill_file}"
    return None


@dataclass
class StrategyConfig:
    name: str
    targets: dict[str, float]
    yahoo_symbols: dict[str, str]
    cash_buffer_pct: float = 0.015
    drift_band_abs: float = 0.05
    deploy_cash_threshold_pct: float = 0.03
    annual_rebalance_month: int = 1
    annual_rebalance_min_drift: float = 0.01
    min_trade_gbp: float = 1.0
    fx_fee: float = 0.0015
    default_qty_decimals: int = 4
    open_buffer_minutes: int = 15
    close_buffer_minutes: int = 15
    max_price_divergence: float = 0.03
    max_orders_per_run: int = 10
    shadow_portfolios: dict = field(default_factory=dict)
    # Optional trend signal (see signals.py). When set, `targets` is replaced at run time
    # by signal["on_targets"] or signal["off_targets"] (which may be empty = all cash).
    signal: dict | None = None

    def __post_init__(self):
        sets = [self.targets]
        if self.signal is not None:
            if self.signal.get("type") != "sma_trend":
                raise SafetyError(f"unsupported signal type {self.signal.get('type')!r}")
            if int(self.signal.get("window", 0)) < 20 or not self.signal.get("symbol"):
                raise SafetyError("sma_trend signal needs a symbol and a window of at least 20 days")
            sets += [self.signal.get("on_targets") or {}, self.signal.get("off_targets") or {}]
        for tg in sets:
            s = sum(tg.values())
            # a signal strategy may hold all cash (empty targets); a static one may not
            lo_ok = s > 0 or (self.signal is not None and not tg)
            if not (lo_ok and s <= 1 + 1e-9):
                raise SafetyError(f"target weights must sum to (0, 1], got {s}")
            if any(w < 0 for w in tg.values()):
                raise SafetyError("negative target weights (shorting) are not allowed")
            missing = set(tg) - set(self.yahoo_symbols)
            if missing:
                raise SafetyError(f"no reference-price symbol for {sorted(missing)}")


def load_strategy(path: Path = CONFIG_PATH) -> StrategyConfig:
    return StrategyConfig(**json.loads(Path(path).read_text()))
