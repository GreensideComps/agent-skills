"""Regime-conditioned track (decision C7): failed Stage 2 signals and seasonal effects, switched by regime.

Frozen by `research/prereg/regime.md` (and its addendum 1), committed before any result was computed. Any later
regime, signal or threshold is a new trial and raises N.

Exploration only: decisions 2015-01 to 2022-11, daily data 2015-01-02 to 2022-12-30. Every input is cut at
2022-12-31 before anything is computed; the 2023-2026 holdout is not read.

    RESEARCH_DATA=/path python3 regime.py [out.md]
"""
from __future__ import annotations

import io
import json
import math
import sys
import zipfile
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

import data_sources
import stage2
import xsection

CUT = pd.Timestamp("2022-12-31")
DAILY_START = "2015-01-01"
N_PRIOR = 102
N_TOTAL = 196
COST = xsection.COST_PER_TURNOVER
THIRDS = [("2015-01-01", "2017-12-31"), ("2018-01-01", "2020-12-31"), ("2021-01-01", "2022-12-31")]
REGIMES = {"R1": "trend: index above its 10-month average", "R2": "volatility: last month's vol below its 60-month median",
           "R3": "calendar: return month in Nov-Apr"}
SEASONAL = {"B1": "Nov-Apr only (sell in May)", "B2": "Turn of month (last day to day +3)",
            "B3": "Pre-holiday day", "B4": "January large-cap reversal (prior-year losers)"}
_N = NormalDist()


def french_daily(name: str = "F-F_Research_Data_Factors_daily") -> pd.DataFrame:
    """Daily table from a Ken French CSV zip, in decimal returns, cut at CUT."""
    path = xsection.DATA / "french" / f"{name}.csv"
    if not path.exists():
        raw = data_sources._get(f"https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{name}_CSV.zip")
        z = zipfile.ZipFile(io.BytesIO(raw))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(z.read(z.namelist()[0]).decode("latin-1"))
    lines = path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.lower().replace(" ", "").startswith(",mkt"))
    cols = [c.strip() for c in lines[start].split(",")][1:]
    rows = []
    for l in lines[start + 1:]:
        parts = [p.strip() for p in l.split(",")]
        if len(parts[0]) != 8 or not parts[0].isdigit():
            break
        rows.append(parts)
    df = pd.DataFrame([r[1:] for r in rows], index=pd.to_datetime([r[0] for r in rows], format="%Y%m%d"),
                      columns=cols).astype(float) / 100
    return df[df.index <= CUT]


def regimes(daily: pd.DataFrame) -> pd.DataFrame:
    """ON flags per decision month-end t, using data up to month-end t-1 only (R3: the calendar)."""
    mkt = daily["Mkt-RF"] + daily["RF"]
    level = (1 + mkt).cumprod()
    m_level = level.resample("ME").last()
    m_vol = mkt.resample("ME").std(ddof=1) * math.sqrt(252)
    out = pd.DataFrame(index=m_level.index)
    prev_level = m_level.shift(1)
    out["R1"] = (prev_level > m_level.shift(1).rolling(10, min_periods=10).mean()).astype(float)
    prev_vol = m_vol.shift(1)
    out["R2"] = (prev_vol < m_vol.shift(1).rolling(60, min_periods=60).median()).astype(float)
    ret_month = (out.index + pd.offsets.MonthEnd(1)).month
    out["R3"] = np.isin(ret_month, [11, 12, 1, 2, 3, 4]).astype(float)
    known = prev_level.notna() & m_level.shift(1).rolling(10, min_periods=10).mean().notna()
    out.loc[~known, "R1"] = np.nan
    out.loc[m_vol.shift(1).rolling(60, min_periods=60).median().isna(), "R2"] = np.nan
    return out


