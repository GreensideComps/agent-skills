"""Q263 (prereg research/always_on/prereg/Q263.md, registered 14 Nov 2026 before data): pooled down-gap exit.

    python3 research/always_on/q263_downgap_exit.py     # writes results/Q263.json
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

RES = "/mnt/project-files/research/always-on/results/Q263.json"
GAP, VOLX = -0.07, 3.0


def main():
    names = {}
    for f in sorted(os.listdir(q.BARS)):
        if f.endswith(".csv") and f != "SPY.csv" and (b := q.load_bars(f"{q.BARS}/{f}")):
            names[f[:-4]] = (b, q.liquid_flags(b))
    # per day: list of (ret, name, idx) for names liquid at prior close
    rets: dict[str, list] = {}
    for s, (b, liq) in names.items():
        for t in range(1, len(b["d"])):
            if liq[t - 1]:
                rets.setdefault(b["d"][t], []).append((b["c"][t] / b["c"][t - 1] - 1, s, t))
    ew = {d: statistics.fmean(r for r, _, _ in v) for d, v in rets.items()}
    # exit windows per (name, lag): set of dates flagged
    flags = {0: set(), 1: set()}
    n_exit = 0
    for s, (b, liq) in names.items():
        d, v = b["d"], b["v"]
        for k in range(21, len(d) - 2):
            if not liq[k - 1] or b["o"][k] / b["c"][k - 1] - 1 > GAP:
                continue
            med = statistics.median(v[k - 20:k])
            if med <= 0 or v[k] < VOLX * med:
                continue
            n_exit += 1
            for lag in (0, 1):
                t = k + 1 + lag
                if d[k + lag][:7] != d[k][:7]:
                    continue
                while t < len(d) and d[t][:7] == d[k][:7]:
                    flags[lag].add((s, d[t]))
                    t += 1
                flags[lag].add((s, "exit", d[k + lag]))
    def series(lag, cost):
        out = {}
        for day, v in rets.items():
            n = len(v)
            x = sum(ew[day] - r for r, s, _ in v if (s, day) in flags[lag])
            c = sum(2 * cost for _, s, _ in v if (s, "exit", day) in flags[lag])
            out[day[:7]] = out.get(day[:7], 0.0) + (x - c) / n
        return q.full(out)
    x = {"excess": series(0, q.COST), "costs_x2": series(0, 2 * q.COST), "lag1": series(1, q.COST)}
    batch = gate.Batch(id="Q263", configs=("Q263",), discovery=q.DISCOVERY, confirmation=q.CONFIRMATION, data="panel")
    g = gate.verdict(batch, {"Q263": x})
    import edge_registry as reg
    cfg = {**q.describe(x["excess"], reg.n_trials(reg.load())), "exits": n_exit,
           "disc_costs_x2_ann_pct": statistics.fmean(gate.window(x["costs_x2"], q.DISCOVERY)) * 1200,
           "disc_lag1_ann_pct": statistics.fmean(gate.window(x["lag1"], q.DISCOVERY)) * 1200,
           "passed": "Q263" in g["passed"]}
    with open(RES, "w") as fh:
        json.dump({"prereg": "prereg/Q263.md", "gate": g, "config": cfg}, fh, indent=1, default=str)
    print("Q263", "PASS" if cfg["passed"] else "FAIL", {k: cfg[k] for k in ("ann_pct", "te_ann_pct", "nw_t", "disc_ann_pct", "disc_nw_t", "thirds_ann_pct", "exits", "disc_lag1_ann_pct")})
    print(g["results"]["Q263"])


if __name__ == "__main__":
    main()
