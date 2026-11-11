"""agent-1.19 exit review: a recorded hold-or-sell decision for every open trade (owner 6 Nov 2026 14:39Z, "at what
point would this system sell a stock ... there should be a conscious thing for this").

Each open trade gets, once a day and whenever its verdict changes, an `exit_review` event that names why it is still
held and what will sell it; every sale already carries its reason in the order intent. Two new sell rules sit beside
each strategy's own tested exits, both stated priors under test by the research loop (unproven until it reports):
- thesis_broken (buyback_value): a filing made after entry shows more shares outstanding than about a year before
  it, i.e. the buyback the trade was bought for has stopped;
- profit_lock (buyback_value, gap_rebound): once a trade has been up `arm` or more, sell when its return falls to
  `keep` of the best return seen.
"""
from __future__ import annotations

from datetime import date, timedelta

SHARES = ("EntityCommonStockSharesOutstanding",)


def profit_lock(ret: float, peak: float, arm: float = 0.25, keep: float = 0.5) -> bool:
    return peak >= arm and ret <= peak * keep


def _share_rows(facts: dict) -> list[dict]:
    rows = []
    for tag in SHARES:
        for r in (((facts.get("facts") or {}).get("dei") or {}).get(tag) or {}).get("units", {}).get("shares", []):
            if r.get("end") and r.get("filed") and r.get("val"):
                rows.append({"end": r["end"], "filed": r["filed"], "val": float(r["val"]), "form": r.get("form", "")})
    return rows


def shares_thesis(facts: dict, since: str) -> dict:
    """{broken: True|False|None, why}. Latest cover-page share count in a filing made on or after `since` (the entry
    day) against the count dated 300-430 days before it. None (UNVERIFIED) when either is missing: nothing is sold."""
    rows = _share_rows(facts)
    new = [r for r in rows if r["filed"] >= since]
    if not new:
        return {"broken": None, "why": "UNVERIFIED: no share count filed since entry yet"}
    last = max(new, key=lambda r: (r["end"], r["filed"]))
    e = date.fromisoformat(last["end"])
    lo, hi = (e - timedelta(days=430)).isoformat(), (e - timedelta(days=300)).isoformat()
    old = [r for r in rows if lo <= r["end"] <= hi]
    if not old:
        return {"broken": None, "why": f"UNVERIFIED: no share count a year before {last['end']}"}
    prev = max(old, key=lambda r: (r["end"], r["filed"]))
    chg = last["val"] / prev["val"] - 1
    detail = (f"shares {prev['val']:,.0f} ({prev['end']}) -> {last['val']:,.0f} ({last['end']}, {last['form']} "
              f"filed {last['filed']}), {chg:+.1%} y/y")
    if chg > 0:
        return {"broken": True, "why": f"thesis broken: {detail}"}
    return {"broken": False, "why": f"buyback intact: {detail}"}


def plan(entry: dict, ret: float | None, peak: float | None, now: float, rule: str | None, sell_why: str | None,
         thesis: str | None = None, broker_stop: float | None = None, lock: dict | None = None) -> dict:
    """One row of the exit ledger: the verdict, and in words what keeps the trade and what will end it."""
    sig = entry["signal"]
    keep, sell_if = [], []
    if rule:
        keep.append(rule)
    if sig.get("stop") is not None:
        sell_if.append(f"down {sig['stop']:.0%} from entry")
    if broker_stop:
        sell_if.append(f"broker stop at {broker_stop}")
    if sig.get("take_profit") is not None and sig["take_profit"] < 5:
        sell_if.append(f"up {sig['take_profit']:.0%} from entry")
    if sig.get("time_stop_s"):
        end = date.fromtimestamp(entry.get("t", now) + sig["time_stop_s"]).isoformat()
        if sig["time_stop_s"] < 5 * 365 * 86400:
            sell_if.append(f"time exit on {end}")
    if lock:
        armed = peak is not None and peak >= lock["arm"]
        sell_if.append(f"profit lock: after +{lock['arm']:.0%}, gives back to {lock['keep']:.0%} of the best gain"
                       + (f" (armed, best {peak:+.1%}, sells at {peak * lock['keep']:+.1%})" if armed else ""))
    if thesis:
        keep.append(thesis)
    return {"ticker": entry["ticker"], "strategy": sig.get("strategy"), "entry_id": entry["id"],
            "since": (entry.get("ts") or "")[:10], "ret": None if ret is None else round(ret, 4),
            "peak": None if peak is None else round(peak, 4),
            "verdict": f"sell: {sell_why}" if sell_why else "hold", "held_because": keep, "sells_if": sell_if}
