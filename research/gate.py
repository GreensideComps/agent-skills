"""Research gate v3: a two-stage test a real edge can pass and noise almost never does.

Pre-registered in research/GATE_V3.md (12 Nov 2026). It applies to trials registered from that date on. Earlier
verdicts are never re-judged.

Why it replaces the deflated-Sharpe gate (research/METHOD_AUDIT.md): the old gate asked one backtest to beat the best
of every trial ever run (t >= 4.69 at N = 486). That bar controls the chance of even one false pass across the whole
history of the project, and it rises with every idea tried, so a real 3% a year edge had about no chance of passing
and the loop could only ever say "fail". Every honest research process that keeps running needs a different shape:

  stage 1  discovery     each idea is declared as a batch of at most MAX_CONFIGS configurations, with its two data
                         windows fixed in advance. On the DISCOVERY window, the batch's one-sided p-values go through
                         Benjamini-Hochberg at q (default 0.10): a lenient screen, so real effects get through.
  stage 2  confirmation  every discovered configuration is tested once on the CONFIRMATION window, data stage 1 never
                         touched, at one-sided alpha / (number discovered). It must also keep its sign with costs
                         doubled and with a one-month lag.
  stage 3  forward demo  a pass goes to the demo as a labelled forward test; real money still needs the go-live rule
                         (research/always_on/GO_LIVE_RULE.md), which is unchanged.

A configuration with no edge passes stages 1 and 2 with probability at most q/k x alpha (0.10/k x 0.05), so even
hundreds of batches send very few false passes to the demo, and the demo's own rule catches those. A real edge is
judged on its own batch, not against everything ever tried, so its chance of passing does not fall as the project
runs longer: it depends only on the size of the edge and the length of the data, which `power()` reports before any
data is touched.

The p-values use the Newey-West t (stats.nw_t) of the monthly excess return, judged against Student's t.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

import stats

EFFECTIVE = "2026-11-12"
MAX_CONFIGS = 10
DEFAULT_Q = 0.10
DEFAULT_ALPHA = 0.05
HOLDOUT_FROM = "2023-01"      # no window may reach the 2023-26 holdout
MIN_MONTHS = 36               # each window needs at least three years of monthly data
# Survivorship (research/SURVIVORSHIP.md, 11 Nov 2026): the stock panel holds almost none of the companies that stopped
# filing, so a long-only stock-panel result can be flattered by up to this much a year (worst case). A stock-panel
# batch must clear it on the confirmation window; long-history index or factor data (Ken French, AQR) declare 0.
SURVIVORSHIP_PP = {"none": 0.0, "panel": 1.0, "panel_weak": 1.7}
_ND = statistics.NormalDist()


@dataclass(frozen=True)
class Batch:
    """One idea's pre-registration: its configurations and the two windows, fixed before any data is read."""
    id: str
    configs: tuple[str, ...]
    discovery: tuple[str, str]          # ("YYYY-MM", "YYYY-MM") inclusive
    confirmation: tuple[str, str]
    q: float = DEFAULT_Q
    alpha: float = DEFAULT_ALPHA
    notes: str = ""
    data: str = "none"      # "panel" for the 2011-2022 stock panel, "panel_weak" if it selects weak-health companies

    def problems(self) -> list[str]:
        out = []
        if not 1 <= len(self.configs) <= MAX_CONFIGS:
            out.append(f"a batch has 1 to {MAX_CONFIGS} configurations, this one has {len(self.configs)}")
        if len(set(self.configs)) != len(self.configs):
            out.append("configuration ids repeat")
        for name, (a, b) in (("discovery", self.discovery), ("confirmation", self.confirmation)):
            if not (_ym(a) and _ym(b)) or a > b:
                out.append(f"{name} window {a}..{b} is not two months in order (YYYY-MM)")
            elif b >= HOLDOUT_FROM:
                out.append(f"{name} window ends {b}: it reaches the 2023-26 holdout")
            elif months_between(a, b) < MIN_MONTHS:
                out.append(f"{name} window has {months_between(a, b)} months, fewer than {MIN_MONTHS}")
        if not out and not (self.discovery[1] < self.confirmation[0] or self.confirmation[1] < self.discovery[0]):
            out.append("the discovery and confirmation windows overlap")
        if self.data not in SURVIVORSHIP_PP:
            out.append(f"data must be one of {sorted(SURVIVORSHIP_PP)}")
        if not 0 < self.q <= 0.2 or not 0 < self.alpha <= 0.05:
            out.append("q must be in (0, 0.2] and alpha in (0, 0.05]")
        return out


def _ym(s: str) -> bool:
    return isinstance(s, str) and len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:].isdigit() \
        and 1 <= int(s[5:]) <= 12


def months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:]) - int(a[5:]) + 1


def window(series: dict[str, float], w: tuple[str, str]) -> list[float]:
    """The values of a {'YYYY-MM' or 'YYYYMM': monthly return} series inside window w, in month order."""
    a, b = w
    norm = {(k if "-" in k else f"{k[:4]}-{k[4:6]}"): v for k, v in series.items()}
    return [norm[m] for m in sorted(norm) if a <= m <= b]


def p_value(x: list[float]) -> dict:
    """One-sided p-value that the mean monthly excess is above zero (Newey-West t, Student's t with n - 1 df)."""
    t = stats.nw_t(x)
    if t is None:
        return {"n": len(x), "t": None, "p": 1.0}
    return {"n": len(x), "t": t, "p": stats.t_sf(t, len(x) - 1), "mean": statistics.fmean(x)}


