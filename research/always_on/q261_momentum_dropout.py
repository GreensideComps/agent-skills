"""Q261 (prereg research/always_on/prereg/Q261.md, registered 14 Nov 2026 before data): weekly drop-out exit.

    python3 research/always_on/q261_momentum_dropout.py     # writes results/Q261.json
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

RES = "/mnt/project-files/research/always-on/results/Q261.json"
TOP, CHECK = 12, 5


def load():
    closes, liq = {}, {}
    for f in sorted(os.listdir(q.BARS)):
        if not f.endswith(".csv") or f == "SPY.csv":
            continue
        b = q.load_bars(f"{q.BARS}/{f}")
        if not b:
            continue
        fl = q.liquid_flags(b)
        s = f[:-4]
        closes[s] = dict(zip(b["d"], b["c"]))
        liq[s] = {d: fl[i] and i >= 252 and b["c"][i - 252] > 0 and (b["c"][i - 21] / b["c"][i - 252] - 1)
                  for i, d in enumerate(b["d"])}
    days = sorted({d for c in closes.values() for d in c})
    return days, closes, liq


def ranks(day, liq):
    sc = [(m, s) for s, L in liq.items() if (m := L.get(day)) is not False and m is not None]
    sc.sort(key=lambda x: (-x[0], x[1]))
    return [s for _, s in sc]


def run(days, closes, liq, arm, cost, lag):
    held, pending, out = set(), [], {}
    month_end = {i for i in range(len(days) - 1) if days[i][:7] != days[i + 1][:7]}
    since = 0
    for i in range(1, len(days)):
        d, p = days[i], days[i - 1]
        r = [closes[s][d] / closes[s][p] - 1 for s in held if d in closes[s] and p in closes[s]]
        ret = statistics.fmean(r) if r else 0.0
        while pending and pending[0][0] == i:          # fills at this close
            _, new = pending.pop(0)
            changed = len(held ^ new) / 2
            ret -= 2 * cost * changed / TOP
            held = new
        out[d[:7]] = (1 + out.get(d[:7], 0.0)) * (1 + ret) - 1
        since += 1
        if i in month_end:
            rk = ranks(d, liq)
            if len(rk) >= 2 * TOP:
                pending.append((i + 1 + lag, set(rk[:TOP])))
            since = 0
        elif arm and since % CHECK == 0 and held:
            rk = ranks(d, liq)
            if len(rk) >= 2 * TOP:
                top_half = set(rk[:len(rk) // 2])
                keep = {s for s in held if s in top_half}
                new = set(keep)
                for s in rk:
                    if len(new) >= TOP:
                        break
                    new.add(s)
                if new != held:
                    pending.append((i + 1 + lag, new))
    return q.full(out)


def main():
    days, closes, liq = load()
    x = {}
    for key, cost, lag in (("excess", q.COST, 0), ("costs_x2", 2 * q.COST, 0), ("lag1", q.COST, 1)):
        base, arm = run(days, closes, liq, False, cost, lag), run(days, closes, liq, True, cost, lag)
        x[key] = q.diff(arm, base)
        if key == "excess":
            book = statistics.fmean(base.values()) * 1200
    batch = gate.Batch(id="Q261", configs=("Q261",), discovery=q.DISCOVERY, confirmation=q.CONFIRMATION, data="panel")
    g = gate.verdict(batch, {"Q261": x})
    import edge_registry as reg
    cfg = {**q.describe(x["excess"], reg.n_trials(reg.load())), "baseline_book_ann_pct": book,
           "disc_costs_x2_ann_pct": statistics.fmean(gate.window(x["costs_x2"], q.DISCOVERY)) * 1200,
           "disc_lag1_ann_pct": statistics.fmean(gate.window(x["lag1"], q.DISCOVERY)) * 1200,
           "passed": "Q261" in g["passed"]}
    with open(RES, "w") as fh:
        json.dump({"prereg": "prereg/Q261.md", "gate": g, "config": cfg}, fh, indent=1, default=str)
    print("Q261", "PASS" if cfg["passed"] else "FAIL", {k: cfg[k] for k in ("ann_pct", "te_ann_pct", "nw_t", "disc_ann_pct", "disc_nw_t", "thirds_ann_pct", "baseline_book_ann_pct")})


if __name__ == "__main__":
    main()
