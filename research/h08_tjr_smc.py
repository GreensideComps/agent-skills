"""P9 (E014): TJR / ICT "smart money" intraday model - liquidity sweep, break of structure, FVG entry.

Pre-registration: research/AGENDA.md P9 (commit cdb86ff, before this script ran).
Signal on NQ=F 5-minute bars; executed on the real 3x Nasdaq fund LQQ3.L 5-minute closes (GBP),
cost per side 0.15% (stress 0.30%). Long only for the tradable result; both directions on NQ at 3x
as an informational upper bound (shorting is not allowed on this account).
Run: python3 h08_tjr_smc.py   (writes research/output/h08_*.csv, experiments/E014.json)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from h02_intraday_orb import bars

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
REG = HERE / "experiments"
TRIALS_BEFORE = 120
GRID = [(e, r) for e in ("next", "fvg50") for r in (1.5, 2.0, 3.0)]
TRIALS_THIS_RUN = len(GRID)
COST, COST_STRESS = 0.0015, 0.0030


def levels(ny: pd.DataFrame, day) -> list[float]:
    d = pd.Timestamp(day)
    prev = ny[(ny.index.date < day)]
    if prev.empty:
        return []
    prev_day = prev.index.date[-1]
    rth = prev[(prev.index.date == prev_day)].between_time("09:30", "15:55")
    asia = ny[(ny.index >= (d - pd.Timedelta(hours=4)).tz_localize(ny.index.tz)) & (ny.index < d.tz_localize(ny.index.tz))]
    lon = ny[(ny.index.date == day)].between_time("02:00", "04:55")
    out = []
    for x in (asia, lon, rth):
        if len(x) >= 6:
            out += [x.low.min(), x.high.max()]
    return out


def setups(ny: pd.DataFrame, direction: int):
    """Yield per day: dict(sweep_i, bos_i, stop, fvg_mid) on the day's NY bars (direction +1 long, -1 short)."""
    for day, d in ny.groupby(ny.index.date):
        lv = levels(ny, day)
        sess = d.between_time("09:30", "11:30")
        if len(sess) < 20 or not lv:
            continue
        win = sess.between_time("09:30", "10:55")
        hi, lo, cl = sess.high.values, sess.low.values, sess.close.values
        found = None
        for i in range(len(win)):
            if direction > 0:
                swept = any(lo[i] < L < max(hi[max(0, i - 6):i + 1]) for L in lv)
            else:
                swept = any(hi[i] > L > min(lo[max(0, i - 6):i + 1]) for L in lv)
            if not swept:
                continue
            ref = hi[max(0, i - 4):i + 1].max() if direction > 0 else lo[max(0, i - 4):i + 1].min()
            ext = lo[i] if direction > 0 else hi[i]
            for k in range(i + 1, min(i + 13, len(sess))):
                ext = min(ext, lo[k]) if direction > 0 else max(ext, hi[k])
                if (direction > 0 and cl[k] > ref) or (direction < 0 and cl[k] < ref):
                    mid = None
                    for m in range(k, i + 1, -1):  # last 3-bar gap in the BOS leg
                        if direction > 0 and hi[m - 2] < lo[m]:
                            mid = (hi[m - 2] + lo[m]) / 2
                            break
                        if direction < 0 and lo[m - 2] > hi[m]:
                            mid = (lo[m - 2] + hi[m]) / 2
                            break
                    found = {"day": day, "sess": sess, "bos": k, "stop": ext, "fvg_mid": mid}
                    break
            if found:
                break
        if found:
            yield found


