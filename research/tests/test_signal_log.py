"""Signal log: outcomes are joined only once the following month has ended."""
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import signal_log  # noqa: E402


def test_outcome_waits_for_the_month_to_end():
    logged = pd.DataFrame({"month": ["2026-10-31", "2026-11-30"], "cik": [1, 1], "band": ["large"] * 2})
    df = pd.DataFrame({"cik": [1, 1], "month": pd.to_datetime(["2026-10-31", "2026-11-30"]), "ret_next": [0.01, 0.02]})
    x = signal_log.outcomes(logged, df, date(2026, 12, 15))
    assert list(x["ret_next"]) == [0.01]  # November's outcome (December's return) is not complete yet


def test_latest_complete_month_excludes_the_current_month():
    df = pd.DataFrame({"month": pd.to_datetime(["2026-09-30", "2026-10-31"])})
    assert signal_log.latest_complete_month(df, date(2026, 10, 14)) == pd.Timestamp("2026-09-30")
    assert signal_log.latest_complete_month(df, date(2026, 11, 2)) == pd.Timestamp("2026-10-31")
