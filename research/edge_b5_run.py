"""B5 trial run: B5-H1-FCFPS-ACCEL-V3 and B5-S2A-GP-12M-V3, version 3 = docs/edge/B5_PREREGISTRATION.md
(version 2) as amended by addenda 1, 2 and 3 (ADDENDUM_3 creates version 3; owner decisions D20, D21).

NOT YET AUTHORISED. Written 2026-10-16 for the owner's review (owner, 14:17Z, item 5); it has never been
executed. It refuses to read any data until every control below passes:

* the run is authorised in `research/edge/status.json` (`b5_trial_run.authorised`, recorded only on the owner's
  explicit word, with the message id);
* the registry validates, N = 102, the version-2 trials are still registered with v2's hash, both version-3 trials
  and addendum 3 are registered with addendum 3's hash, addenda 1 and 2 with theirs, every robustness id is
  registered and uncounted, and this script's input manifest (`docs/edge/B5_RUN_MANIFEST_3.json`) is registered as
  `B5-V3-RUN-MANIFEST-3` with its hash (`B5-V3-RUN-MANIFEST` and `B5-V3-RUN-MANIFEST-2`, registered 2026-10-19 for
  the code before run fixes 1 and 2, are kept unchanged and never used; MANIFEST-3 is proposed, not registered);
* every input file and every code file named in the manifest has the recorded sha256;
* neither trial, nor any of their registered robustness runs, nor any retired B5 id, has a result, and the one-run lock
  (`research/edge/b5_run.lock`) does not exist. The lock is created before any data is read and never removed by
  code: a failed or interrupted run can only be repeated by a recorded owner decision.

The same authorisation and lock are re-checked where data and results are touched, so calling a function directly
does not skip them (owner review 2026-10-19, item 4; hardened after run 1): `load_inputs`, `run_one` and `finish`
call `edge_registry.b5_run_open(verify_files=True)`,
and `edge_registry.require`, which every `bt.run_trial` and `bt.record` calls, refuses either trial id or any of
their robustness ids unless the run is open. `b5_run_open` reads the real status.json, lock, registry and manifest
only, and opens only for an unspent owner authorisation that names the registered manifest by id and sha256, with a
lock naming the same message and manifest (run 1's D26 authorisation is spent: `edge_registry.B5_SPENT_AUTHORISATIONS`).

Both trials run in this one invocation, each exactly once, with every gate from one fixed list (`GATES`); there is
no flag to skip a gate, choose a trial or change a setting. All results are computed first. `finish` then stages all
twelve results in a copy of the registry, computes the shared DSR from that copy (so it always sees both primary
results), writes the report, and only then records the results in one atomic rename (owner review 2026-10-19,
findings A and B; `docs/edge/B5_RUN_FIX_1.md`).

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
MANIFEST = edge_registry.B5_MANIFEST  # docs/edge/B5_RUN_MANIFEST_3.json; earlier manifests stay as registered
LOCK = edge_registry.B5_LOCK  # research/edge/b5_run.lock
OUT = REPO / "equity" / "reports" / "research" / "edge"
CUT = pd.Timestamp("2022-12-31")

TRIALS = {"H1": "B5-H1-FCFPS-ACCEL-V3", "S2A": "B5-S2A-GP-12M-V3"}
MANIFEST_ID = edge_registry.B5_MANIFEST_ID  # B5-V3-RUN-MANIFEST-3 (B5_RUN_FIX_2 and execution hardening)
A3 = "docs/edge/B5_PREREGISTRATION_ADDENDUM_3.md"
SPECS = {"B5-H1-FCFPS-ACCEL-V2": "docs/edge/B5_PREREGISTRATION.md", "B5-S2A-GP-12M-V2": "docs/edge/B5_PREREGISTRATION.md",
         "B5-V2-ADDENDUM-1": "docs/edge/B5_PREREGISTRATION_ADDENDUM_1.md",
         "B5-V2-ADDENDUM-2": "docs/edge/B5_PREREGISTRATION_ADDENDUM_2.md",
         "B5-V3-ADDENDUM-3": A3, "B5-H1-FCFPS-ACCEL-V3": A3, "B5-S2A-GP-12M-V3": A3,
         MANIFEST_ID: "docs/edge/B5_RUN_MANIFEST_3.json"}
# ADDENDUM_3 §3: P9 is the full-window reverse veto (ROB-WINQ); every version-1 and version-2 id is retired.
ROB_IDS = {"P4": "ROB-2XCOST", "P6": "ROB-MISS100", "P7": "ROB-NEXTMONTH", "P8": "ROB-DATAERR", "P9": "ROB-WINQ"}
GATES = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11")
VARIANT_GATES = ("P4", "P5", "P6", "P7", "P8", "P9", "P11")  # each needs its own run
N_EXPECTED = 102  # ADDENDUM_3 §5 (D21): 100 + the two counted version-3 trials
SCHEDULE = {"H1": (b5.H1_REBALANCE, b5.H1_TRANCHES), "S2A": (b5.S2A_REBALANCE, b5.S2A_TRANCHES)}


KNOWN_INPUT_LIMITATIONS = """**Known input-rule limitations (ADDENDUM_2 §1, §3; stated in every B5 report):**

