"""Concentrated-portfolio backtester for the edge-discovery programme (Phase B, step B2; docs/edge/PHASE_B_PLAN.md).

Answers one question for a registered signal on exploration data: would a portfolio of 15 to 30 US stocks,
rebalanced quarterly and held in GBP, have beaten VWRP after costs? In step B2 it runs on synthetic data only; the
owner has not authorised a run on real signals (DECISIONS.md D8-D9).

Rules it does not reimplement (tested in Phase A and B1):

* decision inputs: `edge_rules.decision_frame` (rows dated <= t, no forward or execution columns);
* trade timing: the execution price table (`exec_prices`), whose dates are strictly after each decision;
* holdings whose price disappears or turns invalid: `edge_rules.holding_return` (last valid price, then the
  missing-price mark-down; never favourable);
* report disclosure: `edge_rules.require_disclosure`.

Alignment at each rebalance k (decision month-end t_k, trade date e_k):

1. every holding is valued at e_k; one whose price is missing or invalid at or before e_k has already been closed
   by `holding_return` and sits in cash (0% interest) with an `exit` event in the log;
2. targets come from the decision frame at t_k only: eligible = quality ok, band allowed, score present, price as
   traded >= $1, and, for a new purchase, a usable execution price at e_k (otherwise a `skipped_entry` event);
3. drifted weights are values at e_k over the net asset value (NAV); one-way turnover is sum|target - drifted|;
   the cost is sum over names of |target - drifted| x (FX fee + spread for the name's band at t_k) x multiplier,
   deducted from NAV at e_k;
4. between trade dates every month is a valuation point (the next month's trade date), so returns, exits and
   benchmark periods line up on the same dates.

Currency: positions are USD; the GBP NAV is the USD NAV divided by USD-per-GBP on or before each valuation date.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import edge_registry
import edge_rules
import edge_split

FX_FEE = 0.0015
SPREAD = {"large": 0.0015, "mid": 0.0030, "small": 0.0060}
STAT = "portfolio_excess_vs_vwrp"
BENCH_STALE_DAYS = 5


@dataclass
class Config:
    n: int = 20
    weighting: str = "equal"  # equal | score (rank-proportional) | inv_vol
    rebalance_every: int = 3  # months between rebalances
    buffer: float = 2.0  # holdings ranked up to buffer x N are kept while there is room
    sector_cap: int | None = None  # names per group; default max(3, N // 5); 0 disables
    bands: tuple = ("large",)
    min_price: float = 1.0
    cost_mult: float = 1.0
    missing_return: float = edge_rules.DEFAULT_MISSING_RETURN
    convention: str = edge_rules.DEFAULT_CONVENTION
    select_all: bool = False  # the equal-weighted eligible universe (a benchmark), no buffer or cap

    def cap(self) -> int | None:
        if self.select_all or self.sector_cap == 0:
            return None
        return self.sector_cap if self.sector_cap is not None else max(3, self.n // 5)


@dataclass
class Result:
    nav_usd: pd.Series
    nav_gbp: pd.Series
    log: list = field(default_factory=list)
    holdings: dict = field(default_factory=dict)  # decision month -> {cik: weight}
    turnover: dict = field(default_factory=dict)  # decision month -> one-way turnover (sum |dw| / 2)
    costs: dict = field(default_factory=dict)  # decision month -> cost as a fraction of NAV


def cost_rate(band: str | None, mult: float = 1.0) -> float:
    """One-way cost of trading a name: FX fee plus the band's spread (unknown band: the small-cap spread)."""
    return (FX_FEE + SPREAD.get(band or "small", SPREAD["small"])) * mult


# ---------- prices ----------

