"""B5 trial run: B5-H1-FCFPS-ACCEL-V2 and B5-S2A-GP-12M-V2, exactly as frozen in docs/edge/B5_PREREGISTRATION.md
(version 2) as amended by addenda 1 and 2.

NOT YET AUTHORISED. Written 2026-10-16 for the owner's review (owner, 14:17Z, item 5); it has never been
executed. It refuses to read any data until every control below passes:

* the run is authorised in `research/edge/status.json` (`b5_trial_run.authorised`, recorded only on the owner's
  explicit word, with the message id);
* the registry validates, N = 100, both trials are registered with v2's hash, addenda 1 and 2 are registered with
  their files' hashes, and this script's input manifest (`docs/edge/B5_RUN_MANIFEST.json`) is registered as
  `B5-V2-RUN-MANIFEST` with its hash;
* every input file and every code file named in the manifest has the recorded sha256;
* neither trial, nor any of their registered robustness runs, has a result, and the one-run lock
  (`research/edge/b5_run.lock`) does not exist. The lock is created before any data is read and never removed by
  code: a failed or interrupted run can only be repeated by a recorded owner decision.

Both trials run in this one invocation, each exactly once, with every gate from one fixed list (`GATES`); there is
no flag to skip a gate, choose a trial or change a setting. All results are computed first; then both primary
results are appended to the registry; only then is the shared DSR computed for each, so the DSR always sees both.

Exact command (only after authorisation):  cd research && python3 edge_b5_run.py
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import edge_b5 as b5
import edge_b5_stats as st
import edge_backtest as bt
import edge_registry
import edge_rules

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
MANIFEST = REPO / "docs" / "edge" / "B5_RUN_MANIFEST.json"
LOCK = ROOT / "edge" / "b5_run.lock"
OUT = REPO / "equity" / "reports" / "research" / "edge"
CUT = pd.Timestamp("2022-12-31")

TRIALS = {"H1": "B5-H1-FCFPS-ACCEL-V2", "S2A": "B5-S2A-GP-12M-V2"}
SPECS = {"B5-H1-FCFPS-ACCEL-V2": "docs/edge/B5_PREREGISTRATION.md", "B5-S2A-GP-12M-V2": "docs/edge/B5_PREREGISTRATION.md",
         "B5-V2-ADDENDUM-1": "docs/edge/B5_PREREGISTRATION_ADDENDUM_1.md",
         "B5-V2-ADDENDUM-2": "docs/edge/B5_PREREGISTRATION_ADDENDUM_2.md",
         "B5-V2-RUN-MANIFEST": "docs/edge/B5_RUN_MANIFEST.json"}
ROB_IDS = {"P4": "ROB-2XCOST", "P6": "ROB-MISS100", "P7": "ROB-NEXTMONTH", "P8": "ROB-DATAERR", "P9": "ROB-PITQ"}
GATES = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11")
VARIANT_GATES = ("P4", "P5", "P6", "P7", "P8", "P9", "P11")  # each needs its own run
N_EXPECTED = 100
SCHEDULE = {"H1": (b5.H1_REBALANCE, b5.H1_TRANCHES), "S2A": (b5.S2A_REBALANCE, b5.S2A_TRANCHES)}


KNOWN_INPUT_LIMITATIONS = """**Known input-rule limitations (ADDENDUM_2 §1, §3; stated in every B5 report):**

- Revenue tests: General Dynamics 2017-18 loses 18 fallback rows to a mis-tagged alternate concept (false
  positive); Abbott 2015-01 (about 10.6% basis mixing) is not caught (missed case); EQT and ConocoPhillips rows are
  flagged for derivative-inclusive `Revenues` (a basis difference, conservative).
- Identity rule C: rows between 25x and 100x market cap to assets stay in, where errors and genuine values overlap
  (Curis 97x, BeOne 97x, Larimar 85x after a CIK reuse); Scinai is unscorable for lack of total assets.