def simulate(ny, lq, entry, R, direction, cost, venue):
    trades = []
    for s in setups(ny, direction):
        sess, k = s["sess"], s["bos"]
        hi, lo, cl = sess.high.values, sess.low.values, sess.close.values
        if entry == "next":
            e_i, e_px = k, cl[k]
        else:
            if s["fvg_mid"] is None:
                continue
            e_i = next((m for m in range(k + 1, len(sess)) if (lo[m] <= s["fvg_mid"] if direction > 0 else hi[m] >= s["fvg_mid"])), None)
            if e_i is None:
                continue
            e_px = s["fvg_mid"]
        risk = (e_px - s["stop"]) * direction
        if risk <= 0:
            continue
        tgt = e_px + direction * R * risk
        day_bars = ny[ny.index.date == s["day"]]
        after = day_bars[day_bars.index > sess.index[e_i]]
        lse_end = pd.Timestamp(f"{s['day']} 16:25", tz="Europe/London")
        after = after[after.index <= lse_end]
        x_t, why = (after.index[-1] if len(after) else sess.index[e_i]), "time"
        for t, b in after.iterrows():
            if (direction > 0 and b.low <= s["stop"]) or (direction < 0 and b.high >= s["stop"]):
                x_t, why = t, "stop"
                break
            if (direction > 0 and b.high >= tgt) or (direction < 0 and b.low <= tgt):
                x_t, why = t, "target"
                break
        t_in = sess.index[e_i]
        if venue == "LQQ3":
            a = lq.close.asof(t_in.tz_convert("UTC"))
            b = lq.close.asof(x_t.tz_convert("UTC"))
            if not (np.isfinite(a) and np.isfinite(b)) or t_in.tz_convert("Europe/London").time() < pd.Timestamp("08:15").time():
                continue
            ret = b / a - 1
        else:  # NQ at 3x, informational
            p_in = e_px
            p_out = {"stop": s["stop"], "target": tgt}.get(why, ny.close.asof(x_t))
            ret = 3 * direction * (p_out / p_in - 1)
        trades.append({"day": str(s["day"]), "direction": direction, "entry_ny": str(t_in), "exit_ny": str(x_t), "exit": why,
                       "R": R, "entry": entry, "gross": ret, "net": (1 - cost) * (1 + ret) * (1 - cost) - 1})
    return pd.DataFrame(trades)


def summarise(T: pd.DataFrame, days: list) -> dict:
    if T.empty:
        return {"trades": 0, "total_return": 0.0, "mean_net": None, "win_rate": None, "sharpe_daily": None}
    r = pd.Series(0.0, index=[str(d) for d in days])
    r.loc[T.day] = T.net.values
    return {"trades": len(T), "total_return": float((1 + r).prod() - 1), "mean_net": float(T.net.mean()),
            "win_rate": float((T.net > 0).mean()), "sharpe_daily": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0,
            "worst_trade": float(T.net.min()), "best_trade": float(T.net.max())}


def main():
    nq = bars("NQ=F")
    lq = bars("LQQ3.L")
    ny = nq.tz_convert("America/New_York")
    lq_days = sorted({d for d in lq.tz_convert("Europe/London").index.date})
    days = [d for d in sorted({d for d in ny.index.date}) if d in set(lq_days) and pd.Timestamp(d).weekday() < 5]
    half = len(days) // 2
    is_days, oos_days = days[:half], days[half:]
    rows, all_trades = [], []
    for entry, R in GRID:
        for cost, cl in ((COST, "base"), (COST_STRESS, "x2")):
            T = simulate(ny, lq, entry, R, +1, cost, "LQQ3")
            T = T[T.day.isin([str(d) for d in days])]
            if cl == "base":
                all_trades.append(T.assign(config=f"{entry} {R}R"))
            for per, dd in (("IS", is_days), ("OOS", oos_days), ("ALL", days)):
                sub = T[T.day.isin([str(d) for d in dd])]
                rows.append({"config": f"{entry} {R}R", "venue": "LQQ3 long-only", "cost": cl, "period": per,
                             "start": str(dd[0]), "end": str(dd[-1]), "days": len(dd), **summarise(sub, dd)})
        # informational: both directions on NQ at 3x, base cost
        T2 = pd.concat([simulate(ny, lq, entry, R, d, COST, "NQ") for d in (1, -1)])
        T2 = T2[T2.day.isin([str(d) for d in days])].sort_values("entry_ny").drop_duplicates("day")
        for per, dd in (("IS", is_days), ("OOS", oos_days), ("ALL", days)):
            sub = T2[T2.day.isin([str(d) for d in dd])]
            rows.append({"config": f"{entry} {R}R", "venue": "NQ 3x both directions (not tradable)", "cost": "base", "period": per,
                         "start": str(dd[0]), "end": str(dd[-1]), "days": len(dd), **summarise(sub, dd)})
    # benchmark: hold LQQ3 over the same days (close to close), and cash
    lqd = lq.tz_convert("Europe/London").close.groupby(lambda t: t.date()).last()
    for per, dd in (("IS", is_days), ("OOS", oos_days), ("ALL", days)):
        s = lqd[[d for d in lqd.index if dd[0] <= d <= dd[-1]]]
        rows.append({"config": "hold LQQ3", "venue": "LQQ3", "cost": "none", "period": per, "start": str(dd[0]), "end": str(dd[-1]),
                     "days": len(dd), "trades": 1, "total_return": float(s.iloc[-1] / s.iloc[0] - 1) if len(s) > 1 else None})
    S = pd.DataFrame(rows)
    S.to_csv(OUT / "h08_tjr_summary.csv", index=False)
    pd.concat(all_trades).to_csv(OUT / "h08_tjr_trades.csv", index=False)
    pd.set_option("display.width", 250)
    print(S.round(4).to_string(index=False))
    write_record()


