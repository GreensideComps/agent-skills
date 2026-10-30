"""merger_arb (decision C8, owner 30 Oct 08:15Z): buy the target of an agreed all-cash takeover below the offer price
and hold it to the cash-out.

Deals come only from SEC EDGAR full-text search, and the request carries the contact User-Agent the SEC requires (the
owner supplied it on 30 Oct 09:47Z; it is read at run time from state/sec_user_agent.txt or SEC_USER_AGENT and is not
in the repository). A target is identified only from filings the target itself is the subject of (DEFM14A, PREM14A,
SC 14D9, SC TO-T), never from an 8-K alone, because acquirers file 8-Ks too. The "$X per share in cash" price must
appear in two separate filings (or a filing and its EX-99 press release). A deal is skipped when any filing mentions
stock consideration or an exchange ratio, when it looks hostile (unsolicited, or the board recommends rejecting), when
no merger agreement is mentioned, or when no expected close date can be read. Missing data means no trade. Nothing
here sends an order.
"""
from __future__ import annotations

import calendar
import html
import re
import time

from . import active, execution

NAME = "merger_arb"
EFTS = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{file}"
TARGET_FORMS = ("DEFM14A", "PREM14A", "SC 14D9", "SC TO-T")
FORMS = "DEFM14A,PREM14A,SC TO-T,SC 14D9,8-K"

PRICE = re.compile(r"\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{1,4})?)\s+(?:per\s+share\s+)?in\s+cash", re.I)
PER_SHARE = re.compile(r"\$\s?(\d{1,4}(?:\.\d{1,4})?)\s+per\s+share\s+in\s+cash", re.I)
MIXED = re.compile(r"and\s+(?:\d+(?:\.\d+)?|one|a\s+fraction\s+of\s+an?)\s+(?:validly\s+issued\s+)?(?:shares?\b|share\s+of)|"
                   r"cash\s+and\s+stock|stock\s+consideration|exchange\s+ratio|cash\s+or\s+(?:\d|shares)", re.I)
# a target board's own recommendation against the offer, stated on the front of its SC 14D9 (merger agreements quote
# "recommend that stockholders reject such tender offer" as a hypothetical, so the whole text is not searched)
HOSTILE = re.compile(r"\b(?:board|directors)\b[^.]{0,160}\brecommends?\b[^.]{0,80}\breject\b", re.I)
AGREEMENT = re.compile(r"agreement\s+and\s+plan\s+of\s+merger|merger\s+agreement", re.I)
EXPECT = re.compile(r"\b(?:expect|anticipat)", re.I)
CLOSING = re.compile(r"\b(?:clos|complet|consummat)", re.I)
QUARTER = re.compile(r"(first|second|third|fourth|1st|2nd|3rd|4th)\s+(?:calendar\s+|fiscal\s+)?quarter\s+of\s+"
                     r"(?:calendar\s+|fiscal\s+(?:year\s+)?)?(20\d\d)", re.I)
HALF = re.compile(r"(first|second)\s+half\s+of\s+(?:calendar\s+|fiscal\s+(?:year\s+)?)?(20\d\d)", re.I)
PART = re.compile(r"\b(early|mid|middle\s+of|late|year[- ]end|end\s+of)\s*-?\s*(?:calendar\s+)?(?:year\s+)?(20\d\d)", re.I)
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
BY_DATE = re.compile(r"\b(?:by|before|on\s+or\s+before)\s+(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s+(20\d\d)", re.I)
ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}


def text_of(raw: str) -> str:
    """Plain text of an HTML or text filing."""
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))


EXPIRE = re.compile(r"\boffer\b[^.]{0,200}?\bexpire\b[^.]{0,120}?\bon\s+(?:\w+day,\s+)?(" + "|".join(MONTHS)
                    + r")\s+(\d{1,2}),\s+(20\d\d)", re.I)


def _month_end(y: int, m: int) -> float:
    return calendar.timegm((y, m, calendar.monthrange(y, m)[1], 23, 59, 0))


def expected_close(text: str) -> tuple[float | None, str | None]:
    """The latest moment a sentence about the expected closing names (the end of the stated period, read as
    calendar), from the first such sentence that names one."""
    text = text[:400_000]
    for em in EXPECT.finditer(text):
        a, b = text.rfind(". ", 0, em.start()) + 1, text.find(". ", em.end())
        sent = text[a:b if b > 0 else len(text)]
        if len(sent) > 600 or not CLOSING.search(sent):
            continue
        m = QUARTER.search(sent)
        if m:
            return _month_end(int(m.group(2)), 3 * ORD[m.group(1).lower()]), sent[-160:]
        m = HALF.search(sent)
        if m:
            return _month_end(int(m.group(2)), 6 if m.group(1).lower() == "first" else 12), sent[-160:]
        m = PART.search(sent)
        if m:
            k = m.group(1).lower()
            month = 4 if k == "early" else 8 if k.startswith("mid") else 12
            return _month_end(int(m.group(2)), month), sent[-160:]
        m = BY_DATE.search(sent)
        if m:
            y, mo, dd = int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))
            return calendar.timegm((y, mo, min(dd, calendar.monthrange(y, mo)[1]), 23, 59, 0)), sent[-160:]
    m = EXPIRE.search(text)
    if m:  # a tender offer closes soon after it expires; the spec's limits use expiry + 30 days
        y, mo, dd = int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))
        return calendar.timegm((y, mo, min(dd, calendar.monthrange(y, mo)[1]), 23, 59, 0)) + 30 * 86400, m.group(0)[-160:]
    return None, None


