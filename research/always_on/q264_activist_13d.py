"""Q264 (prereg research/always_on/prereg/Q264.md, registered 14 Nov 2026 before data).

Q264: new SC 13D filing drift sleeve vs the EW liquid universe.
Reuses Q251's loaders, sleeve and reporting so the mechanics match the tested code.

    python3 research/always_on/q264_activist_13d.py     # writes results/Q264.json
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import gate  # noqa: E402
import q251_trend_exits as q  # noqa: E402

RES = "/mnt/project-files/research/always-on/results"
HOLD = 20


def events(names: set[str]) -> dict[str, list[str]]:
    cmap = {}
    with gzip.open(f"{q.DATA}/sec_companies.csv.gz", "rt") as fh:
        for r in csv.DictReader(fh):
            for t in re.split(r"[|,;]", r.get("tickers") or ""):
                t = t.strip().upper().replace(".", "-")
                if t in names:
                    cmap[int(r["cik"])] = t
                    break
    seen, out = set(), {}
    with gzip.open(f"{q.DATA}/edgar_sc13d_1996_2022.csv.gz", "rt") as fh:
        for r in csv.DictReader(fh):
            c = int(r["cik"])
            if r["form"] != "SC 13D" or c not in cmap or (c, r["path"]) in seen:
                continue
            seen.add((c, r["path"]))
            out.setdefault(cmap[c], []).append(r["filed"])
    return {s: sorted(set(v)) for s, v in out.items()}


def signals(sym: str, b: dict, liq: list[bool], filed: list[str]) -> list[dict]:
    import bisect
    import datetime as dt
    out, last = [], None
    for f in filed:
        if last and (dt.date.fromisoformat(f) - dt.date.fromisoformat(last)).days <= 365:
            continue
        last = f
        k = bisect.bisect_right(b["d"], f)
        if k < 1 or k + HOLD + 2 >= len(b["d"]) or not liq[k - 1]:
            continue
        out.append({"sym": sym, "k": k, "day": b["d"][k], "rank": 0})
    return out


def trade(b: dict, s: dict, arm: str, lag: int = 0) -> dict | None:
    i0 = s["k"] + lag
    if i0 + HOLD >= len(b["d"]):
        return None
    t1 = i0 + HOLD - 1
    return q._trade(s["sym"], b, i0, q.OPEN, b["o"][i0], (t1, q.CLOSE, b["c"][t1], "time"))


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

    ev = events(set(bars))
    sig = []
    for sym, b in bars.items():
        sig += signals(sym, b, liq[sym], ev.get(sym, []))

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
    common = {"prereg": "prereg/Q264.md", "universe": len(bars), "signals": len(sig), "trades": tstats}
    for bid, arm in (("Q264", None),):
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