- Revenue tests: General Dynamics 2017-18 loses 18 fallback rows to a mis-tagged alternate concept (false
  positive); Abbott 2015-01 (about 10.6% basis mixing) is not caught (missed case); EQT and ConocoPhillips rows are
  flagged for derivative-inclusive `Revenues` (a basis difference, conservative).
- Identity rule C: rows between 25x and 100x market cap to assets stay in, where errors and genuine values overlap
  (Curis 97x, BeOne 97x, Larimar 85x after a CIK reuse); Scinai is unscorable for lack of total assets.
- T2 uses only filings known at each decision date; restatements filed later are not used (diagnostic only).
- TTM check 4 (independent source) is open: no result carries the E2 label.
- Quality rule (ADDENDUM_3): eligibility uses the point-in-time share-outlier rule. Against the Phase A full-window
  rule it wrongly excludes about 108 universe company-months of 11 genuine companies after mergers or spin-offs
  (76 rows, 9 companies after rule C; e.g. MPLX, Fox, Linde, Viatris) and admits AVITA Medical's 9 inflated rows
  (2019-11 to 2020-07). Both rules wrongly exclude CoStar and The Trade Desk after their 2021 10-for-1 splits.
- P8's 12 data-error company-months were chosen by auditing the whole 2015-2022 price path (later information; a
  veto only). SIC codes (financial exclusion, S2a groups, sector cap) are a 2026 snapshot, not point in time.
"""


P7_WINDOW_DISCLOSURE = """**P7 evaluation window (owner decision D29, option A; `docs/edge/B5_EXECUTION_HARDENING.md` §3):**

- P7 (next-month-close execution) has **94 valuation dates and 93 monthly returns** (2015-02-28 to 2022-11-30). The
  primary and the next-day-close variants (P4, P5, P6, P8, P9, P11) have **95 valuation dates and 94 monthly
  returns** (2015-02-02 to 2022-12-01).
- Under P7 the 2015-01 decision first trades at the 2015-02 month-end, and the 2022-11 decision cannot trade because
  the registered execution file (decisions to 2022-11) holds no 2022-12 month-end close.
- P7 is assessed against the benchmark on its own dates. Its result is **not directly comparable** with variants
  measured over a different window. The registered data, definition and gate are unchanged.
"""


def window_counts(runs: dict) -> list[str]:
    """Report lines with each trial's own counts of monthly returns: the primary's excess series and P7's."""
    out = []
    for r in runs.values():
        n_p, n_7 = len(r["excess"].dropna()), len(r["variants"]["P7"].dropna())
        out.append(f"- {r['id']}: primary {n_p} monthly returns; P7 {n_7} monthly returns.")
    return out


def rob_id(trial: str, gate: str) -> str:
    return f"B5-{trial}-V3-{ROB_IDS[gate]}"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------- controls (no data is read before `preflight` returns) ----------

def preflight(registry: Path = edge_registry.PATH, status: Path = b5.STATUS, manifest: Path = MANIFEST,
              repo: Path = REPO, lock: Path = LOCK) -> dict:
    """Every control, in order; raises at the first failure. Returns what the report records."""
    auth = edge_registry.b5_authorisation(status)  # unspent, and naming this manifest by id and sha256
    if auth["manifest_sha256"] != sha(manifest):
        raise PermissionError("the authorisation names a different manifest sha256 than the run's manifest file")
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
    for rid in (rob_id(t, g) for t in TRIALS for g in ROB_IDS):
        if rid not in reg:
            raise KeyError(f"{rid} is not registered")
        if reg[rid].get("counts_for_dsr") is not False:
            raise ValueError(f"{rid} is a robustness run and must not count for the DSR")
    m = json.loads(manifest.read_text())
    for group in ("inputs", "code"):
        for path, h in m[group].items():
            p = Path(path) if Path(path).is_absolute() else repo / path
            if sha(p) != h:
                raise ValueError(f"{group} file {path} does not match the manifest")
    ids = list(TRIALS.values()) + [rob_id(t, g) for t in TRIALS for g in ROB_IDS] + sorted(edge_registry.B5_RETIRED_IDS)
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


