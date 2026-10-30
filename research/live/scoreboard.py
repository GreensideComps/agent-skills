#!/usr/bin/env python3
"""Demo strategy scoreboard: each strategy tag vs VWRP over the same days, after costs.

Reads only the market agent's own records in /mnt/project-files/market-agent/state
(intents journal with broker fills, and the snapshot events for VWRP prices and
open-position values). Writes SCOREBOARD.json and SCOREBOARD.md next to this file.

Rules applied (see GO_LIVE_RULE.md, pre-registered 30 Oct 2026):
- a trade = one active entry fill, closed by later filled sells of the same ticker
  that are not satellite trims / authorised exits (FIFO by quantity);
- net return uses the broker's walletImpact netValue (FX fee included) both ways;
  open trades are marked at the latest snapshot value less a 0.15% exit FX fee;
- VWRP return = VWRP GBP price at exit (or now) / price at entry - 1, from snapshots;
- kill rule: after 30 closed trades, mean excess vs VWRP <= 0 -> KILL;
- go-live check: see GO_LIVE_RULE.md section 2 (computed here, reported by Claude).

Run: python3 scoreboard.py [--state DIR] [--out DIR]
"""
import argparse
import datetime as dt
import glob
import json
import math
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = "/mnt/project-files/market-agent/state"
EXIT_FX_FEE = 0.0015
VWRP = "VWRPl_EQ"
NON_STRATEGY_SELLS = {"satellite_trim", "authorised_exit", "core_invest"}
# Every strategy tag ever switched on in the demo active sleeve. Killed tags stay
# listed: they count towards the multiple-testing adjustment in the go-live rule.
REGISTERED = ["drop_rebound", "breakout_momentum", "social_trend", "merger_arb", "vol_squeeze", "gap_go", "attention_spike"]
KILL_AFTER = 30
GO_LIVE_MIN_TRADES = 30
GO_LIVE_MIN_DAYS = 91
ALPHA = 0.05


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def t_crit(df, p):
    """One-sided Student t critical value (no scipy): bisection on the t CDF."""
    def cdf(x):
        # regularised incomplete beta via continued fraction
        a, b = df / 2.0, 0.5
        z = df / (df + x * x)
        lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
        front = math.exp(a * math.log(z) + b * math.log(1 - z) - lbeta) / a
        f, c, d = 1.0, 1.0, 0.0
        for i in range(200):
            m = i // 2
            if i == 0:
                num = 1.0
            elif i % 2 == 0:
                num = (m * (b - m) * z) / ((a + 2 * m - 1) * (a + 2 * m))
            else:
                num = -((a + m) * (a + b + m) * z) / ((a + 2 * m) * (a + 2 * m + 1))
            d = 1.0 + num * d
            d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
            c = 1.0 + num / (c if abs(c) > 1e-30 else 1e-30)
            f *= c * d
            if abs(1.0 - c * d) < 1e-12:
                break
        tail = front * (f - 1.0) / 2.0
        return 1 - tail if x > 0 else tail
    lo, hi = 0.0, 50.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if 1 - cdf(mid) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def load(state):
    intents, fills = {}, []
    for line in open(os.path.join(state, "intents", "intents.jsonl")):
        d = json.loads(line)
        if d.get("status") == "intended":
            intents[d["id"]] = d
        elif d.get("status") == "filled" and d.get("broker", {}).get("fill"):
            fills.append(d)
    snaps = []
    for f in sorted(glob.glob(os.path.join(state, "events", "*.jsonl"))):
        for line in open(f):
            if '"snapshot"' not in line:
                continue
            d = json.loads(line)
            if d.get("kind") == "snapshot":
                snaps.append(d)
    snaps.sort(key=lambda s: s["t"])
    return intents, fills, snaps


def vwrp_series(snaps):
    out = []
    for s in snaps:
        for r in s.get("rows", []):
            if r["ticker"] == VWRP and r.get("qty"):
                out.append((s["t"], r["value_gbp"] / r["qty"]))
    return out


