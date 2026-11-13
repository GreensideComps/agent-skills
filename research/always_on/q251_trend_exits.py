"""Q251-Q253 sell-rule batch 8 (prereg research/always_on/prereg/Q251.md, registered 13 Nov 2026 before data).

Exits for the demo's two trend strategies, vol_squeeze and breakout_momentum, on Yahoo daily OHLCV 1995-2022 for the
Q183 universe. Each strategy and each arm runs a 10-slot sleeve measured against the equal-weight liquid universe:

  Q251a/b  trailing 10-session-low exit with no time limit or target, minus the live exit
  Q252a/b  3 x ATR20 stop instead of the fixed-percentage stop, minus the live exit
  Q253a/b  the live rule itself

The entry signals call the agent's own code (market_agent.swing.squeeze, market_agent.review) so the test trades the
rule the demo trades. `simulate` and `sleeve` are pure and tested in research/tests/test_q251_trend_exits.py.

    python3 research/always_on/q251_trend_exits.py            # full run, writes results/Q251.json
"""
from __future__ import annotations

import bisect
import csv
import json
import os
import statistics
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "agent"))

import gate  # noqa: E402
import stats  # noqa: E402
from market_agent import review, swing  # noqa: E402

DATA = "/mnt/project-files/research-data"
BARS = f"{DATA}/yahoo_ohlc_1995"
OUT = "/mnt/project-files/research/always-on/results/Q251.json"
SLOTS = 10
COST = 0.0015                  # a side
MIN_DOLLAR = 10e6
DISCOVERY, CONFIRMATION = ("1996-07", "2009-12"), ("2010-01", "2022-12")
SQ = {"squeeze_pct": 0.10, "volume_x": 1.5, "min_price": 0.0, "min_dollar_volume": 0.0}   # liquidity is applied here
OPEN, INTRA, CLOSE = 0, 1, 2   # moments inside a session, in order


# ------------------------------------------------------------------ data
def load_bars(path: str) -> dict | None:
    """{d, o, h, l, c, v} lists, oldest first, cleaned as the prereg fixes: no close or a price <= 0 drops the row;
    the high is raised to max(open, close, high) and the low lowered to min(open, close, low)."""
    out = {k: [] for k in "dohlcv"}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            try:
                o, h, l, c = (float(r[k]) for k in ("adj_open", "adj_high", "adj_low", "adj_close"))
                v = float(r["volume"] or 0)
            except (ValueError, KeyError):
                continue
            if min(o, h, l, c) <= 0:
                continue
            out["d"].append(r["date"]); out["o"].append(o); out["c"].append(c); out["v"].append(v)
            out["h"].append(max(o, c, h)); out["l"].append(min(o, c, l))
    return out if len(out["d"]) > 300 else None


def liquid_flags(b: dict) -> list[bool]:
    """Per session k: median of close x volume over the 20 sessions up to k is at least $10m."""
    dv = [c * v for c, v in zip(b["c"], b["v"])]
    return [k >= 19 and statistics.median(dv[k - 19:k + 1]) >= MIN_DOLLAR for k in range(len(dv))]


def momentum_off_days(spy: dict, vix: dict[str, float]) -> dict[str, bool]:
    """{day: off} from closes up to and including that day: SPY's close below the mean of its last 10 completed
    month-end closes, or the last VIX close at 25 or more. Missing history blocks (True), as live."""
    out, ends, vix_days = {}, {}, sorted(vix)
    for i, d in enumerate(spy["d"]):
        ends[d[:7]] = spy["c"][i]
        done = [c for m, c in sorted(ends.items()) if m < d[:7]][-10:]
        j = bisect.bisect_right(vix_days, d) - 1
        if len(done) < 10 or j < 0:
            out[d] = True
            continue
        out[d] = spy["c"][i] < sum(done) / 10 or vix[vix_days[j]] >= 25.0
    return out


