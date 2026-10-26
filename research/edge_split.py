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

# Owner decisions of 2026-10-14 (docs/edge/DECISIONS.md). The gate below enforces 1 and 2.
OWNER_SPLIT_APPROVAL = "owner 2026-10-14: split approved provisionally (docs/edge/DECISIONS.md D1)"
MAX_CONFIRMATION_BATCHES = 1  # D2: the holdout serves one confirmation batch, ever

# Column names that suggest a value from after the decision date. ret_next and ret_{h}m are checked by horizon;
# anything else with one of these markers is refused outright, because its horizon is unknown.
FORWARD_MARKERS = ("fwd", "forward", "future", "next", "lead", "outcome", "realised", "realized")


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
    """Compound h-month forward return per company from month-end prices: the product of the h one-month returns
    from t to t+h, so it is NaN unless every month t..t+h has a valid price.

    A price <= 0 is invalid (a Yahoo adjustment error, e.g. NFE's adjusted close is negative from 2019-01 to
    2022-12 and positive after) and is treated as missing, so no return starts, ends or passes through one: a
    ratio across the sign change is a meaningless "return". Stage 2 and `xsection.load` are unchanged."""
    d = df[["cik", "month", price]].copy()
    d[price] = d[price].where(d[price] > 0)
    d["p"] = pd.to_datetime(d["month"]).dt.to_period("M")
    key = d[["cik", "p"]]

    def ahead(k: int) -> pd.Series:
        src = d[["cik", "p", price]].copy()
        src["p"] = src["p"] - k
        return pd.Series(key.merge(src, on=["cik", "p"], how="left")[price].to_numpy(), index=df.index)

    growth = pd.Series(1.0, index=df.index)
    prev = pd.Series(d[price].to_numpy(), index=df.index)
    for k in range(1, horizon + 1):
        nxt = ahead(k)
        growth = growth * (nxt / prev)
        prev = nxt
    return growth - 1


def cut_exploration(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with month <= 2022-12 and no `ret_next` (the 2022-12 row's ret_next is a 2023 return). Every
    exploration path starts here, before features, flags or returns are computed, so nothing computed later
    can depend on a 2023 value."""
    out = df[pd.to_datetime(df["month"]) <= EXPLORATION_LAST_OUTCOME]
    return out.drop(columns=[c for c in ("ret_next",) if c in out]).reset_index(drop=True)


def share_outliers(df: pd.DataFrame) -> pd.Series:
    """Company-months whose share count is over 10x or under 1/10 of the company's median over the rows given:
    mostly XBRL scaling errors on the cover page (e.g. 1.9e14 shares), which inflate market cap and move a small
    company into the large band. Some are real (IPOs, large issuance), so this flags, it does not prove.

    The median is taken over the frame passed in, so the frame must already be cut to the period being studied
    (`cut_exploration`): on the full dataset the median would use 2023-26 share counts."""
    sh = df["shares_out"].where(df["shares_out"] > 0, df["shares_diluted"])
    med = sh.groupby(df["cik"]).transform("median")
    return (sh > 10 * med) | (sh < med / 10)


def share_outliers_pit(df: pd.DataFrame) -> pd.Series:
    """The median is taken over the company's rows dated on or before each month (expanding, including the month
    itself), so a flag uses no later information at all. Phase A sensitivity variant (QX-PIT-*); the PRIMARY quality
    rule of the B5 trials from ADDENDUM_3 (owner decision D20). `share_outliers` remains the Phase A / Stage 2 rule
    (D5) and B5's P9 reverse veto."""
    sh = df["shares_out"].where(df["shares_out"] > 0, df["shares_diluted"])
    order = df.assign(_sh=sh, _m=pd.to_datetime(df["month"])).sort_values(["cik", "_m"])
    med = order.groupby("cik")["_sh"].transform(lambda x: x.expanding().median()).reindex(df.index)
    return (sh > 10 * med) | (sh < med / 10)


def quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Per company-month flags (EVALUATION_SPEC §1; owner decision D5). Compute on a period-cut frame."""
    return pd.DataFrame({"bad_price": (df["adjclose"] <= 0) | (df["close_raw"] <= 0),
                         "share_outlier": share_outliers(df)}, index=df.index)


def with_quality(df: pd.DataFrame) -> pd.DataFrame:
    """The frame with a `quality_ok` column: False where any quality flag is set. Refuses an uncut frame."""
    assert_exploration_only(df)
    f = quality_flags(df)
    return df.assign(quality_ok=~f.any(axis=1))


def cut_series(x: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """A date-indexed series or frame (factors, benchmark, FX) cut at 2022-12. Benchmarks and factors are outcomes
    too: a strategy's excess return over VWRP in 2023 is a holdout number."""
    return x[pd.to_datetime(x.index) <= EXPLORATION_LAST_OUTCOME]


def complete_months(prices: pd.DataFrame, as_of) -> pd.DataFrame:
    """Drop price rows labelled with a month-end after `as_of`. The price builder labels the current, unfinished
    month with its month-end (a row dated 2026-10-31 fetched on 2026-10-14 holds the 14 October price)."""
    return prices[pd.to_datetime(prices["month"]) <= pd.Timestamp(as_of)]


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
            if any(k in str(col).lower() for k in FORWARD_MARKERS):
                raise HoldoutViolation(f"column {col!r} looks forward-looking; name forward returns ret_{{h}}m "
                                       "so their horizon can be checked")
            continue
        bad = df[col].notna() & (months > last_exploration_decision(h))
        if bad.any():
            raise HoldoutViolation(f"{col} reaches past {EXPLORATION_LAST_OUTCOME.date()} for {int(bad.sum())} rows")


def _horizon_of(col: str) -> int | None:
    if col.startswith("ret_") and col.endswith("m") and col[4:-1].isdigit():
        return int(col[4:-1])
    return None


def holdout_gate(batch: dict | None, already_run: set[str]) -> list[str]:
    """Reasons a confirmation batch may NOT open the holdout (empty list = allowed). Nothing calls this with
    intent to run yet; it exists so the rules are code, not memory. A batch needs: no earlier holdout run at all
    (one batch only, D2), a pre-registration commit, the trial ids it confirms, the owner's split approval as
    recorded in OWNER_SPLIT_APPROVAL, and a validated portfolio backtester (owner, 2026-10-14)."""
    if not batch:
        return ["no batch"]
    reasons = []
    if batch.get("id") in already_run:
        reasons.append(f"batch {batch.get('id')} already used the holdout")
    elif len(already_run) >= MAX_CONFIRMATION_BATCHES:
        reasons.append(f"the holdout allows {MAX_CONFIRMATION_BATCHES} confirmation batch and it has been used")
    if batch.get("owner_split_approval") != OWNER_SPLIT_APPROVAL:
        reasons.append("owner has not approved the data split")
    if not batch.get("backtester_validated"):
        reasons.append("portfolio backtester not validated")
    if not batch.get("prereg_commit"):
        reasons.append("no pre-registration commit")
    if not batch.get("trials"):
        reasons.append("no trials listed")
    return reasons