- T2 uses only filings known at each decision date; restatements filed later are not used (diagnostic only).
- TTM check 4 (independent source) is open: no result carries the E2 label.
"""


def rob_id(trial: str, gate: str) -> str:
    return f"B5-{trial}-V2-{ROB_IDS[gate]}"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------- controls (no data is read before `preflight` returns) ----------

def preflight(registry: Path = edge_registry.PATH, status: Path = b5.STATUS, manifest: Path = MANIFEST,
              repo: Path = REPO, lock: Path = LOCK) -> dict:
    """Every control, in order; raises at the first failure. Returns what the report records."""
    try:
        auth = json.loads(status.read_text())["b5_trial_run"]
    except (OSError, KeyError, TypeError, ValueError):
        auth = {}
    if auth.get("authorised") is not True or not str(auth.get("owner_message", "")).startswith("cmsg_"):
        raise PermissionError("trial run not authorised by the owner (status.json b5_trial_run)")
    problems = edge_registry.validate(registry)
    if problems:
        raise ValueError(f"registry invalid: {problems}")
    ev = edge_registry.load(registry)
    if edge_registry.n_trials(ev) != N_EXPECTED:
        raise ValueError(f"N is {edge_registry.n_trials(ev)}, expected {N_EXPECTED}")
    reg = edge_registry.registered(ev)
    for rid, path in SPECS.items():
        if rid not in reg:
            raise KeyError(f"{rid} is not registered")
        if reg[rid].get("spec_sha256") != sha(repo / path):
            raise ValueError(f"{rid}: {path} does not match its registered sha256")
    for tid in TRIALS.values():
        if reg[tid].get("counts_for_dsr") is not True:
            raise ValueError(f"{tid} must count for the DSR")
    m = json.loads(manifest.read_text())
    for group in ("inputs", "code"):
        for path, h in m[group].items():
            p = Path(path) if Path(path).is_absolute() else repo / path
            if sha(p) != h:
                raise ValueError(f"{group} file {path} does not match the manifest")
    ids = list(TRIALS.values()) + [rob_id(t, g) for t in TRIALS for g in ROB_IDS]
    done = [e["id"] for e in ev if e.get("event") == "result" and e.get("id") in ids]
    if done:
        raise ValueError(f"already run (results exist): {done}")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f"one-run lock {lock} exists: this run was already started") from None
    os.write(fd, json.dumps({"owner_message": auth["owner_message"], "manifest": sha(manifest)}).encode())
    os.close(fd)
    return {"owner_message": auth["owner_message"], "manifest_sha256": sha(manifest), "n_trials": N_EXPECTED,
            "check4_complete": b5.check4_complete(status)}


# ---------- inputs (point in time; everything cut at 2022-12-31 on read) ----------

def read_factors(path: Path) -> pd.DataFrame:
    """Ken French CSV, first block, decimal returns (data_sources.french's parser on the frozen, cut file)."""
    lines = path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip().startswith(","))
    cols = [c.strip() for c in lines[start].split(",")][1:]
    rows = []
    for l in lines[start + 1:]:
        parts = [p.strip() for p in l.split(",")]
        if len(parts[0]) != 6 or not parts[0].isdigit():
            break
        rows.append(parts)
    df = pd.DataFrame([r[1:] for r in rows], index=[r[0] for r in rows], columns=cols).astype(float) / 100
    df.index = pd.to_datetime(df.index, format="%Y%m") + pd.offsets.MonthEnd(0)
    if df.index.max() > CUT:
        raise ValueError(f"{path} runs past 2022-12")
    return df


