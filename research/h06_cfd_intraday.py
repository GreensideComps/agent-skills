"""H06 (E012): would gold / Nasdaq day trading work on a CFD account (24-hour trading, tight spreads)?

Data: Yahoo hourly bars for gold futures (GC=F) and Nasdaq-100 futures (NQ=F), about 2.4 years.
Bars are labelled by start time, converted to London time. A "day" runs 23:00 -> 22:00 London
(the CME session). Trade returns run from the close of the entry bar to the close of the exit bar.

Rules (fixed before running), unleveraged; leverage multiplies both gains and losses:
  always_long_session : long from the 23:00 bar to the 21:00 bar every day (a CFD proxy for holding)
  asia_long           : long 23:00 -> 07:00 London only (the "overnight" window)
  london_long         : long 08:00 -> 16:00 London only
  us_long             : long 14:00 -> 21:00 London only
  london_breakout     : range = 07:00 bar; first close beyond it -> long/short; stop on a close back
                        beyond the other side; out by the 16:00 bar
  us_breakout         : same on the 14:00 bar range, out by the 20:00 bar
  follow_yesterday    : at the 08:00 bar close, trade in the direction of yesterday's session; out at 21:00
Costs (typical UK CFD retail): spread 0.02% per side for both markets. Overnight financing
((4.0% + 2.5%)/365) is charged only on positions open at 22:00 London; no rule here is.
Run: python3 h06_cfd_intraday.py   (writes research/output/h06_cfd_intraday.csv)
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
CACHE = HERE / "data" / "intraday"
UA = {"User-Agent": "Mozilla/5.0 (research script)"}
SPREAD = 0.0002
FINANCING_PER_NIGHT = (0.040 + 0.025) / 365


def hourly(sym: str) -> pd.DataFrame:
    path = CACHE / f"{sym.replace('=', '_')}_1h.csv"
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
    return df[df.close > 0]


def session_key(ts: pd.Timestamp):
    # bars from 23:00 belong to the next calendar day's session
    return (ts + pd.Timedelta(hours=1)).date()


def bar(d: pd.DataFrame, hour: int):
    x = d[d.index.hour == hour]
    return x.iloc[0] if len(x) else None


def window(d, h0, h1):
    """Bars from hour h0 to h1 inclusive, in session order (h0 may be 23 = previous evening)."""
    hrs = [(h0 + i) % 24 for i in range(((h1 - h0) % 24) + 1)]
    return d[d.index.hour.isin(hrs)]


def run_rule(px: pd.DataFrame, rule: str):
    out, prev_dir = [], None
    for key, d in px.groupby(px.index.map(session_key)):
        d = d.sort_index()
        res = None
        if rule in ("always_long_session", "asia_long", "london_long", "us_long", "follow_yesterday"):
            h0, h1 = {"always_long_session": (23, 21), "asia_long": (23, 7), "london_long": (8, 16), "us_long": (14, 21),
                      "follow_yesterday": (8, 21)}[rule]
            e, x = bar(d, h0), bar(d, h1)
            if e is not None and x is not None:
                side = 1
                if rule == "follow_yesterday":
                    side = prev_dir if prev_dir is not None else 0
                if side:
                    res = (side, e.close, x.close, False)  # entry at the 23:00 bar close (00:00) and exit by 22:00: never open at 22:00
        else:
            h_rng, h_end = (7, 16) if rule == "london_breakout" else (14, 20)
            rb = bar(d, h_rng)
            rest = window(d, (h_rng + 1) % 24, h_end) if rb is not None else d.iloc[0:0]
            if rb is not None and len(rest):
                for i, (t, b) in enumerate(rest.iterrows()):
                    side = 1 if b.close > rb.high else -1 if b.close < rb.low else 0
                    if side:
                        after = rest.iloc[i + 1:]
                        exit_px = after.iloc[-1].close if len(after) else b.close
                        for _, a in after.iterrows():
                            if (side == 1 and a.close < rb.low) or (side == -1 and a.close > rb.high):
                                exit_px = a.close
                                break
                        res = (side, b.close, exit_px, False)
                        break
        s0, s1 = bar(d, 23), bar(d, 21)
        if s0 is not None and s1 is not None:
            prev_dir = 1 if s1.close > s0.close else -1
        if res:
            side, e, x, overnight = res
            move = x / e - 1
            if abs(move) < 0.2:
                net = (1 + side * move) * (1 - SPREAD) / (1 + SPREAD) - 1 - (FINANCING_PER_NIGHT if overnight else 0)
                out.append({"session": str(key), "side": side, "gross": side * move, "net": net})
    return pd.DataFrame(out)


def main():
    rows = []
    for name, sym in (("gold", "GC=F"), ("nasdaq", "NQ=F")):
        px = hourly(sym)
        hold = px.close.iloc[-1] / px.close.iloc[0] - 1
        for rule in ("always_long_session", "asia_long", "london_long", "us_long", "london_breakout", "us_breakout", "follow_yesterday"):
            t = run_rule(px, rule)
            eq = (1 + t.net).cumprod()
            yrs = (pd.Timestamp(t.session.iloc[-1]) - pd.Timestamp(t.session.iloc[0])).days / 365.25
            rows.append({"market": name, "rule": rule, "trades": len(t), "win_rate": (t.net > 0).mean(), "avg_trade": t.net.mean(),
                         "total_return": eq.iloc[-1] - 1, "CAGR": eq.iloc[-1] ** (1 / yrs) - 1, "maxDD": (eq / eq.cummax() - 1).min(),
                         "gross_total": (1 + t.gross).prod() - 1, "buy_and_hold": hold,
                         "start": t.session.iloc[0], "end": t.session.iloc[-1]})
    S = pd.DataFrame(rows)
    S.to_csv(OUT / "h06_cfd_intraday.csv", index=False)
    pd.set_option("display.width", 250)
    print(S.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