def price_at(series, t):
    """Last VWRP price at or before t; the first one after t if none before."""
    best = None
    for ts, px in series:
        if ts <= t:
            best = px
        else:
            return best if best is not None else px
    return best


def build_trades(intents, fills, snaps, vw):
    rows = []
    for f in fills:
        fill = f["broker"]["fill"]
        sig = (intents.get(f["id"]) or {}).get("signal") or {}
        rows.append({
            "id": f["id"], "ticker": f["broker"]["order"]["ticker"],
            "t": parse_ts(fill["filledAt"]), "qty": fill["quantity"],
            "net": fill["walletImpact"]["netValue"],
            "fees": -sum(x.get("quantity", 0) for x in fill["walletImpact"].get("taxes", [])),
            "type": sig.get("type"), "strategy": sig.get("strategy"),
            "vwrp_px": sig.get("vwrp_px"), "reason": sig.get("exit_reason") or sig.get("reason"),
        })
    rows.sort(key=lambda r: r["t"])
    trades, open_by_ticker = [], {}
    for r in rows:
        if r["qty"] > 0 and r["strategy"] and r["type"] not in NON_STRATEGY_SELLS:
            tr = {"strategy": r["strategy"], "ticker": r["ticker"], "entry_t": r["t"],
                  "qty": r["qty"], "left": r["qty"], "cost": r["net"], "fees": r["fees"],
                  "proceeds": 0.0, "exit_t": None, "exit_reason": None,
                  "vwrp_entry": r["vwrp_px"] or price_at(vw, r["t"])}
            trades.append(tr)
            open_by_ticker.setdefault(r["ticker"], []).append(tr)
        elif r["qty"] < 0 and r["type"] not in NON_STRATEGY_SELLS:
            q = -r["qty"]
            for tr in open_by_ticker.get(r["ticker"], []):
                if q <= 1e-9 or tr["left"] <= 1e-9 or tr["entry_t"] > r["t"]:
                    continue
                take = min(q, tr["left"])
                share = take / q
                tr["proceeds"] += r["net"] * share
                tr["fees"] += r["fees"] * share
                tr["left"] -= take
                q -= take
                if tr["left"] <= 1e-6:
                    tr["exit_t"], tr["exit_reason"] = r["t"], r["reason"]
    # mark the rest from the latest snapshot; a position gone from the book with no
    # recorded sell (e.g. a broker-held stop) is closed at its last seen value, flagged
    last = snaps[-1] if snaps else None
    now = last["t"] if last else None
    for tr in trades:
        if tr["exit_t"]:
            tr["status"] = "closed"
            continue
        held = {r["ticker"]: r for r in (last or {}).get("rows", [])}
        if tr["ticker"] in held:
            row = held[tr["ticker"]]
            val = row["value_gbp"] * min(1.0, tr["left"] / row["qty"]) if row["qty"] else 0
            tr["proceeds"] += val * (1 - EXIT_FX_FEE)
            tr["status"], tr["mark_t"] = "open", now
        else:
            seen = None
            for s in snaps:
                if s["t"] < tr["entry_t"]:
                    continue
                for row in s.get("rows", []):
                    if row["ticker"] == tr["ticker"]:
                        seen = (s["t"], row["value_gbp"])
            if seen:
                tr["proceeds"] += seen[1] * (1 - EXIT_FX_FEE)
                tr["exit_t"], tr["exit_reason"] = seen[0], "left the book with no recorded sell (estimated)"
            tr["status"] = "closed_estimated" if seen else "unknown"
    for tr in trades:
        end = tr["exit_t"] or tr.get("mark_t") or tr["entry_t"]
        v0, v1 = tr["vwrp_entry"], price_at(vw, end)
        tr["net_ret"] = tr["proceeds"] / tr["cost"] - 1 if tr["cost"] else None
        tr["vwrp_ret"] = (v1 / v0 - 1) if (v0 and v1) else None
        tr["excess"] = (tr["net_ret"] - tr["vwrp_ret"]) if tr["vwrp_ret"] is not None else None
        tr["pnl_gbp"] = tr["proceeds"] - tr["cost"]
        tr["days"] = (end - tr["entry_t"]) / 86400
    return trades, now