def atr20(b: dict, k: int) -> float:
    tr = [max(b["h"][i], b["c"][i - 1]) - min(b["l"][i], b["c"][i - 1]) for i in range(k - 19, k + 1)]
    return sum(tr) / 20


# ------------------------------------------------------------------ one trade
def simulate(b: dict, i0: int, px: float, at_open: bool, stop: float | None = None, target: float | None = None,
             time_days: int | None = None, time_strict: bool = False, trail_days: int | None = None,
             trail_arm: float | None = None, review_exit=None, cap: int | None = None) -> tuple[int, int, float, str]:
    """Walk one trade forward from session i0 (bought at `px`, at the open or at the close of i0) and return
    (exit session, moment, exit price, reason). Order inside a session: time limit and cap at the open; a gap
    through the stop or the trailing level at the open; then intraday the stop and trailing level (the higher one
    if both are touched); then the target; then the review at the close. The trailing level on session t is the
    lowest low of sessions t-trail_days..t-1; with `trail_arm` it needs the highest high from the entry session to
    t-1 to have reached px x (1 + trail_arm). A trade still open at the last bar is closed at that close."""
    n = len(b["d"])
    d0 = date.fromisoformat(b["d"][i0])
    limit = d0 + timedelta(days=time_days) if time_days is not None else None
    peak = b["h"][i0] if at_open else px
    start = i0 if at_open else i0 + 1
    for t in range(start, n):
        o, h, l, c = b["o"][t], b["h"][t], b["l"][t], b["c"][t]
        first = at_open and t == i0          # the entry session of a trade bought at the open: no open-time checks
        if not first:
            dt = date.fromisoformat(b["d"][t])
            if limit is not None and (dt > limit if time_strict else dt >= limit):
                return t, OPEN, o, "time"
            if cap is not None and t - i0 >= cap:
                return t, OPEN, o, "cap"
        level = None
        if trail_days is not None and not first and t - trail_days >= 0 \
                and (trail_arm is None or peak >= px * (1 + trail_arm)):
            level = min(b["l"][t - trail_days:t])
        if not first:
            if stop is not None and o <= stop:
                return t, OPEN, o, "stop"
            if level is not None and o < level:
                return t, OPEN, o, "trailing"
            if target is not None and o >= target:
                return t, OPEN, o, "target"
        hit_stop = stop is not None and l <= stop
        hit_trail = level is not None and l < level
        if hit_stop or hit_trail:
            if hit_stop and (not hit_trail or stop >= level):
                return t, INTRA, stop, "stop"
            return t, INTRA, level, "trailing"
        if target is not None and h >= target:
            return t, INTRA, target, "target"
        if review_exit is not None and review_exit(t):
            return t, CLOSE, c, "review"
        peak = max(peak, h)
    return n - 1, CLOSE, b["c"][-1], "end_of_data"


# ------------------------------------------------------------------ signals
def composite(b: dict, k: int) -> float | None:
    if k < 251:
        return None
    return review.score(review.factors(b["c"][k - 251:k + 1], b["v"][k - 251:k + 1]))["composite"]


def squeeze_signals(sym: str, b: dict, liq: list[bool], off: dict[str, bool]) -> list[dict]:
    """vol_squeeze signal days from the agent's own `swing.squeeze`, run on the 271 bars the live check needs."""
    out = []
    c, h, v = b["c"], b["h"], b["v"]
    for k in range(270, len(c) - 1):
        # cheap necessary conditions first; swing.squeeze then decides
        if not liq[k] or c[k] <= max(h[k - 20:k]) or v[k] < 1.5 * sum(v[k - 20:k]) / 20 or off.get(b["d"][k], True):
            continue
        w = {x: b[x][k - 270:k + 1] for x in "ohlcv"}
        w["t"] = [None] * 271
        r = swing.squeeze(w, SQ)
        if r["signal"]:
            out.append({"sym": sym, "k": k, "day": b["d"][k], "rank": r["pct"], "low20": r["low20"]})
    return out


