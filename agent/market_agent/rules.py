"""agent-1.23: every strategy's live buy and sell rules in plain English, built from config.json.

Why this exists: until now the rules lived in a dozen places (a `rule` sentence per strategy, a `sell_rules` list, a
long `rebalance` paragraph, module docstrings, docs/agent/MARKET_AGENT.md), and some of them disagreed with what the
agent does (the screener text still described drop-out swaps after they were switched off). This module is the one
place that says what is live. Every number below is read from the same config the agent trades on, so the page cannot
drift from the live settings, and `python3 -m market_agent rules --check docs/agent/RULES.md` (run by the tests and
by CI) fails when the saved page is out of date.

What is read from config and what is fixed text: the numbers (stops, targets, holding periods, sizes, limits, on/off
switches) come from config; the sentence around each number describes behaviour in code and is pinned by
agent/tests/test_rules.py, which fails if a strategy the agent can trade has no entry here or has no rule that would
ever sell it.
"""
from __future__ import annotations

DISASTER_ONLY = 0.5   # a configured stop this wide is a crash stop, not part of the tested rule
NO_TARGET = 1.0       # a take-profit this large is a placeholder so that only the other exits fire


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%" if abs(x * 100 - round(x * 100)) < 1e-9 else f"{x * 100:.1f}%"


def _days(d: float) -> str:
    d = int(d)
    if d >= 3650:
        return ""
    if d % 365 == 0 or d in (182, 183, 273, 274):
        m = round(d / 30.4)
        return f"{m} months"
    return f"{d} days"


def _common_exits(sc: dict, stop_word: str = "resting at the broker") -> list[str]:
    """The exits every active trade gets from its own numbers (active.exit_orders and the broker stop)."""
    out = []
    s = sc.get("stop_loss")
    if s is not None:
        if s >= DISASTER_ONLY:
            out.append(f"crash stop: a stop {stop_word} {_pct(s)} below the buy price (a safety net, not a tested rule)")
        else:
            out.append(f"stop: a stop {stop_word} {_pct(s)} below the buy price")
    tp = sc.get("take_profit")
    if tp is not None and tp < NO_TARGET:
        out.append(f"target: sold once it is {_pct(tp)} above the buy price")
    d = sc.get("time_stop_days")
    if d is not None and _days(d):
        out.append(f"time limit: sold after {_days(d)} whatever the price")
    return out


def _disaster(a: dict, key: str) -> list[str]:
    d = a.get("disaster_stop") or {}
    if not d.get("enabled") or key not in (d.get("strategies") or []):
        return []
    return [f"safety-net stop: a stop resting at the broker {_pct(d['pct'])} below the buy price; if the broker refuses "
            "or loses it, the agent sells at the same level itself and keeps trying to put the stop back "
            "(unproven: tighter stops tested worse than holding)"]


def _kill(sc: dict, a: dict) -> str:
    n = sc.get("kill_after_trades", a.get("kill_after_trades"))
    d = sc.get("kill_after_days")
    when = f"after {n} closed trades" + (f" or {_days(d) or str(int(d)) + ' days'} from its first buy, whichever is first" if d else "")
    return f"kill rule: {when}, if it has not beaten VWRP it is switched off and everything it holds is sold"