def conditional(series: pd.DataFrame, on: pd.Series) -> pd.Series:
    """Monthly A-series: top quintile minus universe in ON months, net of 2x Stage 2 costs, 0 in OFF months.

    `series` is a Stage 2 large-cap series (month, q5_minus_univ, q5_turnover); `on` is indexed by decision month.
    Turnover is 1.0 on entry after an OFF month, plus an exit turnover of 1.0 in the last ON month before OFF.
    """
    s = series.set_index("month").sort_index()
    flag = on.reindex(s.index).astype("boolean").fillna(False).astype(bool)
    prev_on = flag.shift(1, fill_value=False)
    next_on = flag.shift(-1, fill_value=True)  # the last month of the sample is not an exit
    turn = s["q5_turnover"].where(prev_on, 1.0)
    turn = turn + np.where(flag & ~next_on, 1.0, 0.0)
    net = s["q5_minus_univ"] - 2 * 2 * COST * turn
    return net.where(flag, 0.0)


def daily_switch(daily: pd.DataFrame, on: pd.Series) -> pd.Series:
    """Daily strategy (market when ON, RF otherwise) minus the market, net of 2x costs per one-way switch,
    summed to calendar months."""
    mkt = daily["Mkt-RF"] + daily["RF"]
    flag = on.reindex(daily.index).fillna(False).astype(bool)
    strat = np.where(flag, mkt, daily["RF"])
    switches = (flag != flag.shift(1, fill_value=flag.iloc[0])).astype(float)
    x = pd.Series(strat - mkt.to_numpy() - 2 * COST * switches.to_numpy(), index=daily.index)
    return x.resample("ME").sum()


