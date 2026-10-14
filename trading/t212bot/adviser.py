"""Opportunistic profit-withdrawal adviser: RECOMMENDATIONS ONLY.

Safety boundary
---------------
This module has no access to an API client. It is a pure function of numbers
handed to it, so it cannot place orders, sell holdings, move money or withdraw.
(The Trading 212 public API has no withdrawal/transfer endpoint anyway.)
Any action needs the account owner's explicit approval, taken by them.

Decision policy
---------------
The default is GBP 0. For a long-term compounding objective, money left
invested is expected (not guaranteed) to grow, so taking it out has a cost.
A positive amount is recommended only when one of these owner-configured,
defensible reasons applies (all off by default):

  LIQUIDITY_NEED       a planned expense is due within `liquidity_need_lead_days`;
                       selling ahead of time avoids being forced to sell in a slump
  ABOVE_CAPITAL_CAP    the account exceeds the owner's maximum capital-at-risk
  PROFIT_LOCK          gains exceed a threshold of contributions and set a new
                       high; harvest a fraction of the *new* gains only

Guards: unreliable data (failed reconciliation, stale or missing data) gives
GBP 0; amounts below the "meaningful" threshold give GBP 0; never more than
the account holds; rounded down to whole pounds.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date

from .wrappers import withdrawal_notes


@dataclass
class Holding:
    ticker: str
    value_gbp: float
    currency: str            # instrument currency (GBP/GBX → 'GBP')
    unrealized_pl_gbp: float


@dataclass
class AdviserInput:
    as_of: date
    total_value: float
    free_cash: float
    net_contributions: float
    holdings: list[Holding]
    twr: float | None = None
    drawdown_from_hwm: float | None = None
    data_reliable: bool = True
    reliability_issues: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    as_of: str
    amount_gbp: float
    reason_code: str
    headline: str
    gain_gbp: float
    explanation: list[str]
    calculation: list[str]
    assumptions: list[str]
    uncertainty: str
    scenarios: list[dict]
    effect: dict
    selling_required_gbp: float
    sell_plan: list[dict]
    est_selling_cost_gbp: float
    wrapper_notes: list[str]
    candidates: list[dict]
    safety: str = "Recommendation only. Nothing is sold, transferred or withdrawn without your explicit action."

    def to_dict(self):
        return asdict(self)


def _fv(v: float, r: float, years: float) -> float:
    return v * (1 + r) ** years


def _floor_pounds(x: float) -> float:
    return float(math.floor(max(0.0, x)))


def scenario_table(value: float, amounts: list[float], cfg: dict) -> list[dict]:
    sc = cfg["scenarios"]
    H = cfg["horizon_years"]
    rows = []
    for w in amounts:
        row = {"withdraw_gbp": round(w, 2), "remaining_now_gbp": round(value - w, 2)}
        for k in ("conservative", "base", "adverse"):
            r = sc[k]
            row[f"{k}_portfolio_in_{H}y"] = round(_fv(value - w, r, H), 2)
            row[f"{k}_compounding_cost"] = round(_fv(w, r, H) - w, 2)  # growth forgone on w
        row["shock_loss_avoided_on_withdrawn"] = round(-sc["shock_drawdown"] * w, 2)
        rows.append(row)
    return rows


def sell_plan_for(amount: float, inp: AdviserInput, cfg: dict) -> tuple[float, list[dict], float, float]:
    buffer = cfg["cash_buffer_pct"] * inp.total_value
    usable_cash = max(0.0, inp.free_cash - buffer)
    need = max(0.0, amount - usable_cash)
    invested = sum(h.value_gbp for h in inp.holdings)
    plan, cost, realised = [], 0.0, 0.0
    if need > 0 and invested > 0:
        for h in inp.holdings:
            share = h.value_gbp / invested
            sell = need * share
            c = sell * cfg["sell_cost_pct"]["GBP" if h.currency == "GBP" else "OTHER"]
            g = (sell / h.value_gbp) * h.unrealized_pl_gbp if h.value_gbp > 0 else 0.0
            plan.append({"ticker": h.ticker, "sell_gbp": round(sell, 2), "est_cost_gbp": round(c, 2), "est_realised_gain_gbp": round(g, 2)})
            cost += c
            realised += g
    return need, plan, cost, realised


def advise(inp: AdviserInput, cfg: dict, state: dict | None = None) -> Recommendation:
    state = state or {}
    gain = inp.total_value - inp.net_contributions
    H, sc = cfg["horizon_years"], cfg["scenarios"]
    assumptions = [
        f"Scenario annual returns are assumptions, not forecasts: conservative {sc['conservative']:.0%}, base {sc['base']:.0%}, "
        f"adverse {sc['adverse']:.0%} for {H} years; shock = immediate {sc['shock_drawdown']:.0%} fall. {sc.get('_source', '')}",
        f"Withdrawn money is assumed to be spent or held outside the portfolio, so it earns nothing further in these figures.",
        f"Selling costs assumed {cfg['sell_cost_pct']['GBP']:.2%} (GBP lines) / {cfg['sell_cost_pct']['OTHER']:.2%} (non-GBP, incl. FX fee).",
    ]
    calc = [f"Total value £{inp.total_value:.2f} − net contributions £{inp.net_contributions:.2f} = investment gain £{gain:+.2f}."]
    if inp.twr is not None:
        calc.append(f"Time-weighted return since inception {inp.twr:+.2%} (deposits/withdrawals excluded).")

    # ------------------------------------------------------------ candidates
    candidates: list[dict] = []
    for need in cfg.get("liquidity_needs") or []:
        due = date.fromisoformat(need["by"])
        days = (due - inp.as_of).days
        if 0 <= days <= cfg.get("liquidity_need_lead_days", 90):
            candidates.append({"reason_code": "LIQUIDITY_NEED", "amount": float(need["amount"]),
                               "why": f"planned need '{need.get('label', 'unlabelled')}' of £{float(need['amount']):.2f} due {due} ({days} days)"})
    cap = cfg.get("max_capital_at_risk_gbp")
    if cap is not None and inp.total_value > cap:
        candidates.append({"reason_code": "ABOVE_CAPITAL_CAP", "amount": inp.total_value - cap,
                           "why": f"account £{inp.total_value:.2f} exceeds your maximum capital at risk £{cap:.2f}"})
    pl = cfg.get("profit_lock", {})
    if pl.get("enabled") and inp.net_contributions > 0:
        threshold = pl["min_gain_pct_of_contributions"] * inp.net_contributions
        harvested_hwm = float(state.get("profit_lock_gain_hwm", 0.0))
        if gain >= threshold and gain > harvested_hwm:
            amt = pl["harvest_fraction_of_new_gains"] * (gain - max(harvested_hwm, 0.0))
            candidates.append({"reason_code": "PROFIT_LOCK", "amount": amt,
                               "why": f"gain £{gain:.2f} ≥ threshold £{threshold:.2f} and above the last harvested high £{harvested_hwm:.2f}"})

    # ------------------------------------------------------------ decision
    reason, amount, why = "NO_DEFENSIBLE_REASON", 0.0, []
    if not inp.data_reliable:
        reason = "DATA_NOT_RELIABLE"
        why.append("Account data did not reconcile or is stale/missing, so no withdrawal can be justified until it is fixed: "
                   + "; ".join(inp.reliability_issues))
    elif candidates:
        best = max(candidates, key=lambda c: c["amount"])
        reason, amount = best["reason_code"], best["amount"]
        why.append(f"Reason: {best['why']}.")
        meaningful = max(cfg["min_meaningful_withdrawal_gbp"], cfg["min_meaningful_withdrawal_pct_of_value"] * inp.total_value)
        if reason != "LIQUIDITY_NEED" and amount < meaningful:
            why.append(f"The candidate £{amount:.2f} is below the meaningful threshold £{meaningful:.2f} "
                       "(costs and lost compounding outweigh so small a withdrawal).")
            reason, amount = "BELOW_MEANINGFUL_THRESHOLD", 0.0
        max_out = inp.total_value * (1 - cfg["cash_buffer_pct"])
        if amount > max_out:
            why.append(f"Capped at £{max_out:.2f}, the most the account can release while keeping its cash buffer.")
            amount = max_out
        if amount > max(gain, 0) and amount > 0:
            why.append(f"This exceeds the investment gain (£{max(gain, 0):.2f}), so it would return some of your own contributions, not just profit.")
    else:
        if gain <= 0:
            why.append("There is no investment gain to take: the account is at or below the money you put in.")
        else:
            why.append("No configured reason applies (no planned expense due, no capital cap exceeded, profit-lock not enabled or not triggered). "
                       "A rise in value alone is not a reason to withdraw.")
    amount = _floor_pounds(amount)

    # ------------------------------------------------------------ consequences
    illustrative = sorted({amount, *[_floor_pounds(f * max(gain, 0)) for f in (0.25, 0.5, 1.0)]} - {0.0})
    table_amounts = [0.0] + illustrative
    scenarios = scenario_table(inp.total_value, table_amounts, cfg)
    need, plan, sell_cost, realised = sell_plan_for(amount, inp, cfg)
    effect = {"remaining_value_gbp": round(inp.total_value - amount, 2),
              "remaining_gain_gbp": round(gain - amount, 2),
              f"base_case_value_in_{H}y_if_retained": round(_fv(inp.total_value, sc["base"], H), 2),
              f"base_case_value_in_{H}y_after_withdrawal": round(_fv(inp.total_value - amount, sc["base"], H), 2)}
    if amount == 0:
        if reason == "DATA_NOT_RELIABLE":
            because = "today's account data could not be fully verified, so no withdrawal can be justified"
        elif reason == "BELOW_MEANINGFUL_THRESHOLD":
            because = "the amount a configured rule suggests is too small to be worth the cost to future compounding"
        elif gain <= 0:
            because = "there is no investment gain to take"
        else:
            because = ("none of your configured reasons for taking money out applies, and a rise in value alone is not a reason "
                       f"(the expected cost to future compounding outweighs the benefit: taking the whole £{gain:.2f} gain would forgo "
                       f"about £{_fv(gain, sc['base'], H) - gain:.2f} of growth over {H} years in the base case)")
        headline = (f"Your portfolio has {'increased' if gain >= 0 else 'decreased'} by £{abs(gain):.2f} after adjusting for deposits and "
                    f"withdrawals. I recommend withdrawing £0 because {because}.")
    else:
        sell_txt = f" Funding it requires selling about £{need:.2f} of investments (est. cost £{sell_cost:.2f})." if need > 0 else " It can be paid from available cash without selling."
        headline = (f"Your portfolio has increased by £{gain:.2f} after adjusting for deposits and withdrawals. "
                    f"I recommend considering a withdrawal of £{amount:.0f} ({reason.replace('_', ' ').lower()}).{sell_txt} "
                    "Nothing will happen unless you choose to do it yourself.")
    uncertainty = ("The scenario figures show sensitivity to assumed returns, not predictions. Future returns may be far outside this range "
                   "in either direction, and past returns do not guarantee future results.")
    return Recommendation(
        as_of=inp.as_of.isoformat(), amount_gbp=amount, reason_code=reason, headline=headline, gain_gbp=round(gain, 2),
        explanation=why, calculation=calc, assumptions=assumptions, uncertainty=uncertainty, scenarios=scenarios,
        effect=effect, selling_required_gbp=round(need, 2), sell_plan=plan, est_selling_cost_gbp=round(sell_cost, 2),
        wrapper_notes=withdrawal_notes(cfg.get("account_type", ""), cfg, amount, realised), candidates=candidates)


# ---------------------------------------------------------------- events & notification de-duplication

def detect_events(state: dict, gain: float, drawdown: float | None, net_contributions: float, rec: Recommendation) -> list[str]:
    ev = []
    if gain > float(state.get("gain_hwm", float("-inf"))):
        ev.append(f"new investment-gain high (£{gain:.2f})")
    if net_contributions != state.get("net_contributions", net_contributions):
        ev.append(f"deposit/withdrawal detected (net contributions now £{net_contributions:.2f})")
    for lvl in (-0.10, -0.20, -0.30):
        if drawdown is not None and drawdown <= lvl and float(state.get("worst_drawdown_alerted", 0.0)) > lvl:
            ev.append(f"drawdown breached {lvl:.0%}")
    if rec.reason_code != state.get("last_reason_code"):
        ev.append(f"recommendation basis changed to {rec.reason_code}")
    return ev


def should_notify(rec: Recommendation, state: dict, cfg: dict, today: date) -> tuple[bool, str]:
    last = state.get("last_notified")
    n = cfg.get("notify", {})
    if rec.amount_gbp <= 0:
        if last and last.get("amount_gbp", 0) > 0:
            return True, "previous withdrawal recommendation no longer stands"
        return False, "£0 recommendation - reported in the daily report only"
    if not last:
        return True, "first positive recommendation"
    if last.get("reason_code") != rec.reason_code:
        return True, "different reason"
    if abs(rec.amount_gbp - float(last.get("amount_gbp", 0))) >= n.get("amount_change_threshold_gbp", 10.0):
        return True, "amount changed materially"
    days = (today - date.fromisoformat(last["date"])).days
    if days >= n.get("min_days_between_same_recommendation", 30):
        return True, f"reminder after {days} days"
    return False, f"same recommendation already sent {days} day(s) ago"


def update_state(state: dict, rec: Recommendation, gain: float, drawdown: float | None, net_contributions: float,
                 notified: bool, today: date) -> dict:
    s = dict(state)
    s["gain_hwm"] = max(float(s.get("gain_hwm", float("-inf"))), gain)
    s["net_contributions"] = net_contributions
    s["last_reason_code"] = rec.reason_code
    s["last_eval"] = today.isoformat()
    if drawdown is not None:
        s["worst_drawdown_alerted"] = min(float(s.get("worst_drawdown_alerted", 0.0)), drawdown)
    if notified:
        s["last_notified"] = {"date": today.isoformat(), "amount_gbp": rec.amount_gbp, "reason_code": rec.reason_code}
        if rec.reason_code == "PROFIT_LOCK" and rec.amount_gbp > 0:
            # A withdrawal lowers value and net contributions equally, so the measured gain
            # does not fall; record the harvested level so only NEW gains count next time.
            s["profit_lock_gain_hwm"] = gain
    return s