def strategies(cfg: dict, killed: dict | None = None) -> list[dict]:
    """One dict per strategy the agent can trade: {name, on, status, summary, evidence, buys, sells, size}."""
    a = cfg["active"]
    killed = killed or {}
    w = _pct(a["entry_weight"])
    rv = a.get("review") or {}
    out: list[dict] = []

    def add(name, sc, *, on, evidence, buys, sells, size=None, status=None):
        st = status or ("off" if not on else "on")
        if name in killed:
            st = f"switched off by the system ({killed[name].get('why', 'kill rule')})"
        out.append({"name": name, "on": bool(on) and name not in killed, "status": st, "evidence": evidence,
                    "buys": buys, "sells": [s for s in sells if s], "size": size or f"{w} of the book per trade"})

    review_gate = (f"the multi-horizon price review must score at least {rv['entry_min']:+.2f}, and there must be no "
                   f"earnings report within {rv['earnings_block_days']} days") if rv.get("enabled") else None
    review_exit = (f"review: sold if the multi-horizon price review falls to {rv['exit_max']:+.2f} or lower"
                   if rv.get("enabled") else None)
    moff = a.get("momentum_off") or {}

    def blocked(name):
        if moff.get("enabled") and name in (moff.get("strategies") or []):
            return (f"no new buys while the S&P 500 (SPY) is below its {moff['months']}-month average or the VIX last "
                    f"closed at {moff['vix_hi']:.0f} or more (open trades keep their exits)")
        return None

    for name, sc in (a.get("strategies") or {}).items():
        up = sc["trigger_move"] > 0
        add(name, sc, on=a.get("enabled"), status=sc.get("paused_note"),
            evidence=sc.get("evidence") or "no tested edge: a cheap forward test under the kill rule",
            buys=[f"a watchlist stock ({len(a['watchlist'])} large US names) is {'up' if up else 'down'} "
                  f"{_pct(abs(sc['trigger_move']))} or more on the day", review_gate, blocked(name)],
            sells=[*_common_exits(sc), review_exit, _kill(sc, a)])

    so = a.get("social") or {}
    add("social_trend", so, on=so.get("enabled"),
        evidence="tested and failed overall (Q226); trades only in the one condition that held up, unproven",
        buys=[f"one of {len(so.get('universe') or {})} US consumer brands: the 28-day average of its Wikipedia page "
              f"views is at least {so['z_entry']:.0f} standard deviations above its 52-week norm and still rising",
              f"the stock is not already up more than {_pct(so['max_run_up'])} in 20 trading days",
              f"the VIX closed at {so['vix_min']:.0f} or more on the signal day" if so.get("vix_min") else None,
              "bought at the next US session"],
        sells=[*_common_exits(so),
               f"attention faded: sold once page views are back within {so['z_exit']:.0f} standard deviation of normal",
               _kill(so, a)])

    me = a.get("merger") or {}
    add("merger_arb", me, on=me.get("enabled"), size=f"{_pct(me['entry_weight'])} per deal, at most {me['max_open']} deals",
        evidence="a known premium for deal risk, not tested here: forward test",
        buys=["an agreed all-cash takeover found in SEC filings, with the price confirmed in two filings, not hostile",
              f"the stock trades {_pct(me['min_spread'])} to {_pct(me['max_spread'])} below the offer, the deal is due "
              f"to close within {_days(me['max_days_to_close']) or '12 months'}, and the gap is worth at least "
              f"{_pct(me['min_annualised'])} a year"],
        sells=["deal closes: the shares are paid out in cash", "deal terminated: sold when an SEC filing says so",
               *_common_exits({"stop_loss": me.get("stop_loss")}), _kill(me, a)])

    sw = a.get("swing") or {}
    sq, gp = sw.get("squeeze") or {}, sw.get("gap") or {}
    add("vol_squeeze", sq, on=sq.get("enabled"), status=sq.get("paused_note"),
        evidence=sq.get("evidence") or "no tested edge: forward test under the kill rule",
        buys=[f"a watchlist stock whose 20-day trading range has been in its narrowest {_pct(sq['squeeze_pct'])} of the "
              f"last 250 days closes above its 20-day high on at least {sq['volume_x']}x normal volume",
              f"bought the next session unless it has already run more than {_pct(sq['max_chase'])} further",
              blocked("vol_squeeze")],
        sells=[*_common_exits(sq),
               f"trailing exit: once it has been up {_pct(sq['trail_after'])}, sold if it falls below the lowest price "
               f"of the last {sq['trail_days']} days", _kill(sq, a)])
    add("gap_go", gp, on=gp.get("enabled"), evidence="no tested edge: forward test under the kill rule",
        buys=[f"a watchlist stock opens {_pct(gp['min_gap'])} to {_pct(gp['max_gap'])} higher and, "
              f"{gp['check_from_s'] // 60} to {gp['check_to_s'] // 60} minutes after the US open, still holds at least "
              f"{_pct(gp['min_held'])} of the jump and is above its open and its average price so far",
              f"at most {gp['max_per_day']} a day"],
        sells=["stop: a stop resting at the broker at the low of the first 30 minutes",
               f"target: sold once it is {_pct(gp['take_profit'])} above the buy price",
               f"end of day: sold {gp['flat_before_close_s'] // 60} minutes before the US close, never held overnight",
               _kill(gp, a)])

    for name, vc in (a.get("timing") or {}).items():
        if vc.get("months") and len(set(vc["months"])) == 12:
            buys = [vc["rule"]]
            sells = ["no signal exit: held continuously until the review the kill rule sets"]
            ev = vc.get("evidence", "forward test")
        elif vc.get("months"):
            buys = [vc["rule"]]
            sells = ["calendar: sold at the first London open after the holding month ends"]
            ev = "passed its long-history test but has lost money since 2007: low confidence"
        else:
            buys = [f"at each month end, hold {vc['factor_ticker'].split('l_')[0]} when {vc['factor_symbol']}'s "
                    f"12-month return beats {vc['versus_symbol']}'s, otherwise hold "
                    f"{vc['market_ticker'].split('l_')[0]}", blocked(name)]
            sells = ["switch: sold when the month-end signal names the other fund"]
            ev = "passed its long-history test (1920s to 2022) but weak since 2007 and outside the US: low confidence"
        add(name, vc, on=vc.get("enabled"), evidence=ev, buys=buys, size=f"{_pct(vc['entry_weight'])} of the book",
            sells=[*sells, *_common_exits(vc), _kill(vc, a)])

    ss = a.get("stock_screen") or {}
    ew = ss.get("ew_rebalance") or {}
    add("stock_screen", ss, on=ss.get("enabled"), size=f"{_pct(ss['entry_weight'])} per name, {len(ss.get('picks') or [])} names now",
        evidence="tested and failed (Q199, +3.4% a year, not significant): a low-confidence forward test",
        buys=[f"the top {ss['refresh_top_n']} US stocks by a combined score (gross profitability, free-cash-flow "
              "yield, momentum, low debt, buybacks), skipping any that would break the sector limit or put more than "
              f"{ss['max_per_sic2']} names in one industry group",
              "a new name is bought only to replace one that was sold"],
        sells=["12-month review: once a name has been held 12 months it is replaced by the best name not held, at most "
               "one replacement a month, unless it is still in the top list, in which case it is kept and its 12 months "
               "start again (the tested rule; selling a name the screen would still pick was a drift from it)",
               "a name that merely drops out of the top list is " + ("replaced early" if ss.get("swap_on_dropout", True)
                                                                    else "NOT sold early (that rule tested worse than holding and is off)"),
               "SEC hard event: sold at once on a bankruptcy, delisting, auditor change, restatement, merger or tender filing",
               *_disaster(a, "stock_screen"),
               (f"monthly reset from {ew['from']}: each name is trimmed or topped up to an equal share (unproven)"
                if ew.get("enabled") else None),
               _kill(ss, a)])

    bb = a.get("buyback_value") or {}
    add("buyback_value", bb, on=bb.get("enabled"), size=f"{_pct(bb['entry_weight'])} per name, at most {bb['max_open']} names",
        evidence="tested, positive but not significant (Q206, +3.0% a year): unproven forward test",
        buys=["a monthly screen of US companies worth $2bn or more (no banks or utilities): among the heaviest buyers "
              "of their own shares, share count falling, positive free cash flow, modest debt, and cheap on free cash flow",
              f"cheapest first, at most {bb['max_per_sic2']} per industry group"],
        sells=[f"time limit: sold after {_days(bb['hold_days'])} (6 months for trades opened before 9 Nov 2026)",
               *_disaster(a, "buyback_value"), _kill(bb, a)])

    gr = a.get("gap_rebound") or {}
    add("gap_rebound", gr, on=gr.get("enabled"), size=f"{_pct(gr['entry_weight'])} per name, at most {gr['max_open']} names",
        evidence="not a registered test result (Q205 idea; Q218b high-fear version +4.5% a trade): unproven",
        buys=[f"a liquid US stock worth ${gr['min_mcap'] / 1e9:.0f}bn or more falls {_pct(abs(gr['ear_max']))} or more "
              "against the market around its earnings report, and its business looks weak (no free cash flow or "
              "falling sales)", "bought near the close two days after the report"],
        sells=[f"time limit: sold after {gr['hold_days']} trading days", *_disaster(a, "gap_rebound"), _kill(gr, a)])

    ns = a.get("news_shock") or {}
    add("news_shock_vix_hi", ns, on=ns.get("enabled"), size=f"{_pct(ns['entry_weight'])} per name, at most {ns['max_open']} names",
        evidence="tested and failed the go-live bar (Q222; most of the gain came from 2020): unproven",
        buys=[f"only when the VIX closed at {ns['vix_min']:.0f} or more: a liquid US stock worth "
              f"${ns['min_mcap'] / 1e9:.0f}bn or more falls {_pct(abs(ns['ear_max']))} or more against the market over "
              "two days after a company announcement that is not an earnings report",
              f"bought near the close of the following day; not again in the same name within {ns['no_repeat_days']} sessions"],
        sells=[f"time limit: sold after {ns['hold_days']} trading days", *_disaster(a, "news_shock"), _kill(ns, a)])
    return out


