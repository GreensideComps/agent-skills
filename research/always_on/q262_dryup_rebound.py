"""Q262 (prereg research/always_on/prereg/Q262.md, registered 14 Nov 2026 before data).

Q262: drop then volume dry-up rebound sleeve vs the EW liquid universe.
Reuses Q251's loaders, sleeve and reporting so the mechanics match the tested code.

    python3 research/always_on/q262_dryup_rebound.py     # writes results/Q262.json
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

RES = "/mnt/project-files/research/always-on/results"
DROP, HOLD, CHASE = -0.06, 10, 1.03


def signals(sym: str, b: dict, liq: list[bool]) -> list[dict]:
    out, v = [], b["v"]
    for k in range(21, len(b["d"]) - HOLD - 6):
        if not liq[k - 1] or b["c"][k] / b["c"][k - 1] - 1 > DROP:
            continue
        med = statistics.median(v[k - 20:k])
        if med <= 0 or any(v[k + j] >= med for j in (1, 2, 3)) or min(b["l"][k + 1:k + 4]) < b["l"][k]:
            continue
        out.append({"sym": sym, "k": k + 3, "day": b["d"][k + 3], "rank": b["c"][k] / b["c"][k - 1] - 1})
    return out


def trade(b: dict, s: dict, arm: str, lag: int = 0) -> dict | None:
    k = s["k"]
    i0 = k + 1 + lag
    if i0 + HOLD >= len(b["d"]):
        return None
    px = b["o"][i0]
    if px > CHASE * b["c"][k]:
        return None
    t1 = i0 + HOLD - 1
    return q._trade(s["sym"], b, i0, q.OPEN, px, (t1, q.CLOSE, b["c"][t1], "time"))


def main() -> None:
    names = sorted(f[:-4] for f in os.listdir(q.BARS) if f.endswith(".csv") and f != "SPY.csv")
    bars = {s: b for s in names if (b := q.load_bars(f"{q.BARS}/{s}.csv"))}
    liq = {s: q.liquid_flags(b) for s, b in bars.items()}
    acc_cc: dict[str, list[float]] = {}
    acc_oc: dict[str, list[float]] = {}
    for s, b in bars.items():
        for t in range(1, len(b["d"])):
            if liq[s][t - 1]:
                acc_cc.setdefault(b["d"][t], []).append(b["c"][t] / b["c"][t - 1] - 1)
                acc_oc.setdefault(b["d"][t], []).append(b["c"][t] / b["o"][t] - 1)
    bench_cc = {d: statistics.fmean(v) for d, v in acc_cc.items()}
    bench_oc = {d: statistics.fmean(v) for d, v in acc_oc.items()}

    sig = []
    for sym, b in bars.items():
        sig += signals(sym, b, liq[sym])

    series, tstats = {}, {}
    for arm in ("hold",):
        for lag in (0, 1):
            cands = [trade(bars[s["sym"]], s, arm, lag) for s in sig]
            for label, cost in (("base", q.COST), ("x2", 2 * q.COST)):
                if lag and label == "x2":
                    continue
                m, taken = q.sleeve(cands, sig, bars, bench_cc, bench_oc, cost)
                series[f"{arm}.{'lag1' if lag else label}"] = q.full(m)
                if not lag and label == "base":
                    tstats[arm] = q.trade_stats(taken)

    def ins(arm_minus: str | None) -> dict:
        def one(kind):
            a = series[f"hold.{kind}"]
            return a if arm_minus is None else q.diff(series[f"tstop.{kind}"], a)
        return {"excess": one("base"), "costs_x2": one("x2"), "lag1": one("lag1")}

    import edge_registry as reg
    n = reg.n_trials(reg.load() if hasattr(reg, "load") else [json.loads(l) for l in open(reg.PATH)])
    common = {"prereg": "prereg/Q262.md", "universe": len(bars), "signals": len(sig), "trades": tstats}
    for bid, arm in (("Q262", None),):
        batch = gate.Batch(id=bid, configs=(bid,), discovery=q.DISCOVERY, confirmation=q.CONFIRMATION, data="panel")
        x = ins(arm)
        g = gate.verdict(batch, {bid: x})
        cfg = {**q.describe(x["excess"], n),
               "disc_costs_x2_ann_pct": statistics.fmean(gate.window(x["costs_x2"], q.DISCOVERY)) * 1200,
               "disc_lag1_ann_pct": statistics.fmean(gate.window(x["lag1"], q.DISCOVERY)) * 1200,
               "passed": bid in g["passed"]}
        with open(f"{RES}/{bid}.json", "w") as fh:
            json.dump({**common, "gate": g, "config": cfg}, fh, indent=1, default=str)
        print(bid, "PASS" if cfg["passed"] else "FAIL", {k: cfg[k] for k in ("ann_pct", "te_ann_pct", "nw_t", "disc_ann_pct", "disc_nw_t", "dsr")})
    print(json.dumps(common, default=str)[:600])


if __name__ == "__main__":
    main()
