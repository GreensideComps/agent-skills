"""H05 (E011): day-trading gold on the LSE, flat every night.

Data: Yahoo hourly bars for SGLN.L (iShares Physical Gold, GBX), about 3 years. Bars are
labelled by their start time, London session 08:00-16:30. A trade's return is measured from
the close of its entry bar to the close of its exit bar. Every rule exits by the close of the
15:00 bar (16:00 London) at the latest: never held overnight.

Rules (fixed before running; "short" means buying the 3x/1x short ETP, never short selling):
  R0 long_every_day   : buy at the 08:00 bar close, sell 16:00.
  R1 london_breakout  : range = 08:00 bar high/low. First later hourly close above -> long,
                        below -> short. Stop when a close goes back beyond the other side.
  R2 follow_yesterday : at the 08:00 bar close, go long if yesterday closed up, else short.
  R3 fade_first_hour  : at the 08:00 bar close, go the opposite way to the 08:00 bar's move.
Instruments: 1x (SGLN / 1x short) at 0.03% (tight) and 0.10% per side, and 3x (3LGO / 3SGO) modelled as 3x the
SGLN intraday move at 0.20% per side (the 3x ETPs have only ~3 months of hourly history).
Run: python3 h05_gold_daytrade.py   (writes research/output/h05_*.csv)
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


def hourly(sym: str) -> pd.DataFrame:
    path = CACHE / f"{sym}_1h.csv"
    if not path.exists():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1h&range=730d"
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            res = json.loads(r.read())["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close")},
                          index=pd.to_datetime(res["timestamp"], unit="s", utc=True)).dropna()
        CACHE.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/London")
    return df


def trades_for(day: pd.DataFrame, prev_close: float | None, rule: str) -> tuple[int, float, float] | None:
    """Return (direction, entry_price, exit_price) for one day, or None for no trade."""
    d = day.between_time("08:00", "15:00")
    if len(d) < 6 or d.index[0].hour != 8:
        return None
    first = d.iloc[0]
    last = d.iloc[-1]
    if rule == "long_every_day":
        return 1, first.close, last.close
    if rule == "follow_yesterday":
        if prev_close is None:
            return None
        return (1 if first.open > prev_close else -1), first.close, last.close
    if rule == "fade_first_hour":
        return (-1 if first.close > first.open else 1), first.close, last.close
    if rule == "london_breakout":
        hi, lo = first.high, first.low
        rest = d.iloc[1:]
        for i, (t, b) in enumerate(rest.iterrows()):
            side = 1 if b.close > hi else -1 if b.close < lo else 0
            if side:
                after = rest.iloc[i + 1:]
                for _, a in after.iterrows():
                    if (side == 1 and a.close < lo) or (side == -1 and a.close > hi):
                        return side, b.close, a.close
                return side, b.close, (after.iloc[-1].close if len(after) else b.close)
        return None
    raise ValueError(rule)


def main():
    px = hourly("SGLN.L")
    px = px[(px.close > 0)]
    days = list(px.groupby(px.index.date))
    rows, summary = [], []
    for rule in ("long_every_day", "london_breakout", "follow_yesterday", "fade_first_hour"):
        prev_close = None
        for day, d in days:
            t = trades_for(d, prev_close, rule)
            prev_close = float(d.close.iloc[-1])
            if t is None:
                continue
            side, e, x = t
            move = x / e - 1
            if abs(move) > 0.15:  # Yahoo LSE glitch
                continue
            rows.append({"rule": rule, "date": str(day), "side": side, "move": move})
    T = pd.DataFrame(rows)
    for (rule, lev, cost) in ([(r, 1, 0.0003) for r in T.rule.unique()] + [(r, 1, 0.0010) for r in T.rule.unique()]
                              + [(r, 3, 0.0020) for r in T.rule.unique()]):
        t = T[T.rule == rule]
        net = (1 + lev * t.side * t.move) * (1 - cost) / (1 + cost) - 1
        eq = (1 + net).cumprod()
        yrs = (pd.Timestamp(t.date.iloc[-1]) - pd.Timestamp(t.date.iloc[0])).days / 365.25
        gross = (1 + lev * t.side * t.move).prod() - 1
        summary.append({"rule": rule, "leverage": lev, "cost_per_side": cost, "trades": len(t), "win_rate": (net > 0).mean(),
                        "avg_trade": net.mean(), "total_return": eq.iloc[-1] - 1, "CAGR": eq.iloc[-1] ** (1 / yrs) - 1,
                        "maxDD": (eq / eq.cummax() - 1).min(), "gross_total_no_costs": gross,
                        "start": t.date.iloc[0], "end": t.date.iloc[-1]})
    S = pd.DataFrame(summary)
    hold = px.close.iloc[-1] / px.close.iloc[0] - 1
    S["gold_buy_and_hold_total"] = hold
    S.to_csv(OUT / "h05_gold_daytrade.csv", index=False)
    T.to_csv(OUT / "h05_gold_daytrade_trades.csv", index=False)
    pd.set_option("display.width", 250)
    print(S.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
