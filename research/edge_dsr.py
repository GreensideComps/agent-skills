"""Deflated Sharpe with prior ETF experiments counted in N (owner decision D-B, review finding P30-3).

`edge_registry.deflated_sharpe` is pinned and stays byte-identical, so the extra multiple-testing count from
`edge_families.extra_n()` is applied here instead. The formula is the registry's, with

    N = edge_registry.n_trials(events) + extra_n

Prior experiments add to N only. They add no Sharpe values to the cross-trial variance: their configurations were
not recorded with comparable monthly Sharpe ratios, so the variance still comes from registry results of the same
statistic (floored at 1/n_months, as in the registry).

The caller must pass the family table's sha256 as returned by `extra_n()`; a stale or different table is refused, so
a count can never be computed from one table and cited against another.
"""
from __future__ import annotations

import math
import statistics

import edge_families
import edge_registry


def deflated_sharpe_with_prior(sr: float, n_months: int, skew: float, kurt: float, stat: str, events: list[dict],
                               extra_n: int, table_sha256: str) -> dict:
    if isinstance(extra_n, bool) or not isinstance(extra_n, int) or extra_n < 0:
        raise ValueError(f"extra_n must be a non-negative integer, got {extra_n!r}")
    if table_sha256 != edge_families.table_sha256():
        raise ValueError("table_sha256 does not match the current prior ETF family table")
    n = edge_registry.n_trials(events) + extra_n
    comp = edge_registry.sharpe_list(events, stat)
    floor = 1.0 / n_months
    emp = statistics.variance(comp) if len(comp) >= 2 else 0.0
    var = max(emp, floor)
    g = 0.5772156649
    nd = statistics.NormalDist()
    sr0 = math.sqrt(var) * ((1 - g) * nd.inv_cdf(1 - 1 / n) + g * nd.inv_cdf(1 - 1 / (n * math.e))) if n > 1 else 0.0
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return {"dsr": nd.cdf((sr - sr0) * math.sqrt(n_months - 1) / den), "n_trials": n,
            "n_registry": n - extra_n, "extra_n": extra_n, "table_sha256": table_sha256,
            "n_comparable": len(comp), "var_used": var, "floor_used": var == floor, "sr0": sr0, "stat": stat}