def parse(text: str, form: str = "") -> dict:
    """What one filing says: the per-share cash price, and the flags that rule a deal out."""
    m = PER_SHARE.search(text) or PRICE.search(text)
    close, close_txt = expected_close(text)
    near = text[max(0, m.start() - 200):m.end() + 300] if m else ""  # the consideration clause itself
    return {"price": float(m.group(1).replace(",", "")) if m else None,
            "mixed": bool(MIXED.search(near)), "hostile": is_hostile(text, form),
            "agreement": bool(AGREEMENT.search(text)), "close": close, "close_txt": close_txt}


def is_hostile(text: str, form: str) -> bool:
    if form.split("/")[0] != "SC 14D9":
        return False
    m = HOSTILE.search(text[:30_000])
    return bool(m) and not re.search(r"\bfail|\bif\b|\bwould\b|\bmay\b", m.group(0), re.I)


def target_of(src: dict) -> dict | None:
    """The subject company of a filing: the first named entity, with its first ticker. None without a ticker."""
    names = src.get("display_names") or []
    if not names:
        return None
    m = re.search(r"\(([A-Z][A-Z0-9.\-]{0,5})(?:,[^)]*)?\)\s+\(CIK (\d+)\)", names[0])
    if not m:
        return None
    return {"ticker": m.group(1), "cik": m.group(2), "name": names[0].split("  (")[0].strip()}


def search(get, start: str, end: str, pages: int = 5, q: str = '"per share in cash"', forms: str = FORMS,
           ciks: str | None = None) -> list[dict]:
    """EFTS hits for the cash-offer phrase in deal filings: [{id, form, date, file_type, items, url, target}]."""
    out = []
    for p in range(pages):
        params = {"q": q, "forms": forms, "dateRange": "custom", "startdt": start, "enddt": end, "from": p * 100}
        if ciks:
            params["ciks"] = ciks
        d = get(EFTS, params)
        hits = (d.get("hits") or {}).get("hits") or []
        for h in hits:
            s = h.get("_source") or {}
            adsh, _, fname = h.get("_id", "").partition(":")
            tgt = target_of(s)
            if not tgt or not fname:
                continue
            out.append({"id": h["_id"], "adsh": adsh, "form": s.get("form", ""), "date": s.get("file_date", ""),
                        "file_type": s.get("file_type") or "", "items": s.get("items") or [], "target": tgt,
                        "url": ARCHIVE.format(cik=int(tgt["cik"]), adsh=adsh.replace("-", ""), file=fname)})
        if len(hits) < 100:
            break
    return out


def is_target_form(form: str) -> bool:
    return form.split("/")[0] in TARGET_FORMS


def build_deals(hits: list[dict], docs: dict[str, dict], tradeable) -> dict[str, dict]:
    """One record per target with every filing's reading; `eligible` and `why` say whether it may be traded."""
    by: dict[str, list] = {}
    for h in hits:
        by.setdefault(h["target"]["cik"], []).append(h)
    out = {}
    for cik, hs in by.items():
        if not any(is_target_form(h["form"]) for h in hs):
            continue  # an 8-K alone may be the acquirer's
        tgt = next(h["target"] for h in hs if is_target_form(h["form"]))
        t212 = tradeable(tgt["ticker"])
        read = [(h, docs[h["id"]]) for h in sorted(hs, key=lambda h: h["date"]) if h["id"] in docs]
        priced = [(h, d) for h, d in read if d.get("price")]
        why, offer = None, None
        if priced:
            last = priced[-1][1]["price"]
            conf = [(h, d) for h, d in priced if abs(d["price"] - last) < 1e-6]
            if len({h["adsh"] for h, _ in conf}) >= 2 or any(h["file_type"].upper().startswith("EX-99") for h, _ in conf) and len(conf) >= 2:
                offer = last
        close = next((d["close"] for _, d in reversed(read) if d.get("close")), None)
        if not t212:
            why = f"{tgt['ticker']} is not tradeable on T212"
        elif not read:
            why = "no filing read yet"
        elif offer is None:
            why = "cash price not confirmed in two filings"
        elif any(d["mixed"] for _, d in read):
            why = "not all-cash (stock or election consideration mentioned)"
        elif any(d["hostile"] for _, d in read):
            why = "looks hostile (unsolicited or board recommends rejecting)"
        elif not any(d["agreement"] for _, d in read):
            why = "no merger agreement mentioned"
        elif not close:
            why = "no expected close date stated"
        out[t212 or tgt["ticker"]] = {"target": tgt, "t212": t212, "offer": offer, "close": close,
                                      "filings": [{"id": h["id"], "form": h["form"], "date": h["date"],
                                                   **{k: d.get(k) for k in ("price", "mixed", "hostile", "agreement")}}
                                                  for h, d in read],
                                      "first": min(h["date"] for h in hs), "eligible": why is None, "why": why or "ok"}
    return out


