#!/usr/bin/env python3
"""Audit of the research method itself: could the test have passed anything, and where could it have been fooled?

Reads the trial registry (research/edge/trials.jsonl) and prints the numbers behind research/METHOD_AUDIT.md, then
the survivorship table from always_on/survivorship_coverage.py (which reads the data panel through the holdout
guard and counts which companies have a price row, never what the price did). It registers nothing and changes no
result.

Run:  python3 research/method_audit.py            (prints the tables as Markdown)
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import edge_registry  # noqa: E402
import stats  # noqa: E402

REGISTRY = HERE / "edge" / "trials.jsonl"
PRIOR_N = 102          # trials counted before the registry existed (Stage 2 and earlier programmes)


def load(path: Path = REGISTRY) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def t_values(events: list[dict]) -> list[dict]:
    """Every result that recorded both a per-month Sharpe and its number of months: t = Sharpe x sqrt(months)."""
    reg = {e["id"]: e for e in events if e.get("event") == "register"}
    out = []
    for e in events:
        if e.get("event") == "result" and e.get("sr_monthly") is not None and e.get("n_months"):
            t = e["sr_monthly"] * math.sqrt(e["n_months"])
            out.append({"id": e["id"], "t": t, "months": e["n_months"], "p": stats.t_sf(t, e["n_months"] - 1),
                        "verdict": e.get("verdict"), "what": (reg.get(e["id"]) or {}).get("hypothesis", "")})
    return out


def tails(ts: list[float]) -> list[dict]:
    nd = statistics.NormalDist()
    return [{"t": c, "above": sum(v >= c for v in ts), "below": sum(v <= -c for v in ts),
             "by_luck": len(ts) * (1 - nd.cdf(c))} for c in (1.645, 2.0, 2.5, 3.0)]


def power_table(n_trials: int, te: float = 0.10) -> list[dict]:
    bar = stats.dsr_bar_t(n_trials)
    rows = []
    for ann in (0.02, 0.03, 0.05):
        for years in (8, 30, 95):
            exp_t = ann / te * math.sqrt(years)
            rows.append({"ann": ann, "years": years, "expected_t": exp_t, "p_plain": stats.power(exp_t, 2.0),
                         "p_bar": stats.power(exp_t, bar),
                         "years_for_80": stats.months_needed(ann, te, bar) / 12})
    return rows


def main() -> None:
    ev = load()
    n_reg = edge_registry.n_trials(ev)
    n = n_reg + PRIOR_N
    tv = t_values(ev)
    ts = [r["t"] for r in tv]
    results = [e for e in ev if e.get("event") == "result"]
    print(f"registry: {len(results)} results, {n_reg} counted trials (+{PRIOR_N} earlier = N {n})")
    print(f"bar: a deflated Sharpe of 0.95 at N {n} needs t >= {stats.dsr_bar_t(n):.2f}; "
          f"at N 100 {stats.dsr_bar_t(100):.2f}; at N 10 {stats.dsr_bar_t(10):.2f}")
    print("\n| True edge a year | Years of data | Expected t | Chance of t >= 2 | Chance of clearing the bar | Years needed for an 80% chance |\n|---|---|---|---|---|---|")
    for r in power_table(n):
        print(f"| {r['ann']:.0%} | {r['years']} | {r['expected_t']:.2f} | {r['p_plain']:.0%} | {r['p_bar']:.1%} | {r['years_for_80']:.0f} |")
    months = [e["n_months"] for e in results if e.get("n_months")]
    print(f"\nresults with a recorded length: {len(months)}; median {statistics.median(months):.0f} months; "
          f"{sum(m <= 120 for m in months)} of them 10 years or less")
    print(f"\nresults with both a Sharpe and a length (t can be computed): {len(ts)} of {len(results)}")
    print(f"mean t {statistics.fmean(ts):+.2f}, spread (sd) {statistics.pstdev(ts):.2f} (pure luck would give 0 and 1)")
    print("\n| t at least | Results above | Results below the negative | Expected by luck, each side |\n|---|---|---|---|")
    for r in tails(ts):
        print(f"| {r['t']} | {r['above']} | {r['below']} | {r['by_luck']:.1f} |")
    p = [r["p"] for r in tv]
    print(f"\nfalse-discovery view (Benjamini-Hochberg): {sum(stats.bh_fdr(p, 0.10))} discoveries at 10%, "
          f"{sum(stats.bh_fdr(p, 0.10, dependent=True))} allowing any dependence; Holm (family-wise 5%): {sum(stats.holm(p))}")
    print("\n| t | Trial | Months | Recorded verdict | Idea |\n|---|---|---|---|---|")
    keep = stats.bh_fdr(p, 0.10)
    for r, k in sorted(zip(tv, keep), key=lambda z: -z[0]["t"]):
        if k:
            print(f"| {r['t']:.2f} | {r['id']} | {r['months']} | {r['verdict']} | {r['what'][:110]} |")
    srs = [e["sr_monthly"] for e in results if e.get("sr_monthly") is not None]
    print(f"\nspread of recorded monthly Sharpes across trials: variance {statistics.variance(srs):.4f} "
          f"({statistics.variance(srs) * 96:.1f}x the 1/96 the copied formulas assume for an 8-year test)")
    print()
    sys.path.insert(0, str(HERE / "always_on"))
    import survivorship_coverage  # noqa: PLC0415  (reads the data panel through the holdout guard)
    survivorship_coverage.main()


if __name__ == "__main__":
    main()
