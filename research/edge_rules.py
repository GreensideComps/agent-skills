"""Execution timing and missing-price rules for the edge-discovery portfolio backtester (docs/edge/PHASE_B_PLAN.md).

Written in the Phase A review so the rules are code and tested before the backtester exists. The backtester must
build each decision from `decision_frame`, time its trades with `execution_time`, and value holdings with
`holding_return`.

Timing (PHASE_B_PLAN.md §2.1):

* A decision is made at month-end t from what is known by then: filings dated on or before t, and prices up to
  the close of t's last trading day.
* Default execution, `next_day_close`: the close of the first trading day after t. Every input, including a
  filing dated t that was accepted after the close, is public by then, so the trade is achievable. Trading at the
  close of t itself is not: the order would have to be placed before the close it uses.
* Robustness, `next_month_close`: the close of the following month-end (one month late). It needs only the
  monthly prices the research dataset already has.

Missing prices: a holding whose price disappears (delisting, acquisition, ticker change, a gap in the data) or
turns invalid (<= 0) is closed at its last valid price, then marked down by `missing_return` (default -30%; -100%
is the stress; 0% is shown only as a labelled optimistic bound). A missing price can therefore never make a
position look better than its last valid price did. These rules apply only to companies that *are* in the data;
companies delisted before 2026 have no prices at all, and no rule here removes that survivorship bias.
"""
from __future__ import annotations

import pandas as pd

import edge_split

CONVENTIONS = ("next_day_close", "next_month_close")
DEFAULT_CONVENTION = "next_day_close"
DEFAULT_MISSING_RETURN = -0.30
STRESS_MISSING_RETURNS = (-0.30, -1.0)
# Columns that hold information from after the decision: forward returns and execution-time prices.
FORBIDDEN_PREFIXES = ("ret_", "exec_")


# Every backtest report opens with this (docs/edge/PHASE_A_AUDIT.md §11.10, owner 2026-10-15). It states what no
# result can fix on free data, so a report cannot imply the limitations have been solved.
STANDING_LIMITATIONS = """**Standing limitations (not solved by anything in this report):**

1. **Survivorship bias.** Companies that stopped trading before 2026 have no free prices and are never held, so
   every result is biased upward by an unknown amount. The missing-price stresses (-30%, -100%) apply only to
   companies that are in the data; they do not remove this bias.
2. **Missing prices are indistinguishable.** Delistings, acquisitions and ticker changes all get the same
   conservative mark-down.
3. **The 2023-2026 holdout is partly seen**, so a holdout pass is weaker than a clean out-of-sample test.
4. **One ticker per company, today's SIC codes, unofficial free prices (Yahoo).**
5. **Benchmark:** actual VWRP only from 2019-09; VWRL (its distributing twin) before that.
"""


def require_disclosure(report: str) -> str:
    """Return the report unchanged if it opens (after its title) with STANDING_LIMITATIONS; raise otherwise."""
    body = report.split("\n", 1)[1] if report.startswith("#") else report
    if not body.lstrip().startswith(STANDING_LIMITATIONS.strip()):
        raise ValueError("a backtest report must open with edge_rules.STANDING_LIMITATIONS")
    return report


class LookAhead(RuntimeError):
    """Raised when a decision could use information that is not available before its trade executes."""


def execution_time(decision, convention: str = DEFAULT_CONVENTION) -> pd.Timestamp:
    """When a decision made at month-end `decision` trades. Business days only (exchange holidays are handled by
    taking the first trading day with a price on or after this date)."""
    t = pd.Timestamp(decision) + pd.offsets.MonthEnd(0)
    if convention == "next_day_close":
        return t + pd.offsets.BDay(1)
    if convention == "next_month_close":
        return t + pd.offsets.MonthEnd(1)
    raise ValueError(f"convention must be one of {CONVENTIONS}")


def exploration_execution(decision, convention: str = DEFAULT_CONVENTION) -> pd.Timestamp:
    """`execution_time`, refusing a trade that would execute after the exploration period. The exploration
    backtest's last valuation is the 2022-12 month-end close, so its last holding period ends there."""
    ex = execution_time(decision, convention)
    if ex > edge_split.EXPLORATION_LAST_OUTCOME:
        raise edge_split.HoldoutViolation(f"a decision at {pd.Timestamp(decision).date()} executes on {ex.date()}, "
                                          f"after {edge_split.EXPLORATION_LAST_OUTCOME.date()}")
    return ex


def decision_frame(panel: pd.DataFrame, decision) -> pd.DataFrame:
    """The rows and columns a decision at month-end `decision` may use: months up to and including it, without
    forward returns or execution prices. Raises LookAhead if any row relies on a filing dated after its month."""
    t = pd.Timestamp(decision) + pd.offsets.MonthEnd(0)
    d = panel[pd.to_datetime(panel["month"]) <= t]
    drop = [c for c in d.columns if c == "ret_next" or str(c).startswith(FORBIDDEN_PREFIXES)]
    d = d.drop(columns=drop)
    if "last_filed" in d:
        filed = pd.to_datetime(d["last_filed"], errors="coerce")
        if (filed > pd.to_datetime(d["month"])).any():
            raise LookAhead("a row uses a filing dated after its month")
    return d


def assert_executable(information_time, execution) -> None:
    """Every input must be known strictly before the trade executes."""
    if pd.Timestamp(execution) <= pd.Timestamp(information_time):
        raise LookAhead(f"execution {pd.Timestamp(execution).date()} is not after the information it uses "
                        f"({pd.Timestamp(information_time).date()})")


def holding_return(prices: pd.Series, start, end, missing_return: float = DEFAULT_MISSING_RETURN) -> tuple[float, str]:
    """Return of a position bought at `start` and valued at `end` from a date-indexed price series.

    Returns (return, status): "priced" when the end price is valid; "missing" when it is absent or <= 0, in which
    case the position is closed at the last valid price in (start, end) and marked down by `missing_return`.
    `missing_return` must be <= 0, so a missing price never helps the strategy."""
    if missing_return > 0:
        raise ValueError("missing_return must be <= 0: a disappearance cannot be assumed to be good news")
    s = prices.sort_index()
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    p0 = s.get(t0)
    if p0 is None or not p0 > 0:
        raise ValueError(f"no valid price to buy at on {t0.date()}")
    last = p0
    for v in s[(s.index > t0) & (s.index <= t1)]:
        if not v > 0:  # NaN or <= 0: the position ends at the last valid price
            return float(last / p0 * (1 + missing_return) - 1), "missing"
        last = v
    if t1 not in s.index:
        return float(last / p0 * (1 + missing_return) - 1), "missing"
    return float(last / p0 - 1), "priced"