def open_deals(records: list[dict]) -> list[dict]:
    return [e for e in active.open_trades(records) if e["signal"].get("strategy") == NAME]


def entry_orders(cfg, records, positions, quote_of, fx, total, cash, day, now, vwrp_px, disabled, state) -> tuple[list, list]:
    """Entries for eligible deals whose live spread and annualised return pass the spec's filters."""
    mc = cfg["active"]["merger"]
    notes: list[str] = []
    if NAME in disabled or not state:
        return [], notes
    held = open_deals(records)
    if len(held) >= mc["max_open"]:
        return [], notes
    open_tk = {e["ticker"] for e in active.open_trades(records)}
    tried = {r["ticker"] for r in execution.latest_intents(records).values()
             if (r.get("signal") or {}).get("type") == "active_entry" and r.get("ts", "").startswith(day)}
    size = mc["entry_weight"] * total
    reserve = 1 + cfg["core"].get("buy_reserve", 0)
    out = []
    for tk, d in sorted((state.get("deals") or {}).items()):
        if not d.get("eligible") or tk in open_tk or tk in tried or tk in positions or tk in state.get("terminated", {}):
            continue
        q = quote_of(tk)
        if not q or not fx:
            notes.append(f"{NAME}: {tk} has no validated quote")
            continue
        spread = d["offer"] / q["price"] - 1
        days = (d["close"] - now) / 86400
        ann = spread * 365 / days if days > 0 else None
        if not mc["min_spread"] <= spread <= mc["max_spread"]:
            notes.append(f"{NAME}: {tk} spread {spread:+.1%} outside {mc['min_spread']:.0%}-{mc['max_spread']:.0%}")
            continue
        if days <= 0 or days > mc["max_days_to_close"]:
            notes.append(f"{NAME}: {tk} expected close {days:.0f} days away")
            continue
        if ann < mc["min_annualised"]:
            notes.append(f"{NAME}: {tk} annualised {ann:.1%} < {mc['min_annualised']:.0%}")
            continue
        if cash < size * reserve:
            notes.append(f"{NAME}: {tk} qualifies but cash £{cash:.2f} < £{size * reserve:.2f}")
            break
        qty = math_floor(size / (q["price"] / fx), cfg["active"]["qty_decimals"])
        if qty <= 0:
            continue
        out.append((tk, qty, qty * q["price"] / fx, q["price"], True,
                    f"active entry: {NAME} ({mc['rule']}); offer ${d['offer']} vs ${q['price']}: spread {spread:+.1%}, "
                    f"{ann:.0%} annualised to {time.strftime('%Y-%m-%d', time.gmtime(d['close']))}",
                    {"type": "active_entry", "strategy": NAME, "rule": mc["rule"], "offer": d["offer"],
                     "close": d["close"], "spread": round(spread, 4), "annualised": round(ann, 4),
                     "target": d["target"], "filings": [f["id"] for f in d["filings"]],
                     "entry_px": q["price"], "stop": mc["stop_loss"], "take_profit": mc["take_profit"],
                     "time_stop_s": mc["time_stop_days"] * 86400, "quote": q, "vwrp_px": vwrp_px}))
        if len(held) + len(out) >= mc["max_open"]:
            break
    return out, notes


def math_floor(x: float, dp: int) -> float:
    return int(x * 10 ** dp) / 10 ** dp


def closed_exit_record(entry: dict, fx: float | None, vwrp_px) -> dict:
    """The exit for a deal that closed: the shares were cashed out at the offer, so the position is gone. The value is
    the offer converted at today's rate, marked as an estimate until the broker's cash record is reconciled."""
    qty = float(entry["quantity"])
    val = qty * entry["signal"]["offer"] / fx if fx else float(entry.get("value_gbp") or 0)
    return {"ticker": entry["ticker"], "quantity": -qty, "value_gbp": round(val, 2), "price": entry["signal"]["offer"],
            "status": "filled", "order_id": None, "broker": {"estimated": True},
            "reason": f"active exit (deal closed): {NAME} cashed out at ${entry['signal']['offer']}",
            "signal": {"type": "active_exit", "entry_id": entry["id"], "strategy": NAME, "why": "deal_closed",
                       "vwrp_px": vwrp_px}}


def terminated(hits: list[dict], cik: str, since: str) -> dict | None:
    """A target 8-K after entry reporting a terminated material agreement (item 1.02) without a completion (2.01)."""
    for h in hits:
        if h["target"]["cik"] == cik and h["date"] >= since and "1.02" in h["items"] and "2.01" not in h["items"]:
            return h
    return None