def discovery(batch: Batch, pvals: dict[str, float]) -> list[str]:
    """Stage 1: the configurations Benjamini-Hochberg keeps at q among the batch's discovery-window p-values. Every
    declared configuration must have a p-value: one left out would quietly shrink the batch."""
    missing = set(batch.configs) - set(pvals)
    if missing:
        raise ValueError(f"no discovery p-value for {sorted(missing)}: every declared configuration counts")
    extra = set(pvals) - set(batch.configs)
    if extra:
        raise ValueError(f"p-values for undeclared configurations {sorted(extra)}")
    ids = list(batch.configs)
    keep = stats.bh_fdr([pvals[i] for i in ids], batch.q)
    return [i for i, k in zip(ids, keep) if k]


def confirmation(batch: Batch, found: list[str], conf: dict[str, dict], robust: dict[str, dict]) -> dict[str, dict]:
    """Stage 2 for each discovered configuration. conf[id] = p_value() on the confirmation window; robust[id] has
    'costs_x2_mean' and 'lag1_mean' (confirmation-window mean monthly excess under each stress)."""
    out = {}
    cut = batch.alpha / max(len(found), 1)
    surv = SURVIVORSHIP_PP.get(batch.data, 0.0) / 100 / 12   # monthly
    for i in found:
        c, r = conf.get(i) or {}, robust.get(i) or {}
        checks = {"confirmed": c.get("p", 1.0) <= cut and (c.get("mean") or 0) > 0,
                  "costs_x2": (r.get("costs_x2_mean") or 0) > 0,
                  "lag1": (r.get("lag1_mean") or 0) > 0}
        if surv:
            checks["survivorship"] = (c.get("mean") or 0) > surv
        out[i] = {"alpha_used": cut, "p": c.get("p"), "t": c.get("t"), "checks": checks, "pass": all(checks.values())}
    return out


def verdict(batch: Batch, disc_series: dict[str, dict], conf_inputs: dict[str, dict] | None = None) -> dict:
    """The whole gate from monthly excess series. disc_series[id] = {'excess': {month: r}, 'costs_x2': {...},
    'lag1': {...}} over the full exploration data; windows are applied here, so a caller cannot pass the wrong slice.
    Returns {batch, discovered, results: {id: ...}, passed: [...]} and never reads the confirmation window of a
    configuration stage 1 did not keep."""
    probs = batch.problems()
    if probs:
        raise ValueError("; ".join(probs))
    disc_p = {i: p_value(window(s["excess"], batch.discovery)) for i, s in disc_series.items()}
    found = discovery(batch, {i: d["p"] for i, d in disc_p.items()})
    conf, robust = {}, {}
    for i in found:
        s = disc_series[i]
        conf[i] = p_value(window(s["excess"], batch.confirmation))
        robust[i] = {"costs_x2_mean": _mean(window(s.get("costs_x2") or {}, batch.confirmation)),
                     "lag1_mean": _mean(window(s.get("lag1") or {}, batch.confirmation))}
    res = confirmation(batch, found, conf, robust)
    results = {i: {"discovery": disc_p[i], "kept": i in found, **(res.get(i) or {"pass": False})} for i in batch.configs}
    return {"batch": batch.id, "gate": "v3", "discovered": found, "results": results,
            "passed": [i for i in batch.configs if results[i]["pass"]]}


def _mean(x: list[float]) -> float | None:
    return statistics.fmean(x) if x else None


# ---------------------------------------------------------------- power, before any data is read
def power(ann_excess: float, ann_te: float, discovery_months: int, confirmation_months: int, k: int = 1,
          q: float = DEFAULT_Q, alpha: float = DEFAULT_ALPHA) -> dict:
    """Chance that a configuration with a true annual excess `ann_excess` (tracking error `ann_te`) passes stages 1
    and 2, when it is the only real one among k (so BH keeps it at p <= q/k: the conservative case)."""
    sr_m = (ann_excess / 12) / (ann_te / math.sqrt(12))
    t1, t2 = sr_m * math.sqrt(discovery_months), sr_m * math.sqrt(confirmation_months)
    z1, z2 = _ND.inv_cdf(1 - q / k), _ND.inv_cdf(1 - alpha)
    p1, p2 = 1 - _ND.cdf(z1 - t1), 1 - _ND.cdf(z2 - t2)
    return {"expected_t_discovery": t1, "expected_t_confirmation": t2, "z_discovery": z1, "z_confirmation": z2,
            "p_discovery": p1, "p_confirmation": p2, "p_pass": p1 * p2,
            "false_pass_per_config": (q / k) * alpha}


def power_line(ann_excess: float, ann_te: float, discovery_months: int, confirmation_months: int, k: int = 1) -> str:
    """One line for the pre-registration, with the verdict RUN (chance of passing a true edge >= 25%) or REDESIGN."""
    p = power(ann_excess, ann_te, discovery_months, confirmation_months, k)
    v = "RUN" if p["p_pass"] >= 0.25 else "REDESIGN (longer data, fewer configs or a stronger signal)"
    return (f"gate v3 power: {ann_excess:.1%}/yr at {ann_te:.0%} TE, {discovery_months}+{confirmation_months} months, "
            f"k={k}: P(pass) {p['p_pass']:.0%} (discovery {p['p_discovery']:.0%}, confirmation "
            f"{p['p_confirmation']:.0%}); a no-edge config passes {p['false_pass_per_config']:.2%}: {v}")
