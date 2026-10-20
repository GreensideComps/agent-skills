"""B5-HANDCHECK: the fixed real-data implementation check (docs/edge/B5_HANDCHECK_PLAN.md, as narrowed by the owner
on 2026-10-16 11:53Z: placebo score only; no H1 or S2a score, ranking, return or NAV is computed).

The engine (`edge_backtest.run_trial`) runs both frozen B5 portfolio configurations with a placebo score. An
independent simulator below, which does not import edge_backtest or edge_rules, recomputes every month from the
raw files: eligibility, ranking, selection (buffer and sector cap), weights, drift, turnover, costs, missing-price
exits, FX, tranche combination and benchmark labels. Five fixed dates get a detailed table; the share counts of
two companies per date are re-read from SEC's live XBRL API.

Every input is cut at 2022-12-31 on read. Usage: SEC_USER_AGENT='<app> <email>' python3 edge_b5_handcheck.py
"""
import gzip
import hashlib
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import edge_b5 as b5
import edge_backtest as bt
import edge_exec_prices
import edge_registry
import edge_rules
import edge_split
import stage2
import xsection

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "equity" / "reports" / "research" / "edge"
EDGE = edge_exec_prices.OUT_DIR
CUT = pd.Timestamp("2022-12-31")
DATES = ["2015-01-31", "2015-04-30", "2019-07-31", "2020-03-31", "2022-11-30"]
TOL = 1e-9
RATE = {"large": 0.0030, "mid": 0.0045, "small": 0.0075}  # FX 0.15% + spread, one way (independent copy)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------- inputs (shared by both sides; the panel itself is re-derived independently in `raw_check`) ----------

def panel() -> pd.DataFrame:
    df = edge_split.with_quality(edge_split.cut_exploration(xsection.load()))
    comp = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(comp, on="cik", how="left")
    df["group"] = df["sic"].map(stage2.sic_group)
    df["financial"] = df["group"] == "finance"
    fresh = (df["month"] - pd.to_datetime(df["ttm_end"], errors="coerce")).dt.days.between(0, b5.FRESH_DAYS)
    df["fresh"] = fresh
    df["score"] = b5.placebo_score(df["cik"]).where(fresh & ~df["financial"])
    return df


def exec_rows() -> pd.DataFrame:
    x = pd.read_csv(EDGE / "exec_prices_to_2022.csv.gz")
    x = x[pd.to_datetime(x["month"]) <= CUT]
    return x


def fx_series() -> pd.Series:
    f = pd.read_csv(EDGE / "gbpusd_daily_to_2022.csv.gz", parse_dates=["date"])
    return edge_split.cut_series(f.set_index("date")["usd_per_gbp"])


def bench_frame() -> pd.DataFrame:
    b = pd.read_csv(EDGE / "benchmarks_daily_gbp_to_2022.csv.gz", parse_dates=["date"])
    return edge_split.cut_series(b.set_index("date")[["VWRP", "VWRL"]])


# ---------- engine side ----------

CONFIGS = {"quarterly (H1 rules)": (b5.H1_REBALANCE, b5.H1_TRANCHES),
           "12-month (S2a rules)": (b5.S2A_REBALANCE, b5.S2A_TRANCHES)}


def cfg(rebalance: int) -> bt.Config:
    return bt.Config(n=b5.N_NAMES, weighting="equal", rebalance_every=rebalance, buffer=b5.BUFFER,
                     sector_cap=b5.SECTOR_CAP, bands=("large",), min_price=1.0, cost_mult=1.0,
                     missing_return=-0.30, convention="next_day_close", selection="top_n")


def engine(p: pd.DataFrame, ex: pd.DataFrame, fx: pd.Series) -> dict:
    out = {}
    cols = ["cik", "month", "score", "band", "quality_ok", "group", "close_raw"]
    for name, (k, starts) in CONFIGS.items():
        out[name] = {s: bt.run_trial("B5-HANDCHECK", edge_registry.PATH, p[cols], ex, fx, cfg(k), start=s,
                                     end=b5.EVAL_LAST_DECISION) for s in starts}
    return out


