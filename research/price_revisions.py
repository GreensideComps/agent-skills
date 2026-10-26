"""Revision detection between two pulls of the same daily prices (mini fund Stage 2 §2).

Yahoo rewrites history: after a dividend it scales every earlier `adjclose`; after a split it scales every earlier
`close` and `adjclose`. This module compares an old and a new pull, session by session, and classifies each
difference. It never decides which value is "right" and never edits the old records; the output is a list of
revision events to append (INTERFACES §0.4).

Classes:
* `dividend_adjustment`  only adjclose changed, by one common factor shared by a contiguous block of the
  earliest changed sessions (all changed sessions precede every unchanged one);
* `split_adjustment`     close and adjclose changed by the same common factor, under the same block rule;
* `unexplained`          anything else (including a single changed value); reported, never hidden;
* `new_row` / `dropped_row`  a session present in only one pull.

Values within ADJUSTMENT_TOL (relative) of each other count as the same; such sub-tolerance changes are counted as
`float_noise`, not reported as revisions (P33-5).

Known limits, kept on the safe side by design:
* One factor per class (P33-6, accepted exception). Two dividends between pulls rescale older sessions by two
  different factors; the sessions that do not match the most common factor are classed `unexplained`. That is a
  false alarm, never a hidden change. Piecewise factor blocks can come with the work package that approves live
  pulls.
* No persistence (P33-7, accepted exception). `compare()` returns events and writes nothing; an append-only
  `price_revisions.jsonl` is deferred to the live-pull work package, because without a second real pull there is
  nothing to persist.
"""
from __future__ import annotations

from collections import Counter

from price_provenance import ADJUSTMENT_TOL


def _ratio(new, old):
    if new is None or old is None or old == 0:
        return None
    return new / old


def _same(a, b):
    return a is not None and b is not None and abs(a - b) <= ADJUSTMENT_TOL * max(1.0, abs(b))


def _equal(a, b):
    """Both missing, exactly equal, or equal within the relative tolerance."""
    return a == b or _same(a, b)


def compare(old: list[dict], new: list[dict]) -> dict:
    o = {r["session_date"]: r for r in old}
    n = {r["session_date"]: r for r in new}
    sym = {r["symbol"] for r in old + new}
    if len(sym) > 1:
        raise ValueError(f"compare one symbol at a time, got {sorted(sym)}")
    events = []
    for d in sorted(set(n) - set(o)):
        events.append({"session_date": d, "class": "new_row", "new_record_id": n[d]["record_id"]})
    for d in sorted(set(o) - set(n)):
        events.append({"session_date": d, "class": "dropped_row", "old_record_id": o[d]["record_id"]})

    changed, noise = {}, 0
    for d in sorted(set(o) & set(n)):
        a, b = o[d], n[d]
        close_same = _equal(a["close"], b["close"])
        adj_same = _equal(a["adjclose"], b["adjclose"])
        if close_same and adj_same:
            if a["close"] != b["close"] or a["adjclose"] != b["adjclose"]:
                noise += 1
            continue
        changed[d] = {"rc": None if close_same else _ratio(b["close"], a["close"]),
                      "ra": None if adj_same else _ratio(b["adjclose"], a["adjclose"]),
                      "close_same": close_same}
    shared = sorted(set(o) & set(n))
    first_unchanged = next((d for d in shared if d not in changed), None)

    def mode_factor(kind):
        vals = [round(c["ra"], 9) for c in changed.values() if c["ra"] is not None and kind(c)]
        return Counter(vals).most_common(1)[0][0] if vals else None

    div_f = mode_factor(lambda c: c["close_same"])
    split_f = mode_factor(lambda c: not c["close_same"] and c["rc"] is not None and _same(c["rc"], c["ra"]))
    for d, c in changed.items():
        before_block = first_unchanged is None or d < first_unchanged
        if c["close_same"] and _same(c["ra"], div_f) and before_block and _block_ok(changed, d, shared):
            cls, factor = "dividend_adjustment", div_f
        elif (not c["close_same"] and _same(c["rc"], c["ra"]) and _same(c["ra"], split_f) and before_block
              and _block_ok(changed, d, shared)):
            cls, factor = "split_adjustment", split_f
        else:
            cls, factor = "unexplained", None
        events.append({"session_date": d, "class": cls, "factor": factor,
                       "old": {"close": o[d]["close"], "adjclose": o[d]["adjclose"], "record_id": o[d]["record_id"]},
                       "new": {"close": n[d]["close"], "adjclose": n[d]["adjclose"], "record_id": n[d]["record_id"]},
                       "revision_reason": cls})
    events.sort(key=lambda e: (e["session_date"], e["class"]))
    counts = Counter(e["class"] for e in events)
    return {"symbol": next(iter(sym), None), "events": events, "counts": dict(counts),
            "unexplained": counts.get("unexplained", 0), "float_noise": noise}


def _block_ok(changed: dict, d: str, shared: list[str]) -> bool:
    """A vendor adjustment rewrites every session before some date: all sessions up to d must be changed."""
    return all(s in changed for s in shared if s <= d)