FUND_COLS = ["ocf", "capex", "fcf_end", "gross_profit", "gp_end", "gp_restated", "revenue", "rev_end", "rev_conflict",
             "cost_of_revenue", "cor_end", "cor_restated", "ocf_restated", "capex_restated", "foreign_form"]


def attach_fundamentals(df: pd.DataFrame, fx_rows: dict) -> pd.DataFrame:
    """The SEC inputs and flags of every company-month, each as known at that row's own month-end:
    `edge_b5_inputs.company_month(rows, month)` with no `align` and no `retro_as_of`, so only facts filed on or
    before the month-end are read and the retrospective T2 diagnostic is never computed here."""
    import edge_b5_inputs as bi
    recs = [bi.company_month(fx_rows.get(c, {}), m) for c, m in zip(df["cik"], df["month"].dt.strftime("%Y-%m-%d"))]
    return pd.concat([df, pd.DataFrame(recs, index=df.index)[FUND_COLS]], axis=1)


def load_inputs() -> dict:  # pragma: no cover - reads the research data; exercised only by an authorised run
    edge_registry.b5_run_open(verify_files=True)
    import edge_split
    import stage2
    import xsection
    sys.path.insert(0, str(REPO / "equity"))
    from equity import panel as epanel

    df = st.with_quality_columns(edge_split.cut_exploration(xsection.load()))
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
    df = attach_fundamentals(df, fx_rows)
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

def s2a_scores(df: pd.DataFrame, quality: str) -> pd.Series:
    """S2a: gross profitability ranked (percentile) within SIC group among the month's eligible non-financial
    names (eligible as in edge_backtest.eligible, with the given quality column)."""
    gpa = b5.s2a_profitability(df)
    ok = (df[quality].astype(bool) & (df["band"] == "large") & (df["close_raw"] >= 1.0) & gpa.notna()
          & ~df["financial"].astype(bool))
    return gpa.where(ok).groupby([df["month"], df["group"]]).rank(pct=True)


def engine_panel(df: pd.DataFrame, quality: str, score: pd.Series) -> pd.DataFrame:
    """The engine's panel with `quality_ok` set from the named rule."""
    return df[["cik", "month", "band", "group", "close_raw"]].assign(quality_ok=df[quality].astype(bool), score=score)


def score_panels(df: pd.DataFrame) -> dict:
    """Engine panels for each trial (ADDENDUM_3): the primary uses the point-in-time quality rule for eligibility and
    for S2a's rank population; the P9 panel (reverse veto) uses the full-window rule, with S2a re-ranked in that
    population. The P5 universe and P4, P6-P8, P11 are built from the primary panel. A frame with a bare
    `quality_ok` column is refused, so the rule is never chosen implicitly."""
    if "quality_ok" in df:
        raise ValueError("ambiguous quality column: expected quality_ok_pit and quality_ok_window only")
    h1 = b5.h1_score(df)
    p, v = b5.PRIMARY_QUALITY, b5.VETO_QUALITY
    return {"H1": {"primary": engine_panel(df, p, h1), "P9": engine_panel(df, v, h1)},
            "S2A": {"primary": engine_panel(df, p, s2a_scores(df, p)), "P9": engine_panel(df, v, s2a_scores(df, v))}}


# ---------- one trial: primary, every variant, every statistic ----------

def config(rebalance: int) -> bt.Config:
    return bt.Config(n=b5.N_NAMES, weighting="equal", rebalance_every=rebalance, buffer=b5.BUFFER,
                     sector_cap=b5.SECTOR_CAP, bands=("large",), min_price=1.0, cost_mult=1.0,
                     missing_return=edge_rules.DEFAULT_MISSING_RETURN, convention=edge_rules.DEFAULT_CONVENTION,
                     selection="top_n")


def first_exec_date(ex: pd.DataFrame, convention: str = edge_rules.DEFAULT_CONVENTION) -> pd.Timestamp:
    """The evaluation start: the trade date of the 2015-01-31 decision under the run's own execution convention
    (B5_PREREGISTRATION §1: "the execution after the 2015-01-31 decision"), taken from the same
    `edge_backtest.price_table` the backtest trades on. Run 1 used the next-day-close date for every run, so P7
    (next-month close, whose first trade is the 2015-02 month-end) had no NAV there and stopped the run
    (B5_RUN_FIX_2)."""
    dates = bt.price_table(ex, convention)[1]
    first = pd.Timestamp(b5.EVAL_FIRST_DECISION)
    if first not in dates.index:
        raise ValueError(f"no {convention} trade date for the {b5.EVAL_FIRST_DECISION} decision")
    return pd.Timestamp(dates[first])


