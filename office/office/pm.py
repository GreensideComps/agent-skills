"""Portfolio manager pm-1.0 (owner decision D-T16; rules fixed first in docs/office/PM_SPEC.md).

Proposal only. This module imports no broker code, places no order and changes no holding: `propose` returns a
record and nothing else. Until a strategy passes the research gates and the owner lists it in
`office/config/pm_eligible.json`, every proposal is 100% VWRP, the documented no-trade outcome.

Every limit is checked here in code, and each check carries its inputs and arithmetic so a reader can redo it.
A proposal that breaks a limit, or that a limit cannot be verified for, is rejected whole (never scaled down) and
the 100% VWRP default stands.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from . import sectors

VERSION = "pm-1.0"
CORE = "VWRP"
MAX_OUTSIDE_CORE = 0.20
MAX_PER_COMPANY = 0.05
MAX_SECTOR_ACTIVE = 0.10
REVIEW_RELATIVE = -0.15
LOOKTHROUGH_MAX_AGE_DAYS = 95
EPS = 1e-9


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def trial_verdicts(events: list[dict]) -> dict[str, dict]:
    """Per trial id: its registered kind and its latest gate verdict (None when it has no verdict)."""
    out: dict[str, dict] = {}
    for e in events:
        tid = e.get("id")
        if not tid:
            continue
        rec = out.setdefault(tid, {"kind": None, "verdict": None})
        if e.get("event") == "register":
            rec["kind"] = e.get("kind")
        elif e.get("event") == "result" and e.get("verdict") is not None:
            rec["verdict"] = e["verdict"]
    return out


def eligible(cfg: dict, verdicts: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Split the configured strategies into eligible ones and refusals, each refusal with its reason (§1)."""
    ok, refused = [], []
    for s in cfg.get("strategies", []):
        sid = s.get("id", "?")
        why = None
        if not str(s.get("owner_decision", "")).startswith("cmsg_"):
            why = "no owner decision id (cmsg_...)"
        elif not s.get("trials"):
            why = "cites no trial"
        else:
            for t in s["trials"]:
                v = verdicts.get(t)
                if v is None:
                    why = f"trial {t} is not in the registry"
                elif v["kind"] != "trial":
                    why = f"{t} is registered as {v['kind']}, not a trial"
                elif v["verdict"] != "pass":
                    why = f"trial {t} verdict is {v['verdict']}, not pass"
                if why:
                    break
        (refused if why else ok).append({"id": sid, "reason": why} if why else s)
    return ok, refused


def lookthrough(cfg: dict | None, today: dt.date) -> tuple[dict, list[str]]:
    """VWRP sector and company weights mapped onto the 11 sectors, and the flags that apply to them (§3)."""
    flags = []
    if not cfg or not cfg.get("sector_weights"):
        return {"sectors": None, "companies": {}}, ["unverifiable: no VWRP look-through data has been entered"]
    if not cfg.get("source"):
        flags.append("unverifiable: VWRP look-through has no source")
    try:
        age = (today - dt.date.fromisoformat(cfg["as_of"])).days
        if age > LOOKTHROUGH_MAX_AGE_DAYS:
            flags.append(f"unverifiable: VWRP look-through is {age} days old (limit {LOOKTHROUGH_MAX_AGE_DAYS})")
    except (KeyError, TypeError, ValueError):
        flags.append("unverifiable: VWRP look-through has no valid as-of date")
    mapped: dict[str, float] = {}
    for name, w in cfg["sector_weights"].items():
        s = sectors.from_icb(name)
        if s is None:
            flags.append(f"unverifiable: provider sector {name!r} has no mapping")
            continue
        mapped[s] = mapped.get(s, 0.0) + float(w)
    flags.append("classification mismatch: VWRP sectors are FTSE/ICB, satellites are SIC-mapped (sectors.py)")
    return {"sectors": mapped, "companies": {k: float(v) for k, v in cfg.get("top_holdings", {}).items()}}, flags


