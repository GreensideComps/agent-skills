"""Trend signal that switches the strategy's targets (pure logic + one loader).

sma_trend: if the signal symbol's last COMPLETED daily close is above its N-day simple
moving average, hold `on_targets`, otherwise `off_targets` (empty = all cash).
Backtest: research/h03_leveraged_trend.py (signal at close t, traded the next day).

Safety: today's bar is always dropped (it may be a live, unfinished price), and the
signal refuses to run on data more than `max_age_days` calendar days old, so a broken
data feed stops trading instead of trading on a stale signal.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .config import SafetyError, StrategyConfig


def sma_state(closes: pd.Series, window: int, today: date, max_age_days: int = 5) -> dict:
    s = closes.dropna()
    s = s[s.index.date < today]
    if len(s) < window:
        raise SafetyError(f"signal: only {len(s)} closes, need {window}")
    last_day = s.index[-1].date()
    if (today - last_day).days > max_age_days:
        raise SafetyError(f"signal: last close {last_day} is more than {max_age_days} days old")
    sma = float(s.iloc[-window:].mean())
    last = float(s.iloc[-1])
    return {"on": last > sma, "last_close": last, "sma": sma, "gap": last / sma - 1, "as_of": last_day.isoformat()}


def resolve_targets(cfg: StrategyConfig, today: date, loader) -> tuple[dict[str, float], dict]:
    """Return (targets, info). `loader(symbol)` returns a DataFrame with an 'adjclose' column."""
    sig = cfg.signal
    if sig is None:
        return dict(cfg.targets), {"type": "static"}
    st = sma_state(loader(sig["symbol"])["adjclose"], int(sig["window"]), today, int(sig.get("max_age_days", 5)))
    targets = dict(sig["on_targets"] if st["on"] else (sig.get("off_targets") or {}))
    return targets, {"type": "sma_trend", "symbol": sig["symbol"], "window": int(sig["window"]), **st}
