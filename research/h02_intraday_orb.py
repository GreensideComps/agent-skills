"""H02 (exploratory): US-open opening-range breakout traded with 3x Nasdaq-100 ETPs on the LSE.

Rule (fixed before running):
  * Signal on QQQ 5-minute bars (near real time). Opening range = high/low of the first
    OR_MIN minutes after the 09:30 New York open.
  * First 5-minute close above the range high -> buy LQQ3 (3x long, GBX).
    First close below the range low -> buy LQQS (3x short, GBX). One trade per day.
  * Stop: QQQ closes back beyond the opposite side of the range. Otherwise exit at the last
    bar before the LSE close (15:30 London). Never held overnight.
  * Fill at the ETP's 5-minute close of the signal/exit bar, paying COST per side (spread).
Grid: OR_MIN in {15, 30}; COST per side 0.15% (base) and 0.30% (stress).
Benchmark: holding LQQ3 over the same window; and doing nothing (cash).

Sample: the ~60 days of 5-minute history Yahoo serves (about 40 trading days). This is far too
short to prove anything; it only shows what the rule would have done recently.
Run: python3 h02_intraday_orb.py   (writes research/output/h02_*.csv)
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
CACHE = HERE / "data" / "intraday"
UA = {"User-Agent": "Mozilla/5.0 (research script)"}


def bars(sym: str) -> pd.DataFrame:
    path = CACHE / f"{sym.replace('=', '_')}_5m.csv"
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=5m&range=60d"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        res = json.loads(r.read())["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close", "volume")},
                      index=pd.to_datetime(res["timestamp"], unit="s", utc=True)).dropna(subset=["close"])
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    return df


def run(or_min: int, cost: float, qqq: pd.DataFrame, lng: pd.DataFrame, sht: pd.DataFrame) -> pd.DataFrame:
    trades = []
    ny = qqq.tz_convert("America/New_York")
    for day, d in ny.groupby(ny.index.date):
        d = d.between_time("09:30", "15:55")
        if len(d) < 20:
            continue
        rng = d[d.index < d.index[0] + pd.Timedelta(minutes=or_min)]
        if len(rng) < or_min // 5:
            continue
        hi, lo = rng.high.max(), rng.low.min()
        rest = d[d.index >= d.index[0] + pd.Timedelta(minutes=or_min)]
        lse_close = pd.Timestamp(f"{day} 15:25", tz="Europe/London")  # last 5m bar before LSE close
        rest = rest[rest.index.tz_convert("Europe/London") <= lse_close]
        if rest.empty:
            continue
        side, entry_t = None, None
        for t, b in rest.iterrows():
            if b.close > hi:
                side, entry_t = "long", t
                break
            if b.close < lo:
                side, entry_t = "short", t
                break
        if side is None:
            trades.append({"date": str(day), "side": "none", "ret": 0.0})
            continue
        etp = lng if side == "long" else sht
        after = rest[rest.index > entry_t]
        exit_t, why = (after.index[-1] if len(after) else entry_t), "close"
        for t, b in after.iterrows():
            if (side == "long" and b.close < lo) or (side == "short" and b.close > hi):
                exit_t, why = t, "stop"
                break
        e = etp.close.asof(entry_t.tz_convert("UTC"))
        x = etp.close.asof(exit_t.tz_convert("UTC"))
        stale = (entry_t.tz_convert("UTC") - etp.index[etp.index <= entry_t.tz_convert("UTC")][-1]) > pd.Timedelta(minutes=15)
        if pd.isna(e) or pd.isna(x) or stale:
            trades.append({"date": str(day), "side": "skip_nodata", "ret": 0.0})
            continue
        r = (x * (1 - cost)) / (e * (1 + cost)) - 1
        trades.append({"date": str(day), "side": side, "entry_utc": str(entry_t.tz_convert("UTC")),
                       "exit_utc": str(exit_t.tz_convert("UTC")), "exit": why, "etp_entry": e, "etp_exit": x, "ret": r})
    return pd.DataFrame(trades)


def main():
    qqq, lng, sht = bars("QQQ"), bars("LQQ3.L"), bars("LQQS.L")
    rows, all_trades = [], []
    for or_min in (15, 30):
        for cost in (0.0015, 0.0030):
            t = run(or_min, cost, qqq, lng, sht)
            t["or_min"], t["cost"] = or_min, cost
            all_trades.append(t)
            tr = t[t.side.isin(["long", "short"])]
            eq = (1 + t.ret).prod()
            rows.append({"or_min": or_min, "cost_per_side": cost, "days": len(t), "trades": len(tr),
                         "win_rate": (tr.ret > 0).mean(), "avg_trade": tr.ret.mean(), "best": tr.ret.max(),
                         "worst": tr.ret.min(), "total_return": eq - 1,
                         "max_drawdown": float(((1 + t.ret).cumprod() / (1 + t.ret).cumprod().cummax() - 1).min())})
    S = pd.DataFrame(rows)
    T = pd.concat(all_trades)
    first, last = T.date.min(), T.date.max()
    hold = lng.close[(lng.index.date >= pd.Timestamp(first).date()) & (lng.index.date <= pd.Timestamp(last).date())]
    S["benchmark_hold_LQQ3"] = hold.iloc[-1] / hold.iloc[0] - 1
    S["period"] = f"{first}..{last}"
    S.to_csv(OUT / "h02_orb_summary.csv", index=False)
    T.to_csv(OUT / "h02_orb_trades.csv", index=False)
    pd.set_option("display.width", 200)
    print(S.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