def load_inputs() -> dict:  # pragma: no cover - reads the research data; exercised only by an authorised run
    import edge_b5_inputs as bi
    import edge_split
    import stage2
    import xsection
    sys.path.insert(0, str(REPO / "equity"))
    from equity import panel as epanel

    df = edge_split.with_quality(edge_split.cut_exploration(xsection.load()))
    df = st.with_pit_quality(df)
    comp = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", usecols=["cik", "sic"])
    df = df.merge(comp, on="cik", how="left")
    df["group"] = df["sic"].map(stage2.sic_group)
    df["financial"] = df["group"] == "finance"
    ciks = set(df.loc[df["band"] == "large", "cik"])
    df = df[df["cik"].isin(ciks) & (df["month"] >= "2012-01-31")].reset_index(drop=True)
    metrics = {"revenue", "ocf", "capex", "gross_profit", "cost_of_revenue", "total_assets"}
    fx_rows: dict = {}
    for r in epanel.read(xsection.DATA / "sec_facts_panel.csv.gz", ciks):
        if r["metric"] in metrics and r["unit"] == "USD" and r["filed"] <= str(CUT.date()):
            fx_rows.setdefault(r["cik"], {}).setdefault(r["metric"], []).append(r)
    recs = [bi.company_month(fx_rows.get(c, {}), m) for c, m in zip(df["cik"], df["month"].dt.strftime("%Y-%m-%d"))]
    keep = ["ocf", "capex", "fcf_end", "gross_profit", "gp_end", "gp_restated", "revenue", "rev_end", "rev_conflict",
            "cost_of_revenue", "cor_end", "cor_restated", "ocf_restated", "capex_restated", "foreign_form"]
    df = pd.concat([df, pd.DataFrame(recs, index=df.index)[keep]], axis=1)
    edge_dir = Path(__import__("edge_exec_prices").OUT_DIR)
    ex = pd.read_csv(edge_dir / "exec_prices_to_2022.csv.gz")
    ex = ex[pd.to_datetime(ex["month"]) <= CUT]
    f = pd.read_csv(edge_dir / "gbpusd_daily_to_2022.csv.gz", parse_dates=["date"])
    fxs = edge_split.cut_series(f.set_index("date")["usd_per_gbp"])
    b = pd.read_csv(edge_dir / "benchmarks_daily_gbp_to_2022.csv.gz", parse_dates=["date"])
    bench = edge_split.cut_series(b.set_index("date")[["VWRP", "VWRL"]])
    factors = read_factors(ROOT / "edge" / "factors" / "F-F_Research_Data_5_Factors_2x3_to_2022.csv").join(
        read_factors(ROOT / "edge" / "factors" / "F-F_Momentum_Factor_to_2022.csv"), how="inner")
    factors.columns = [c.strip() for c in factors.columns]
    moves = pd.read_csv(OUT / "exec_prices_audit_moves.csv")
    return {"panel": df, "exec": ex, "fx": fxs, "bench": bench, "factors": factors,
            "data_errors": st.data_error_months(moves)}


# ---------- scores ----------

def s2a_scores(df: pd.DataFrame, quality: str = "quality_ok") -> pd.Series:
    """S2a: gross profitability ranked (percentile) within SIC group among the month's eligible non-financial
    names (eligible as in edge_backtest.eligible, with the given quality column)."""
    gpa = b5.s2a_profitability(df)
    ok = (df[quality].astype(bool) & (df["band"] == "large") & (df["close_raw"] >= 1.0) & gpa.notna()
          & ~df["financial"].astype(bool))
    return gpa.where(ok).groupby([df["month"], df["group"]]).rank(pct=True)


def score_panels(df: pd.DataFrame) -> dict:
    """Engine panels for each trial: the primary, and the P9 panel (point-in-time quality; S2a re-ranked)."""
    cols = ["cik", "month", "band", "quality_ok", "group", "close_raw"]
    h1 = df[cols].assign(score=b5.h1_score(df))
    s2 = df[cols].assign(score=s2a_scores(df))
    return {"H1": {"primary": h1, "P9": h1.assign(quality_ok=df["quality_ok_pit"])},
            "S2A": {"primary": s2, "P9": s2.assign(quality_ok=df["quality_ok_pit"],
                                                   score=s2a_scores(df, "quality_ok_pit"))}}