def breakout_signals(sym: str, b: dict, liq: list[bool], off: dict[str, bool]) -> list[dict]:
    out = []
    c = b["c"]
    for k in range(251, len(c) - 1):
        move = c[k] / c[k - 1] - 1
        if move < 0.05 or not liq[k] or off.get(b["d"][k], True):
            continue
        comp = composite(b, k)
        if comp is not None and comp >= 0.25:
            out.append({"sym": sym, "k": k, "day": b["d"][k], "rank": -move})
    return out


def squeeze_trade(b: dict, s: dict, arm: str, lag: int = 0) -> dict | None:
    """One vol_squeeze trade under an exit arm: 'live', 'trail' (Q251a) or 'atr' (Q252a). None when the chase rule
    or an impossible stop refuses the entry."""
    k, i0 = s["k"], s["k"] + 1 + lag
    if i0 >= len(b["d"]):
        return None
    px = b["o"][i0]
    if px > 1.03 * b["c"][k]:
        return None
    stop = px - 3 * atr20(b, k) if arm == "atr" else max(s["low20"], px * 0.92)
    if stop >= px:
        return None
    if arm == "trail":
        ex = simulate(b, i0, px, True, stop=stop, trail_days=10, cap=250)
    else:
        ex = simulate(b, i0, px, True, stop=stop, time_days=28, trail_days=10, trail_arm=0.10)
    return _trade(s["sym"], b, i0, OPEN, px, ex)


def breakout_trade(b: dict, s: dict, arm: str, lag: int = 0) -> dict | None:
    k = s["k"]
    i0, at_open = (k + 1, True) if lag else (k, False)
    if i0 >= len(b["d"]) - 1:
        return None
    px = b["o"][i0] if at_open else b["c"][k]
    stop = px - 3 * atr20(b, k) if arm == "atr" else px * 0.95
    if stop >= px:
        return None
    if arm == "trail":
        ex = simulate(b, i0, px, at_open, stop=stop, trail_days=10, cap=250)
    else:
        ex = simulate(b, i0, px, at_open, stop=stop, target=px * 1.10, time_days=5, time_strict=True,
                      review_exit=lambda t: (composite(b, t) or 0) <= -0.35)
    return _trade(s["sym"], b, i0, OPEN if at_open else CLOSE, px, ex)


def _trade(sym: str, b: dict, i0: int, m0: int, px: float, ex: tuple) -> dict:
    t1, m1, px1, why = ex
    return {"sym": sym, "i0": i0, "m0": m0, "px": px, "i1": t1, "m1": m1, "px1": px1, "why": why,
            "d0": b["d"][i0], "d1": b["d"][t1], "ret": px1 / px - 1, "sessions": t1 - i0}


# ------------------------------------------------------------------ sleeve
def trade_days(b: dict, tr: dict) -> list[tuple[str, float, bool]]:
    """(day, trade return that day, benchmark is open-to-close) for each session the trade is open."""
    out = []
    for t in range(tr["i0"], tr["i1"] + 1):
        start = tr["px"] if t == tr["i0"] else b["c"][t - 1]
        end = tr["px1"] if t == tr["i1"] else b["c"][t]
        if t == tr["i0"] and tr["m0"] == CLOSE:
            continue                                   # bought at the close: no return that session
        out.append((b["d"][t], end / start - 1, t == tr["i0"] and tr["m0"] == OPEN))
    return out


