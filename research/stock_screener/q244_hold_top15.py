"""Q244: how the screener holds its top 15 (prereg /mnt/project-files/research/always-on/prereg/Q244.md).
R0 = current live rule; b = capped top 15 monthly; c = owner's rule (hold until out of top 15, no fillers);
d = c with a top-30 sell buffer. Data to 2022-12-31 only (exploration)."""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick1 as p1  # noqa: E402

COST, SLOTS, SECTOR_MAX, N0 = p1.COST, 15, 6, 484
OUT = Path("/mnt/project-files/research/always-on/results/Q244.json")


def sector(sic) -> str:
    s = int(sic) if pd.notna(sic) else 0
    if 2000 <= s <= 2199 or 2840 <= s <= 2844 or 5400 <= s <= 5499 or s == 5912 or 5140 <= s <= 5149:
        return "staples"
    if (2300 <= s <= 2399 or s == 3021 or 3100 <= s <= 3199 or 3711 <= s <= 3716 or 3940 <= s <= 3949
            or 5200 <= s <= 5999 or 7000 <= s <= 7099 or 7900 <= s <= 7999 or 8200 <= s <= 8299
            or 2510 <= s <= 2599 or 3630 <= s <= 3639 or 1520 <= s <= 1531):
        return "discretionary"
    if 3570 <= s <= 3579 or 3600 <= s <= 3699 or 7370 <= s <= 7379 or 3820 <= s <= 3829:
        return "tech"
    if 2830 <= s <= 2836 or 3840 <= s <= 3851 or 8000 <= s <= 8099:
        return "health"
    if 1300 <= s <= 1399 or 2900 <= s <= 2999:
        return "energy"
    if 1000 <= s <= 1499 or 2600 <= s <= 2699 or 2800 <= s <= 2899 or 3300 <= s <= 3399:
        return "materials"
    if 4800 <= s <= 4899 or 2700 <= s <= 2799 or 7810 <= s <= 7849:
        return "communication"
    return "industrials"


def build():
    df = p1.load()
    df = df[df["month"] <= "2022-12-31"]
    by = {m: g for m, g in df.groupby("month")}
    out = []
    for m in sorted(by):
        if m < pd.Timestamp("2014-12-31") or m > pd.Timestamp("2022-11-30"):
            continue
        u = p1.universe(by[m])
        g = p1.score(u)
        g = g.assign(rank=np.arange(1, len(g) + 1), sec=g["sic"].map(sector)).set_index("cik")
        uu = u.set_index("cik")
        r = uu["ret_next"]
        w = uu["mcap"].where(r.notna())
        out.append({"m": m, "G": g, "R": r, "ew": float(r.mean()), "mkt": float((r * w).sum() / w.sum())})
    return out


def fits(c, hold, G):
    sec = G.loc[c, "sec"]; s2 = G.loc[c, "sic2"]
    hs = [h for h in hold if h is not None and h in G.index]
    return (sum(G.loc[h, "sec"] == sec for h in hs) < SECTOR_MAX
            and sum(G.loc[h, "sic2"] == s2 for h in hs) < p1.PER_SIC)


def fill(hold, G, maxrank):
    """Fill empty slots with the best unheld names within caps and rank <= maxrank."""
    n = 0
    for c in G.index:
        if None not in hold:
            break
        if G.loc[c, "rank"] > maxrank:
            break
        if c in hold or not fits(c, hold, G):
            continue
        hold[hold.index(None)] = c; n += 1
    return n


def sim(M, rule, cost=COST, lag=0):
    hold, rows = [None] * SLOTS, []
    for k, x in enumerate(M):
        G = M[max(k - lag, 0)]["G"]  # decision data (lagged one month for the lag check)
        trades = 0
        if rule == "R0":
            if all(h is None for h in hold):
                trades += fill(hold, G, 10**9)
            else:
                for i, h in enumerate(hold):  # gate fail -> immediate swap
                    if h is not None and h not in G.index:
                        hold[i] = None
                held = [(G.loc[h, "score"], i) for i, h in enumerate(hold) if h is not None and h in G.index]
                if held:
                    sc, i = min(held)
                    if G.loc[hold[i], "rank"] > SLOTS:
                        hold[i] = None
                trades += fill(hold, G, 10**9)
        elif rule == "b":
            target = [None] * SLOTS
            fill(target, G, SLOTS)
            trades = len(set(t for t in target if t) - set(h for h in hold if h))
            hold = target
        elif rule in ("c", "d"):
            band = SLOTS if rule == "c" else 30
            for i, h in enumerate(hold):
                if h is not None and (h not in G.index or G.loc[h, "rank"] > band):
                    hold[i] = None
            trades += fill(hold, G, SLOTS)
        R = x["R"]
        rs = [x["mkt"] if h is None else (0.0 if pd.isna(R.get(h, np.nan)) else float(R.get(h))) for h in hold]
        net = float(np.mean(rs)) - 2 * cost * trades / SLOTS
        rows.append((x["m"] + pd.offsets.MonthEnd(1), net, x["ew"], sum(h is None for h in hold), trades))
    return pd.DataFrame(rows, columns=["month", "net", "ew", "cash_slots", "trades"]).set_index("month")


def tstat(d):
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


def main():
    M = build()
    fx = p1.gbp_factor(); vw = p1.vwrp_monthly()
    legs = {r: sim(M, r) for r in ["R0", "b", "c", "d"]}
    base = legs["R0"]["net"]
    res = {}
    for r, n in zip("bcd", range(N0, N0 + 3)):
        x = legs[r]; d = x["net"] - base
        s = {"months": len(d), "mean_d_pct_m": float(d.mean() * 100), "ann_d_pct": float(d.mean() * 1200), "t": tstat(d),
             "thirds_pct_m": [float(v.mean() * 100) for v in np.array_split(d.values, 3)],
             "costs2_mean_d_pct_m": float(((sim(M, r, cost=2 * COST)["net"] - sim(M, "R0", cost=2 * COST)["net"]).mean()) * 100),
             "lag_mean_d_pct_m": float(((sim(M, r, lag=1)["net"] - sim(M, "R0", lag=1)["net"]).mean()) * 100),
             "trades_per_yr": float(x["trades"].iloc[1:].sum() / (len(x) / 12)), "avg_cash_slots": float(x["cash_slots"].mean())}
        sr = d.mean() / d.std(ddof=1)
        s["dsr"] = float(p1.dsr({"sr_m": sr, "months": len(d), "skew": float(d.skew()), "kurt": float(d.kurt() + 3)}, n))
        res["Q244" + r] = s
    for r, x in legs.items():
        f = fx.reindex(x.index); f0 = fx.shift(1).reindex(x.index)
        g = (1 + x["net"]) * f0 / f - 1
        res.setdefault("legs", {})[r] = {
            "cagr_usd": float((1 + x["net"]).prod() ** (12 / len(x)) - 1),
            "vs_ew_ann_pct": float((x["net"] - x["ew"]).mean() * 1200),
            "vs_vwrp_gbp_ann_pct": float((g - vw.reindex(x.index)).mean() * 1200),
            "trades_per_yr": float(x["trades"].iloc[1:].sum() / (len(x) / 12)), "avg_cash_slots": float(x["cash_slots"].mean())}
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
