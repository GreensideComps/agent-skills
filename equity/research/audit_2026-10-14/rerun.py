import sys; sys.path.insert(0, "/home/user/agent-skills/equity")
from pathlib import Path
from equity.store import Store
from equity.ingest import latest_securities
from equity.sec import SecClient
from equity import backtest
secs = backtest.sample(list(latest_securities(Store()).values()), 600, 7)
backtest.collect(secs, SecClient(), Path("/home/user/agent-skills/equity/research/output/screen_backtest_rows_rerun.jsonl"))
print("RERUN DONE")
