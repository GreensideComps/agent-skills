"""Read-only health and market monitor, run between trading runs (hourly routine).

It never places, modifies or cancels orders: the T212 client is wrapped in ReadOnlyClient. It checks:
  - the account can be read, and value / drawdown since inception and since the peak;
  - holdings match what the trend signal says they should be (a mismatch means a run failed or was skipped);
  - no orders are left pending;
  - how close the signal symbol is to its moving average on the live price (a flip warns that the next
    run will trade - the strategy still trades only at the daily run, as backtested);
  - large intraday moves in held instruments;
  - the trading run itself: last run age, run_failed / order_ambiguous / order_rejected since then;
  - the KILL switch.
Alerts: INFO (noted), WARN (worth a look), CRITICAL (needs attention now). Exit code 0 / 1 / 2.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .signals import sma_state

FLIP_WARN_GAP = 0.01          # signal within 1% of its moving average
INTRADAY_WARN = -0.05         # held instrument down 5% today
INTRADAY_CRIT = -0.10
DD_WARN, DD_CRIT = -0.15, -0.30
WEIGHT_TOL = 0.10             # holdings vs target weight
RUN_STALE = timedelta(days=4)  # covers a weekend + one missed run


def _alert(alerts, level, msg):
    alerts.append({"level": level, "msg": msg})


def check(cfg, journal, ro, quotes, daily_loader, now: datetime, kill_file: Path) -> dict:
    alerts: list[dict] = []
    out: dict = {"ts_utc": now.isoformat(timespec="seconds"), "strategy": cfg.name}

    # ---- trading run health (from the journal, no network)
    runs = journal.events("run_start")
    last_run = runs[-1] if runs else None
    if last_run is None:
        _alert(alerts, "WARN", "no trading run recorded yet")
    else:
        age = now - datetime.fromisoformat(last_run["ts_utc"])
        out["last_run_utc"] = last_run["ts_utc"]
        if age > RUN_STALE:
            _alert(alerts, "CRITICAL", f"trading bot has not run for {age.days} days")
        since = [e for e in journal.events() if e.get("run_id") == last_run.get("run_id")]
        for e in since:
            if e.get("kind") in ("run_failed", "order_ambiguous", "order_rejected"):
                _alert(alerts, "CRITICAL", f"last run: {e['kind']} {e.get('error') or e.get('reason') or ''}".strip())
    if kill_file.exists():
        _alert(alerts, "WARN", "trading/KILL is present: the bot will not trade")

    # ---- account
    try:
        summ, pos, pend = ro.account_summary(), ro.positions(), ro.pending_orders()
    except Exception as e:  # report, never guess
        _alert(alerts, "CRITICAL", f"account read failed: {type(e).__name__}: {e}")
        return _finish(out, alerts, journal)
    total = float(summ["totalValue"])
    cash = float(summ["cash"]["availableToTrade"])
    out.update(total_value_gbp=total, cash_gbp=cash)
    inception = float((journal.load_state().get("inception") or {}).get("total_value_gbp") or total)
    values = [float(s["total_value_gbp"]) for s in journal.snapshots()] + \
             [float(e["total_value_gbp"]) for e in journal.events("monitor") if e.get("total_value_gbp")] + [total]
    peak = max(values)
    out.update(return_since_inception=total / inception - 1, drawdown_from_peak=total / peak - 1, peak_gbp=peak)
    dd = total / peak - 1
    if dd <= DD_CRIT:
        _alert(alerts, "CRITICAL", f"account {dd:.1%} below its peak £{peak:.2f}")
    elif dd <= DD_WARN:
        _alert(alerts, "WARN", f"account {dd:.1%} below its peak £{peak:.2f}")
    if pend:
        _alert(alerts, "WARN", f"{len(pend)} pending order(s) on the account")
    weights = {p["instrument"]["ticker"]: float(p["walletImpact"]["currentValue"]) / total for p in pos} if total > 0 else {}
    out["weights"] = {k: round(v, 4) for k, v in weights.items()}

    # ---- signal on live price vs moving average
    targets = dict(cfg.targets)
    sig = cfg.signal
    if sig:
        try:
            closes = daily_loader(sig["symbol"])["adjclose"]
            st = sma_state(closes, int(sig["window"]), now.date(), int(sig.get("max_age_days", 5)))
            targets = dict(sig["on_targets"] if st["on"] else (sig.get("off_targets") or {}))
            live = quotes.quote(sig["symbol"])
            # live estimate of today's SMA: last window-1 completed closes + the live price
            s = closes.dropna()
            s = s[s.index.date < now.date()]
            sma_live = (float(s.iloc[-(int(sig["window"]) - 1):].sum()) + live.price) / int(sig["window"])
            gap_live = live.price / sma_live - 1
            out["signal"] = {"symbol": sig["symbol"], "on_at_last_close": st["on"], "gap_at_last_close": round(st["gap"], 4),
                             "live_price": live.price, "live_gap": round(gap_live, 4), "live_as_of": live.as_of.isoformat()}
            if (gap_live > 0) != st["on"]:
                _alert(alerts, "WARN", f"{sig['symbol']} has crossed its {sig['window']}-day average intraday "
                                       f"(gap {gap_live:+.2%}); if it closes there the next run will switch "
                                       f"{'into' if gap_live > 0 else 'out of'} the position")
            elif abs(gap_live) < FLIP_WARN_GAP:
                _alert(alerts, "INFO", f"{sig['symbol']} is {gap_live:+.2%} from its {sig['window']}-day average")
        except Exception as e:
            _alert(alerts, "CRITICAL", f"signal data problem: {type(e).__name__}: {e}")
    if getattr(cfg, "mode", "rules") == "discretionary":
        try:
            from .config import load_discretionary
            targets = load_discretionary(cfg)["targets"]
        except Exception as e:
            _alert(alerts, "CRITICAL", f"discretionary targets unreadable: {e}")
    held_target = {t: w * (1 - cfg.cash_buffer_pct) for t, w in targets.items()}
    for t in set(held_target) | set(weights):
        diff = weights.get(t, 0.0) - held_target.get(t, 0.0)
        if abs(diff) > WEIGHT_TOL:
            _alert(alerts, "WARN", f"{t} is {weights.get(t, 0.0):.0%} of the account vs target {held_target.get(t, 0.0):.0%}")

    # ---- intraday moves of what is held
    moves = {}
    for p in pos:
        t = p["instrument"]["ticker"]
        sym = cfg.yahoo_symbols.get(t)
        if not sym:
            continue
        try:
            d = daily_loader(sym)["close"].dropna()
            prev = d[d.index.date < now.date()]
            q = quotes.quote(sym)
            prev_close = float(prev.iloc[-1]) / (100.0 if q.currency == "GBP" and float(prev.iloc[-1]) > 20 * q.price else 1.0)
            mv = q.price / prev_close - 1
            moves[t] = round(mv, 4)
            if mv <= INTRADAY_CRIT:
                _alert(alerts, "CRITICAL", f"{t} down {mv:.1%} today")
            elif mv <= INTRADAY_WARN:
                _alert(alerts, "WARN", f"{t} down {mv:.1%} today")
        except Exception as e:
            _alert(alerts, "WARN", f"no intraday price for {t}: {type(e).__name__}")
    out["intraday_moves"] = moves
    return _finish(out, alerts, journal)


def _finish(out, alerts, journal):
    out["alerts"] = alerts
    lv = {a["level"] for a in alerts}
    out["exit"] = 2 if "CRITICAL" in lv else 1 if "WARN" in lv else 0
    journal.event("monitor", **{k: v for k, v in out.items() if k != "exit"})
    return out


def run(now: datetime | None = None) -> dict:
    from .client import T212Client
    from .config import load_credentials, load_strategy
    from .journal import Journal
    from .market import YahooQuotes
    from .readonly import ReadOnlyClient
    from .shadow import yahoo_daily
    root = Path(__file__).resolve().parent.parent
    ro = ReadOnlyClient(T212Client(load_credentials()))
    return check(load_strategy(), Journal(), ro, YahooQuotes(), yahoo_daily, now or datetime.now(timezone.utc), root / "KILL")