def write_record():
    S = pd.read_csv(OUT / "h08_tjr_summary.csv")
    base = S[(S.venue == "LQQ3 long-only") & (S.cost == "base")]
    is_ = base[base.period == "IS"]
    pick = is_.loc[is_.sharpe_daily.fillna(-9).idxmax(), "config"]
    oos = base[(base.period == "OOS") & (base.config == pick)].iloc[0]
    oos2 = S[(S.venue == "LQQ3 long-only") & (S.cost == "x2") & (S.period == "OOS") & (S.config == pick)].iloc[0]
    hold = S[(S.config == "hold LQQ3") & (S.period == "OOS")].iloc[0]
    both = S[(S.venue.str.startswith("NQ")) & (S.period == "OOS") & (S.config == pick)].iloc[0]

    def rr(x, nd=4):
        return None if pd.isna(x) else round(float(x), nd)
    losing = not (oos.total_return > 0)
    decision = "REJECTED" if losing else "AWAITING_EVIDENCE"
    detail = (f"In-sample pick {pick}. Out-of-sample ({oos.start}..{oos.end}, {int(oos.days)} days): {int(oos.trades)} trades, "
              f"total {oos.total_return:+.1%} after 0.15%/side ({oos2.total_return:+.1%} at 0.30%/side), win rate "
              f"{(oos.win_rate if pd.notna(oos.win_rate) else 0):.0%}; holding LQQ3 {hold.total_return:+.1%}. ")
    detail += ("Loses money out-of-sample after costs: rejected." if losing else
               "Positive but on far too few trades to mean anything, and cannot meet the 20-year history test: paper-track only.")
    rec = {
        "id": "E014", "title": "TJR / ICT smart-money intraday model (sweep, break of structure, FVG)", "date": "2026-10-14",
        "agenda_item": "P9 (owner request)",
        "hypothesis": "Buying 3x Nasdaq after a New York-morning sweep of Asia/London/previous-day lows and a break of structure, "
                      "with the stop under the sweep and a fixed R target, makes money after costs.",
        "rationale": "Proponents: stop liquidity is swept before reversals. No audited or peer-reviewed evidence known.",
        "data": ["Yahoo NQ=F 5-minute bars (~60 days)", "Yahoo LQQ3.L 5-minute bars (~60 days)"],
        "methodology": "Rules frozen in AGENDA P9 before running (third-party TradingView definitions). Grid entry {next, fvg50} x "
                       "target {1.5R, 2R, 3R}; pick on first-half Sharpe, test on second half.",
        "benchmark": "Holding LQQ3 over the same days; cash",
        "costs": "0.15% per side on LQQ3 (stress 0.30%)",
        "in_sample": f"{is_.start.iloc[0]}..{is_.end.iloc[0]}", "out_of_sample": f"{oos.start}..{oos.end}",
        "results": [{"config": r.config, "venue": r.venue, "cost": r.cost, "period": r.period, "trades": int(r.trades) if pd.notna(r.trades) else 0,
                     "total_return": rr(r.total_return), "win_rate": rr(r.win_rate, 3), "sharpe_daily": rr(r.sharpe_daily, 2)}
                    for r in S.itertuples()],
        "robustness": ["cost x2", "all 6 grid configs reported", "both-direction NQ variant as an upper bound"],
        "limitations": ["Only ~60 days of 5-minute data: a few dozen trades at most, no statistical power",
                        "TJR's exact rules are not public; this is one mechanical reading of the published model",
                        "Fills at 5-minute closes of LQQ3; real stop fills can be worse",
                        "Long-only: half the model's trades (shorts) are not allowed on this account"],
        "trials": TRIALS_THIS_RUN, "decision": decision, "decision_detail": detail, "promoted": False,
        "evidence": ["research/h08_tjr_smc.py", "research/output/h08_tjr_summary.csv", "research/output/h08_tjr_trades.csv"],
    }
    rec["informational_both_directions_oos"] = {"config": pick, "trades": int(both.trades), "total_return": rr(both.total_return)}
    REG.joinpath("E014.json").write_text(json.dumps(rec, indent=1) + "\n")
    print("E014:", decision, "-", detail)


if __name__ == "__main__":
    main()
