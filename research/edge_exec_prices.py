"""Execution prices for the edge-discovery backtester (Phase B step B1; docs/edge/PHASE_B_PLAN.md §2.1, §4).

The default execution convention trades a month-end decision at the close of the first trading day after it
(`edge_rules.execution_time`, "next_day_close"). The research dataset has month-end closes only, so this module
builds, for every priced US company and every decision month from 2009-12 to 2022-11:

* `me_date`, `me_adjclose`: the company's last daily close on or before the month-end (the decision close);
* `exec_date`, `exec_adjclose`, `exec_close`: the close on the first US trading day after the month-end.

It also builds the benchmark and FX series the backtester needs (VWRP.L, VWRL.L in GBP; USD per GBP with FRED
first and Yahoo as the fallback, the source recorded per day).

**Strict cutoff.** Every request asks only for dates up to 2022-12-31 (Yahoo `period2`, FRED `coed`), and every
parsed series is checked again, so no 2023 value is downloaded, cached or written. The 2022-12 decision would
execute in January 2023, so it has no row (`edge_rules.exploration_execution` refuses it too).

**Prices are for returns only.** Yahoo adjusts the whole history for splits and dividends known today, so a
level fetched now is scaled by later corporate actions; ratios within 2009-2022 are not. Market caps and the $1
filter keep using the research dataset's point-in-time `close_raw`.

Columns starting with `exec_` are refused by `edge_rules.decision_frame`, so an execution price cannot leak into
a decision.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import edge_split

CUTOFF = edge_split.EXPLORATION_LAST_OUTCOME  # 2022-12-31
FIRST_DECISION = pd.Timestamp("2009-12-31")
LAST_DECISION = pd.Timestamp("2022-11-30")  # the 2022-12 decision executes in 2023
FETCH_START = pd.Timestamp("2009-11-01")
CALENDAR_SYMBOL = "SPY"  # NYSE trading days
BENCHMARKS = {"VWRP": "VWRP.L", "VWRL": "VWRL.L"}
FIELDS = ["cik", "ticker", "month", "me_date", "me_adjclose", "exec_date", "exec_adjclose", "exec_close", "status"]
STATUSES = ("ok", "stale_month_end", "missing_exec", "invalid_price", "no_month_end")
OUT_DIR = Path("/mnt/project-files/research-data/edge")


def _epoch(t: pd.Timestamp) -> int:
    return int(pd.Timestamp(t).tz_localize("UTC").timestamp())


def chart_url(symbol: str) -> str:
    """Yahoo daily chart request ending before 2023-01-01 00:00 UTC (no 2023 bar can be returned)."""
    end = _epoch(CUTOFF + pd.Timedelta(days=1))
    return (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={_epoch(FETCH_START)}"
            f"&period2={end}&interval=1d&events=div%7Csplit&includeAdjustedClose=true")


def fred_url(series: str) -> str:
    return (f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
            f"&cosd={FETCH_START.date()}&coed={CUTOFF.date()}")


def assert_cut(dates, what: str) -> None:
    """Raise HoldoutViolation if any date is after 2022-12-31."""
    d = pd.to_datetime(pd.Series(list(dates)))
    if len(d) and (d > CUTOFF).any():
        raise edge_split.HoldoutViolation(f"{what}: {int((d > CUTOFF).sum())} dates after {CUTOFF.date()}")


def parse_daily(body: bytes, symbol: str = "") -> pd.DataFrame:
    """Yahoo chart JSON -> DataFrame indexed by exchange-local date with close and adjclose; rows after the cutoff
    are dropped (a response should contain none) and the result is checked."""
    res = (json.loads(body).get("chart", {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise ValueError(f"{symbol}: no chart result")
    off = int(res.get("meta", {}).get("gmtoffset") or 0)
    idx = pd.to_datetime([t + off for t in res["timestamp"]], unit="s").normalize()
    q = res["indicators"]["quote"][0]["close"]
    a = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q
    df = pd.DataFrame({"close": pd.to_numeric(q, errors="coerce"), "adjclose": pd.to_numeric(a, errors="coerce")},
                      index=idx)
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"]).sort_index()
    df = df[df.index <= CUTOFF]
    df.attrs["currency"] = res.get("meta", {}).get("currency")
    assert_cut(df.index, symbol)
    return df


def decision_months() -> list[pd.Timestamp]:
    return list(pd.date_range(FIRST_DECISION, LAST_DECISION, freq="ME"))


def calendar_dates(calendar: pd.DatetimeIndex, month: pd.Timestamp) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """(last trading day on or before the month-end, first trading day after it) from the market calendar."""
    before = calendar[calendar <= month]
    after = calendar[calendar > month]
    return (before[-1] if len(before) else None), (after[0] if len(after) else None)


def company_rows(daily: pd.DataFrame, calendar: pd.DatetimeIndex, cik: int, ticker: str,
                 months: list[pd.Timestamp] | None = None) -> list[dict]:
    """One row per decision month for one company. Status:

    * ok: month-end close on the calendar's last trading day and a close on the first trading day after;
    * stale_month_end: the company's last close before the month-end is earlier than the calendar's;
    * missing_exec: no close on the first trading day after the month-end (no later day is substituted);
    * invalid_price: a close <= 0 at either point;
    * no_month_end: no close at or before the month-end in that month."""
    assert_cut(daily.index, ticker)
    rows = []
    for m in months or decision_months():
        if m > LAST_DECISION:
            raise edge_split.HoldoutViolation(f"decision {m.date()} would execute after {CUTOFF.date()}")
        cal_me, cal_ex = calendar_dates(calendar, m)
        if cal_ex is None or cal_ex > CUTOFF:
            raise edge_split.HoldoutViolation(f"no execution day by {CUTOFF.date()} for {m.date()}")
        seg = daily[(daily.index <= m) & (daily.index > m - pd.offsets.MonthBegin(1))]
        if seg.empty:
            continue  # not trading that month; the dataset's coverage check counts these
        me = seg.iloc[-1]
        row = {"cik": cik, "ticker": ticker, "month": m.date().isoformat(), "me_date": seg.index[-1].date().isoformat(),
               "me_adjclose": float(me["adjclose"]), "exec_date": cal_ex.date().isoformat(),
               "exec_adjclose": float("nan"), "exec_close": float("nan"), "status": "ok"}
        if cal_ex in daily.index:
            ex = daily.loc[cal_ex]
            row["exec_adjclose"], row["exec_close"] = float(ex["adjclose"]), float(ex["close"])
        if not me["adjclose"] > 0 or (cal_ex in daily.index and not row["exec_adjclose"] > 0):
            row["status"] = "invalid_price"
        elif cal_ex not in daily.index:
            row["status"] = "missing_exec"
        elif seg.index[-1] != cal_me:
            row["status"] = "stale_month_end"
        rows.append(row)
    return rows


# ---------- FX and benchmarks ----------

def parse_fred(body: bytes) -> pd.Series:
    s = pd.read_csv(io.BytesIO(body), index_col=0, parse_dates=True).iloc[:, 0]
    s = pd.to_numeric(s, errors="coerce").dropna()
    s = s[s.index <= CUTOFF]
    assert_cut(s.index, "FRED")
    return s


def gbpusd(get) -> pd.DataFrame:
    """USD per GBP, daily to 2022-12-31: FRED DEXUSUK where it has a value, Yahoo GBPUSD=X otherwise (FRED was
    unreachable from the research container on 2026-10-14). Column `source` records which, per day."""
    try:
        fred = parse_fred(get(fred_url("DEXUSUK")))
    except Exception:  # noqa: BLE001 - fall back, recorded in `source`
        fred = pd.Series(dtype=float)
    try:
        yh = parse_daily(get(chart_url("GBPUSD=X")), "GBPUSD=X")["close"]
    except Exception:  # noqa: BLE001
        yh = pd.Series(dtype=float)
    if fred.empty and yh.empty:
        raise RuntimeError("no GBPUSD source reachable (FRED DEXUSUK and Yahoo GBPUSD=X both failed)")
    idx = fred.index.union(yh.index)
    out = pd.DataFrame({"usd_per_gbp": fred.reindex(idx)}, index=idx)
    out["source"] = "FRED:DEXUSUK"
    fill = out["usd_per_gbp"].isna()
    out.loc[fill, "usd_per_gbp"] = yh.reindex(idx)[fill]
    out.loc[fill, "source"] = "Yahoo:GBPUSD=X"
    out = out.dropna(subset=["usd_per_gbp"])
    assert_cut(out.index, "GBPUSD")
    return out


def benchmarks(get) -> pd.DataFrame:
    """Daily adjusted closes in GBP for VWRP.L and VWRL.L to 2022-12-31 (Yahoo quotes some LSE lines in pence)."""
    cols = {}
    for name, sym in BENCHMARKS.items():
        d = parse_daily(get(chart_url(sym)), sym)
        scale = 0.01 if d.attrs.get("currency") in ("GBp", "GBX") else 1.0  # pence to pounds
        cols[name] = d["adjclose"] * scale
    out = pd.DataFrame(cols).sort_index()
    assert_cut(out.index, "benchmarks")
    return out


# ---------- integrity ----------

def _mi(months: pd.Series) -> pd.Series:
    """Month index (year * 12 + month), so consecutive months differ by 1."""
    d = pd.to_datetime(months)
    return d.dt.year * 12 + d.dt.month


def check(rows: pd.DataFrame, calendar: pd.DatetimeIndex, monthly: pd.DataFrame | None = None,
          fx: pd.DataFrame | None = None, bench: pd.DataFrame | None = None) -> list[dict]:
    """Integrity checks: FAIL means the file must not be used; WARN is a limitation to state."""
    out = []

    def r(name, ok, detail, warn=False):
        out.append({"check": name, "status": "PASS" if ok else ("WARN" if warn else "FAIL"), "detail": detail})

    dup = int(rows.duplicated(["cik", "month"]).sum())
    r("one row per company-month", dup == 0, f"{dup} duplicate (cik, month) rows")
    dates = pd.concat([pd.to_datetime(rows[c]) for c in ("month", "me_date", "exec_date")])
    late = int((dates > CUTOFF).sum())
    r("strict cutoff: no date after 2022-12-31", late == 0 and pd.to_datetime(rows["month"]).max() <= LAST_DECISION,
      f"{late} dates after the cutoff; last decision month {rows['month'].max()}")
    exp = {m.date().isoformat(): calendar_dates(calendar, m)[1].date().isoformat() for m in decision_months()}
    wrong = int((rows["exec_date"] != rows["month"].map(exp)).sum())
    after = int((pd.to_datetime(rows["exec_date"]) <= pd.to_datetime(rows["month"])).sum())
    r("execution date is the first US trading day after the month-end", wrong == 0 and after == 0,
      f"{wrong} rows differ from the calendar; {after} not after the decision")
    me_late = int((pd.to_datetime(rows["me_date"]) > pd.to_datetime(rows["month"])).sum())
    r("decision close is on or before the month-end", me_late == 0, f"{me_late} rows after")
    ok = rows["status"] == "ok"
    bad = int((ok & ~((rows["me_adjclose"] > 0) & (rows["exec_adjclose"] > 0))).sum())
    r("usable rows have positive prices", bad == 0, f"{bad} 'ok' rows with a missing or non-positive price")
    counts = rows["status"].value_counts().to_dict()
    r("row status", True, ", ".join(f"{k} {v:,}" for k, v in sorted(counts.items())), warn=True)
    out[-1]["status"] = "WARN" if counts.get("ok", 0) < len(rows) else "PASS"
    ov = (rows.loc[ok, "exec_adjclose"] / rows.loc[ok, "me_adjclose"] - 1).abs()
    r("overnight moves over 50% (decision close to execution close)", int((ov > 0.5).sum()) == 0,
      f"{int((ov > 0.5).sum())} of {int(ok.sum()):,}; median absolute move {ov.median():.3%}", warn=True)
    if monthly is not None:
        mm = monthly[(monthly["currency"] == "USD") & (pd.to_datetime(monthly["month"]) <= LAST_DECISION)
                     & (pd.to_datetime(monthly["month"]) >= FIRST_DECISION)]
        key = rows.loc[ok, ["cik", "month"]].astype({"cik": int}).assign(k=1)
        cov = mm[["cik", "month"]].astype({"cik": int}).merge(key, on=["cik", "month"], how="left")["k"].notna()
        r("coverage of the research dataset's USD company-months", cov.mean() > 0.95,
          f"{int(cov.sum()):,} of {len(cov):,} ({cov.mean():.1%}) have an 'ok' execution row", warn=True)
        a = rows[ok].assign(m=_mi(rows.loc[ok, "month"])).sort_values(["cik", "m"])
        a["r_daily"] = a.groupby("cik")["me_adjclose"].pct_change()
        a.loc[a.groupby("cik")["m"].diff() != 1, "r_daily"] = float("nan")
        b = mm.assign(m=_mi(mm["month"])).sort_values(["cik", "m"])
        b["r_monthly"] = b.groupby("cik")["adjclose"].pct_change()
        b.loc[b.groupby("cik")["m"].diff() != 1, "r_monthly"] = float("nan")
        j = a[["cik", "m", "r_daily"]].astype({"cik": int}).merge(b[["cik", "m", "r_monthly"]].astype({"cik": int}),
                                                                   on=["cik", "m"]).dropna()
        agree = ((j["r_daily"] - j["r_monthly"]).abs() <= 0.001).mean() if len(j) else float("nan")
        r("month-end returns agree with the research dataset (within 0.1 points)", agree >= 0.99,
          f"{agree:.2%} of {len(j):,} monthly returns agree", warn=True)
    if fx is not None:
        assert_cut(fx.index, "fx")
        src = fx["source"].value_counts().to_dict()
        r("FX: positive, cut at 2022-12, source recorded", bool((fx["usd_per_gbp"] > 0).all()),
          f"{len(fx):,} days to {fx.index.max().date()}; " + ", ".join(f"{k} {v:,}" for k, v in src.items()))
        miss = [m.date().isoformat() for m in decision_months() if fx.index[fx.index <= m].empty
                or (m - fx.index[fx.index <= m][-1]).days > 7]
        r("FX: a rate within 7 days of every decision month-end", not miss, f"{len(miss)} months without")
    if bench is not None:
        assert_cut(bench.index, "benchmarks")
        first = {c: str(bench[c].first_valid_index().date()) for c in bench}
        r("benchmarks: cut at 2022-12, positive", bool((bench.fillna(1) > 0).all().all()),
          f"to {bench.index.max().date()}; first values " + ", ".join(f"{k} {v}" for k, v in first.items()))
    return out


def report(checks: list[dict], manifest: dict) -> str:
    lines = ["# Execution-price dataset integrity (edge-discovery Phase B, step B1)", "",
             "First-trading-day closes for the next-day execution convention, decisions 2009-12 to 2022-11, cut "
             "at 2022-12-31 at the download itself. FAIL = do not use; WARN = a limitation to state.", "",
             "| Check | Status | Detail |", "|---|---|---|"]
    lines += [f"| {c['check']} | **{c['status']}** | {c['detail']} |" for c in checks]
    lines += ["", "## Files", "", "| File | Rows | SHA-256 |", "|---|---:|---|"]
    lines += [f"| {f} | {v['rows']:,} | `{v['sha256'][:16]}…` |" for f, v in manifest["files"].items()]
    lines += ["", f"Built {manifest['built_utc']} from Yahoo chart (daily) and FRED; {manifest['tickers_failed']} "
              f"of {manifest['tickers']} tickers returned no data.", "",
              "Prices are for returns only: Yahoo adjusts history for splits and dividends known today. Survivorship "
              "bias is unchanged by this file (`edge_rules.STANDING_LIMITATIONS`)."]
    return "\n".join(lines) + "\n"


# ---------- build ----------

def _get(url: str) -> bytes:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from data_sources import _get as get  # noqa: PLC0415 - same proxy-tolerant fetch as the rest of research/
    return get(url)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out_dir: Path = OUT_DIR, get=_get, workers: int = 4, limit: int | None = None, log=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import xsection  # noqa: PLC0415
    monthly = pd.read_csv(xsection.DATA / "prices_monthly.csv.gz", dtype={"cik": int})
    monthly = edge_split.cut_exploration(monthly)
    usd = monthly[(monthly["currency"] == "USD") & (pd.to_datetime(monthly["month"]) >= FIRST_DECISION)]
    tickers = usd.drop_duplicates("cik")[["cik", "ticker"]].values.tolist()[:limit]
    calendar = parse_daily(get(chart_url(CALENDAR_SYMBOL)), CALENDAR_SYMBOL).index
    rows, failed, lock = [], [], threading.Lock()

    def one(ct):
        cik, t = ct
        try:
            d = parse_daily(get(chart_url(t.replace(".", "-").replace("/", "-"))), t)
            rs = company_rows(d, calendar, int(cik), t)
        except edge_split.HoldoutViolation:
            raise
        except Exception:  # noqa: BLE001 - counted
            rs = None
        with lock:
            if rs is None:
                failed.append(t)
            else:
                rows.extend(rs)
        time.sleep(0.1)

    with ThreadPoolExecutor(workers) as ex:
        for i, _ in enumerate(ex.map(one, tickers)):
            if log and i % 250 == 0:
                log(f"{i}/{len(tickers)} rows {len(rows):,} failed {len(failed)}")
    df = pd.DataFrame(rows, columns=FIELDS).sort_values(["cik", "month"]).reset_index(drop=True)
    fx = gbpusd(get)
    bench = benchmarks(get)
    files = {"exec_prices_to_2022.csv.gz": df, "gbpusd_daily_to_2022.csv.gz": fx.rename_axis("date"),
             "benchmarks_daily_gbp_to_2022.csv.gz": bench.rename_axis("date")}
    man = {"built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cutoff": str(CUTOFF.date()),
           "decisions": [str(FIRST_DECISION.date()), str(LAST_DECISION.date())], "calendar": CALENDAR_SYMBOL,
           "tickers": len(tickers), "tickers_failed": len(failed), "failed_sample": failed[:20], "files": {}}
    for name, frame in files.items():
        p = out_dir / name
        with gzip.open(p, "wt", newline="") as f:
            frame.to_csv(f, index=name != "exec_prices_to_2022.csv.gz")
        man["files"][name] = {"rows": len(frame), "sha256": _sha(p)}
    checks = check(df, calendar, monthly, fx, bench)
    man["checks"] = {c["check"]: c["status"] for c in checks}
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1))
    rep = Path(__file__).resolve().parent.parent / "equity" / "reports" / "research" / "edge" / "exec_prices_integrity.md"
    rep.write_text(report(checks, man))
    (rep.with_suffix(".json")).write_text(json.dumps({"checks": checks, "manifest": man}, indent=1))
    log(rep.read_text())
    return man


def load(out_dir: Path = OUT_DIR) -> pd.DataFrame:
    """The execution-price file, checked against its manifest hash and the cutoff."""
    man = json.loads((out_dir / "manifest.json").read_text())
    p = out_dir / "exec_prices_to_2022.csv.gz"
    if _sha(p) != man["files"][p.name]["sha256"]:
        raise RuntimeError(f"{p} does not match its manifest")
    df = pd.read_csv(p, dtype={"cik": int})
    assert_cut(pd.concat([pd.to_datetime(df[c]) for c in ("month", "me_date", "exec_date")]), p.name)
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    m = build(Path(a.out), workers=a.workers, limit=a.limit)
    sys.exit(1 if "FAIL" in m["checks"].values() else 0)