def summarise(trades, now):
    tags = list(REGISTERED) + sorted({t["strategy"] for t in trades} - set(REGISTERED))
    k = len(tags)
    out = []
    for tag in tags:
        ts = [t for t in trades if t["strategy"] == tag]
        closed = [t for t in ts if t["status"] in ("closed", "closed_estimated") and t["excess"] is not None]
        ex = [t["excess"] for t in closed]
        n = len(closed)
        mean_ex = statistics.mean(ex) if ex else None
        sd = statistics.stdev(ex) if n > 1 else None
        tstat = mean_ex / (sd / math.sqrt(n)) if (sd and sd > 0) else None
        first = min((t["entry_t"] for t in ts), default=None)
        live_days = (now - first) / 86400 if (first and now) else 0
        crit = t_crit(n - 1, ALPHA / k) if n > 2 else None
        halves = None
        if n >= 2:
            h = n // 2
            halves = [statistics.mean(ex[:h]), statistics.mean(ex[h:])]
        pnl = sum(t["pnl_gbp"] for t in closed)
        vw_pnl = sum(t["cost"] * t["vwrp_ret"] for t in closed)
        if n >= KILL_AFTER:
            kill = "KILL: not beating VWRP after 30 trades" if (mean_ex or 0) <= 0 else "survives the 30-trade check"
        else:
            kill = f"{n}/{KILL_AFTER} closed trades"
        checks = {
            "trades>=30": n >= GO_LIVE_MIN_TRADES,
            "live>=91d": live_days >= GO_LIVE_MIN_DAYS,
            "mean_excess>0": bool(mean_ex and mean_ex > 0),
            "t>=crit": bool(tstat and crit and tstat >= crit),
            "both_halves>0": bool(halves and min(halves) > 0),
            "gbp_beats_vwrp": n > 0 and pnl > vw_pnl,
        }
        out.append({
            "strategy": tag, "trades_total": len(ts), "closed": n,
            "open": sum(1 for t in ts if t["status"] == "open"),
            "win_rate": (sum(1 for t in closed if t["net_ret"] > 0) / n) if n else None,
            "beat_vwrp_rate": (sum(1 for e in ex if e > 0) / n) if n else None,
            "mean_net_ret": statistics.mean([t["net_ret"] for t in closed]) if n else None,
            "mean_vwrp_ret": statistics.mean([t["vwrp_ret"] for t in closed]) if n else None,
            "mean_excess": mean_ex, "sd_excess": sd, "t_stat": tstat, "t_needed": crit,
            "pnl_gbp": round(pnl, 2), "vwrp_same_money_gbp": round(vw_pnl, 2),
            "open_pnl_gbp": round(sum(t["pnl_gbp"] for t in ts if t["status"] == "open"), 2),
            "open_mean_excess": statistics.mean(oe) if (oe := [t["excess"] for t in ts if t["status"] == "open" and t["excess"] is not None]) else None,
            "first_trade": iso(first) if first else None, "live_days": round(live_days, 1),
            "kill_rule": kill, "go_live_checks": checks, "go_live_eligible": all(checks.values()),
        })
    return out, k


def pct(x):
    return "n/a" if x is None else f"{x * 100:+.2f}%"