def check(sats: list[dict], look: dict) -> list[dict]:
    """Every constraint for a candidate book: core VWRP plus satellites [{ticker, weight, sic}] (§2)."""
    out_w = sum(float(h["weight"]) for h in sats)
    core = 1.0 - out_w
    res = [{"constraint": "outside_core", "limit": MAX_OUTSIDE_CORE, "value": out_w, "enforced": True,
            "calc": " + ".join(f"{h['ticker']} {h['weight']:.4f}" for h in sats) + f" = {out_w:.4f}" if sats
            else "no satellites = 0", "pass": out_w <= MAX_OUTSIDE_CORE + EPS}]
    for h in sats:
        w = float(h["weight"])
        res.append({"constraint": f"per_company:{h['ticker']}", "limit": MAX_PER_COMPANY, "value": w,
                    "enforced": True, "calc": f"direct {w:.4f}", "pass": w <= MAX_PER_COMPANY + EPS})
        if h["ticker"] in look["companies"]:
            lt = look["companies"][h["ticker"]]
            tot = w + core * lt
            res.append({"constraint": f"per_company_lookthrough:{h['ticker']}", "limit": MAX_PER_COMPANY,
                        "value": tot, "enforced": False, "calc": f"{w:.4f} + core {core:.4f} x VWRP {lt:.4f} = "
                        f"{tot:.4f}", "pass": tot <= MAX_PER_COMPANY + EPS})
    if not sats:
        res.append({"constraint": "sector_active", "limit": MAX_SECTOR_ACTIVE, "value": 0.0, "enforced": True,
                    "calc": "100% VWRP: every sector equals VWRP's, active weight 0", "pass": True})
        return res
    unknown = [h["ticker"] for h in sats if sectors.from_sic(h.get("sic")) is None]
    if unknown or look["sectors"] is None:
        why = (f"unknown sector for {unknown}" if unknown else "") + \
              ("; " if unknown and look["sectors"] is None else "") + \
              ("no VWRP look-through data" if look["sectors"] is None else "")
        res.append({"constraint": "sector_active", "limit": MAX_SECTOR_ACTIVE, "value": None, "enforced": True,
                    "calc": f"cannot be computed: {why}", "pass": False})
        return res
    sat_by: dict[str, float] = {}
    for h in sats:
        s = sectors.from_sic(h["sic"])
        sat_by[s] = sat_by.get(s, 0.0) + float(h["weight"])
    for s in sorted(set(sat_by) | set(look["sectors"])):
        vw = look["sectors"].get(s, 0.0)
        port = core * vw + sat_by.get(s, 0.0)
        active = port - vw
        res.append({"constraint": f"sector_active:{s}", "limit": MAX_SECTOR_ACTIVE, "value": active,
                    "enforced": True, "calc": f"core {core:.4f} x VWRP {vw:.4f} + satellites {sat_by.get(s, 0.0):.4f}"
                    f" - VWRP {vw:.4f} = {active:+.4f}", "pass": abs(active) <= MAX_SECTOR_ACTIVE + EPS})
    return res


def review(series: list[tuple[str, float, float]] | None) -> dict:
    """The −15% relative review threshold (§4). `series`: month-end (date, sleeve value, VWRP value), GBP, oldest
    first, starting at the sleeve's inception. Opens a review only; it never changes a weight."""
    if not series:
        return {"status": "not applicable", "reason": "no satellite sleeve"}
    if len(series) < 2:
        return {"status": "not enough data", "reason": "fewer than two month-end marks"}

    def window(a, b):
        rs, rv = b[1] / a[1] - 1, b[2] / a[2] - 1
        rel = (1 + rs) / (1 + rv) - 1
        return {"from": a[0], "to": b[0], "sleeve": rs, "vwrp": rv, "relative": rel,
                "calc": f"(1 + {rs:+.4f}) / (1 + {rv:+.4f}) - 1 = {rel:+.4f}"}
    last = series[-1]
    trailing = window(series[max(0, len(series) - 13)], last)
    inception = window(series[0], last)
    breach = [n for n, w in (("trailing_12m", trailing), ("since_inception", inception))
              if w["relative"] <= REVIEW_RELATIVE + EPS]
    return {"status": "review_threshold breached" if breach else "within threshold", "threshold": REVIEW_RELATIVE,
            "trailing_12m": trailing, "since_inception": inception, "breached": breach,
            "escalation": ["critical alert in the digest", "owner-review item recorded",
                           "no weight changes until the owner decides"] if breach else [],
            "flags": ["sleeve prices are price-only unless dividends are recorded; VWRP is accumulating"]}


