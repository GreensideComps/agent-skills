"""Owner decision D-A (2026-10-23): append-only verdict annotations for results recorded without a verdict, and
eligibility checks so a failed trial can never qualify. The tests write only to copies; the committed registry is
only read and must stay byte-identical. The proposed events are a committed fixture (review finding P30-4), so the
tests do not depend on the docs folder."""
import hashlib
import json
import shutil
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_registry  # noqa: E402
import edge_verdicts as ev  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edge_verdicts" / "annotation_events.json"
DOCS_COPY = REPO / "docs" / "minifund" / "proposals" / "DA_VERDICT_ANNOTATION_EVENTS.json"
EXPECTED_LEDGER = REPO / "docs" / "minifund" / "proposals" / "DA_verdict_annotations.expected.jsonl"
B5_V3 = ("B5-H1-FCFPS-ACCEL-V3", "B5-S2A-GP-12M-V3")
RUN_2_REGISTRY_SHA256 = "de03d38b18a2d80b5c4d20f647c8ff35f5471157aba71fa99da6b550fb1217e6"
DAY = "2026-10-23"


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise NetworkBlocked("network access attempted in an offline test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def proposed():
    assert FIXTURE.is_file(), f"fixture missing: {FIXTURE} (copy of DA_VERDICT_ANNOTATION_EVENTS.json)"
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "verdict_annotations.jsonl"


def test_the_fixture_is_a_byte_copy_of_the_proposal_when_the_docs_exist():
    if not DOCS_COPY.exists():
        pytest.skip("docs/minifund not present")
    assert FIXTURE.read_bytes() == DOCS_COPY.read_bytes()


def _append(events, p, **kw):
    ev.append(events, path=p, on_date=kw.pop("on_date", DAY), **kw)


def test_proposed_annotations_validate_and_leave_the_registry_untouched(ledger):
    reg_before = edge_registry.PATH.read_bytes()
    _append(proposed(), ledger)
    assert ev.validate(ledger) == []
    assert edge_registry.PATH.read_bytes() == reg_before
    assert hashlib.sha256(b"".join(reg_before.splitlines(keepends=True)[:252])).hexdigest() == RUN_2_REGISTRY_SHA256
    events = edge_registry.load()
    assert edge_registry.n_trials(events) == 102  # an annotation adds no trial and no result
    assert {t: ev.verdicts(events, ev.load(ledger))[t] for t in B5_V3} == {t: "fail" for t in B5_V3}


def test_the_bytes_do_not_depend_on_the_system_date(ledger, monkeypatch):
    import datetime as dt

    class Later(dt.date):
        @classmethod
        def today(cls):
            return cls(2031, 1, 1)
    monkeypatch.setattr(ev, "date", Later)
    _append(proposed(), ledger)
    if EXPECTED_LEDGER.exists():
        assert ledger.read_bytes() == EXPECTED_LEDGER.read_bytes()
    assert all(json.loads(l)["date"] == DAY for l in ledger.read_text().splitlines())


def test_on_date_is_required_and_must_be_iso(ledger):
    with pytest.raises(TypeError):
        ev.append(proposed(), path=ledger)
    with pytest.raises(ValueError):
        _append(proposed(), ledger, on_date="23/10/2026")
    assert not ledger.exists()


def test_failed_and_unverdicted_trials_never_qualify(ledger):
    events = edge_registry.load()
    for t in B5_V3:  # before D-A is applied: no verdict recorded, still refused
        ok, why = ev.allocation_eligible(t, events, [])
        assert not ok and "not recorded" in why
    _append(proposed(), ledger)
    ann = ev.load(ledger)
    for t in B5_V3:  # after: refused as failed
        ok, why = ev.allocation_eligible(t, events, ann)
        assert not ok and "fail" in why
    assert not [t for t in edge_registry.registered(events) if ev.allocation_eligible(t, events, ann)[0]]
    assert not ev.allocation_eligible("S2-S2a", events, ann)[0]  # inconclusive is not a pass
    assert not ev.allocation_eligible("DIAG-S1a-h3", events, ann)[0]  # diagnostics never qualify
    assert not ev.allocation_eligible("NOT-REGISTERED", events, ann)[0]


def test_a_pass_annotation_is_refused_and_no_file_is_created(ledger):
    with pytest.raises(ValueError, match="pass not allowed"):
        _append([dict(proposed()[0], verdict="pass", label="pass")], ledger)
    assert not ledger.exists()


def test_a_hand_written_correctly_chained_pass_line_is_reported(ledger):
    e = dict(proposed()[0], verdict="pass", label="pass", date=DAY, prev=edge_registry.GENESIS)
    ledger.write_text(json.dumps(e, sort_keys=True) + "\n")
    assert any("verdict pass not allowed in annotations" in p for p in ev.validate(ledger))


def test_a_forged_pass_ledger_never_makes_a_trial_eligible():
    events = edge_registry.load()
    forged = [dict(a, verdict="pass") for a in proposed()]
    for t in B5_V3:
        for ann in ([], proposed(), forged):
            assert ev.allocation_eligible(t, events, ann)[0] is False


def test_an_owner_decision_outside_the_pinned_set_is_refused(ledger):
    with pytest.raises(ValueError, match="not a pinned owner decision"):
        _append([dict(proposed()[0], owner_decision="cmsg_x")], ledger)
    with pytest.raises(ValueError, match="not a pinned owner decision"):
        _append([dict(proposed()[0], verdict="inconclusive", label="inconclusive")], ledger)
    assert not ledger.exists()


@pytest.mark.parametrize("change, problem", [
    ({"annotates_line": 240}, "is not B5-H1-FCFPS-ACCEL-V3's result"),
    ({"id": "S2-S1a", "annotates_line": 0}, "is not S2-S1a's result"),
    ({"annotates_line_sha256": "0" * 64}, "no longer has the annotated sha256"),
    ({"verdict": "pass?"}, "not in"),
    ({"owner_decision": "owner said so"}, "owner decision id"),
    ({"evidence_sha256": "f" * 64}, "does not have the recorded sha256"),
])
def test_bad_annotations_are_refused_and_nothing_is_written(ledger, change, problem):
    with pytest.raises(ValueError, match=problem):
        _append([dict(proposed()[0], **change)], ledger)
    assert not ledger.exists() and not ledger.with_suffix(".tmp").exists()


def test_an_annotation_of_a_result_that_has_a_verdict_is_refused(ledger):
    lines = edge_registry.PATH.read_text().splitlines()
    n = next(i for i, l in enumerate(lines, 1) if '"id": "S2-S1a"' in l and '"result"' in l)
    a = dict(proposed()[0], id="S2-S1a", annotates_line=n, annotates_line_sha256=edge_registry.line_hash(lines[n - 1]))
    with pytest.raises(ValueError, match="already carries verdict"):
        _append([a], ledger)


def test_a_second_annotation_and_any_edit_are_refused(ledger):
    _append(proposed(), ledger)
    with pytest.raises(ValueError):
        _append([dict(proposed()[0])], ledger)
    text = ledger.read_text()
    ledger.write_text(text.replace('"verdict": "fail"', '"verdict": "inconclusive"', 1))
    assert any("hash chain" in p for p in ev.validate(ledger))


def test_a_changed_evidence_file_invalidates_the_ledger_and_blocks_appends(tmp_path):
    repo = tmp_path / "repo"
    ev_file = repo / "equity" / "reports" / "research" / "edge" / "b5_trials.md"
    ev_file.parent.mkdir(parents=True)
    shutil.copy(REPO / "equity" / "reports" / "research" / "edge" / "b5_trials.md", ev_file)
    ledger = tmp_path / "l.jsonl"
    ev.append(proposed()[:1], path=ledger, on_date=DAY, repo=repo)
    assert ev.validate(ledger, repo=repo) == []
    ev_file.write_bytes(ev_file.read_bytes() + b"\nedited\n")
    assert any("does not have the recorded sha256" in p for p in ev.validate(ledger, repo=repo))
    with pytest.raises(ValueError, match="invalid before append"):
        ev.append(proposed()[1:], path=ledger, on_date=DAY, repo=repo)


def test_the_committed_annotation_file_if_present_is_valid():
    assert ev.validate() == []