# ---------- one trial: primary, every variant, every statistic ----------

def config(rebalance: int) -> bt.Config:
    return bt.Config(n=b5.N_NAMES, weighting="equal", rebalance_every=rebalance, buffer=b5.BUFFER,
                     sector_cap=b5.SECTOR_CAP, bands=("large",), min_price=1.0, cost_mult=1.0,
                     missing_return=edge_rules.DEFAULT_MISSING_RETURN, convention=edge_rules.DEFAULT_CONVENTION,
                     selection="top_n")


def first_exec_date(ex: pd.DataFrame) -> pd.Timestamp:
    d = ex.loc[pd.to_datetime(ex["month"]) == pd.Timestamp(b5.EVAL_FIRST_DECISION), "exec_date"]
    return min(pd.Timestamp(x) for x in d.unique())


def run_combined(run_id: str, registry: Path, panel: pd.DataFrame, data: dict, cfg: bt.Config, starts) -> dict:
    res = [bt.run_trial(run_id, registry, panel, data["exec"], data["fx"], cfg, start=s, end=b5.EVAL_LAST_DECISION)
           for s in starts]
    first = first_exec_date(data["exec"])
    return {"results": res, "nav_gbp": b5.combine_tranches([r.nav_gbp for r in res], first),
            "nav_usd": b5.combine_tranches([r.nav_usd for r in res], first)}


def monthly_excess(nav_gbp: pd.Series, bench: pd.DataFrame) -> pd.Series:
    r = nav_gbp.pct_change().dropna()
    b = bt.benchmark_returns(bench, nav_gbp.index)["return"]
    j = pd.concat([r.rename("s"), b.rename("b")], axis=1).dropna()
    return j["s"] - j["b"]


def usd_by_start_month(nav_usd: pd.Series) -> pd.Series:
    """ADDENDUM_2 §4: each period's USD return is labelled with the calendar month of its start (execution) date."""
    r = nav_usd.pct_change().dropna()
    r.index = nav_usd.index[:-1]
    return r


def nonoverlap_t(excess: pd.Series) -> float:
    """ADDENDUM_2 §4: the monthly excess series in date order, observations 1, 13, 25, ...; simple t, ddof 1."""
    x = pd.Series(excess, dtype=float).dropna().sort_index().iloc[::12]
    if len(x) < 3 or x.std() == 0:
        return float("nan")
    return float(x.mean() / (x.std() / math.sqrt(len(x))))


def run_one(trial: str, panels: dict, data: dict, registry: Path) -> dict:
    """Every run and statistic for one trial. Appends nothing."""
    tid = TRIALS[trial]
    k, starts = SCHEDULE[trial]
    cfg = config(k)
    prim = run_combined(tid, registry, panels[trial]["primary"], data, cfg, starts)
    m = bt.metrics(prim["nav_gbp"], data["bench"])
    excess = monthly_excess(prim["nav_gbp"], data["bench"])
    variants, var_metrics = {}, {}
    for gate, (vcfg, transform) in st.robustness_variants(cfg, data["data_errors"]).items():
        panel = panels[trial]["P9"] if gate == "P9" else transform(panels[trial]["primary"])
        run_id = tid if gate == "P5" else rob_id(trial, gate)
        v = run_combined(run_id, registry, panel, data, vcfg, starts)
        if gate == "P5":  # the primary's monthly return minus the universe's
            a, u = prim["nav_gbp"].pct_change().dropna(), v["nav_gbp"].pct_change().dropna()
            variants[gate] = (a - u).dropna()
        else:
            variants[gate] = monthly_excess(v["nav_gbp"], data["bench"])
            var_metrics[gate] = bt.metrics(v["nav_gbp"], data["bench"])
    top = st.largest_contributor([r.contrib for r in prim["results"]])
    loo = run_combined(tid, registry, st.without(panels[trial]["primary"], top), data, cfg, starts)
    variants["P11"] = monthly_excess(loo["nav_gbp"], data["bench"])
    missing = set(VARIANT_GATES) - set(variants)
    if missing:
        raise RuntimeError(f"gate inputs missing: {sorted(missing)}")
    alpha = st.factor_alpha(usd_by_start_month(prim["nav_usd"]), data["factors"], b5.NW_LAGS[trial])
    return {"trial": trial, "id": tid, "metrics": m, "excess": excess, "variants": variants,
            "variant_metrics": var_metrics, "alpha": alpha, "top_contributor": top,
            "t_nw": b5.newey_west_t(excess, b5.NW_LAGS[trial]),
            "t_nonoverlap": nonoverlap_t(excess) if trial == "S2A" else None}


