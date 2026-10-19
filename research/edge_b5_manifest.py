"""Writes docs/edge/B5_RUN_MANIFEST.json: the sha256 of every input file and every repository code file the B5 run
reads or imports (`edge_b5_run`). The manifest is registered as B5-V3-RUN-MANIFEST only on the owner's word; after
that, any change to a listed file makes `edge_b5_run.preflight` refuse. `tests/test_edge_b5_run.py` checks that CODE
is exactly the set of repository modules the run path imports, so a new import cannot escape the manifest.

Usage: python3 edge_b5_manifest.py   (never run after registration without a recorded owner decision)
"""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = "/mnt/project-files/research-data"
INPUTS = [f"{DATA}/monthly_metrics.csv.gz", f"{DATA}/prices_monthly.csv.gz", f"{DATA}/sec_companies.csv.gz",
          f"{DATA}/sec_facts_panel.csv.gz", f"{DATA}/edge/exec_prices_to_2022.csv.gz",
          f"{DATA}/edge/gbpusd_daily_to_2022.csv.gz", f"{DATA}/edge/benchmarks_daily_gbp_to_2022.csv.gz",
          "research/edge/factors/F-F_Research_Data_5_Factors_2x3_to_2022.csv",
          "research/edge/factors/F-F_Momentum_Factor_to_2022.csv",
          "equity/reports/research/edge/exec_prices_audit_moves.csv"]
CODE = ["research/edge_b5_run.py", "research/edge_b5.py", "research/edge_b5_inputs.py", "research/edge_b5_stats.py",
        "research/edge_backtest.py", "research/edge_rules.py", "research/edge_registry.py", "research/edge_split.py",
        "research/xsection.py", "research/stage2.py", "research/edge_exec_prices.py", "research/data_sources.py",
        "equity/equity/__init__.py", "equity/equity/panel.py", "equity/equity/fundamentals.py",
        "equity/equity/industry.py"]
NOTE = ("B5 run manifest: every input and code file the run reads, by sha256. Registered as B5-V3-RUN-MANIFEST only "
        "on the owner's authorisation; edge_b5_run.preflight refuses any mismatch.")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build() -> dict:
    def path(s):
        return Path(s) if Path(s).is_absolute() else REPO / s
    return {"note": NOTE, "inputs": {p: sha(path(p)) for p in INPUTS}, "code": {p: sha(path(p)) for p in CODE}}


def main() -> None:
    out = REPO / "docs" / "edge" / "B5_RUN_MANIFEST.json"
    out.write_text(json.dumps(build(), indent=1) + "\n")
    print(out, sha(out))


if __name__ == "__main__":
    main()