def sleeve(cands: list[dict | None], signals: list[dict], bars: dict, bench_cc: dict, bench_oc: dict,
           cost: float = COST, slots: int = SLOTS) -> tuple[dict[str, float], list[dict]]:
    """Run one arm's sleeve: take signals in order (day, rank, ticker) while a slot is free and the name is not held,
    and return ({month: excess return of the sleeve}, trades taken). A slot is free once its trade's exit session is
    before the new trade's entry session, or the same session for an entry at the close."""
    order = sorted((i for i in range(len(signals)) if cands[i] is not None),
                   key=lambda i: (cands[i]["d0"], cands[i]["m0"], signals[i]["rank"], signals[i]["sym"]))
    open_tr: list[dict] = []
    taken: list[dict] = []
    monthly: dict[str, float] = {}
    w = 1.0 / slots
    for i in order:
        tr = cands[i]
        open_tr = [x for x in open_tr if not (x["d1"] < tr["d0"] or (x["d1"] == tr["d0"] and tr["m0"] == CLOSE))]
        if len(open_tr) >= slots or any(x["sym"] == tr["sym"] for x in open_tr):
            continue
        open_tr.append(tr)
        taken.append(tr)
        for day, r, oc in trade_days(bars[tr["sym"]], tr):
            bm = (bench_oc if oc else bench_cc).get(day, 0.0)
            monthly[day[:7]] = monthly.get(day[:7], 0.0) + w * (r - bm)
        for day in (tr["d0"], tr["d1"]):
            monthly[day[:7]] = monthly.get(day[:7], 0.0) - w * cost
    return monthly, taken


def months(a: str, b: str) -> list[str]:
    y, m = int(a[:4]), int(a[5:])
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def full(series: dict[str, float]) -> dict[str, float]:
    return {m: series.get(m, 0.0) for m in months(DISCOVERY[0], CONFIRMATION[1])}


