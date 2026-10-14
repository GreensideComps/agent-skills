"""Monthly point-in-time company metrics from the SEC fact panel (STRATEGY_V2, Stage 1).

For every company and every month-end, the figures an investor could have known on that date:
trailing-twelve-month flows and the latest balance-sheet values, each from filings made on or before
the month-end. One row per company-month while the company is filing (a periodic filing within the
last 15 months). Companies that stopped filing simply stop appearing; they are not dropped from
earlier months, which is what removes survivorship bias from the fundamentals side.

Only US-dollar money values are used; a company reporting in another currency gets no money metrics
(recorded as such) rather than mixed currencies.
"""
from __future__ import annotations

import csv
import gzip
from datetime import date, timedelta
from itertools import groupby
from multiprocessing import Pool
from pathlib import Path

from . import panel
from .fundamentals import CONCEPTS

FLOW = [m for m, (k, u, _) in CONCEPTS.items() if k == "flow" and u == "money"] + ["eps_diluted"]
INSTANT = [m for m, (k, u, _) in CONCEPTS.items() if k == "instant"] + ["shares_out"]
UNIT = {m: ("USD/shares" if m in ("eps_diluted", "eps_basic") else "shares" if m in ("shares_out", "shares_diluted")
            else "USD") for m in FLOW + INSTANT + ["shares_diluted"]}
ACTIVE_MONTHS = 15
MAX_AGE_MONTHS = 18  # a figure for a period that ended longer ago than this is treated as unknown
FIELDS = (["cik", "month", "last_filed", "ttm_end"] + [f"ttm_{m}" for m in FLOW] + [m for m in INSTANT]
          + ["shares_diluted"])


def month_ends(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while True:
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        d = (nxt - timedelta(days=1)).isoformat()
        if d > end:
            return out
        out.append(d)
        y, m = nxt.year, nxt.month


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def company_months(cik: int, rows: list[dict], months: list[str]) -> list[dict]:
    """Rows for one company: metrics as known at each month-end while it is filing."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r["unit"] == UNIT.get(r["metric"]):
            by.setdefault(r["metric"], []).append(r)
    filings = sorted({r["filed"] for r in rows})
    if not filings:
        return []
    out, prev, fi = [], None, 0
    for mo in months:
        if mo < filings[0]:
            continue
        changed = False
        while fi < len(filings) and filings[fi] <= mo:
            fi, changed = fi + 1, True
        last = filings[fi - 1]
        if _months_between(last, mo) > ACTIVE_MONTHS:
            prev = None
            continue
        if changed or prev is None:
            rec = {"cik": cik, "last_filed": last}
            def fresh(x):
                return x if x and _months_between(x["end"], mo) <= MAX_AGE_MONTHS else None
            rev = fresh(panel.ttm(by.get("revenue", []), mo))
            rec["ttm_end"] = rev["end"] if rev else ""
            for m in FLOW:
                t = fresh(panel.ttm(by.get(m, []), mo))
                rec[f"ttm_{m}"] = t["val"] if t else ""
            for m in INSTANT + ["shares_diluted"]:
                if m == "shares_diluted":  # weighted-average count of the latest period, not summed
                    ks = [r for r in panel.known(by.get(m, []), mo) if r["start"]]
                    x = fresh(max(ks, key=lambda r: (r["end"], r["filed"])) if ks else None)
                else:
                    x = fresh(panel.latest(by.get(m, []), mo))
                v = x["val"] if x else ""
                rec[m] = v
            prev = rec
        out.append({**prev, "month": mo})
    return out


def _work(args):
    cik, rows, months = args
    return company_months(cik, rows, months)


def build(facts_path: Path, out_path: Path, start: str = "2009-12-31", end: str | None = None,
          processes: int = 4, log=print) -> dict:
    end = end or date.today().isoformat()
    months = month_ends(start, end)
    stats = {"companies": 0, "company_months": 0}

    def jobs():
        for cik, grp in groupby(panel.read(facts_path), key=lambda r: r["cik"]):
            yield cik, list(grp), months
    with gzip.open(out_path, "wt", newline="") as gz, Pool(processes) as pool:
        w = csv.DictWriter(gz, fieldnames=FIELDS)
        w.writeheader()
        for i, recs in enumerate(pool.imap(_work, jobs(), chunksize=16)):
            stats["companies"] += 1
            if recs:
                w.writerows(recs)
                stats["company_months"] += len(recs)
            if log and i % 2000 == 0:
                log(f"{i} companies, {stats['company_months']:,} company-months")
    return stats


PRICE_FIELDS = ["cik", "ticker", "month", "close_raw", "adjclose", "currency"]


def fetch_prices(companies_path: Path, out_path: Path, get=None, pause: float = 0.25, log=print,
                 since: str = "2009-12-31") -> dict:
    """Monthly closes for every company with a ticker in SEC's data (its first-listed ticker).

    `close_raw` is the close as it traded that month (split adjustment undone with later splits), for
    point-in-time market caps; `adjclose` includes dividends, for returns. Companies without a ticker,
    or whose ticker Yahoo no longer serves (most delisted names), get no prices: that gap is counted,
    not filled. Resumable: tickers already in `out_path` are skipped.
    """
    import time as _time  # noqa: PLC0415
    from .backtest import CHART, parse_monthly, raw_close  # noqa: PLC0415
    from .prices import _get  # noqa: PLC0415
    get = get or _get
    done = set()
    if out_path.exists():
        with gzip.open(out_path, "rt", newline="") as f:
            done = {r["ticker"] for r in csv.DictReader(f)}
    with gzip.open(companies_path, "rt", newline="") as f:
        comps = [r for r in csv.DictReader(f) if r["tickers"] and r["entity_type"] == "operating"]
    stats = {"with_ticker": len(comps), "fetched": 0, "failed": 0, "skipped": 0}
    new = not out_path.exists()
    end = int(_time.time())
    with gzip.open(out_path, "at", newline="") as gz:
        w = csv.DictWriter(gz, fieldnames=PRICE_FIELDS)
        if new:
            w.writeheader()
        for i, c in enumerate(comps):
            t = c["tickers"].split("|")[0]
            if t in done:
                stats["skipped"] += 1
                continue
            sym = t.replace(".", "-").replace("/", "-")
            try:
                s = parse_monthly(get(CHART.format(sym=sym, end=end)))
                rows = []
                for (y, m) in sorted(s["bars"]):
                    mo = month_ends(f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-31")
                    if not mo or mo[0] < since:
                        continue
                    rows.append({"cik": c["cik"], "ticker": t, "month": mo[0], "close_raw": raw_close(s, y, m),
                                 "adjclose": s["bars"][(y, m)][1], "currency": s["currency"]})
                w.writerows(rows)
                stats["fetched"] += 1
            except Exception:  # noqa: BLE001 - counted; delisted tickers are expected to fail
                stats["failed"] += 1
            if pause:
                _time.sleep(pause)
            if log and i % 250 == 0:
                log(f"{i}/{len(comps)} {stats}")
    return stats
