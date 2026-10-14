"""Reproducible data layer for the Trading 212 strategy research.

Every series is downloaded once and cached under research/data/ so later runs
are reproducible offline. Sources (all public, no credentials):

* Yahoo Finance chart API (query1.finance.yahoo.com/v8/finance/chart): daily
  close and dividend/split-adjusted close for funds, ETFs and FX pairs.
* Kenneth R. French Data Library (Dartmouth): monthly factor returns.
* FRED (St. Louis Fed): UK 3-month interbank rate and GBP/USD history.

Nothing here talks to Trading 212.
"""
from __future__ import annotations

import io
import json
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (research script)"}


def _get(url: str, retries: int = 4) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # network flakiness through the proxy
            last = e
            # FRED resets Python's connections through the proxy; curl over HTTP/1.1 works.
            r = subprocess.run(["curl", "-sSf", "--http1.1", "-m", "60", "-A", UA["User-Agent"], url],
                               capture_output=True)
            if r.returncode == 0 and r.stdout:
                return r.stdout
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def yahoo(symbol: str, refresh: bool = False) -> pd.DataFrame:
    """Daily 'close' and 'adjclose' (total-return proxy) for a Yahoo symbol."""
    path = DATA / "yahoo" / f"{symbol.replace('^', '_').replace('=', '_')}.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?period1=0&period2=9999999999&interval=1d&events=div%7Csplit&includeAdjustedClose=true"
    )
    js = json.loads(_get(url))
    res = js["chart"]["result"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s").normalize()
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose", q["close"])
    df = pd.DataFrame(
        {"open": q["open"], "close": q["close"], "adjclose": adj, "volume": q["volume"]},
        index=idx,
    )
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
    df.attrs["currency"] = res["meta"].get("currency")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    meta = DATA / "yahoo" / "_meta.json"
    m = json.loads(meta.read_text()) if meta.exists() else {}
    m[symbol] = {"currency": res["meta"].get("currency"), "fetched": pd.Timestamp.now().isoformat()}
    meta.write_text(json.dumps(m, indent=1))
    return df


def yahoo_currency(symbol: str) -> str:
    return json.loads((DATA / "yahoo" / "_meta.json").read_text())[symbol]["currency"]


def french(name: str) -> pd.DataFrame:
    """Monthly table (first block) from a Ken French CSV zip, in decimal returns."""
    path = DATA / "french" / f"{name}.csv"
    if not path.exists():
        raw = _get(
            f"https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{name}_CSV.zip"
        )
        z = zipfile.ZipFile(io.BytesIO(raw))
        txt = z.read(z.namelist()[0]).decode("latin-1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(txt)
    lines = path.read_text().splitlines()
    # first header line containing a comma followed by YYYYMM rows
    start = next(i for i, l in enumerate(lines) if l.strip().startswith(",") or l.lower().startswith(",mkt"))
    rows = []
    for l in lines[start + 1:]:
        parts = [p.strip() for p in l.split(",")]
        if len(parts[0]) != 6 or not parts[0].isdigit():
            break
        rows.append(parts)
    cols = [c.strip() for c in lines[start].split(",")][1:]
    df = pd.DataFrame([r[1:] for r in rows], index=[r[0] for r in rows], columns=cols).astype(float) / 100
    df.index = pd.to_datetime(df.index, format="%Y%m") + pd.offsets.MonthEnd(0)
    return df


def fred(series: str) -> pd.Series:
    path = DATA / "fred" / f"{series}.csv"
    if not path.exists():
        raw = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    return pd.to_numeric(s, errors="coerce").dropna()