def write(out_dir, summary, trades, k, now):
    gen = iso(now) if now else iso(dt.datetime.now(dt.timezone.utc).timestamp())
    payload = {"generated_from_snapshot": gen, "rule": "GO_LIVE_RULE.md", "k_strategies": k,
               "alpha_per_strategy": ALPHA / k, "strategies": summary,
               "trades": [{**{x: t[x] for x in ("strategy", "ticker", "status", "exit_reason")},
                           "entry": iso(t["entry_t"]), "exit": iso(t["exit_t"]) if t["exit_t"] else None,
                           "cost_gbp": round(t["cost"], 2), "value_or_proceeds_gbp": round(t["proceeds"], 2),
                           "fees_gbp": round(t["fees"], 2), "net_ret": t["net_ret"], "vwrp_ret": t["vwrp_ret"],
                           "excess": t["excess"], "days": round(t["days"], 2)} for t in trades]}
    tmp = os.path.join(out_dir, "SCOREBOARD.json.tmp")
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, os.path.join(out_dir, "SCOREBOARD.json"))

    L = [f"# Demo strategy scoreboard", "",
         f"As of the agent's snapshot at {gen}. Demo account only. Every return is after Trading 212 costs "
         f"(FX fee both ways; open trades marked less the exit fee). \"vs VWRP\" compares each trade with "
         f"holding VWRP over exactly the same days. No tax: everything will sit in an ISA.", "",
         "| Strategy | Closed | Open | Win rate | Avg net | Avg VWRP same days | Avg excess | Net £ | VWRP £ same money | Open trades: £ / avg excess so far | 30-trade kill rule | Go-live |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in summary:
        wr = "n/a" if s["win_rate"] is None else f"{s['win_rate'] * 100:.0f}%"
        gl = "ELIGIBLE: Claude reports to owner" if s["go_live_eligible"] else \
            f"no ({sum(s['go_live_checks'].values())}/6 checks)"
        L.append(f"| {s['strategy']} | {s['closed']} | {s['open']} | {wr} | {pct(s['mean_net_ret'])} | "
                 f"{pct(s['mean_vwrp_ret'])} | {pct(s['mean_excess'])} | {s['pnl_gbp']:+.2f} | "
                 f"{s['vwrp_same_money_gbp']:+.2f} | {s['open_pnl_gbp']:+.2f} / {pct(s['open_mean_excess'])} | "
                 f"{s['kill_rule']} | {gl} |")
    L += ["", f"Go-live needs all six checks in [GO_LIVE_RULE.md](GO_LIVE_RULE.md). With {k} strategies on test, "
          f"the excess must clear a one-sided t-test at {ALPHA / k:.4f} (Bonferroni).", "", "## Trades", "",
          "| Strategy | Ticker | Status | Entry | Exit | Days | Cost £ | Value £ | Net | VWRP | Excess |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(trades, key=lambda t: t["entry_t"], reverse=True):
        L.append(f"| {t['strategy']} | {t['ticker'].split('_')[0]} | {t['status']} | {iso(t['entry_t'])} | "
                 f"{iso(t['exit_t']) if t['exit_t'] else '-'} | {t['days']:.1f} | {t['cost']:.2f} | "
                 f"{t['proceeds']:.2f} | {pct(t['net_ret'])} | {pct(t['vwrp_ret'])} | {pct(t['excess'])} |")
    if not trades:
        L.append("| - | - | no active trades yet | | | | | | | | |")
    tmp = os.path.join(out_dir, "SCOREBOARD.md.tmp")
    with open(tmp, "w") as fh:
        fh.write("\n".join(L) + "\n")
    os.replace(tmp, os.path.join(out_dir, "SCOREBOARD.md"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    intents, fills, snaps = load(a.state)
    vw = vwrp_series(snaps)
    trades, now = build_trades(intents, fills, snaps, vw)
    summary, k = summarise(trades, now)
    write(a.out, summary, trades, k, now)
    elig = [s["strategy"] for s in summary if s["go_live_eligible"]]
    print(f"scoreboard: {len(trades)} trades, {k} strategies, eligible: {elig or 'none'}")


if __name__ == "__main__":
    main()