# ---------- independent side (no edge_backtest / edge_rules imports) ----------

def ind_prices(ex: pd.DataFrame):
    ex = ex.copy()
    ex["month"] = pd.to_datetime(ex["month"])
    ex["exec_date"] = pd.to_datetime(ex["exec_date"])
    d = ex.groupby("month")["exec_date"].first()
    ok = ex["status"].isin(["ok", "stale_month_end"]) & (ex["exec_adjclose"] > 0)
    price = ex.assign(p=ex["exec_adjclose"].where(ok)).pivot_table(index="month", columns="cik", values="p",
                                                                   aggfunc="last", dropna=False)
    buy = ex.assign(b=(ex["status"] == "ok") & ok).pivot_table(index="month", columns="cik", values="b",
                                                                aggfunc="last", dropna=False)
    return d, price, buy.fillna(False).astype(bool)


def ind_fx(fx: pd.Series, d: pd.Timestamp) -> float:
    s = fx[fx.index <= d]
    assert len(s) and (d - s.index[-1]).days <= 7, f"no FX within 7 days of {d.date()}"
    return float(s.iloc[-1])


def ind_select(fr: pd.DataFrame, held: set, buyable) -> tuple[list, list, pd.DataFrame]:
    e = fr[fr["quality_ok"].astype(bool) & (fr["band"] == "large") & fr["score"].notna() & (fr["close_raw"] >= 1.0)]
    e = e.sort_values(["score", "cik"], ascending=[False, True]).reset_index(drop=True)
    e["rank"] = np.arange(1, len(e) + 1)
    rank, grp = dict(zip(e["cik"], e["rank"])), dict(zip(e["cik"], e["group"]))
    order = ([c for c in sorted(held, key=lambda c: rank.get(c, 1e9)) if rank.get(c, 1e9) <= 20]
             + [c for c in sorted(held, key=lambda c: rank.get(c, 1e9)) if 20 < rank.get(c, 1e9) <= 40])
    kept_n = sum(1 for c in held if rank.get(c, 1e9) <= 20)
    chosen, cnt, passed = [], {}, []
    for i, c in enumerate(order):
        if i >= kept_n and len(chosen) >= 20:
            continue
        if cnt.get(grp[c], 0) >= 4:
            passed.append((c, "cap"))
            continue
        chosen.append(c)
        cnt[grp[c]] = cnt.get(grp[c], 0) + 1
    for c in e["cik"]:
        if len(chosen) >= 20:
            break
        if c in held:
            continue
        if not buyable(c):
            passed.append((c, "no price"))
            continue
        if cnt.get(grp[c], 0) >= 4:
            passed.append((c, "cap"))
            continue
        chosen.append(c)
        cnt[grp[c]] = cnt.get(grp[c], 0) + 1
    return chosen, passed, e


