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
    """VWRP sector and company weights mapped onto the 11 sectors, whether they are verified, and the flags (§3).

    Verified means: entered with a source, a valid as-of date at most LOOKTHROUGH_MAX_AGE_DAYS old, every provider
    sector mapped, and weights summing to 100% +/- 2 points. Unverified data is still used to show the arithmetic,
    but no check that depends on it can pass (owner, 20 Oct 12:19Z)."""
    flags = []
    if not cfg or not cfg.get("sector_weights"):
        return {"sectors": None, "companies": {}, "verified": False,
                "evidence": {"source": None, "as_of": None}}, \
            ["unverified: no VWRP look-through data has been entered"]
    if not cfg.get("source"):
        flags.append("unverified: VWRP look-through has no source")
    age = None
    try:
        age = (today - dt.date.fromisoformat(cfg["as_of"])).days
        if age > LOOKTHROUGH_MAX_AGE_DAYS or age < 0:
            flags.append(f"unverified: VWRP look-through is {age} days old (limit {LOOKTHROUGH_MAX_AGE_DAYS})")
    except (KeyError, TypeError, ValueError):
        flags.append("unverified: VWRP look-through has no valid as-of date")
    mapped: dict[str, float] = {}
    for name, w in cfg["sector_weights"].items():
        sec = sectors.from_icb(name)
        if sec is None:
            flags.append(f"unverified: provider sector {name!r} has no mapping")
            continue
        mapped[sec] = mapped.get(sec, 0.0) + float(w)
    total = sum(float(w) for w in cfg["sector_weights"].values())
    if abs(total - 1.0) > 0.02:
        flags.append(f"unverified: VWRP sector weights sum to {total:.4f}, not 1 +/- 0.02")
    verified = not flags
    flags.append("classification mismatch: VWRP sectors are FTSE/ICB, satellites are SIC-mapped (sectors.py)")
    return {"sectors": mapped, "companies": {k: float(v) for k, v in cfg.get("top_holdings", {}).items()},
            "verified": verified, "evidence": {"source": cfg.get("source"), "as_of": cfg.get("as_of"),
                                               "age_days": age, "sector_weight_sum": round(total, 6)}}, flags


def _status(ok: bool, verified: bool = True) -> str:
    return "fail" if not ok else ("pass" if verified else "unverified")


