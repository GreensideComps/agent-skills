"""B5 trial building blocks, frozen in docs/edge/B5_PREREGISTRATION.md (version 2) as amended by
docs/edge/B5_PREREGISTRATION_ADDENDUM_1.md and docs/edge/B5_PREREGISTRATION_ADDENDUM_2.md. Nothing here reads data.

Owner, 2026-10-16 11:53Z: preparatory engineering and synthetic tests are approved; running H1 or S2a is not.
This module defines the scores, the tranche combination, the placebo score for the hand-check and the frozen
exploratory gates. It computes no return of either trial; the run script (not written yet) will be separately
approved.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import stage2

# ---------- frozen constants (B5_PREREGISTRATION.md v2) ----------
N_NAMES = 20
BUFFER = 2.0
SECTOR_CAP = 4
FRESH_DAYS = 183  # decision month-end at most this many days after the TTM period end
YEAR_DAYS = (350, 380)  # consecutive TTM periods used together must end about one year apart
SPLIT_SNAP = math.log(1.25)  # |ln s| at or below this is "no split" (absorbs dividend drift in adjclose)
SHARE_GUARD = math.log(3.0)  # |ln q| above this: score missing (merger, spin-off or share-count error)
H1_REBALANCE, H1_TRANCHES = 3, ("2014-11-30", "2014-12-31", "2015-01-31")
S2A_REBALANCE = 12
S2A_TRANCHES = tuple(str(d.date()) for d in pd.date_range("2014-02-28", "2015-01-31", freq="ME"))
EVAL_FIRST_DECISION, EVAL_LAST_DECISION = "2015-01-31", "2022-11-30"
NW_LAGS = {"H1": 3, "S2A": 12}
PLACEBO_SALT = "B5-HANDCHECK"

GATES = {  # P1-P11; every one must hold for "E2 candidate"
    "P1_t": 3.0, "P1_s2a_nonoverlap_t": 2.0, "P2_dsr": 0.80, "P3_alpha_t": 2.0,
}
LEAD_T = 2.0
STATUS = Path(__file__).resolve().parent / "edge" / "status.json"
E2_BLOCKED_LABEL = "gates passed; E2 label withheld (TTM check 4 open)"


def check4_complete(path: Path = STATUS) -> bool:
    """ADDENDUM_1 §6: the independent-source check (TTM check 4) is recorded complete only by the owner. Until then
    no result may carry the E2 label and no confirmation batch may be registered. A missing or unreadable status
    counts as open."""
    try:
        return json.loads(path.read_text())["ttm_check4_independent_source"]["complete"] is True
    except (OSError, KeyError, TypeError, ValueError):
        return False


# ---------- shared ----------

def mcap_shares(df: pd.DataFrame) -> pd.Series:
    """The share count used for market cap (xsection.load): cover-page shares, else weighted diluted."""
    return df["shares_out"].where(df["shares_out"] > 0, df["shares_diluted"])


def _lag(df: pd.DataFrame, col: str, k: int) -> pd.Series:
    if "p" not in df:
        df = df.assign(p=pd.to_datetime(df["month"]).dt.to_period("M"))
    return stage2.lag(df, col, k)


def _days(a: pd.Series, b: pd.Series) -> pd.Series:
    return (pd.to_datetime(b) - pd.to_datetime(a)).dt.days


IDENTITY_CIKS = frozenset({1635327})  # ADDENDUM_2 §3: The Stars Group's 40-F accounts priced with Flutter's FLUT
IMPLAUSIBLE_MCAP_TO_ASSETS = 100.0
IDENTITY_RULE = "C"  # ADDENDUM_2 §3 (owner preferred C, 2026-10-16 14:17Z); A and B kept for the comparison only


def _clean(df: pd.DataFrame, col: str) -> pd.Series:
    """A data-quality flag passes only when it is exactly False (or 0). Missing column raises; missing value fails."""
    return df[col].map(lambda v: v is False or v == 0).astype(bool)


def _domestic(df: pd.DataFrame) -> pd.Series:
    """ADDENDUM_1 §3: rows whose latest balance sheet came from a 10-K or 10-Q. Fails closed: a missing column
    raises, and a missing value (no balance sheet known) counts as not domestic."""
    return _clean(df, "foreign_form")


def identity_ok(df: pd.DataFrame, rule: str | None = None) -> pd.Series:
    """ADDENDUM_2 §3. Rule C (in force): the row fails when its CIK is 1635327, or when
    mcap > 100 x total_assets, strictly, with both fields as of the row's own month-end:
      mcap = (shares_out if > 0 else shares_diluted) x close_raw  (xsection.load; shares from the latest filing
             known at the month-end, close_raw the unadjusted month-end close);
      total_assets = the monthly dataset's latest balance-sheet value known at the month-end.
    Missing or non-positive total_assets, or missing mcap: the ratio is undefined and rule C does not exclude the
    row; such a row still has no H1 or S2a score because both require total_assets > 0 (and the universe requires
    a market cap). A missing column raises. A: no 20-F/40-F balance sheet (Addendum 1 §3). B: CIK 1635327 only."""
    rule = IDENTITY_RULE if rule is None else rule
    if rule == "A":
        return _domestic(df)
    named = ~df["cik"].isin(IDENTITY_CIKS)
    if rule == "B":
        return named
    if rule == "C":
        ratio = df["mcap"] / df["total_assets"].where(df["total_assets"] > 0)
        return named & ~(ratio > IMPLAUSIBLE_MCAP_TO_ASSETS)
    raise ValueError(f"unknown identity rule {rule!r}")


# ---------- H1 ----------

def split_factor(close_raw: pd.Series, adjclose: pd.Series, close_raw_12: pd.Series, adjclose_12: pd.Series
                 ) -> pd.Series:
    """s_t = k_(t-12) / k_t with k = close_raw / adjclose; 1 when |ln s| <= ln 1.25. A 2-for-1 split between
    t-12 and t gives s = 2. Adjustments after t multiply both k's and cancel."""
    k, k12 = close_raw / adjclose, close_raw_12 / adjclose_12
    s = (k12 / k).where((close_raw > 0) & (adjclose > 0) & (close_raw_12 > 0) & (adjclose_12 > 0))
    return s.where(np.log(s).abs() > SPLIT_SNAP, 1.0).where(s.notna())