def independent(p: pd.DataFrame, ex: pd.DataFrame, fx: pd.Series, k: int, start: str) -> dict:
    dates, price, buy = ind_prices(ex)
    months = [m for m in dates.index if pd.Timestamp(start) <= m <= pd.Timestamp(b5.EVAL_LAST_DECISION)]
    frames = {m: g for m, g in p.groupby("month")}
    units, last, band_of, cash = {}, {}, {}, 1.0
    nav_usd, nav_gbp, hold, turn, costs, exits, detail = {}, {}, {}, {}, {}, [], {}
    for i, m in enumerate(months):
        d = dates[m]
        vals = {}
        for c in list(units):
            px = price.at[m, c] if c in price.columns else np.nan
            if not (px > 0):
                v = units[c] * last[c] * 0.7
                cash += v
                exits.append((str(d.date()), int(c)))
                del units[c], last[c]
                continue
            last[c] = px
            vals[c] = units[c] * px
        nav = cash + sum(vals.values())
        if i % k == 0:
            fr = frames.get(m, p.iloc[:0])
            chosen, passed, ranked = ind_select(fr, set(units), lambda c: c in buy.columns and bool(buy.at[m, c]))
            w_t = {c: 1 / len(chosen) for c in chosen} if chosen else {}
            w_d = {c: v / nav for c, v in vals.items()}
            band = {c: b for c, b in zip(fr["cik"], fr["band"]) if isinstance(b, str)}
            names = set(w_t) | set(w_d)
            cost = sum(abs(w_t.get(c, 0) - w_d.get(c, 0)) * RATE.get(band.get(c) or band_of.get(c), RATE["small"])
                       for c in names)
            turn[m] = sum(abs(w_t.get(c, 0) - w_d.get(c, 0)) for c in names) / 2
            costs[m] = cost
            nav *= 1 - cost
            units = {c: nav * w / price.at[m, c] for c, w in w_t.items()}
            last = {c: price.at[m, c] for c in w_t}
            band_of = {c: band.get(c) or band_of.get(c) for c in w_t}
            cash = nav * (1 - sum(w_t.values()))
            hold[m] = set(w_t)
            detail[m] = {"ranked": ranked, "chosen": chosen, "passed": passed, "w_d": w_d, "w_t": w_t,
                         "cost": cost, "frame": fr}
        nav_usd[d] = nav
        nav_gbp[d] = nav / ind_fx(fx, d)
    g = pd.Series(nav_gbp)
    return {"nav_usd": pd.Series(nav_usd), "nav_gbp": g / g.iloc[0], "hold": hold, "turn": turn, "costs": costs,
            "exits": exits, "detail": detail}


def ind_bench(bench: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for a, b in zip(dates[:-1], dates[1:]):
        lab, r = "none", np.nan
        for col, label in (("VWRP", "actual VWRP"), ("VWRL", "VWRL-based")):
            s = bench[col].dropna()
            sa, sb = s[s.index <= a], s[s.index <= b]
            if len(sa) and len(sb) and (a - sa.index[-1]).days <= 5 and (b - sb.index[-1]).days <= 5:
                lab, r = label, sb.iloc[-1] / sa.iloc[-1] - 1
                break
        rows.append({"end": b, "return": r, "label": lab})
    return pd.DataFrame(rows).set_index("end")


# ---------- raw data and SEC re-reads ----------

def raw_check(rows: list[tuple[int, pd.Timestamp]]) -> list[dict]:
    """Eligibility inputs for the fixed companies, recomputed from the raw CSV files (cut on read)."""
    m = pd.read_csv(xsection.DATA / "monthly_metrics.csv.gz", usecols=["cik", "month", "ttm_end", "shares_out",
                                                                       "shares_diluted"])
    m = m[pd.to_datetime(m["month"]) <= CUT]
    pr = pd.read_csv(xsection.DATA / "prices_monthly.csv.gz", usecols=["cik", "month", "close_raw", "adjclose",
                                                                      "currency"])
    pr = pr[pd.to_datetime(pr["month"]) <= CUT]
    pr = pr[pr["currency"] == "USD"].drop_duplicates(["cik", "month"], keep="last")
    out = []
    for cik, mo in rows:
        s = mo.strftime("%Y-%m-%d")
        a = m[(m["cik"] == cik) & (m["month"] == s)]
        b = pr[(pr["cik"] == cik) & (pr["month"] == s)]
        if a.empty or b.empty:
            out.append({"cik": cik, "month": s, "mcap_raw": None})
            continue
        sh = a["shares_out"].iloc[0] if a["shares_out"].iloc[0] > 0 else a["shares_diluted"].iloc[0]
        out.append({"cik": cik, "month": s, "shares": float(sh), "close_raw": float(b["close_raw"].iloc[0]),
                    "mcap_raw": float(sh * b["close_raw"].iloc[0]), "ttm_end": a["ttm_end"].iloc[0]})
    return out


def panel_source(cik: int, as_of: str, metric: str) -> dict | None:
    """The fact the dataset used for `metric` at `as_of` (panel.latest for instants; the latest weighted-average
    period for shares_diluted, as equity.monthly does), read from the facts panel with filings cut at as_of."""
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(ROOT.parent / "equity"))
    from equity import panel as fpanel  # noqa: PLC0415
    rows = [r for r in fpanel.read(xsection.DATA / "sec_facts_panel.csv.gz", {cik})
            if r["metric"] == metric and r["unit"] == "shares" and r["filed"] <= as_of]
    if metric == "shares_diluted":
        ks = [r for r in fpanel.known(rows, as_of) if r["start"]]
        return max(ks, key=lambda r: (r["end"], r["filed"])) if ks else None
    return fpanel.latest(rows, as_of)


