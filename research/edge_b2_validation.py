"""B2: run the synthetic validation suite for the portfolio backtester and write the validation report.

Synthetic data only (owner, 2026-10-15 12:41Z). Nothing here reads the research dataset or any price file.
Usage: python3 edge_b2_validation.py  ->  equity/reports/research/edge/b2_validation.md
"""
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import edge_backtest as bt
import edge_rules

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "equity" / "reports" / "research" / "edge" / "b2_validation.md"

ITEMS = {
    "1": "Planted signal recovered; random scores earn nothing",
    "2": "Hand-computed 5-company portfolio (NAV, holdings, turnover, costs)",
    "3": "Buffers, sector cap, weighting",
    "4": "Costs by band, scaled exactly by the multiplier",
    "5": "Exclusions: quality flag, price under $1, other bands",
    "6": "Timing: no look-ahead, execution after the decision, 2023 refused, robustness convention",
    "7": "Missing prices for new entries and holdings",
    "8": "Currency conversion",
    "9": "Benchmark metrics and VWRP/VWRL labels",
    "10": "Registration, result records and DSR pooling",
}


def run_suite(xml: Path) -> list[dict]:
    subprocess.run([sys.executable, "-m", "pytest", str(ROOT / "tests" / "test_edge_backtest.py"), "-q",
                    f"--junitxml={xml}"], cwd=ROOT, check=False)
    out = []
    for tc in ET.parse(xml).getroot().iter("testcase"):
        failed = tc.find("failure") is not None or tc.find("error") is not None
        m = re.match(r"test_(\d+)_", tc.get("name"))
        out.append({"name": tc.get("name"), "item": m.group(1) if m else "report", "passed": not failed})
    return out


def body(tests: list[dict]) -> str:
    n_ok = sum(t["passed"] for t in tests)
    verdict = "**PASS**" if n_ok == len(tests) else "**FAIL**"
    lines = [f"Run {datetime.now(timezone.utc).isoformat(timespec='seconds')}. Synthetic data only: no research "
             "dataset, price file or holdout value is read. No signal is explored and no trial is run.", "",
             f"## Result: {verdict}, {n_ok} of {len(tests)} tests pass", "",
             "| Plan item (PHASE_B_PLAN.md §3) | Tests | Passed |", "|---|---:|---:|"]
    for k, label in ITEMS.items():
        ts = [t for t in tests if t["item"] == k]
        lines.append(f"| {k}. {label} | {len(ts)} | {sum(t['passed'] for t in ts)} |")
    rep = [t for t in tests if t["item"] == "report"]
    lines.append(f"| Reports open with the standing limitations | {len(rep)} | {sum(t['passed'] for t in rep)} |")
    lines += ["", "Every test: `research/tests/test_edge_backtest.py`. Failing tests, if any: "
              + (", ".join(t["name"] for t in tests if not t["passed"]) or "none") + ".", "", MEANING]
    return "\n".join(lines)


MEANING = """## What was validated

- **Portfolio engine** (`research/edge_backtest.py`):
  - A planted signal (return = 0.02 × last month's score + noise) earns the expected excess over the
    equal-weighted pool, within 25%, with t > 5.
  - Random scores over 8 seeds average under 0.3%/month.
  - A 4-month, 5-company portfolio matches an independent hand calculation to 1e-12: NAV, holdings,
    turnover and costs.
- **Timing:**
  - Changing every score and price after month k leaves holdings and NAV through month k identical.
  - Every trade date is strictly after its decision.
  - A same-day trade raises `LookAhead`. Any 2023 row or execution date raises `HoldoutViolation`.
  - The next-month-close convention trades at the following month-end.
- **Missing prices**, as listed in `PHASE_B_PLAN.md` §7.2:
  - A new entry with `missing_exec`, `invalid_price` or no row is skipped and logged. `stale_month_end` blocks
    a purchase but still values a holding.
  - A holding that loses its price exits at the last valid price less 30%. The cash earns 0% until the next
    rebalance, and NAV accounts for every position.
  - Results order 0% ≥ −30% ≥ −100%. Even the 0% bound stops at the last price, and a positive assumption
    is refused.
- **Costs:**
  - Per band, 0.30% large, 0.45% mid and 0.75% small per unit of weight traded (FX 0.15% + spread).
  - The 2x and 3x multipliers scale them exactly.
- **FX:**
  - A constant rate leaves returns unchanged.
  - A known GBP/USD path converts exactly.
- **Constraints:**
  - Rank buffer (hold to 2N).
  - Sector cap never exceeded; skipped names are logged.
  - Equal, score and inverse-volatility weights sum to 1.
  - Quality-flagged rows, prices under $1 and other bands are never bought.
- **Benchmark:**
  - Tracking error, information ratio, share of months ahead and relative drawdown match a hand calculation.
  - The label switches to "actual VWRP" at the period starting 2019-08-01 (VWRP's first full month; see
    `PHASE_B_PLAN.md` §7.4).
  - A 2023 benchmark value is refused.
- **Governance:**
  - An unregistered trial, or one already reported, is refused.
  - Results record their statistic.
  - The DSR pools only portfolio results and uses the registry's trial count.
- **Mutation check:** to confirm the tests can fail, three deliberate bugs were injected one at a time, then
  reverted:
  - ignoring the missing-price markdown made 5 tests fail;
  - ignoring the cost multiplier made 9 fail;
  - letting stale-price names be bought made 1 fail.

## Not validated here (and why)

- **Real-data behaviour.** B2 is synthetic by instruction; the first real run is B3, which needs the owner's
  approval and a registered trial.
- **The Ken French proxy segment before 2012-06.** It is not built; `benchmark_returns` labels those periods
  "none". Trials start in 2015 (the VWRL segment), so the proxy is needed only for an explicit pre-2012
  robustness run.
- **Stage 2 reproduction through the new engine** (PHASE_B_PLAN.md §4, B3 gate). It uses real data, so it
  waits for approval.
- **Survivorship bias.** Software cannot test this away; see the standing limitations above.
"""


def main() -> None:
    xml = ROOT / ".b2_junit.xml"
    try:
        tests = run_suite(xml)
    finally:
        xml.unlink(missing_ok=True)
    text = edge_rules.require_disclosure(bt.report("B2 validation: portfolio backtester on synthetic data", {},
                                                   body(tests)))
    OUT.write_text(text)
    print(f"{sum(t['passed'] for t in tests)}/{len(tests)} passed -> {OUT}")


if __name__ == "__main__":
    main()