def propose(*, eligible_cfg: dict, trial_events: list[dict], look_cfg: dict | None, today: dt.date,
            current: dict[str, float] | None = None, series=None, evidence: dict | None = None) -> dict:
    """One proposal record (§5). Pure: reads only its arguments."""
    ok, refused = eligible(eligible_cfg, trial_verdicts(trial_events))
    look, flags = lookthrough(look_cfg, today)
    sats = [h for s in ok for h in s.get("holdings", [])]
    checks = check(sats, look)
    failed = [c["constraint"] for c in checks if c["enforced"] and not c["pass"]]
    flags += [f"look-through company weight above {MAX_PER_COMPANY:.0%}: {c['constraint'].split(':', 1)[1]}"
              for c in checks if not c["enforced"] and not c["pass"]]
    flags += [f"unknown sector: {h['ticker']} has no usable SIC code" for h in sats
              if sectors.from_sic(h.get("sic")) is None]
    if sats and not failed:
        targets = [{"ticker": h["ticker"], "weight": float(h["weight"]), "reason": f"eligible strategy "
                    f"{s['id']} (owner {s['owner_decision']}, trials {s['trials']})"}
                   for s in ok for h in s.get("holdings", [])]
        core = 1.0 - sum(t["weight"] for t in targets)
        targets.insert(0, {"ticker": CORE, "weight": core, "reason": "core: the remainder"})
        verdict = "accepted"
    else:
        targets = [{"ticker": CORE, "weight": 1.0, "reason": "no strategy has passed the research gates" if not sats
                    else f"candidate rejected ({', '.join(failed)}); the 100% VWRP default stands"}]
        verdict = "default" if not sats else "rejected"
    tw = {t["ticker"]: round(t["weight"], 6) for t in targets}
    cur = {k: round(float(v), 6) for k, v in (current or {CORE: 1.0}).items() if v}
    return {"version": VERSION, "as_of": today.isoformat(), "verdict": verdict, "targets": targets,
            "no_trade": tw == cur, "constraints": checks, "failed": failed, "refused_strategies": refused,
            "flags": flags, "review": review(series if sats else None), "evidence": evidence or {},
            "orders": "none: pm-1.0 is proposal-only"}


def from_repo(repo: Path, today: dt.date | None = None) -> dict:
    """Build today's proposal from the files in the repository, with their hashes as evidence."""
    paths = {"pm_eligible": repo / "office/config/pm_eligible.json",
             "vwrp_lookthrough": repo / "office/config/vwrp_lookthrough.json",
             "trials": repo / "research/edge/trials.jsonl"}
    trials = [json.loads(x) for x in paths["trials"].read_text().splitlines() if x.strip()] \
        if paths["trials"].exists() else []
    look = json.loads(paths["vwrp_lookthrough"].read_text()) if paths["vwrp_lookthrough"].exists() else None
    return propose(eligible_cfg=json.loads(paths["pm_eligible"].read_text()), trial_events=trials, look_cfg=look,
                   today=today or dt.datetime.now(dt.timezone.utc).date(),
                   evidence={k: sha(p) for k, p in paths.items()} | {"trial_events": len(trials)})