def sec_reread(cik: int, as_of: str, metric: str, ua: str) -> dict:
    """Re-read from SEC's live XBRL API the exact fact (taxonomy, concept, period, filing) the dataset used."""
    src = panel_source(cik, as_of, metric)
    if src is None:
        return {"sec_shares": None, "note": "no source fact found"}
    # companyfacts, not companyconcept: on 2026-10-16 companyconcept returned no facts for Fortive (CIK 1659166)
    # while companyfacts held the same filing's value
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        body = gzip.decompress(raw) if r.headers.get("Content-Encoding") == "gzip" else raw
    time.sleep(0.25)
    facts = json.loads(body)["facts"].get(src["taxonomy"], {}).get(src["concept"], {}).get("units", {}).get("shares", [])
    hit = [f for f in facts if f["accn"] == src["accn"] and f["end"] == src["end"]
           and (f.get("start") or "") == (src["start"] or "")]
    return {"sec_shares": float(hit[0]["val"]) if hit else None, "concept": f"{src['taxonomy']}:{src['concept']}",
            "sec_end": src["end"], "sec_filed": src["filed"], "sec_form": src["form"], "sec_accn": src["accn"],
            "metric": metric}


# ---------- comparison and report ----------

def compare(eng, ind, bench_eng, bench_ind) -> dict:
    r = {}
    nu = (eng.nav_usd - ind["nav_usd"]).abs().max()
    ng = (eng.nav_gbp - ind["nav_gbp"]).abs().max()
    r["months"] = len(ind["nav_usd"])
    r["max_nav_usd_diff"] = float(nu)
    r["max_nav_gbp_diff"] = float(ng)
    r["holdings_equal"] = all(set(eng.holdings[m]) == ind["hold"][m] for m in ind["hold"]) and \
        set(eng.holdings) == set(ind["hold"])
    r["max_turnover_diff"] = float(max(abs(eng.turnover[m] - ind["turn"][m]) for m in ind["turn"]))
    r["max_cost_diff"] = float(max(abs(eng.costs[m] - ind["costs"][m]) for m in ind["costs"]))
    eng_exits = sorted((str(e["date"].date()), int(e["cik"])) for e in eng.log if e["event"] == "exit")
    r["exits_equal"] = eng_exits == sorted(ind["exits"])
    r["exits"] = len(ind["exits"])
    r["bench_labels_equal"] = bool((bench_eng["label"] == bench_ind["label"]).all())
    r["max_bench_diff"] = float((bench_eng["return"] - bench_ind["return"]).abs().max())
    r["max_date"] = str(max(eng.nav_usd.index).date())
    r["pass"] = (nu <= TOL and ng <= TOL and r["holdings_equal"] and r["max_turnover_diff"] <= TOL
                 and r["max_cost_diff"] <= TOL and r["exits_equal"] and r["bench_labels_equal"]
                 and r["max_bench_diff"] <= TOL and pd.Timestamp(r["max_date"]) <= CUT)
    return r