def run_combined(run_id: str, registry: Path, panel: pd.DataFrame, data: dict, cfg: bt.Config, starts) -> dict:
    res = [bt.run_trial(run_id, registry, panel, data["exec"], data["fx"], cfg, start=s, end=b5.EVAL_LAST_DECISION)
           for s in starts]
    first = first_exec_date(data["exec"], cfg.convention)
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
    edge_registry.b5_run_open(verify_files=True)
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


def finish(runs: dict, registry: Path, status: Path, evidence: str, report_path: Path, pre: dict) -> dict:
    """Record every result and write the report as one step (owner review 2026-10-19, findings A and B):

    1. refuse unless both trials and every gate input and robustness metric are present, and each of the twelve ids
       is open and has no result (`edge_registry.require`);
    2. stage the twelve result events in a copy of the registry (`edge_registry.stage`); the registry is untouched;
    3. compute each trial's shared DSR from the staged copy (both primary results, N = 102) and its verdict;
    4. write the report to `<report>.pending`;
    5. commit: the staged copy replaces the registry in one rename (`edge_registry.commit`);
    6. rename the pending report to `report_path`.

    A failure in steps 1-5 leaves the registry byte-identical and removes the staged copy and the pending report (the
    one-run lock stays, so a rerun still needs a recorded owner decision). Only step 6 follows the commit; if it fails,
    the results are recorded and the full report is in the pending file."""
    edge_registry.b5_run_open(verify_files=True)
    if set(runs) != set(TRIALS):
        raise RuntimeError("both trials must be computed before anything is recorded")
    for trial, r in runs.items():
        if r["id"] != TRIALS[trial] or set(r["variants"]) != set(VARIANT_GATES) \
                or set(r["variant_metrics"]) != set(ROB_IDS):
            raise RuntimeError(f"{trial}: incomplete robustness runs; nothing recorded")
    events = [bt.result_event(TRIALS[t], runs[t]["metrics"], evidence) for t in TRIALS]
    events += [bt.result_event(rob_id(t, g), runs[t]["variant_metrics"][g], evidence) for t in TRIALS for g in ROB_IDS]
    for e in events:
        edge_registry.require(e["id"], registry)
    pending = report_path.with_name(report_path.name + ".pending")
    staged, old = edge_registry.stage(events, registry)
    committed = False
    try:
        recorded = {e["id"] for e in edge_registry.load(staged) if e.get("event") == "result"}
        if not set(TRIALS.values()) <= recorded:
            raise RuntimeError("both primary results must be staged before the shared DSR")
        out = {}
        for trial in TRIALS:
            r = runs[trial]
            d = bt.dsr(r["metrics"], staged)
            if d["n_trials"] != N_EXPECTED or d["n_comparable"] < 2:
                raise RuntimeError(f"shared DSR must see N={N_EXPECTED} and both results: {d}")
            vi = st.verdict_inputs(r["excess"], r["variants"], r["t_nonoverlap"], r["t_nw"], d["dsr"], r["alpha"],
                                   trial)
            v = b5.verdict(vi, status)
            if set(v["checks"]) != set(GATES):
                raise RuntimeError("a gate is missing from the verdict")
            out[trial] = {"dsr": d, "verdict_inputs": vi, "verdict": v}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(report(pre, runs, out))
        edge_registry.commit(staged, old, registry)
        committed = True
    finally:
        if not committed:
            for f in (staged, pending):
                if f.exists():
                    f.unlink()
    os.replace(pending, report_path)
    return out


def report(pre: dict, runs: dict, final: dict) -> str:
    L = ["# B5 exploratory trials: H1 and S2a", "",
         "**Exploratory evidence only (2015-2022, survivorship-biased free data). A passing result is not proof of a "
         "deployable edge, authorises no confirmation test, holdout access or demo allocation, and changes nothing "
         "in any account.**", "",
         f"Authorised by owner message {pre['owner_message']}; manifest sha256 {pre['manifest_sha256']}; "
         f"N = {pre['n_trials']}; TTM check 4 complete: {pre['check4_complete']}.", "", KNOWN_INPUT_LIMITATIONS, "",
         P7_WINDOW_DISCLOSURE] + window_counts(runs) + [""]
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


def main() -> int:  # pragma: no cover
    """The only entry point: real registry, status, manifest and lock, no parameters."""
    registry, status = edge_registry.PATH, b5.STATUS
    pre = preflight()
    data = load_inputs()
    panels = score_panels(data["panel"])
    runs = {t: run_one(t, panels, data, registry) for t in TRIALS}
    evidence = "equity/reports/research/edge/b5_trials.md"
    finish(runs, registry, status, evidence, REPO / evidence, pre)
    print(f"written {evidence}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
