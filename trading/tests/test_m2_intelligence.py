"""Milestone 2: performance maths, reconciliation, adviser, report, email delivery."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import NOW, FakeQuotes, FakeT212, INSTRUMENTS, exchanges_for
from t212bot import adviser as adv
from t212bot import daily, emailer, intel, performance as perf, research_feed, sample
from t212bot.client import T212Client
from t212bot.config import Credentials, SafetyError
from t212bot.readonly import ReadOnlyClient

D = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
ADV_CFG = json.loads((Path(__file__).parent.parent / "config" / "adviser.json").read_text())


# ================================================================ performance

def test_flows_signs_and_net():
    f = perf.extract_flows([
        {"type": "DEPOSIT", "amount": 100, "dateTime": "2026-01-01T00:00:00Z"},
        {"type": "WITHDRAW", "amount": -30, "dateTime": "2026-02-01T00:00:00Z"},
        {"type": "WITHDRAW", "amount": 20, "dateTime": "2026-03-01T00:00:00Z"},    # sign-agnostic
        {"type": "FEE", "amount": -1.5, "dateTime": "2026-03-02T00:00:00Z"},
        {"type": "TRANSFER", "amount": 5, "dateTime": "2026-03-03T00:00:00Z"},
    ])
    assert f.deposits == 100 and f.withdrawals == 50 and f.net == 50 and f.fees == 1.5 and len(f.other) == 1


def test_deposit_is_not_performance():
    snaps = [(D("2026-01-01T00:00"), 100.0), (D("2026-01-02T00:00"), 150.0)]
    flows = [perf.CashFlow(D("2026-01-01T23:59"), 50.0, "DEPOSIT")]
    assert abs(perf.time_weighted(snaps, flows).twr) < 1e-3


def test_withdrawal_is_not_a_loss():
    snaps = [(D("2026-01-01T00:00"), 150.0), (D("2026-01-02T00:00"), 120.0)]
    flows = [perf.CashFlow(D("2026-01-01T00:01"), -30.0, "WITHDRAW")]
    assert abs(perf.time_weighted(snaps, flows).twr) < 1e-3


def test_twr_chain_link_hwm_and_drawdown():
    snaps = [(D("2026-01-01T00:00"), 100.0), (D("2026-01-02T00:00"), 110.0), (D("2026-01-03T00:00"), 99.0),
             (D("2026-01-04T00:00"), 104.5)]
    p = perf.time_weighted(snaps, [])
    assert p.twr == pytest.approx(0.045)
    assert p.hwm == pytest.approx(1.10) and p.max_drawdown == pytest.approx(-0.10)
    assert p.drawdown == pytest.approx(1.045 / 1.10 - 1)


def test_twr_with_too_little_data():
    assert perf.time_weighted([], []).twr is None
    assert perf.time_weighted([(D("2026-01-01T00:00"), 100.0)], []).twr is None


def test_fill_stats_fees_and_quantities():
    S = sample.sample_inputs(NOW)
    fs = perf.fill_stats(S["acct"]["orders"].data)
    assert fs.fees == pytest.approx(0.12) and fs.fees_by_type == {"CURRENCY_CONVERSION_FEE": pytest.approx(0.12)}
    assert fs.qty_by_ticker["IWMOl_EQ"] == pytest.approx(0.735) and fs.sells_net == pytest.approx(9.48)


def _recon(S, **over):
    a = S["acct"]
    summary = dict(a["summary"].data, **over)
    fl = perf.extract_flows(a["transactions"].data)
    return perf.reconcile(summary, a["positions"].data, fl, perf.fill_stats(a["orders"].data), 0.35)


def test_reconciliation_passes_on_consistent_data():
    assert all(c.status == "PASS" for c in _recon(sample.sample_inputs(NOW)))


def test_reconciliation_flags_missing_cash():
    S = sample.sample_inputs(NOW)
    cash = dict(S["acct"]["summary"].data["cash"], availableToTrade=0.55)   # £1 missing
    checks = {c.name: c.status for c in _recon(S, cash=cash, totalValue=139.99)}
    assert checks["R3 cash ledger"] == "FAIL" and checks["R4 gain = P&L components"] == "FAIL"


def test_reconciliation_flags_quantity_mismatch_and_skips_when_incomplete():
    S = sample.sample_inputs(NOW)
    a = S["acct"]
    pos = json.loads(json.dumps(a["positions"].data))
    pos[0]["quantity"] = 9.9
    fl = perf.extract_flows(a["transactions"].data)
    checks = {c.name: c.status for c in perf.reconcile(a["summary"].data, pos, fl, perf.fill_stats(a["orders"].data), 0.35)}
    assert checks["R5 holdings = Σ fills"] == "FAIL"
    checks = {c.name: c.status for c in perf.reconcile(a["summary"].data, pos, fl, perf.fill_stats([]), 0.35, history_complete=False)}
    assert checks["R3 cash ledger"] == "SKIP" and checks["R5 holdings = Σ fills"] == "SKIP"


# ================================================================ adviser

def _inp(value=140.0, contrib=100.0, cash=2.0, reliable=True, issues=None):
    h = [adv.Holding("VWRPl_EQ", (value - cash) / 2, "GBP", 5.0), adv.Holding("IWMOl_EQ", (value - cash) / 2, "USD", 5.0)]
    return adv.AdviserInput(date(2026, 10, 13), value, cash, contrib, h, data_reliable=reliable, reliability_issues=issues or [])


def test_zero_when_no_gain():
    r = adv.advise(_inp(value=95), ADV_CFG)
    assert r.amount_gbp == 0 and "no investment gain" in r.headline


def test_zero_when_gain_but_no_configured_reason():
    r = adv.advise(_inp(value=250), ADV_CFG)
    assert r.amount_gbp == 0 and r.reason_code == "NO_DEFENSIBLE_REASON"
    assert r.headline.startswith("Your portfolio has increased by £150.00 after adjusting for deposits and withdrawals. I recommend withdrawing £0")


def test_zero_when_data_unreliable_even_if_rules_fire():
    cfg = dict(ADV_CFG, max_capital_at_risk_gbp=100.0)
    r = adv.advise(_inp(value=250, reliable=False, issues=["reconciliation did not pass"]), cfg)
    assert r.amount_gbp == 0 and r.reason_code == "DATA_NOT_RELIABLE"


def test_zero_when_below_meaningful_threshold():
    cfg = dict(ADV_CFG, max_capital_at_risk_gbp=135.0)          # only £5 above cap
    r = adv.advise(_inp(value=140), cfg)
    assert r.amount_gbp == 0 and r.reason_code == "BELOW_MEANINGFUL_THRESHOLD"


def test_capital_cap_recommends_excess_and_explains_selling():
    cfg = dict(ADV_CFG, max_capital_at_risk_gbp=200.0)
    r = adv.advise(_inp(value=300, contrib=100, cash=2), cfg)
    assert r.amount_gbp == 100 and r.reason_code == "ABOVE_CAPITAL_CAP"
    assert r.selling_required_gbp > 90 and r.sell_plan and r.est_selling_cost_gbp > 0
    assert "Nothing will happen unless you choose" in r.headline


def test_profit_lock_harvests_only_new_gains_once():
    cfg = dict(ADV_CFG, profit_lock=dict(ADV_CFG["profit_lock"], enabled=True))
    r = adv.advise(_inp(value=300, contrib=100), cfg)
    assert r.reason_code == "PROFIT_LOCK" and r.amount_gbp == 50          # 25% of £200 gain
    st = adv.update_state({}, r, 200.0, 0.0, 100.0, True, date(2026, 10, 13))
    r2 = adv.advise(_inp(value=300, contrib=100), cfg, st)                   # same gain: nothing new to harvest
    assert r2.amount_gbp == 0


def test_liquidity_need_inside_window_only():
    cfg = dict(ADV_CFG, liquidity_needs=[{"amount": 40, "by": "2026-11-30", "label": "holiday"}])
    assert adv.advise(_inp(value=140), cfg).reason_code == "LIQUIDITY_NEED"
    cfg = dict(ADV_CFG, liquidity_needs=[{"amount": 40, "by": "2027-12-30", "label": "later"}])
    assert adv.advise(_inp(value=140), cfg).amount_gbp == 0


def test_never_more_than_account_and_flags_contributions():
    cfg = dict(ADV_CFG, liquidity_needs=[{"amount": 1000, "by": "2026-10-20", "label": "big"}])
    r = adv.advise(_inp(value=140, contrib=100), cfg)
    assert r.amount_gbp <= 140 * (1 - ADV_CFG["cash_buffer_pct"])
    assert any("contributions" in x for x in r.explanation)


def test_isa_and_gia_notes_are_separate():
    cfg = dict(ADV_CFG, max_capital_at_risk_gbp=200.0)
    gia = adv.advise(_inp(value=300), cfg).wrapper_notes
    isa = adv.advise(_inp(value=300), dict(cfg, account_type="ISA")).wrapper_notes
    assert any("Capital Gains Tax" in n for n in gia) and not any("ISA" in n for n in gia)
    assert any("ISA" in n for n in isa) and not any("Capital Gains Tax" in n for n in isa)


def test_notification_dedupe():
    cfg = dict(ADV_CFG, max_capital_at_risk_gbp=200.0)
    r = adv.advise(_inp(value=300), cfg)
    today = date(2026, 10, 13)
    assert adv.should_notify(r, {}, cfg, today)[0]
    st = adv.update_state({}, r, 200, 0, 100, True, today)
    assert not adv.should_notify(r, st, cfg, today + timedelta(days=1))[0]            # same again: silent
    r_big = adv.advise(_inp(value=330), cfg)
    assert adv.should_notify(r_big, st, cfg, today + timedelta(days=1))[0]            # material change
    assert adv.should_notify(r, st, cfg, today + timedelta(days=31))[0]               # reminder
    zero = adv.advise(_inp(value=150), ADV_CFG)
    assert adv.should_notify(zero, st, cfg, today)[0]                                 # previous rec withdrawn
    assert not adv.should_notify(zero, {}, cfg, today)[0]                              # £0 never spams


def test_adviser_cannot_trade_or_move_money():
    src = (Path(__file__).parent.parent / "t212bot" / "adviser.py").read_text()
    for forbidden in ("place_market_order", "cancel_order", "_request", "T212Client", "urllib", "requests", "transfer(", "withdraw("):
        assert forbidden not in src, forbidden
    ro = ReadOnlyClient(T212Client(Credentials("k", "s"), transport=FakeT212(), sleep=lambda s: None))
    for name in ("place_market_order", "cancel_order", "_request", "_t"):
        with pytest.raises(SafetyError):
            getattr(ro, name)
    with pytest.raises(SafetyError):
        ro.x = 1


# ================================================================ report compute: failures & staleness

def _compute(acct, events=None, market=None, snaps=None, prev=None, delivery=None, now=NOW):
    S = sample.sample_inputs(now)
    return intel.compute(acct, snaps if snaps is not None else S["snaps"], events if events is not None else S["events"],
                         "test", ADV_CFG, {}, {"experiments": [], "agenda": [], "log": [], "registry_problems": []},
                         market if market is not None else S["market"], prev, delivery, now)


def test_api_failure_is_prominent_and_never_zero():
    S = sample.sample_inputs(NOW)
    acct = dict(S["acct"], summary=intel.Src(False, None, "ApiError: HTTP 503", "t"))
    M, _ = _compute(acct)
    assert any(a["level"] == "CRITICAL" and "summary" in a["msg"] for a in M["alerts"])
    assert M["account"] is None and M["adviser"]["reason_code"] == "DATA_NOT_RELIABLE"
    md = intel.render_md(M)
    assert "CRITICAL" in md and "missing, not zero" in md


def test_missing_transactions_blocks_adviser():
    S = sample.sample_inputs(NOW)
    acct = dict(S["acct"], transactions=intel.Src(False, None, "timeout", "t"))
    M, _ = _compute(acct)
    assert M["adviser"]["amount_gbp"] == 0 and M["adviser"]["reason_code"] == "DATA_NOT_RELIABLE"
    assert M["performance"]["investment_gain"] is None


def test_stale_market_data_and_idle_bot_are_flagged():
    S = sample.sample_inputs(NOW)
    market = dict(S["market"], price_data_last_date=(NOW - timedelta(days=9)).date().isoformat())
    old = [{"ts_utc": (NOW - timedelta(days=8)).isoformat(), "run_id": "r", "kind": "run_start"}]
    M, _ = _compute(S["acct"], events=old, market=market)
    msgs = " ".join(a["msg"] for a in M["alerts"])
    assert "stale" in msgs and "has not run for 8 days" in msgs


def test_market_failure_degrades_gracefully():
    S = sample.sample_inputs(NOW)
    M, _ = _compute(S["acct"], market={"market_error": "URLError: offline", "shadow": {"error": "URLError: offline"}})
    md = intel.render_md(M)
    assert "Unavailable: URLError" in md and "Volatility estimate unavailable" in md


def test_previous_email_failure_is_critical():
    S = sample.sample_inputs(NOW)
    M, _ = _compute(S["acct"], delivery={"report_date": "2026-10-12", "status": "failed", "provider": "resend", "detail": "401"})
    assert any(a["level"] == "CRITICAL" and "NOT delivered" in a["msg"] for a in M["alerts"])


def test_sample_report_is_labelled_example(tmp_path):
    S = sample.sample_inputs(NOW)
    M, _ = intel.compute(S["acct"], S["snaps"], S["events"], "t", ADV_CFG, {}, intel.research_bundle(), S["market"],
                         S["prev"], S["delivery"], NOW, example=True)
    md = intel.render_md(M)
    assert md.startswith("> **EXAMPLE DATA") and "[VERIFIED]" not in md


def test_html_escapes_and_renders_tables():
    h = intel.md_to_html("# T\n\n| a | b |\n|---|---|\n| <x> | **y** |\n", "t")
    assert "<table>" in h and "&lt;x&gt;" in h and "<strong>y</strong>" in h


def test_registry_records_are_valid_and_validator_catches_problems():
    recs, problems = research_feed.load_registry()
    assert recs and not problems
    assert research_feed.validate({"id": "X", "decision": "PROMOTED", "promoted": True})       # missing fields
    good = dict(recs[0], promoted=True)
    assert "promoted=true requires decision PROMOTED" in research_feed.validate(good)


# ================================================================ email

class FakeHTTP:
    def __init__(self, statuses):
        self.statuses, self.calls = list(statuses), []

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, json.loads(body)))
        st = self.statuses.pop(0)
        return st, json.dumps({"id": f"msg-{len(self.calls)}"}) if st < 300 else '{"message":"err"}'


def _cfg(**k):
    base = dict(REPORT_EMAIL_PROVIDER="resend", REPORT_EMAIL_TO="owner@example.com", REPORT_EMAIL_FROM="Bot <bot@example.com>",
                RESEND_API_KEY="re_test")
    base.update(k)
    return emailer.load_config(base)


def _msg():
    return emailer.Email("s", "text", "<p>html</p>", "owner@example.com", "Bot <bot@example.com>")


def test_config_problems_and_secret_redaction():
    assert "RESEND_API_KEY not set" in _cfg(RESEND_API_KEY="").problems()
    assert "re_test" not in repr(_cfg())


def test_send_success_records_ledger_and_idempotency(tmp_path):
    http = FakeHTTP([200])
    r = emailer.deliver(_msg(), _cfg(), "2026-10-13", root=tmp_path, http=http, sleep=lambda s: None)
    assert r.status == "sent" and r.provider_id == "msg-1"
    assert http.calls[0][1]["Idempotency-Key"] == emailer.idempotency_key("2026-10-13", "daily", "owner@example.com")
    assert emailer.last_delivery(tmp_path)["status"] == "sent"


def test_transient_errors_retry_then_succeed(tmp_path):
    http = FakeHTTP([503, 429, 200])
    slept = []
    r = emailer.deliver(_msg(), _cfg(), "2026-10-13", root=tmp_path, http=http, sleep=slept.append)
    assert r.status == "sent" and r.attempts == 3 and slept == [2, 4]
    assert [x["status"] for x in emailer.ledger_records(tmp_path)] == ["retry", "retry", "sent"]


def test_permanent_error_fails_fast(tmp_path):
    http = FakeHTTP([401, 200])
    r = emailer.deliver(_msg(), _cfg(), "2026-10-13", root=tmp_path, http=http, sleep=lambda s: None)
    assert r.status == "failed" and r.attempts == 1 and len(http.calls) == 1


def test_transient_exhaustion_fails(tmp_path):
    r = emailer.deliver(_msg(), _cfg(), "2026-10-13", root=tmp_path, http=FakeHTTP([500] * 4), sleep=lambda s: None)
    assert r.status == "failed" and "exhausted" in r.detail


def test_duplicate_prevention_and_force(tmp_path):
    http = FakeHTTP([200, 200])
    assert emailer.deliver(_msg(), _cfg(), "2026-10-13", root=tmp_path, http=http).status == "sent"
    assert emailer.deliver(_msg(), _cfg(), "2026-10-13", root=tmp_path, http=http).status == "skipped_duplicate"
    assert len(http.calls) == 1
    assert emailer.deliver(_msg(), _cfg(), "2026-10-13", root=tmp_path, http=http, force=True).status == "sent"


def test_concurrent_job_lock_and_stale_recovery(tmp_path):
    with emailer.SendLock(tmp_path):
        with pytest.raises(emailer.LockBusy):
            with emailer.SendLock(tmp_path):
                pass
    (tmp_path / ".email.lock").write_text(json.dumps({"pid": 1, "t": 0}))       # crashed job, long ago
    http = FakeHTTP([200])
    assert emailer.deliver(_msg(), _cfg(), "2026-10-13", root=tmp_path, http=http).status == "sent"
    assert any(r["status"] == "lock_recovered" for r in emailer.ledger_records(tmp_path))


def test_outbox_is_not_delivery(tmp_path):
    r = emailer.deliver(_msg(), emailer.load_config({}), "2026-10-13", root=tmp_path)
    assert r.status == "outbox" and Path(r.provider_id).exists() and "NOT emailed" in r.detail


def test_smtp_auth_failure_is_permanent(tmp_path):
    import smtplib

    class Bad:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            raise smtplib.SMTPAuthenticationError(535, b"bad")
    cfg = emailer.load_config(dict(REPORT_EMAIL_PROVIDER="smtp", REPORT_EMAIL_TO="a@b.c", REPORT_EMAIL_FROM="b@b.c",
                                   SMTP_HOST="h", SMTP_USER="u", SMTP_PASSWORD="p"))
    r = emailer.deliver(_msg(), cfg, "2026-10-13", root=tmp_path, smtp_factory=lambda c: Bad(), sleep=lambda s: None)
    assert r.status == "failed" and r.attempts == 1


@pytest.mark.parametrize("utc,expect", [
    ("2026-03-28T07:15:00", False),   # GMT: 07:15 local, before 07:30
    ("2026-03-28T07:31:00", True),
    ("2026-03-29T06:45:00", True),    # BST started 01:00 UTC: 07:45 local
    ("2026-03-29T06:25:00", False),   # 07:25 BST
    ("2026-10-25T06:45:00", False),   # BST ended 01:00 UTC: 06:45 GMT
    ("2026-10-25T07:30:00", True),
])
def test_report_time_respects_uk_daylight_saving(utc, expect):
    assert emailer.due(D(utc), "07:30")[0] is expect


# ================================================================ end-to-end (fake API + fake email)

@pytest.fixture
def deployed(make_client, cfg, journal, tmp_path):
    """A fake demo account after the bot's initial deployment."""
    from t212bot.executor import Bot
    fake = FakeT212()
    Bot(make_client(fake), cfg, journal, quotes=FakeQuotes(), now=lambda: NOW, sleep=lambda s: None,
        instruments=INSTRUMENTS, exchanges=exchanges_for(NOW), env={}, kill_file=tmp_path / "KILL").run(execute=True)
    return fake


