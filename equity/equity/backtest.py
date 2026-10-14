"""Point-in-time backtest of the screen score (M8, test 1). Pre-registered in research/screen_backtest_prereg.md.

Research only: nothing here writes to the screen, valuation or paper ledgers. Each decision
date sees only XBRL facts filed by then, and prices as they traded then.
"""
from __future__ import annotations

import copy
import json
import math
import random
import shutil
import statistics
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import screener
from .fundamentals import analyse
from .industry import classify, supported
from .prices import PriceError, _get, yahoo_symbol

YEARS = range(2012, 2026)
CHART = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1293840000&period2={end}"
         "&interval=1mo&events=div%2Csplits")


def pit_facts(facts: dict, cutoff: str) -> dict:
    """Copy of companyfacts keeping only values filed on or before `cutoff` (YYYY-MM-DD)."""
    out = {k: v for k, v in facts.items() if k != "facts"}
    out["facts"] = {}
    for tax, concepts in facts.get("facts", {}).items():
        for name, c in concepts.items():
            units = {u: [x for x in vals if x.get("filed", "9999") <= cutoff] for u, vals in c.get("units", {}).items()}
            units = {u: v for u, v in units.items() if v}
            if units:
                out["facts"].setdefault(tax, {})[name] = {**{k: v for k, v in c.items() if k != "units"},
                                                          "units": units}
    return out