def h1_velocity(df: pd.DataFrame) -> pd.DataFrame:
    """G_t = (FCF_t - q_t x FCF_(t-12)) / TA_t, and the inputs behind it, for every row (point in time: each
    row's values are as known at its own month-end; the t-12 values are the row of t-12, as filed then).

    Required columns: cik, month, ocf, capex, fcf_end (common TTM period end of ocf and capex, None if they
    differ or either is missing: `edge_b5_inputs.fcf_inputs`), shares_out, shares_diluted, total_assets,
    close_raw, adjclose, ocf_restated and capex_restated (ADDENDUM_2 §2: T2, point in time; True or missing makes
    FCF unavailable), and the columns of the identity rule in force (`identity_ok`; C needs cik and mcap)."""
    d = df.sort_values(["cik", "month"]).reset_index(drop=True).copy()
    d["month"] = pd.to_datetime(d["month"])
    d["p"] = d["month"].dt.to_period("M")
    d["sh"] = mcap_shares(d)
    d["fcf"] = (d["ocf"] - d["capex"]).where(d["ocf"].notna() & d["capex"].notna() & d["fcf_end"].notna())
    fresh = _days(d["fcf_end"], d["month"]).between(0, FRESH_DAYS)
    d["fcf"] = d["fcf"].where(fresh & identity_ok(d) & _clean(d, "ocf_restated") & _clean(d, "capex_restated"))
    for c in ("fcf", "sh", "close_raw", "adjclose", "fcf_end"):
        d[f"{c}_12"] = _lag(d, c, 12)
    d["s"] = split_factor(d["close_raw"], d["adjclose"], d["close_raw_12"], d["adjclose_12"])
    d["q"] = d["sh"] / (d["sh_12"] * d["s"])
    year_apart = _days(d["fcf_end_12"], d["fcf_end"]).between(*YEAR_DAYS)
    ok = (d["fcf"].notna() & d["fcf_12"].notna() & (d["total_assets"] > 0) & (d["sh"] > 0) & (d["sh_12"] > 0)
          & d["q"].notna() & (np.log(d["q"]).abs() <= SHARE_GUARD) & year_apart)
    d["G"] = ((d["fcf"] - d["q"] * d["fcf_12"]) / d["total_assets"]).where(ok)
    return d


def h1_score(df: pd.DataFrame) -> pd.Series:
    """H1_t = G_t - G_(t-12): this year's change in split-neutral free cash flow per share (scaled by assets per
    share) minus last year's. Financials have no score. Returned aligned to df's index."""
    d = h1_velocity(df.assign(_i=np.arange(len(df))))
    d["G_12"] = _lag(d, "G", 12)
    d["fcf_end_24"] = _lag(d, "fcf_end", 24)
    chain = _days(d["fcf_end_24"], d["fcf_end_12"]).between(*YEAR_DAYS)
    score = (d["G"] - d["G_12"]).where(chain & d["G"].notna() & d["G_12"].notna())
    if "financial" in d:
        score = score.where(~d["financial"].astype(bool))
    return pd.Series(score.to_numpy(), index=d["_i"].to_numpy()).sort_index().set_axis(df.index)


# ---------- S2a ----------