def _run(fake, journal, tmp_path, **kw):
    ro = ReadOnlyClient(T212Client(Credentials("k", "s"), transport=fake, sleep=lambda s: None))
    market = {"shadow": {"note": "offline test"}, "market_error": "offline"}
    research = {"experiments": [], "agenda": [], "log": [], "registry_problems": []}
    return daily.run(ro=ro, journal=journal, reports_root=tmp_path / "reports", market=market, research=research,
                     sleep=lambda s: None, **kw)


def test_end_to_end_report_send_and_no_trading(deployed, journal, tmp_path):
    posts_before = len(deployed.posts)
    http = FakeHTTP([200])
    env = dict(REPORT_EMAIL_PROVIDER="resend", REPORT_EMAIL_TO="o@example.com", REPORT_EMAIL_FROM="b@example.com", RESEND_API_KEY="k")
    out = _run(deployed, journal, tmp_path, send=True, env=env, http=http, now=NOW + timedelta(hours=1))
    assert out["delivery"]["status"] == "sent" and out["exit"] in (0, 2)
    assert len(deployed.posts) == posts_before                                   # reporting placed no orders
    M = json.loads(Path(out["paths"]["json"]).read_text())
    assert M["reconciliation_ok"] is True, M["reconciliation"]
    assert M["delivery"]["status"] == "sent"
    assert "Daily report" in http.calls[0][2]["subject"]