def b_flags(cal: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """B1-B3 ON days on the trading calendar `cal`."""
    cal = pd.DatetimeIndex(sorted(cal))
    s = pd.Series(cal, index=cal)
    b1 = pd.Series(np.isin(cal.month, [11, 12, 1, 2, 3, 4]), index=cal)
    ym = cal.to_period("M")
    pos_in_month = s.groupby(ym).cumcount().to_numpy()
    is_last = np.r_[ym[1:] != ym[:-1], True]
    b2 = pd.Series((pos_in_month <= 2) | is_last, index=cal)
    b2.iloc[:2] = False  # the first days have no observed month-end before them
    nxt = cal[1:].append(pd.DatetimeIndex([cal[-1] + pd.Timedelta(days=1)]))
    gap_days = (nxt - cal).days
    b3 = []
    for d, g in zip(cal, gap_days):
        skipped = [d + pd.Timedelta(days=k) for k in range(1, g)]
        b3.append(any(x.weekday() < 5 for x in skipped))
    b3 = pd.Series(b3, index=cal)
    b3.iloc[-1] = False
    return {"B1": b1, "B2": b2, "B3": b3}


def january_reversal(df: pd.DataFrame) -> tuple[pd.Series, int]:
    """B4: bottom decile of large caps by 12-month return at each December month-end, held in January, minus
    the large-cap universe, net of 2x costs (full entry and exit). Returns the monthly series and event count."""
    d = xsection.investable(df[(df["month"] >= stage2.START) & (df["month"] <= stage2.END) & (df["band"] == "large")])
    out, events = {}, 0
    for mo, g in d.groupby("month"):
        if mo.month != 12:
            continue
        g = g.dropna(subset=["s6a_mom_12_1", "ret_next"])
        if len(g) < 30:
            continue
        q = pd.qcut(g["s6a_mom_12_1"].rank(method="first"), 10, labels=False)
        losers = g[q == 0]
        events += len(losers)
        out[mo] = losers["ret_next"].mean() - g["ret_next"].mean() - 2 * 2 * COST * 1.0
    return pd.Series(out, dtype=float), events


def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    order = sorted(pvals, key=pvals.get)
    m, ok, still = len(order), {}, True
    for i, k in enumerate(order):
        still = still and pvals[k] <= alpha / (m - i)
        ok[k] = still
    return ok


def dsr(sr: float, n_obs: int, skew: float, kurt: float, var_srs: float, n_trials: int = N_TOTAL) -> float:
    g = 0.5772156649
    sr0 = math.sqrt(var_srs) * ((1 - g) * _N.inv_cdf(1 - 1 / n_trials) + g * _N.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return float(_N.cdf((sr - sr0) * math.sqrt(n_obs - 1) / den))


def score(x: pd.Series, factors: pd.DataFrame) -> dict:
    """Monthly series stats. Index = return month-end."""
    x = x.dropna()
    t = xsection.newey_west_t(x)
    st = stage2.sharpe_stats(x)
    thirds = [bool(x.loc[a:b].mean() > 0) if len(x.loc[a:b]) else False for a, b in THIRDS]
    return {"months": len(x), "ann": float(x.mean() * 12), "t": t, "sr": st, "thirds": thirds,
            "alpha": stage2.factor_alpha(x, factors)}


def evaluate_all(series: dict[str, tuple[pd.Series, int, int]], factors: pd.DataFrame) -> dict:
    """series: id -> (monthly series, on_count, min_on). Applies the five pass rules."""
    res = {k: {**score(s, factors), "on": on, "min_on": mn} for k, (s, on, mn) in series.items()}
    p = {k: 1 - _N.cdf(r["t"]) if r["t"] is not None else 1.0 for k, r in res.items()}
    hk = holm(p)
    srs = [r["sr"]["sr"] for r in res.values()]
    var = float(np.var(srs, ddof=1))
    for k, r in res.items():
        st = r["sr"]
        r["p_one_sided"], r["holm"] = p[k], hk[k]
        r["dsr"] = dsr(st["sr"], st["n"], st["skew"], st["kurt"], var) if st["n"] > 2 else 0.0
        a = (r["alpha"] or {}).get("alpha_ann")
        checks = {"t_ge_3_holm": (r["t"] or 0) >= 3 and hk[k], "dsr_ge_0.9": r["dsr"] >= 0.9,
                  "thirds_2_of_3": sum(r["thirds"]) >= 2, "alpha_pos": a is not None and a > 0}
        r["checks"] = checks
        if r["on"] < r["min_on"]:
            r["verdict"] = "inconclusive"
        elif all(checks.values()):
            r["verdict"] = "pass"
        else:
            r["verdict"] = "fail"
    return res


def main(out: Path) -> None:
    df = xsection.load()
    assert df["month"].max() >= pd.Timestamp(stage2.HOLDOUT_START)
    df = df[df["month"] <= stage2.END].copy()  # holdout cut before anything is computed
    months = sorted(df.loc[df["month"] >= stage2.START, "month"].unique())
    df = stage2.build_features(df, months)
    f5 = data_sources.french("F-F_Research_Data_5_Factors_2x3")
    mom = data_sources.french("F-F_Momentum_Factor")
    factors = pd.concat([f5.drop(columns=["RF"]), mom], axis=1, sort=True)
    factors.columns = [c.strip() for c in factors.columns]
    factors = factors[factors.index <= CUT]
    daily = french_daily()
    reg = regimes(daily)

    series, info = {}, {}
    for tid, (_, desc, fn) in stage2.TRIALS.items():
        ev = xsection.evaluate(df, fn, tid, start=stage2.START, end=stage2.END, bands=("large",))
        s = ev["series"].get("large")
        if s is None:
            continue
        for r in REGIMES:
            for state, want in (("on", True), ("off", False)):
                on = (reg[r] == float(want)) & reg[r].notna()
                x = conditional(s, on)
                x.index = pd.DatetimeIndex(x.index) + pd.offsets.MonthEnd(1)
                n_on = int(on.reindex(s["month"]).fillna(False).astype(bool).sum())
                k = f"A-{tid}-{r}-{state}"
                series[k] = (x, n_on, 30)
                dd = s.set_index("month")["d10_d1"].where(on.reindex(s["month"]).fillna(False).astype(bool).to_numpy())
                info[k] = {"desc": f"{desc} | {REGIMES[r]} = {state.upper()}", "d10_d1_on_ann": float(dd.mean() * 12)}

    dd = daily[daily.index >= DAILY_START]
    for b, flag in b_flags(dd.index).items():
        series[b] = (daily_switch(dd, flag), int(flag.sum()), 200)
        info[b] = {"desc": SEASONAL[b]}
    b4, n4 = january_reversal(df)
    b4.index = pd.DatetimeIndex(b4.index) + pd.offsets.MonthEnd(1)
    full = pd.Series(0.0, index=pd.date_range("2015-02-28", "2022-12-31", freq="ME"))
    full.loc[b4.index] = b4
    series["B4"] = (full, n4, 200)
    info["B4"] = {"desc": SEASONAL["B4"]}

    assert len(series) == 94, len(series)
    res = evaluate_all(series, factors)
    for k in res:
        res[k].update(info[k])
    report(res, reg, out)
    out.with_suffix(".json").write_text(json.dumps(res, indent=1, default=str))


def report(res: dict, reg: pd.DataFrame, out: Path) -> None:
    passes = [k for k, r in res.items() if r["verdict"] == "pass"]
    inc = [k for k, r in res.items() if r["verdict"] == "inconclusive"]
    r_in = reg.loc[stage2.START:stage2.END]
    L = ["# Regime-conditioned track (C7): results", "",
         "Pre-registration: `research/prereg/regime.md` (with addendum 1), committed before this run. Exploration "
         "data only (decisions 2015-01 to 2022-11; daily data to 2022-12-30). The 2023-2026 holdout was not read.",
         f"Trials in this batch: {len(res)}. Trial total used for deflation: N = {N_TOTAL} ({N_PRIOR} earlier + 94).",
         "", f"**Passes: {len(passes)}** ({', '.join(passes) or 'none'}). Inconclusive: {len(inc)}"
         f"{' (' + ', '.join(inc) + ')' if inc else ''}. Everything else failed.", "",
         "> Survivor bias from Stage 2 applies to the A trials (free prices exclude companies that later "
         "disappeared).", "",
         "Regime ON months in the exploration window: " +
         ", ".join(f"{k} {int(r_in[k].fillna(False).astype(bool).sum())} of {len(r_in)}" for k in REGIMES) + ".", "",
         "| Trial | Description | ON | Net a yr | NW t | Holm | DSR | Thirds | FF5+UMD alpha | Verdict |",
         "|---|---|---:|---:|---:|---|---:|---|---:|---|"]
    order = sorted(res, key=lambda k: -(res[k]["t"] or -99))
    for k in order:
        r = res[k]
        a = (r["alpha"] or {}).get("alpha_ann")
        L.append(f"| {k} | {r['desc']} | {r['on']} | {r['ann']:+.2%} | {r['t'] if r['t'] is None else round(r['t'], 2)} | "
                 f"{'yes' if r['holm'] else 'no'} | {r['dsr']:.2f} | {''.join('+' if x else '-' for x in r['thirds'])} | "
                 f"{'' if a is None else f'{a:+.2%}'} | **{r['verdict']}** |")
    L += ["", "## Pass rules (frozen)", "",
          "All required: NW t >= 3 and Holm-significant across the 94 (one-sided, alpha 0.05); deflated Sharpe >= 0.9 "
          "with N = 196; positive in 2 of 3 sub-periods (2015-17, 2018-20, 2021-22); FF5+UMD alpha > 0. Fewer than "
          "30 ON months (A) or 200 events (B) = inconclusive. A trials: top quintile minus universe in ON months, net "
          "of twice the Stage 2 costs, 0 otherwise. B1-B3: market on ON days, cash otherwise, minus the market.", "",
          "A pass earns forward-only paper tracking (6 months or 30 trades) before any weight in the satellite.", ""]
    out.write_text("\n".join(L))
    print("\n".join(L[:12]))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("regime.md"))
