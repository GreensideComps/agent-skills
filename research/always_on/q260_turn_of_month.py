"""Q260 (prereg research/always_on/prereg/Q260.md, registered 14 Nov 2026 before data): turn-of-month premium.

    python3 research/always_on/q260_turn_of_month.py     # writes results/Q260.json
"""
from __future__ import annotations

import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import gate  # noqa: E402
import q251_trend_exits as q  # noqa: E402

RES = "/mnt/project-files/research/always-on/results/Q260.json"
RT = 2 * q.COST


def ew_returns() -> dict[str, float]:
    acc: dict[str, list[float]] = {}
    for f in sorted(os.listdir(q.BARS)):
        if not f.endswith(".csv") or f == "SPY.csv":
            continue
        b = q.load_bars(f"{q.BARS}/{f}")
        if not b:
            continue
        liq = q.liquid_flags(b)
        for t in range(1, len(b["d"])):
            if liq[t - 1]:
                acc.setdefault(b["d"][t], []).append(b["c"][t] / b["c"][t - 1] - 1)
    return {d: statistics.fmean(v) for d, v in acc.items() if len(v) >= 20}


def series(r: dict[str, float], shift: int, cost: float) -> dict[str, float]:
    days = sorted(r)
    ends = [i for i in range(len(days) - 1) if days[i][:7] != days[i + 1][:7]]
    out, prev_hi = {}, None
    for e in ends:
        lo, hi = e - 1 + shift, e + 3 + shift
        if prev_hi is None or hi >= len(days) or lo <= prev_hi + 1:
            prev_hi = hi
            continue
        tom = [r[days[i]] for i in range(lo, hi + 1)]
        oth = [r[days[i]] for i in range(prev_hi + 1, lo)]
        out[days[e][:7]] = sum(tom) - len(tom) / len(oth) * sum(oth) - cost
        prev_hi = hi
    return q.full(out)


def main() -> None:
    r = ew_returns()
    x = {"excess": series(r, 0, RT), "costs_x2": series(r, 0, 2 * RT), "lag1": series(r, 1, RT)}
    batch = gate.Batch(id="Q260", configs=("Q260",), discovery=q.DISCOVERY, confirmation=q.CONFIRMATION, data="panel")
    g = gate.verdict(batch, {"Q260": x})
    import edge_registry as reg
    n = reg.n_trials(reg.load())
    gross = series(r, 0, 0.0)
    cfg = {**q.describe(x["excess"], n), "gross_ann_pct": statistics.fmean(gross.values()) * 1200,
           "disc_costs_x2_ann_pct": statistics.fmean(gate.window(x["costs_x2"], q.DISCOVERY)) * 1200,
           "disc_lag1_ann_pct": statistics.fmean(gate.window(x["lag1"], q.DISCOVERY)) * 1200,
           "passed": "Q260" in g["passed"]}
    with open(RES, "w") as fh:
        json.dump({"prereg": "prereg/Q260.md", "days": len(r), "gate": g, "config": cfg}, fh, indent=1, default=str)
    print("Q260", "PASS" if cfg["passed"] else "FAIL", {k: cfg[k] for k in ("ann_pct", "gross_ann_pct", "te_ann_pct", "nw_t", "disc_ann_pct", "disc_nw_t", "thirds_ann_pct")})


if __name__ == "__main__":
    main()