def pick(det: dict, panel_m: pd.DataFrame) -> list[tuple[str, int]]:
    """The fixed companies (plan §3), chosen by rule."""
    rk, out = det["ranked"], []
    for r in (1, 20, 21):
        x = rk.loc[rk["rank"] == r, "cik"]
        if len(x):
            out.append((f"rank {r}", int(x.iloc[0])))
    buf = [c for c in det["chosen"] if 20 < int(rk.loc[rk["cik"] == c, "rank"].iloc[0]) <= 40]
    if buf:
        out.append(("buffer hold", int(min(buf, key=lambda c: int(rk.loc[rk["cik"] == c, "rank"].iloc[0])))))
    for why, lab in (("cap", "sector-cap skip"), ("no price", "missing-price skip")):
        x = [c for c, w in det["passed"] if w == why]
        if x:
            out.append((lab, int(x[0])))
    f = panel_m.sort_values("cik")
    rules = {"quality flag": ~f["quality_ok"].astype(bool) & (f["band"] == "large"),
             "price under $1": f["close_raw"] < 1.0, "below $10bn": f["band"].isin(["mid", "small"]),
             "financial": f["financial"] & (f["band"] == "large"),
             "stale TTM": ~f["fresh"] & (f["band"] == "large") & ~f["financial"]}
    for lab, mask in rules.items():
        if mask.any():
            out.append((f"excluded: {lab}", int(f.loc[mask, "cik"].iloc[0])))
    return out


def row_check(lab, c, m, det, panel_m, fx, d, rawd) -> dict:
    fr = panel_m.set_index("cik")
    x = fr.loc[c] if c in fr.index else None
    rk = det["ranked"].set_index("cik")
    raw = rawd.get((c, m.strftime("%Y-%m-%d")), {})
    elig_ind = (x is not None and bool(x["quality_ok"]) and x["band"] == "large" and pd.notna(x["score"])
                and x["close_raw"] >= 1.0)
    band_raw = None if not raw.get("mcap_raw") else ("large" if raw["mcap_raw"] >= 10e9 else "below large")
    return {"role": lab, "cik": c, "rank": int(rk.loc[c, "rank"]) if c in rk.index else None,
            "eligible": elig_ind, "in_ranking": c in rk.index,
            "mcap_raw_$bn": round(raw["mcap_raw"] / 1e9, 3) if raw.get("mcap_raw") else None,
            "band_dataset": None if x is None else x["band"], "band_raw": band_raw,
            "band_match": band_raw is None or (band_raw == "large") == (x is not None and x["band"] == "large"),
            "w_before": round(det["w_d"].get(c, 0.0), 6), "w_after": round(det["w_t"].get(c, 0.0), 6),
            "group": None if x is None else x["group"]}