def diff(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {m: a[m] - b[m] for m in a}


# ------------------------------------------------------------------ reporting
def describe(x: dict[str, float], n_trials: int) -> dict:
    v = [x[m] for m in sorted(x)]
    mm = stats.moments(v)
    third = len(v) // 3
    return {"ann_pct": mm["mean"] * 1200, "te_ann_pct": mm["sd"] * 12 ** 0.5 * 100, "nw_t": stats.nw_t(v),
            "n_months": mm["n"], "sr_monthly": mm["sr"], "skew": mm["skew"], "kurt": mm["kurt"],
            "thirds_ann_pct": [statistics.fmean(v[i * third:(i + 1) * third if i < 2 else None]) * 1200 for i in range(3)],
            "dsr": stats.deflated_sharpe_of(v, n_trials),
            "disc_ann_pct": statistics.fmean(gate.window(x, DISCOVERY)) * 1200,
            "disc_nw_t": stats.nw_t(gate.window(x, DISCOVERY)),
            "conf_ann_pct_info_only": statistics.fmean(gate.window(x, CONFIRMATION)) * 1200}


def trade_stats(tr: list[dict]) -> dict:
    if not tr:
        return {"trades": 0}
    r = [t["ret"] for t in tr]
    why: dict[str, int] = {}
    for t in tr:
        why[t["why"]] = why.get(t["why"], 0) + 1
    return {"trades": len(tr), "win_rate": sum(1 for x in r if x > 0) / len(r), "mean_ret_pct": statistics.fmean(r) * 100,
            "median_ret_pct": statistics.median(r) * 100, "mean_sessions": statistics.fmean(t["sessions"] for t in tr),
            "exits": why}


def bench_decision(d: dict, d2: dict, dl: dict) -> bool:
    """The prereg's BENCH test for a failed exit config: discovery-window mean positive with t >= 1.0, and positive
    on the discovery window with costs doubled and with a one-session lag."""
    w = gate.window(d, DISCOVERY)
    t = stats.nw_t(w)
    return (statistics.fmean(w) > 0 and t is not None and t >= 1.0
            and statistics.fmean(gate.window(d2, DISCOVERY)) > 0 and statistics.fmean(gate.window(dl, DISCOVERY)) > 0)


def main() -> None:
    names = sorted(f[:-4] for f in os.listdir(BARS) if f.endswith(".csv") and f != "SPY.csv")
    bars = {s: b for s in names if (b := load_bars(f"{BARS}/{s}.csv"))}
    spy = load_bars(f"{BARS}/SPY.csv")
    vix = {}
    for r in csv.DictReader(open(f"{DATA}/fred/VIXCLS.csv")):
        try:
            vix[r["observation_date"]] = float(r["VIXCLS"])
        except ValueError:
            pass
    off = momentum_off_days(spy, vix)
    liq = {s: liquid_flags(b) for s, b in bars.items()}
    # equal-weight liquid-universe return per day: close-to-close and open-to-close, names liquid the session before
    acc_cc: dict[str, list[float]] = {}
    acc_oc: dict[str, list[float]] = {}
    for s, b in bars.items():
        for t in range(1, len(b["d"])):
            if liq[s][t - 1]:
                acc_cc.setdefault(b["d"][t], []).append(b["c"][t] / b["c"][t - 1] - 1)
                acc_oc.setdefault(b["d"][t], []).append(b["c"][t] / b["o"][t] - 1)
    bench_cc = {d: statistics.fmean(v) for d, v in acc_cc.items()}
    bench_oc = {d: statistics.fmean(v) for d, v in acc_oc.items()}

    sig = {"squeeze": [], "breakout": []}
    for s, b in bars.items():
        sig["squeeze"] += squeeze_signals(s, b, liq[s], off)
        sig["breakout"] += breakout_signals(s, b, liq[s], off)
    maker = {"squeeze": squeeze_trade, "breakout": breakout_trade}
    series: dict[str, dict] = {}
    trades: dict[str, dict] = {}
    for strat in ("squeeze", "breakout"):
        for arm in ("live", "trail", "atr"):
            for lag in (0, 1):
                cands = [maker[strat](bars[s["sym"]], s, arm, lag) for s in sig[strat]]
                for label, cost in (("base", COST), ("x2", 2 * COST)):
                    if lag and label == "x2":
                        continue
                    m, taken = sleeve(cands, sig[strat], bars, bench_cc, bench_oc, cost)
                    key = f"{strat}.{arm}.{'lag1' if lag else label}"
                    series[key] = full(m)
                    if not lag and label == "base":
                        trades[f"{strat}.{arm}"] = trade_stats(taken)

    def inputs(strat: str, arm: str | None) -> dict:
        def one(kind: str) -> dict:
            live = series[f"{strat}.live.{kind}"]
            return live if arm is None else diff(series[f"{strat}.{arm}.{kind}"], live)
        return {"excess": one("base"), "costs_x2": one("x2"), "lag1": one("lag1")}

    cfg = {"Q251a": ("squeeze", "trail"), "Q251b": ("breakout", "trail"), "Q252a": ("squeeze", "atr"),
           "Q252b": ("breakout", "atr"), "Q253a": ("squeeze", None), "Q253b": ("breakout", None)}
    n_at = {"Q251a": 493, "Q251b": 494, "Q252a": 495, "Q252b": 496, "Q253a": 497, "Q253b": 498}
    rep = {"prereg": "prereg/Q251.md", "universe": len(bars), "signals": {k: len(v) for k, v in sig.items()},
           "trades": trades, "gate": {}, "configs": {}}
    for bid in ("Q251", "Q252", "Q253"):
        ids = tuple(i for i in cfg if i.startswith(bid))
        batch = gate.Batch(id=bid, configs=ids, discovery=DISCOVERY, confirmation=CONFIRMATION, data="panel")
        ins = {i: inputs(*cfg[i]) for i in ids}
        rep["gate"][bid] = gate.verdict(batch, ins)
        for i in ids:
            rep["configs"][i] = {**describe(ins[i]["excess"], n_at[i]),
                                 "disc_costs_x2_ann_pct": statistics.fmean(gate.window(ins[i]["costs_x2"], DISCOVERY)) * 1200,
                                 "disc_lag1_ann_pct": statistics.fmean(gate.window(ins[i]["lag1"], DISCOVERY)) * 1200,
                                 "passed": i in rep["gate"][bid]["passed"],
                                 "bench": bid != "Q253" and i not in rep["gate"][bid]["passed"]
                                 and bench_decision(ins[i]["excess"], ins[i]["costs_x2"], ins[i]["lag1"])}
    json.dump(rep, open(OUT, "w"), indent=1, default=str)
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main()