def finish(runs: dict, registry: Path, status: Path, evidence: str) -> dict:
    """Append both primary results (and the robustness results), THEN compute the shared DSR and the verdicts."""
    if set(runs) != set(TRIALS):
        raise RuntimeError("both trials must be computed before anything is recorded")
    for trial, r in runs.items():
        bt.record(r["id"], r["metrics"], registry, evidence)
    for trial, r in runs.items():
        for gate in ROB_IDS:
            bt.record(rob_id(trial, gate), r["variant_metrics"][gate], registry, evidence)
    out = {}
    for trial, r in runs.items():
        d = bt.dsr(r["metrics"], registry)
        if d["n_trials"] != N_EXPECTED or d["n_comparable"] < 2:
            raise RuntimeError(f"shared DSR must see N={N_EXPECTED} and both results: {d}")
        vi = st.verdict_inputs(r["excess"], r["variants"], r["t_nonoverlap"], r["t_nw"], d["dsr"], r["alpha"], trial)
        v = b5.verdict(vi, status)
        if set(v["checks"]) != set(GATES):
            raise RuntimeError("a gate is missing from the verdict")
        out[trial] = {"dsr": d, "verdict_inputs": vi, "verdict": v}
    return out


def report(pre: dict, runs: dict, final: dict) -> str:
    L = ["# B5 exploratory trials: H1 and S2a", "",
         "**Exploratory evidence only (2015-2022, survivorship-biased free data). A passing result is not proof of a "
         "deployable edge, authorises no confirmation test, holdout access or demo allocation, and changes nothing "
         "in any account.**", "",
         f"Authorised by owner message {pre['owner_message']}; manifest sha256 {pre['manifest_sha256']}; "
         f"N = {pre['n_trials']}; TTM check 4 complete: {pre['check4_complete']}.", "", KNOWN_INPUT_LIMITATIONS, ""]
    for trial, r in runs.items():
        f = final[trial]
        L += [f"## {r['id']}", "", f"Verdict: **{f['verdict']['label']}**", "",
              "| Gate | Pass |", "|---|---|"] + [f"| {g} | {f['verdict']['checks'][g]} |" for g in GATES]
        L += ["", "| Statistic | Value |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in {**r["metrics"], "t_nw": r["t_nw"], "t_nonoverlap": r["t_nonoverlap"],
                                             "alpha": r["alpha"], "dsr": f["dsr"], "top_contributor": r["top_contributor"],
                                             **{f"net excess {g}": st.net_excess(x) for g, x in r["variants"].items()},
                                             "thirds": st.thirds(r["excess"])}.items()]
        L.append("")
    return bt.report("B5 exploratory trials", {}, "\n".join(L))


def main(registry: Path = edge_registry.PATH, status: Path = b5.STATUS) -> int:  # pragma: no cover
    pre = preflight(registry, status)
    data = load_inputs()
    panels = score_panels(data["panel"])
    runs = {t: run_one(t, panels, data, registry) for t in TRIALS}
    evidence = "equity/reports/research/edge/b5_trials.md"
    final = finish(runs, registry, status, evidence)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b5_trials.md").write_text(report(pre, runs, final))
    print(f"written {evidence}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