def check(sats: list[dict], look: dict) -> list[dict]:
    """Every constraint for a candidate book: core VWRP plus satellites [{ticker, weight, sic}] (§2).

    Each record: constraint, limit, value, calc (the arithmetic), evidence, enforced, status (pass / fail /
    unverified). A breach is "fail" even on unverified data; a check that only passes on unverified or missing
    data is "unverified", never "pass"."""
    out_w = sum(float(h["weight"]) for h in sats)
    core = 1.0 - out_w
    ev = look["evidence"]
    res = [{"constraint": "outside_core", "limit": MAX_OUTSIDE_CORE, "value": out_w, "enforced": True,
            "calc": " + ".join(f"{h['ticker']} {float(h['weight']):.4f}" for h in sats) + f" = {out_w:.4f}" if sats
            else "no satellites = 0", "evidence": "proposal weights", "status": _status(out_w <= MAX_OUTSIDE_CORE + EPS)}]
    for h in sats:
        w = float(h["weight"])
        res.append({"constraint": f"per_company:{h['ticker']}", "limit": MAX_PER_COMPANY, "value": w,
                    "enforced": True, "calc": f"direct {w:.4f}", "evidence": "proposal weights",
                    "status": _status(w <= MAX_PER_COMPANY + EPS)})
        lt = look["companies"].get(h["ticker"])
        tot = w + core * (lt or 0.0)
        res.append({"constraint": f"per_company_lookthrough:{h['ticker']}", "limit": MAX_PER_COMPANY,
                    "value": tot, "enforced": False, "evidence": ev,
                    "calc": f"{w:.4f} + core {core:.4f} x VWRP {lt:.4f} = {tot:.4f}" if lt is not None
                    else f"{w:.4f} + core {core:.4f} x VWRP weight (not in the entered top holdings) >= {tot:.4f}",
                    "status": _status(tot <= MAX_PER_COMPANY + EPS, look["verified"] and lt is not None)})
    unknown = [h["ticker"] for h in sats if sectors.from_sic(h.get("sic")) is None]
    if look["sectors"] is None:
        res.append({"constraint": "sector_active", "limit": MAX_SECTOR_ACTIVE, "value": None, "enforced": True,
                    "calc": "cannot be computed: no VWRP look-through data", "evidence": ev, "status": "unverified"})
        return res
    sat_by: dict[str, float] = {}
    for h in sats:
        sec = sectors.from_sic(h.get("sic"))
        if sec:
            sat_by[sec] = sat_by.get(sec, 0.0) + float(h["weight"])
    for sec in sectors.SECTORS:
        vw = look["sectors"].get(sec, 0.0)
        port = core * vw + sat_by.get(sec, 0.0)
        active = port - vw
        res.append({"constraint": f"sector_active:{sec}", "limit": MAX_SECTOR_ACTIVE, "value": active,
                    "enforced": True, "evidence": ev,
                    "calc": f"portfolio = core {core:.4f} x VWRP {vw:.4f} + satellites {sat_by.get(sec, 0.0):.4f} = "
                    f"{port:.4f}; active = {port:.4f} - VWRP {vw:.4f} = {active:+.4f}",
                    "status": _status(abs(active) <= MAX_SECTOR_ACTIVE + EPS, look["verified"] and not unknown)})
    if unknown:
        res.append({"constraint": "sector_classified", "limit": None, "value": unknown, "enforced": True,
                    "calc": f"no sector for {unknown}: their weight is missing from the sector rows above",
                    "evidence": "SIC codes in pm_eligible.json", "status": "unverified"})
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
    failed = [c["constraint"] for c in checks if c["enforced"] and c["status"] == "fail"]
    unverified = [c["constraint"] for c in checks if c["enforced"] and c["status"] == "unverified"]
    flags += [f"look-through company weight above {MAX_PER_COMPANY:.0%}: {c['constraint'].split(':', 1)[1]}"
              for c in checks if not c["enforced"] and c["status"] == "fail"]
    flags += [f"unknown sector: {h['ticker']} has no usable SIC code" for h in sats
              if sectors.from_sic(h.get("sic")) is None]
    if sats and not failed and not unverified:
        targets = [{"ticker": h["ticker"], "weight": float(h["weight"]), "reason": f"eligible strategy "
                    f"{s['id']} (owner {s['owner_decision']}, trials {s['trials']})"}
                   for s in ok for h in s.get("holdings", [])]
        core = 1.0 - sum(t["weight"] for t in targets)
        targets.insert(0, {"ticker": CORE, "weight": core, "reason": "core: the remainder"})
        verdict = "accepted"
    elif sats:
        why = ", ".join([f"{c} failed" for c in failed] + [f"{c} unverified" for c in unverified])
        targets = [{"ticker": CORE, "weight": 1.0, "reason": f"candidate rejected ({why}); the 100% VWRP default "
                    "stands"}]
        verdict = "rejected"
    else:
        # The default is the fallback, so it stands whatever the data; its unverified checks are shown, not passed.
        targets = [{"ticker": CORE, "weight": 1.0, "reason": "no strategy has passed the research gates"}]
        verdict = "default"
    tw = {t["ticker"]: round(t["weight"], 6) for t in targets}
    cur = {k: round(float(v), 6) for k, v in (current or {CORE: 1.0}).items() if v}
    return {"version": VERSION, "as_of": today.isoformat(), "verdict": verdict, "targets": targets,
            "no_trade": tw == cur, "constraints": checks, "failed": failed, "unverified": unverified,
            "refused_strategies": refused,
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