def price_table(exec_rows: pd.DataFrame, convention: str = edge_rules.DEFAULT_CONVENTION
                ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """(prices, trade_dates, entry_ok).

    * prices: date x cik table of usable prices at trade dates, NaN where the price is missing or invalid (a
      held name then exits through `holding_return`);
    * trade_dates: the trade date of each decision month;
    * entry_ok: date x cik, True where a new purchase is allowed at that date.

    next_day_close: the execution close on the first trading day after the month-end. Usable for valuing a holding
    when B1's status is ok or stale_month_end (the execution close itself is fine); a new purchase also needs a
    current decision close, so only status ok. next_month_close: the next month-end's close (B1's `me_adjclose`
    of the following month), usable when that close is positive and not stale."""
    d = exec_rows.copy()
    d["month"] = pd.to_datetime(d["month"])
    edge_rules_assert_cut(pd.to_datetime(d["exec_date"]))
    edge_rules_assert_cut(d["month"])
    if convention == "next_day_close":
        ex = pd.to_datetime(d["exec_date"])
        per = d.assign(date=ex).groupby("month")["date"].agg(["min", "max"])
        if (per["min"] != per["max"]).any():
            raise ValueError("execution dates differ across companies within a month")
        dates = per["min"]
        valid = d["status"].isin(["ok", "stale_month_end"]) & (d["exec_adjclose"] > 0)
        px = d.assign(date=ex, p=d["exec_adjclose"].where(valid), e=(d["status"] == "ok") & valid)
    elif convention == "next_month_close":
        valid = d["status"].isin(["ok", "missing_exec"]) & (d["me_adjclose"] > 0)
        # the close at month-end m is the trade price for the decision at m - 1 month
        px = d.assign(date=d["month"], p=d["me_adjclose"].where(valid), e=valid)
        months = sorted(d["month"].unique())
        dates = pd.Series([m + pd.offsets.MonthEnd(1) for m in months], index=pd.DatetimeIndex(months))
        dates = dates[dates.isin(set(months))]
    else:
        raise ValueError(f"convention must be one of {edge_rules.CONVENTIONS}")
    table = px.pivot_table(index="date", columns="cik", values="p", aggfunc="last", dropna=False).sort_index()
    entry = px.pivot_table(index="date", columns="cik", values="e", aggfunc="last", dropna=False).sort_index()
    entry = entry.reindex(index=table.index, columns=table.columns).fillna(False).astype(bool)
    for m, e in dates.items():
        edge_rules.assert_executable(m, e)
    return table, dates.sort_index(), entry


def edge_rules_assert_cut(dates) -> None:
    d = pd.to_datetime(pd.Series(list(dates)))
    if len(d) and (d > edge_split.EXPLORATION_LAST_OUTCOME).any():
        raise edge_split.HoldoutViolation("a price or trade date is after 2022-12-31")


def rate_on_or_before(series: pd.Series, d: pd.Timestamp, stale_days: int = 7) -> float:
    s = series[series.index <= d]
    if s.empty or (d - s.index[-1]).days > stale_days:
        raise ValueError(f"no value within {stale_days} days before {d.date()}")
    return float(s.iloc[-1])


# ---------- selection ----------

def eligible(frame: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    f = frame[frame["quality_ok"].astype(bool) & frame["band"].isin(cfg.bands) & frame["score"].notna()
              & (frame["close_raw"] >= cfg.min_price)]
    return f.sort_values(["score", "cik"], ascending=[False, True]).assign(rank=lambda x: np.arange(1, len(x) + 1))


def select(ranked: pd.DataFrame, held: set, buyable: set, cfg: Config) -> tuple[list, list]:
    """Names to hold after this rebalance, and (cik, reason) for names passed over. Held names need no new
    execution price check (they were valued at e_k); new names must be buyable."""
    if cfg.select_all:
        chosen = [c for c in ranked["cik"] if c in held or c in buyable]
        return chosen, [(c, "no execution price") for c in ranked["cik"] if c not in held and c not in buyable]
    n, cap = cfg.n, cfg.cap()
    rank = dict(zip(ranked["cik"], ranked["rank"]))
    group = dict(zip(ranked["cik"], ranked["group"]))
    kept = sorted([c for c in held if rank.get(c, math.inf) <= n], key=rank.get)
    buf = sorted([c for c in held if n < rank.get(c, math.inf) <= cfg.buffer * n], key=rank.get)
    rest = [c for c in ranked["cik"] if c not in held]
    chosen, counts, passed = [], {}, []

    def add(c):
        g = group.get(c)
        if cap is not None and counts.get(g, 0) >= cap:
            passed.append((c, f"sector cap ({g})"))
            return
        chosen.append(c)
        counts[g] = counts.get(g, 0) + 1

    for c in kept:
        add(c)
    for c in buf:
        if len(chosen) < n:
            add(c)
    for c in rest:
        if len(chosen) >= n:
            break
        if c not in buyable:
            passed.append((c, "no execution price"))
            continue
        add(c)
    return chosen, passed


def target_weights(chosen: list, ranked: pd.DataFrame, cfg: Config) -> dict:
    if not chosen:
        return {}
    if cfg.weighting == "equal" or cfg.select_all:
        return {c: 1 / len(chosen) for c in chosen}
    r = ranked.set_index("cik").loc[chosen]
    if cfg.weighting == "score":
        w = (len(chosen) + 1 - r["score"].rank(ascending=False, method="first")).astype(float)
    elif cfg.weighting == "inv_vol":
        v = r["vol12"].where(r["vol12"] > 0)
        w = (1 / v).fillna((1 / v).mean() if v.notna().any() else 1.0)
    else:
        raise ValueError("weighting must be equal, score or inv_vol")
    return (w / w.sum()).to_dict()


# ---------- engine ----------

def run(panel: pd.DataFrame, exec_rows: pd.DataFrame, fx: pd.Series, cfg: Config,
        start=None, end=None) -> Result:
    """Simulate the strategy. `panel`: cik, month, score, band, quality_ok, group, close_raw (and vol12 for
    inv_vol). `exec_rows`: the B1 schema. `fx`: USD per GBP by date."""
    panel = panel.copy()
    panel["month"] = pd.to_datetime(panel["month"])
    edge_split.assert_exploration_only(panel)
    edge_rules_assert_cut(fx.index)
    prices, trade_dates, entry_ok = price_table(exec_rows, cfg.convention)
    months = [m for m in trade_dates.index if (start is None or m >= pd.Timestamp(start))
              and (end is None or m <= pd.Timestamp(end))]
    if not months:
        raise ValueError("no decision months in range")
    rebal = set(months[::cfg.rebalance_every])
    pos: dict = {}  # cik -> {"entry": date, "value0": USD at entry, "band": band at last decision}
    cash = 1.0
    res = Result(nav_usd=pd.Series(dtype=float), nav_gbp=pd.Series(dtype=float))
    nav0_gbp = None
    for m in months:
        d = trade_dates[m]
        # 1. value holdings at d; close any whose price went missing
        values = {}
        for c, p in list(pos.items()):
            series = prices[c] if c in prices else pd.Series(dtype=float)
            r, status = edge_rules.holding_return(series, p["entry"], d, cfg.missing_return)
            v = p["value0"] * (1 + r)
            if status == "missing":
                cash += v
                res.log.append({"date": d, "event": "exit", "cik": c, "reason": "missing or invalid price",
                                "return": r})
                del pos[c]
            else:
                values[c] = v
        nav = cash + sum(values.values())
        if m in rebal:
            frame = edge_rules.decision_frame(panel, m)
            frame = frame[frame["month"] == m]
            ranked = eligible(frame, cfg)
            ok_d = entry_ok.loc[d] if d in entry_ok.index else pd.Series(dtype=bool)
            buyable = {c for c in ranked["cik"] if c in ok_d.index and bool(ok_d[c])}
            chosen, passed = select(ranked, set(pos), buyable, cfg)
            for c, why in passed:
                if why == "no execution price":
                    res.log.append({"date": d, "event": "skipped_entry", "cik": c, "reason": why})
                else:
                    res.log.append({"date": d, "event": "skipped_cap", "cik": c, "reason": why})
            w_t = target_weights(chosen, ranked, cfg)
            w_d = {c: v / nav for c, v in values.items()} if nav > 0 else {}
            band = dict(zip(frame["cik"], frame["band"]))
            names = set(w_t) | set(w_d)
            dw = {c: abs(w_t.get(c, 0.0) - w_d.get(c, 0.0)) for c in names}
            cost = sum(dw[c] * cost_rate(band.get(c, pos.get(c, {}).get("band")), cfg.cost_mult) for c in names)
            nav_after = nav * (1 - cost)
            res.turnover[m] = sum(dw.values()) / 2
            res.costs[m] = cost
            res.holdings[m] = dict(w_t)
            pos = {c: {"entry": d, "value0": nav_after * w, "band": band.get(c)} for c, w in w_t.items()}
            cash = nav_after * (1 - sum(w_t.values()))
            nav = nav_after
            if not w_t:
                res.log.append({"date": d, "event": "all_cash", "reason": "no eligible names"})
            elif len(w_t) < cfg.n and not cfg.select_all:
                res.log.append({"date": d, "event": "short", "reason": f"{len(w_t)} of {cfg.n} names"})
        res.nav_usd.loc[d] = nav
        g = nav / rate_on_or_before(fx, d)
        res.nav_gbp.loc[d] = g
    if res.nav_gbp.size:
        base = res.nav_gbp.iloc[0]
        res.nav_gbp = res.nav_gbp / base
    return res


# ---------- benchmarks and metrics ----------

def benchmark_returns(bench: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Benchmark return for each period between consecutive valuation dates, with its label: 'actual VWRP' where
    VWRP has a price at both ends, 'VWRL-based' where only VWRL has, else 'none'. A price must be dated on or
    before the valuation date and within 5 days of it."""
    edge_rules_assert_cut(bench.index)
    out = []
    for a, b in zip(dates[:-1], dates[1:]):
        lab, r = "none", float("nan")
        for name, label in (("VWRP", "actual VWRP"), ("VWRL", "VWRL-based")):
            if name not in bench:
                continue
            try:
                pa = rate_on_or_before(bench[name].dropna(), a, BENCH_STALE_DAYS)
                pb = rate_on_or_before(bench[name].dropna(), b, BENCH_STALE_DAYS)
            except ValueError:
                continue
            lab, r = label, pb / pa - 1
            break
        out.append({"start": a, "end": b, "return": r, "label": lab})
    return pd.DataFrame(out).set_index("end")


def max_drawdown(wealth: pd.Series) -> float:
    return float((wealth / wealth.cummax() - 1).min())


def metrics(nav_gbp: pd.Series, bench: pd.DataFrame | None = None, res: Result | None = None) -> dict:
    r = nav_gbp.pct_change().dropna()
    years = len(r) / 12
    out = {"months": len(r), "cagr": float(nav_gbp.iloc[-1] / nav_gbp.iloc[0]) ** (1 / years) - 1 if years else float("nan"),
           "vol": float(r.std() * math.sqrt(12)), "sharpe": float(r.mean() / r.std() * math.sqrt(12)) if r.std() > 0 else float("nan"),
           "max_drawdown": max_drawdown(nav_gbp)}
    if bench is not None:
        b = benchmark_returns(bench, nav_gbp.index)
        j = pd.concat([r.rename("s"), b["return"].rename("b"), b["label"]], axis=1).dropna(subset=["s", "b"])
        ex = j["s"] - j["b"]
        te = float(ex.std() * math.sqrt(12))
        out.update({"te": te, "ir": float(ex.mean() * 12 / te) if te > 0 else float("nan"),
                    "sr_excess_monthly": float(ex.mean() / ex.std()) if ex.std() > 0 else float("nan"),
                    "share_months_ahead": float((ex > 0).mean()),
                    "relative_drawdown": max_drawdown((1 + j["s"]).cumprod() / (1 + j["b"]).cumprod()),
                    "benchmark_labels": j["label"].value_counts().to_dict(),
                    "first_actual_vwrp_period": str(j.index[j["label"] == "actual VWRP"].min().date())
                    if (j["label"] == "actual VWRP").any() else None,
                    "excess_skew": float(ex.skew()), "excess_kurt": float(ex.kurt() + 3)})
    if res is not None and res.holdings:
        out["turnover_per_year"] = float(sum(res.turnover.values()) / years) if years else float("nan")
        out["max_weight"] = float(max(max(w.values(), default=0) for w in res.holdings.values()))
        out["top5_weight"] = float(np.mean([sum(sorted(w.values(), reverse=True)[:5]) for w in res.holdings.values()]))
        out["missing_price_exits"] = sum(1 for e in res.log if e["event"] == "exit")
        out["skipped_entries"] = sum(1 for e in res.log if e["event"] == "skipped_entry")
    return out


# ---------- registration, DSR and report ----------

def run_trial(trial_id: str, registry, *args, **kwargs) -> Result:
    """Run a registered trial: refuses an unregistered trial or one that already has a result."""
    edge_registry.require(trial_id, registry)
    return run(*args, **kwargs)


def record(trial_id: str, m: dict, registry, evidence: str) -> dict:
    """Append the trial's result with its statistic, so the DSR pools it only with comparable results."""
    edge_registry.require(trial_id, registry)
    return edge_registry.append({"event": "result", "id": trial_id, "evidence": evidence, "stat": STAT,
                                 "sr_monthly": m["sr_excess_monthly"], "n_months": m["months"]}, registry)


def dsr(m: dict, registry) -> dict:
    return edge_registry.deflated_sharpe(m["sr_excess_monthly"], m["months"], m["excess_skew"], m["excess_kurt"],
                                         STAT, edge_registry.load(registry))


def report(title: str, m: dict, body: str = "") -> str:
    lines = [f"# {title}", "", edge_rules.STANDING_LIMITATIONS] + (["| Metric | Value |", "|---|---|"] if m else [])
    lines += [f"| {k} | {v:.4f} |" if isinstance(v, float) else f"| {k} | {v} |" for k, v in m.items()]
    return edge_rules.require_disclosure("\n".join(lines) + "\n" + body)