def test_end_to_end_email_failure_exit_code_and_next_report(deployed, journal, tmp_path):
    env = dict(REPORT_EMAIL_PROVIDER="resend", REPORT_EMAIL_TO="o@example.com", REPORT_EMAIL_FROM="b@example.com", RESEND_API_KEY="k")
    out = _run(deployed, journal, tmp_path, send=True, env=env, http=FakeHTTP([401]), now=NOW + timedelta(hours=1))
    assert out["exit"] == 3 and out["delivery"]["status"] == "failed"
    out2 = _run(deployed, journal, tmp_path, send=False, now=NOW + timedelta(days=1))
    assert any("NOT delivered" in a["msg"] for a in out2["alerts"])


def test_schedule_gate_and_duplicate_jobs(deployed, journal, tmp_path):
    env = dict(REPORT_EMAIL_PROVIDER="resend", REPORT_EMAIL_TO="o@example.com", REPORT_EMAIL_FROM="b@example.com", RESEND_API_KEY="k")
    early = datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc)     # 06:00 BST, before 07:30
    assert _run(deployed, journal, tmp_path, send=True, env=env, respect_schedule=True, now=early)["status"] == "not_due"
    late = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)      # 08:00 BST
    http = FakeHTTP([200, 200])
    assert _run(deployed, journal, tmp_path, send=True, env=env, respect_schedule=True, now=late, http=http)["delivery"]["status"] == "sent"
    again = _run(deployed, journal, tmp_path, send=True, env=env, respect_schedule=True, now=late + timedelta(hours=1), http=http)
    assert again["status"] == "already_sent" and len(http.calls) == 1


def test_report_with_credentials_missing_still_produced(journal, tmp_path):
    class Dead:
        def __getattr__(self, n):
            def f(*a, **k):
                raise RuntimeError("credentials unavailable")
            return f
    out = daily.run(ro=Dead(), journal=journal, reports_root=tmp_path / "r", market={"market_error": "x", "shadow": {"error": "x"}},
                    research={"experiments": [], "agenda": [], "log": [], "registry_problems": []}, now=NOW)
    assert out["exit"] == 2 and Path(out["paths"]["md"]).exists()
    assert "missing, not zero" in Path(out["paths"]["md"]).read_text()
