"""research/always_on/exit_classes.py: how vanished companies left, and the survivorship bias bound."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "always_on"))
import exit_classes as ec  # noqa: E402


def f(form, date, items=""):
    return {"form": form, "date": date, "items": items}


def test_bankruptcy_beats_everything():
    c = ec.classify([f("8-K", "2018-03-01", "1.03,9.01"), f("DEFM14A", "2018-01-01")], "2018-02")
    assert c["class"] == "distressed"


def test_a_merger_proxy_or_change_of_control_near_the_end_is_acquired():
    assert ec.classify([f("DEFM14A", "2016-05-01"), f("15-12B", "2016-09-01")], "2016-08")["class"] == "acquired"
    assert ec.classify([f("8-K", "2016-08-02", "5.01,3.01")], "2016-08")["class"] == "acquired"
    assert ec.classify([f("SC 14D9", "2016-07-01")], "2016-08")["class"] == "acquired"


def test_an_old_merger_filing_does_not_count():
    # a merger proxy five years before the exit is some earlier deal, not the exit
    c = ec.classify([f("DEFM14A", "2011-01-01"), f("8-K", "2016-07-01", "3.01"), f("25-NSE", "2016-08-01")], "2016-08")
    assert c["class"] == "distressed"


def test_nothing_telling_is_other():
    assert ec.classify([f("10-K", "2016-02-01"), f("15-15D", "2016-09-01")], "2016-08")["class"] == "other"


def test_filings_reads_the_recent_block():
    sub = {"filings": {"recent": {"form": ["8-K", "10-K"], "filingDate": ["2020-01-02", "2019-12-01"],
                                  "items": ["1.03"]}}}
    assert ec.filings(sub) == [f("8-K", "2020-01-02", "1.03"), f("10-K", "2019-12-01", "")]


def test_collect_caches_and_survives_a_bad_cik(tmp_path):
    calls = []

    def fetch(cik, ua):
        calls.append(cik)
        if cik == 2:
            raise OSError("404")
        return {"name": "X", "filings": {"recent": {"form": ["DEFM14A"], "filingDate": ["2015-05-01"]}}}
    gone = {1: {"last": "2015-06", "first_big": "2013-01"}, 2: {"last": "2015-06", "first_big": "2013-01"}}
    cache = tmp_path / "c.json"
    out = ec.collect(gone, "ua", cache=cache, pause=0, fetch=fetch)
    assert out["1"]["class"] == "acquired" and out["2"]["class"] == "other" and "404" in out["2"]["error"]
    ec.collect(gone, "ua", cache=cache, pause=0, fetch=fetch)
    assert calls == [1, 2]  # cached, including the failure (recorded as unknown)
    assert json.loads(cache.read_text())["1"]["name"] == "X"


def test_bias_signs():
    recs = {"1": {"class": "acquired", "last": "2015-03"}, "2": {"class": "distressed", "last": "2015-04"}}
    r = ec.bias_table(recs, {2015: 100})[0]
    # central: 1% distressed x (10% + 55%) + 1% acquired x (10% - 25%) = 0.65 - 0.15 = +0.50 pp
    assert abs(r["bias_central_pp"] - 0.50) < 1e-9
    # worst: 1% x 110% + 1% x (10% - 15%) = 1.10 - 0.05 = +1.05 pp
    assert abs(r["bias_worst_pp"] - 1.05) < 1e-9
    acq_only = ec.bias_table({"1": {"class": "acquired", "last": "2015-03"}}, {2015: 100})[0]
    assert acq_only["bias_central_pp"] < 0  # leaving out takeovers makes survivor-only data look worse