def s2a_profitability(df: pd.DataFrame) -> pd.Series:
    """Stage 2's gross profitability with v2's point-in-time rule: gross profit (or revenue - cost of revenue)
    only when its own TTM period end is at most 183 days before the month-end, divided by total assets (> 0).
    A stale gross profit is never used; the row falls back to revenue - cost of revenue only if those are fresh.
    ADDENDUM_2 §1: the fallback is unavailable when revenue fails tests T0-T2 (`rev_conflict`, from
    `edge_b5_inputs.revenue_check`) or cost of revenue mixes bases (`cor_restated`, test T2); a `GrossProfit` tag
    whose TTM mixes bases (`gp_restated`, T2) is not used. All flags are point in time. Rows failing the identity
    rule (`identity_ok`, ADDENDUM_2 §3) are unavailable.
    Required columns: month, gross_profit, gp_end, gp_restated, revenue, cost_of_revenue, rev_end, cor_end,
    rev_conflict, cor_restated, total_assets, and the identity rule's columns. A missing flag value counts as failing (fail closed)."""
    m = pd.to_datetime(df["month"])
    gp_ok = df["gross_profit"].notna() & _days(df["gp_end"], m).between(0, FRESH_DAYS) & _clean(df, "gp_restated")
    alt_ok = (df["revenue"].notna() & df["cost_of_revenue"].notna() & (df["rev_end"] == df["cor_end"])
              & _days(df["rev_end"], m).between(0, FRESH_DAYS) & _clean(df, "rev_conflict") & _clean(df, "cor_restated"))
    gp = df["gross_profit"].where(gp_ok, (df["revenue"] - df["cost_of_revenue"]).where(alt_ok))
    return (gp / df["total_assets"].where(df["total_assets"] > 0)).where(identity_ok(df))


def s2a_score(frame: pd.DataFrame) -> pd.Series:
    """Percentile rank of gross profitability within SIC group among one month's eligible names, financials
    excluded (stage2._neutral on the engine's eligible set)."""
    x = frame["gp_assets"].where(~frame["financial"].astype(bool))
    return x.groupby(frame["group"]).rank(pct=True)


# ---------- portfolio helpers ----------

def combine_tranches(navs: list[pd.Series], start) -> pd.Series:
    """Equal capital in each tranche at the evaluation start, then no rebalancing between tranches (so no
    trading cost is hidden): combined NAV = mean of the tranche NAVs, each rebased to 1 at `start`."""
    start = pd.Timestamp(start)
    cols = []
    for s in navs:
        s = s[s.index >= start]
        if s.empty or s.index[0] != start:
            raise ValueError("every tranche must have a NAV on the evaluation start date")
        cols.append(s / s.iloc[0])
    j = pd.concat(cols, axis=1)
    if j.isna().any().any():
        raise ValueError("tranche NAV dates differ")
    return j.mean(axis=1)


def placebo_score(cik: pd.Series) -> pd.Series:
    """Hand-check score: a fixed hash of the CIK, carrying no information about returns."""
    return cik.map(lambda c: -int(hashlib.sha256(f"{PLACEBO_SALT}{int(c)}".encode()).hexdigest()[:15], 16) / 16 ** 15)


def newey_west_t(x: pd.Series, lags: int) -> float:
    x = pd.Series(x).dropna().to_numpy()
    n = len(x)
    if n < lags + 2:
        return float("nan")
    e = x - x.mean()
    s = e @ e / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * (e[L:] @ e[:-L]) / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else float("nan")


def verdict(r: dict, status: Path = STATUS) -> dict:
    """Frozen P1-P11 decision. `r` holds the primary statistics and every robustness result. Robustness results
    can only veto: none of them is ever used in place of the primary. Missing inputs fail closed.

    ADDENDUM_1 §6: while TTM check 4 is open, a result passing every gate is labelled E2_BLOCKED_LABEL, never
    "E2 candidate". Passing the gates is not evidence that survivorship bias is bounded or that an investable edge
    exists."""
    def pos(k):
        v = r.get(k)
        return v is not None and math.isfinite(v) and v > 0

    t = r.get("t_nw", float("nan"))
    checks = {
        "P1": math.isfinite(t) and t >= GATES["P1_t"] and (
            r.get("trial") != "S2A" or (r.get("t_nonoverlap") is not None and r["t_nonoverlap"] >= GATES["P1_s2a_nonoverlap_t"])),
        "P2": r.get("dsr") is not None and r["dsr"] >= GATES["P2_dsr"],
        "P3": pos("alpha") and r.get("alpha_t") is not None and r["alpha_t"] >= GATES["P3_alpha_t"],
        "P4": pos("excess_2x"), "P5": pos("excess_vs_universe"), "P6": pos("excess_miss100"),
        "P7": pos("excess_nextmonth"), "P8": pos("excess_dataerr"), "P9": pos("excess_pitq"),
        "P10": sum(1 for v in r.get("excess_thirds", []) if v is not None and v > 0) >= 2,
        "P11": pos("excess_without_top_contributor"),
    }
    if all(checks.values()):
        label = "E2 candidate" if check4_complete(status) else E2_BLOCKED_LABEL
    elif math.isfinite(t) and LEAD_T <= t < GATES["P1_t"] and all(v for k, v in checks.items() if k not in ("P1", "P2")):
        label = "lead, not a pass"
    else:
        label = "fail"
    return {"checks": checks, "label": label, "check4_complete": check4_complete(status)}