def render(cfg: dict, killed: dict | None = None) -> str:
    """The whole rules page as Markdown. Deterministic: the same config gives the same text."""
    a, lim, core = cfg["active"], cfg["limits"], cfg["core"]
    rows = strategies(cfg, killed)
    L = ["# What the demo agent buys and sells, and why",
         "",
         f"Generated from `agent/market_agent/config.json` ({cfg['version']}) by `python3 -m market_agent rules`. "
         "Do not edit by hand: change the config or `rules.py`, then run "
         "`python3 -m market_agent rules --write docs/agent/RULES.md`. The tests fail if this page is out of date.",
         "",
         "Demo account only. No strategy here has passed the go-live rule; each is a small forward test.",
         "",
         "## The book",
         "",
         f"- Core: everything not in a strategy is held in VWRP. Spare cash above £{core['invest_cash_above_gbp']:.0f} "
         "is put into VWRP.",
         f"- Listed exits: {', '.join(t.split('_')[0].rstrip('l') for t in cfg['exits']['tickers'])} are sold in full whenever held.",
         f"- Single-name cap: {_pct(lim['max_name_weight'])} of the book (VWRP exempt).",
         f"- Order limits: at most £{lim['max_order_gbp']:.0f} an order, {lim['max_orders_per_day']} orders and "
         f"£{lim['max_turnover_gbp_per_day']:.0f} of trading a day. Buys only from the approved list of "
         f"{len(lim['buy_whitelist'])} tickers.",
         f"- Short-term sleeve brakes: no new short-term buys for the day after a loss of {_pct(a['daily_loss_stop'])} of "
         f"the book in one day; frozen for good if the sleeve loses {_pct(a['freeze_loss'])} of its £{a['sleeve_start_gbp']:.0f} start.",
         f"- Cash kept back: {_pct(a['cash_reserve_weight'])} of the book while short-term strategies are on.",
         "- Self-check: on every broker pass the agent tests nine promises about the whole book (every holding that "
         "needs a stop has one resting at the broker, nothing is held without a rule that will sell it, no overdue "
         "exits, no unknown orders or positions, no oversized or unpriced holdings) and raises an alert when one "
         "stays broken. `python3 -m market_agent audit` prints the latest result.",
         "",
         "## Strategies at a glance",
         "",
         "| Strategy | Status | Size | Evidence |",
         "|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['name']} | {r['status']} | {r['size']} | {r['evidence']} |")
    for r in rows:
        L += ["", f"## {r['name']}", "", f"Status: {r['status']}. Size: {r['size']}.", "", "Buys when:", ""]
        L += [f"- {b}" for b in r["buys"] if b]
        L += ["", "Sells when (whichever comes first):", ""]
        L += [f"- {s}" for s in r["sells"]]
    return "\n".join(L) + "\n"