def parse_monthly(body: bytes) -> dict:
    """{'bars': {(y, m): (close, adjclose)}, 'splits': [(date, ratio)], 'currency': str}"""
    res = (json.loads(body).get("chart", {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise PriceError("no chart result")
    q = res["indicators"]["quote"][0]["close"]
    a = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q
    bars = {}
    for t, c, ac in zip(res["timestamp"], q, a):
        if c is not None and ac is not None:
            d = datetime.fromtimestamp(t, timezone.utc).date()
            bars[(d.year, d.month)] = (float(c), float(ac))
    splits = sorted((datetime.fromtimestamp(s["date"], timezone.utc).date(), s["numerator"] / s["denominator"])
                    for s in (res.get("events", {}).get("splits") or {}).values() if s.get("denominator"))
    return {"bars": bars, "splits": splits, "currency": res["meta"].get("currency")}


def raw_close(series: dict, y: int, m: int) -> float | None:
    """Close as it traded at the end of (y, m): undo the split adjustment for later splits."""
    bar = series["bars"].get((y, m))
    if bar is None:
        return None
    end = date(y, m, 28)
    factor = math.prod(r for d, r in series["splits"] if d > end)
    return bar[0] * factor


def forward_return(series: dict, y: int, m: int = 4) -> float | None:
    a, b = series["bars"].get((y, m)), series["bars"].get((y + 1, m))
    return None if a is None or b is None else b[1] / a[1] - 1


def company_rows(facts: dict, sic, series: dict, cfg: dict, company_id: str) -> list[dict]:
    """One scored row per decision year for one company."""
    template = classify(sic)
    rows = []
    for y in YEARS:
        cutoff = f"{y}-04-30"
        fwd = forward_return(series, y)
        px = raw_close(series, y, 4)
        if fwd is None or px is None:
            continue
        a = analyse(pit_facts(facts, cutoff), date(y, 4, 30), template)
        if not a["years"]:
            continue
        snap = {"company_id": company_id, "rid": f"bt:{company_id}:{y}", "entity_name": a["entity_name"],
                **{k: a[k] for k in ("years", "derived", "summary", "flags", "confidence", "shares_outstanding",
                                     "method_version", "reporting_currency")},
                "industry_template": template, "screen_supported": supported(template)}
        price = {"close": px, "date": cutoff, "rid": "bt", "currency": series["currency"]}
        r = screener.score_company(snap, price, cfg, date(y, 4, 30))
        rows.append({"company_id": company_id, "year": y, "total": r["total"], "eligible": r["eligible"],
                     "scores": r["scores"], "failed_gates": r["failed_gates"], "fwd_return": fwd,
                     "template": template})
    return rows


def collect(securities: list[dict], sec, out_path: Path, cfg: dict | None = None, get=_get,
            log=print) -> list[dict]:
    """Fetch, score and append rows per company to `out_path` (JSONL, resumable)."""
    cfg = cfg or screener.load_config()
    done = set()
    if out_path.exists():
        done = {json.loads(line)["company_id"] for line in out_path.read_text().splitlines() if line.strip()}
    end = int(time.time())
    for i, s in enumerate(securities):
        if s["company_id"] in done:
            continue
        rec = {"company_id": s["company_id"], "symbol": s["symbol"], "rows": [], "error": None}
        tmp = Path(tempfile.mkdtemp(prefix="bt-sec-"))
        sec.cache_dir = tmp   # raw companyfacts are large: keep none of them
        try:
            series = parse_monthly(get(CHART.format(sym=yahoo_symbol(s), end=end)))
            if series["currency"] != "USD":
                rec["error"] = f"price currency {series['currency']}"
            else:
                facts = sec.company_facts(s["cik"], max_age_s=0)
                sic = sec.submissions(s["cik"], max_age_s=0).get("sic") or None
                rec["rows"] = company_rows(facts, sic, series, cfg, s["company_id"])
        except Exception as e:  # noqa: BLE001 - recorded per company; the run continues
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        with out_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        if log and i % 25 == 0:
            log(f"{i}/{len(securities)} {s['symbol']}: {len(rec['rows'])} rows {rec['error'] or ''}")
    return [json.loads(line) for line in out_path.read_text().splitlines() if line.strip()]


def sample(securities: list[dict], n: int = 600, seed: int = 7) -> list[dict]:
    seen, pool = set(), []
    for s in sorted(securities, key=lambda s: s["symbol"]):
        if not s.get("absent") and s.get("sec_match") == "high" and s["company_id"] not in seen:
            seen.add(s["company_id"])
            pool.append(s)
    return random.Random(seed).sample(pool, min(n, len(pool)))


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 5:
        return None
    rx, ry = _ranks(x), _ranks(y)
    return statistics.correlation(rx, ry)


def evaluate(records: list[dict], spy: dict | None = None, min_scored: int = 20) -> dict:
    """The pre-registered measures, per year and overall."""
    rows = [r for rec in records for r in rec["rows"]]
    per_year = []
    for y in YEARS:
        scored = [r for r in rows if r["year"] == y and r["total"] is not None]
        if len(scored) < min_scored:
            continue
        ic = spearman([r["total"] for r in scored], [r["fwd_return"] for r in scored])
        ranked = [r["fwd_return"] for r in scored if r["eligible"]]
        allr = statistics.mean(r["fwd_return"] for r in scored)
        q = sorted(scored, key=lambda r: r["total"])
        k = max(1, len(q) // 5)
        per_year.append({"year": y, "scored": len(scored), "ranked": len(ranked), "ic": ic,
                         "ranked_return": statistics.mean(ranked) if ranked else None,
                         "scored_return": allr,
                         "ranked_minus_scored": (statistics.mean(ranked) - allr) if ranked else None,
                         "top_minus_bottom_quintile": statistics.mean(r["fwd_return"] for r in q[-k:])
                         - statistics.mean(r["fwd_return"] for r in q[:k]),
                         "spy_return": forward_return(spy, y) if spy else None})
    ics = [p["ic"] for p in per_year if p["ic"] is not None]
    wins = [p["ranked_minus_scored"] > 0 for p in per_year if p["ranked_minus_scored"] is not None]
    mean_ic = statistics.mean(ics) if ics else None
    t = (mean_ic / (statistics.stdev(ics) / math.sqrt(len(ics)))) if len(ics) > 2 and statistics.stdev(ics) else None
    win_rate = sum(wins) / len(wins) if wins else None
    return {"years": per_year, "mean_ic": mean_ic, "ic_t": t, "ranked_win_rate": win_rate,
            "pass": bool(mean_ic is not None and mean_ic > 0 and t is not None and t >= 2
                         and win_rate is not None and win_rate >= 0.6),
            "companies": len(records), "companies_with_rows": sum(1 for r in records if r["rows"]),
            "errors": sum(1 for r in records if r["error"])}


def report(ev: dict) -> str:
    def p(x, f="{:+.1%}"):
        return "" if x is None else f.format(x)
    lines = ["# Screen backtest (M8, test 1): does the screen-1.0 score predict 12-month returns?", "",
             "Pre-registration: [`screen_backtest_prereg.md`](screen_backtest_prereg.md), committed before this ran.",
             "", f"**Verdict: {'PASS' if ev['pass'] else 'FAIL'}** against the pre-registered condition "
             "(mean IC > 0 with t >= 2, and the ranked basket beats all scored companies in >= 60% of years).", "",
             f"- Mean IC {p(ev['mean_ic'], '{:+.3f}')}, t = {p(ev['ic_t'], '{:.2f}')} over {len(ev['years'])} years",
             f"- Ranked basket beat all scored companies in {p(ev['ranked_win_rate'], '{:.0%}')} of years",
             f"- Companies sampled {ev['companies']}, with at least one scored year {ev['companies_with_rows']}, "
             f"errors {ev['errors']}", "",
             "| Year (Apr to Apr) | Scored | Ranked | IC | Ranked basket | All scored | Ranked minus all "
             "| Top minus bottom quintile | SPY |", "|---|---|---|---|---|---|---|---|---|"]
    for y in ev["years"]:
        lines.append(f"| {y['year']} | {y['scored']} | {y['ranked']} | {p(y['ic'], '{:+.3f}')} | "
                     f"{p(y['ranked_return'])} | {p(y['scored_return'])} | {p(y['ranked_minus_scored'])} | "
                     f"{p(y['top_minus_bottom_quintile'])} | {p(y['spy_return'])} |")
    lines += ["", "Biases (stated in advance): survivorship (only companies listed today), small early "
              "cross-sections, no costs, unofficial prices. Read the verdict as evidence about ranking, not as a "
              "return forecast."]
    return "\n".join(lines) + "\n"