def main() -> None:
    edge_registry.require("B5-HANDCHECK")
    hashes = {f: sha(xsection.DATA / f) for f in ("monthly_metrics.csv.gz", "prices_monthly.csv.gz",
                                                   "sec_companies.csv.gz")}
    hashes.update({f: sha(EDGE / f) for f in ("exec_prices_to_2022.csv.gz", "gbpusd_daily_to_2022.csv.gz",
                                              "benchmarks_daily_gbp_to_2022.csv.gz")})
    p, ex, fx, bench = panel(), exec_rows(), fx_series(), bench_frame()
    eng = engine(p, ex, fx)
    results, details, combined = {}, {}, {}
    for name, (k, starts) in CONFIGS.items():
        inds = {s: independent(p, ex, fx, k, s) for s in starts}
        for s in starts:
            e = eng[name][s]
            be = bt.benchmark_returns(bench, e.nav_gbp.index)
            bi = ind_bench(bench, inds[s]["nav_gbp"].index)
            results[(name, s)] = compare(e, inds[s], be, bi)
        first = sorted(pd.Timestamp(d) for d in ex.loc[pd.to_datetime(ex["month"]) == b5.EVAL_FIRST_DECISION,
                                                         "exec_date"].unique())[0]
        c_eng = b5.combine_tranches([eng[name][s].nav_gbp for s in starts], first)
        ind_rebased = [inds[s]["nav_gbp"][inds[s]["nav_gbp"].index >= first] for s in starts]
        c_ind = pd.concat([x / x.iloc[0] for x in ind_rebased], axis=1).mean(axis=1)
        combined[name] = {"periods": int(len(c_eng) - 1), "max_diff": float((c_eng - c_ind).abs().max()),
                          "first": str(first.date()), "last": str(c_eng.index[-1].date()),
                          "placebo_combined_nav_end": float(c_eng.iloc[-1])}
        details[name] = inds
    # fixed dates: the tranche whose rebalance falls on each date
    ua = os.environ.get("SEC_USER_AGENT", "")
    picks, rows = {}, []
    for name, (k, starts) in CONFIGS.items():
        for dstr in DATES:
            m = pd.Timestamp(dstr)
            for s in starts:
                det = details[name][s]["detail"].get(m)
                if det is not None:
                    picks[(name, dstr)] = (s, det, pick(det, det["frame"]))
                    break
    raw_rows = sorted({(c, pd.Timestamp(dstr)) for (name, dstr), (_, _, pk) in picks.items() for _, c in pk})
    rawd = {(r["cik"], r["month"]): r for r in raw_check(raw_rows)}
    sec = []
    for (name, dstr), (s, det, pk) in picks.items():
        m = pd.Timestamp(dstr)
        d = edge_exec_prices_date(ex, m)
        for lab, c in pk:
            rows.append({"config": name, "date": dstr, "tranche": s, **row_check(lab, c, m, det, det["frame"], fx, d, rawd)})
        if name.startswith("quarterly") and ua:
            for lab, c in pk[:2]:  # rank 1 and rank 20
                x = det["frame"].set_index("cik").loc[c]
                metric = "shares_out" if x["shares_out"] > 0 else "shares_diluted"
                srec = sec_reread(c, dstr, metric, ua)
                ds = x[metric]
                sec.append({"date": dstr, "role": lab, "cik": c, "dataset_shares": float(ds), **srec,
                            "match": srec.get("sec_shares") is not None and abs(srec["sec_shares"] - ds) <= 0.5})
    fixed_ok = all(r["band_match"] and (r["eligible"] == r["in_ranking"]) for r in rows)
    weights_ok = all(abs(sum(det["w_t"].values()) - 1) <= TOL for (_, det, _) in picks.values() if det["w_t"])
    cap_ok = all(max(pd.Series([det["frame"].set_index("cik").loc[c, "group"] for c in det["chosen"]]).value_counts(),
                     default=0) <= b5.SECTOR_CAP for (_, det, _) in picks.values())
    verdict = (all(r["pass"] for r in results.values()) and all(c["max_diff"] <= TOL for c in combined.values())
               and fixed_ok and weights_ok and cap_ok and all(s["match"] for s in sec))
    res = {"run": datetime.now(timezone.utc).isoformat(timespec="seconds"), "hashes": hashes,
           "per_tranche": {f"{a} | {b}": v for (a, b), v in results.items()}, "combined": combined,
           "fixed_rows": rows, "sec_rereads": sec, "fixed_ok": fixed_ok, "weights_ok": weights_ok,
           "cap_ok": cap_ok, "verdict": "PASS" if verdict else "FAIL"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b5_handcheck.json").write_text(json.dumps(res, indent=1, default=str))
    (OUT / "b5_handcheck.md").write_text(report(res))
    print(res["verdict"], json.dumps(combined), fixed_ok, weights_ok, cap_ok, len(sec), sum(s["match"] for s in sec))


def edge_exec_prices_date(ex: pd.DataFrame, m: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(ex.loc[pd.to_datetime(ex["month"]) == m, "exec_date"].iloc[0])


def report(res: dict) -> str:
    L = [f"Run {res['run']}. Registry id `B5-HANDCHECK` (diagnostic, not counted). **Placebo score only:** no H1 "
         "or S2a score, ranking, return or NAV was computed. Inputs cut at 2022-12-31 on read.", "",
         f"## Verdict: **{res['verdict']}**", "",
         "### 1. Engine vs independent recomputation, every month of every tranche", "",
         "| Configuration and tranche start | Months | Max NAV diff (USD, GBP) | Holdings equal | Max turnover diff "
         "| Max cost diff | Missing-price exits (equal) | Benchmark labels equal | Max benchmark diff | Last date | Pass |",
         "|---|---:|---|---|---:|---:|---|---|---:|---|---|"]
    for k, v in res["per_tranche"].items():
        L.append(f"| {k} | {v['months']} | {v['max_nav_usd_diff']:.1e}, {v['max_nav_gbp_diff']:.1e} | "
                 f"{v['holdings_equal']} | {v['max_turnover_diff']:.1e} | {v['max_cost_diff']:.1e} | {v['exits']} "
                 f"({v['exits_equal']}) | {v['bench_labels_equal']} | {v['max_bench_diff']:.1e} | {v['max_date']} | "
                 f"{v['pass']} |")
    L += ["", "### 2. Tranche combination (`edge_b5.combine_tranches` vs an independent mean of rebased NAVs)", "",
          "| Configuration | Periods | From | To | Max diff | Placebo combined NAV at end |", "|---|---:|---|---|---:|---:|"]
    for k, v in res["combined"].items():
        L.append(f"| {k} | {v['periods']} | {v['first']} | {v['last']} | {v['max_diff']:.1e} | "
                 f"{v['placebo_combined_nav_end']:.4f} |")
    L += ["", "The placebo NAV is shown only to prove the arithmetic runs end to end; it is a hash-ordered portfolio "
          "and carries no information about any trial.", "",
          "### 3. Fixed dates and companies (chosen by rule; plan §2-3)", "",
          f"Recomputed from the raw CSV files: market cap and band. All rows consistent: **{res['fixed_ok']}**. "
          f"Target weights sum to 1: **{res['weights_ok']}**. Sector cap of 4 held: **{res['cap_ok']}**.", "",
          "| Config | Date | Tranche | Role | CIK | Rank | Eligible | Mcap raw ($bn) | Band (dataset / raw) | Weight before → after |",
          "|---|---|---|---|---:|---:|---|---:|---|---|"]
    for r in res["fixed_rows"]:
        L.append(f"| {r['config']} | {r['date']} | {r['tranche']} | {r['role']} | {r['cik']} | {r['rank'] or ''} | "
                 f"{r['eligible']} | {r['mcap_raw_$bn'] or ''} | {r['band_dataset']} / {r['band_raw']} | "
                 f"{r['w_before']} → {r['w_after']} |")
    L += ["", "### 4. Market-cap share counts re-read from SEC's live XBRL API (quarterly configuration, ranks 1 and 20)", "",
          "This re-reads the filings' tagged values from SEC today, so it tests the download, panel and point-in-time "
          "steps. It is not an independent source: it reads the same XBRL filings.", "",
          "| Date | Role | CIK | Field (concept) | Dataset shares | SEC shares | Period end | Filed | Form | Match |",
          "|---|---|---:|---|---:|---:|---|---|---|---|"]
    for s in res["sec_rereads"]:
        L.append(f"| {s['date']} | {s['role']} | {s['cik']} | {s.get('metric')} ({s.get('concept')}) | {s['dataset_shares']:,.0f} | "
                 f"{(s.get('sec_shares') or 0):,.0f} | {s.get('sec_end')} | {s.get('sec_filed')} | {s.get('sec_form')} | "
                 f"{s['match']} |")
    L += ["", "### Data files (sha256)", ""] + [f"- `{k}`: `{v}`" for k, v in res["hashes"].items()]
    return edge_rules.require_disclosure(bt.report("B5 hand-check: real-data implementation (placebo score)", {},
                                                   "\n".join(L) + "\n"))


if __name__ == "__main__":
    main()
