"""Data split for the edge-discovery programme (Phase A). Policy: docs/edge/SPLIT_POLICY.md.

Three periods, by the month an outcome is *realised* in, not the month a decision is made:

* exploration: outcomes realised 2012-01 .. 2022-12. Free use; every definition tried is a registry trial.
* holdout (confirmation): outcomes realised 2023-01 .. 2026-09. Read once per pre-registered batch. Locked.
* prospective: decisions from 2026-10-31 on (the monthly signal log and any later live log).

A decision at month-end t with an h-month horizon realises its outcome over months t+1 .. t+h, so the last
exploration decision for horizon h is 2022-12 minus h months (h = 1: 2022-11, h = 12: 2021-12). Code that
explores calls `exploration_view` first: it removes every row after 2022-12 and every forward-return column that
would reach into 2023, so a holdout outcome cannot be read by accident however the frame is used afterwards.

Nothing in this module opens the holdout. `holdout_gate` only checks whether a batch would be allowed to.
"""
from __future__ import annotations

import pandas as pd

EXPLORATION_FIRST_OUTCOME = pd.Timestamp("2012-01-31")
EXPLORATION_LAST_OUTCOME = pd.Timestamp("2022-12-31")
HOLDOUT_FIRST_OUTCOME = pd.Timestamp("2023-01-31")
HOLDOUT_LAST_OUTCOME = pd.Timestamp("2026-09-30")
PROSPECTIVE_FIRST_DECISION = pd.Timestamp("2026-10-31")  # research/signal_log.py FIRST_MONTH
HORIZONS = (1, 3, 6, 12)


class HoldoutViolation(RuntimeError):
    """Raised when exploration code could read an outcome realised in the holdout."""


def _month_end(t) -> pd.Timestamp:
    return pd.Timestamp(t) + pd.offsets.MonthEnd(0)


def last_exploration_decision(horizon: int) -> pd.Timestamp:
    """Last month-end decision whose h-month outcome ends by 2022-12."""
    if horizon < 1:
        raise ValueError("horizon must be at least 1 month")
    return _month_end(EXPLORATION_LAST_OUTCOME - pd.DateOffset(months=horizon))


def outcome_end(decision, horizon: int) -> pd.Timestamp:
    return _month_end(pd.Timestamp(decision) + pd.DateOffset(months=horizon))


def period_of_outcome(decision, horizon: int) -> str:
    """'exploration', 'holdout', 'prospective' or 'pre-sample' for the outcome of one decision."""
    end = outcome_end(decision, horizon)
    first = outcome_end(decision, 1)
    if end <= EXPLORATION_LAST_OUTCOME:
        return "exploration" if first >= EXPLORATION_FIRST_OUTCOME else "pre-sample"
    if pd.Timestamp(decision) >= PROSPECTIVE_FIRST_DECISION or first > HOLDOUT_LAST_OUTCOME:
        return "prospective"
    return "holdout"  # any part of the outcome in 2023-01 .. 2026-09 makes it a holdout outcome


def forward_return(df: pd.DataFrame, horizon: int, price: str = "adjclose") -> pd.Series:
    """Compound h-month forward return per company from month-end prices; NaN unless all h months exist."""
    d = df[["cik", "month", price]].copy()
    d["p"] = pd.to_datetime(d["month"]).dt.to_period("M")
    src = d[["cik", "p", price]].copy()
    src["p"] = src["p"] - horizon
    m = d[["cik", "p"]].merge(src, on=["cik", "p"], how="left")
    return pd.Series(m[price].to_numpy() / d[price].to_numpy() - 1, index=df.index)


def exploration_view(df: pd.DataFrame, horizons=HORIZONS, prices: pd.DataFrame | None = None) -> pd.DataFrame:
    """The frame exploration code may use: no rows after 2022-12, and `ret_{h}m` forward returns (plus
    `ret_next` when present) only where the outcome ends by 2022-12. Forward returns are computed after the cut,
    so they cannot see a 2023 price. `prices` (cik, month, adjclose; one row per company-month) is the price
    history to compound; without it the frame's own `adjclose` rows are used, which needs a row every month."""
    out = df[pd.to_datetime(df["month"]) <= EXPLORATION_LAST_OUTCOME].copy()
    months = pd.to_datetime(out["month"])
    if "ret_next" in out:
        out.loc[months > last_exploration_decision(1), "ret_next"] = float("nan")
    src = out if prices is None else prices[pd.to_datetime(prices["month"]) <= EXPLORATION_LAST_OUTCOME].reset_index(drop=True)
    if "adjclose" in src:
        key = src[["cik", "month"]].assign(month=pd.to_datetime(src["month"]))
        for h in horizons:
            fr = key.assign(r=forward_return(src, h).to_numpy())
            m = out[["cik"]].assign(month=months).merge(fr, on=["cik", "month"], how="left")
            out[f"ret_{h}m"] = pd.Series(m["r"].to_numpy(), index=out.index).where(months <= last_exploration_decision(h))
    assert_exploration_only(out)
    return out


def assert_exploration_only(df: pd.DataFrame) -> None:
    """Raise HoldoutViolation if the frame holds a row or a forward outcome realised after 2022-12."""
    months = pd.to_datetime(df["month"])
    if (months > EXPLORATION_LAST_OUTCOME).any():
        raise HoldoutViolation(f"rows after {EXPLORATION_LAST_OUTCOME.date()} present: {months.max().date()}")
    for col in df.columns:
        h = 1 if col == "ret_next" else _horizon_of(col)
        if h is None:
            continue
        bad = df[col].notna() & (months > last_exploration_decision(h))
        if bad.any():
            raise HoldoutViolation(f"{col} reaches past {EXPLORATION_LAST_OUTCOME.date()} for {int(bad.sum())} rows")


def _horizon_of(col: str) -> int | None:
    if col.startswith("ret_") and col.endswith("m") and col[4:-1].isdigit():
        return int(col[4:-1])
    return None


def holdout_gate(batch: dict | None, already_run: set[str]) -> list[str]:
    """Reasons a confirmation batch may NOT open the holdout (empty list = allowed). Phase A never calls this
    with intent to run; it exists so the rule is code, not memory. A batch needs: an id not run before, a
    pre-registration commit, the trial ids it confirms, and a recorded owner approval of the split."""
    if not batch:
        return ["no batch"]
    reasons = []
    if batch.get("id") in already_run:
        reasons.append(f"batch {batch.get('id')} already used the holdout")
    if not batch.get("prereg_commit"):
        reasons.append("no pre-registration commit")
    if not batch.get("trials"):
        reasons.append("no trials listed")
    if not batch.get("owner_split_approval"):
        reasons.append("owner has not approved the data split")
    return reasons
