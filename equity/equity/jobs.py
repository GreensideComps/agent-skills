"""Job-run ledger: what ran, with which inputs, and how it ended.

A job writes a `start` event and later a `finish` event (status ok / failed / skipped).
A `start` with no `finish` older than its timeout is reported as stuck. An idempotency
key lets a scheduler retry a job safely: once a run with that key finished `ok`,
later runs with the same key are skipped instead of repeated.
"""
from __future__ import annotations

import secrets
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .store import Store, utc_now


class JobSkipped(Exception):
    pass


def _redact(text: str, secrets_to_hide: list[str]) -> str:
    for s in secrets_to_hide:
        if s:
            text = text.replace(s, "<redacted>")
    return text


def completed_keys(store: Store) -> set[str]:
    return {e["idempotency_key"] for e in store.jobs.read()
            if e.get("event") == "finish" and e.get("status") == "ok" and e.get("idempotency_key")}


@contextmanager
def job(store: Store, name: str, inputs: dict, idempotency_key: str | None = None,
        force: bool = False, redact: list[str] | None = None):
    """Record a job run. Yields a dict the job fills with its `outputs` summary.

    Raises JobSkipped (before the body runs) if the key already completed ok.
    Exceptions from the body are recorded as `failed` and re-raised.
    """
    if idempotency_key and not force and idempotency_key in completed_keys(store):
        raise JobSkipped(f"{name}: {idempotency_key} already completed")
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    store.jobs.append({"rid": f"{run_id}:start", "event": "start", "run_id": run_id, "job": name,
                       "idempotency_key": idempotency_key, "inputs": inputs, "ts_utc": utc_now()})
    result: dict = {"outputs": {}}
    try:
        yield result
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        err = _redact(f"{type(exc).__name__}: {exc}", redact or [])
        tb = _redact(traceback.format_exc(limit=5), redact or [])
        store.jobs.append({"rid": f"{run_id}:finish", "event": "finish", "run_id": run_id, "job": name,
                           "idempotency_key": idempotency_key, "status": "failed", "error": err,
                           "traceback": tb[-2000:], "ts_utc": utc_now()})
        raise
    store.jobs.append({"rid": f"{run_id}:finish", "event": "finish", "run_id": run_id, "job": name,
                       "idempotency_key": idempotency_key, "status": "ok",
                       "outputs": result["outputs"], "ts_utc": utc_now()})


def job_health(store: Store, now: datetime | None = None, stuck_after: timedelta = timedelta(hours=2)) -> dict:
    """Summarise job history: last ok run per job, failures, and stuck (unfinished) runs."""
    now = now or datetime.now(timezone.utc)
    starts, finishes = {}, {}
    for e in store.jobs.read():
        (starts if e["event"] == "start" else finishes)[e["run_id"]] = e
    last_ok, last_failed, stuck = {}, {}, []
    for run_id, s in starts.items():
        f = finishes.get(run_id)
        if f is None:
            if now - datetime.fromisoformat(s["ts_utc"]) > stuck_after:
                stuck.append({"job": s["job"], "run_id": run_id, "started": s["ts_utc"]})
            continue
        bucket = last_ok if f["status"] == "ok" else last_failed
        if s["job"] not in bucket or f["ts_utc"] > bucket[s["job"]]["ts_utc"]:
            bucket[s["job"]] = f
    return {"last_ok": {k: v["ts_utc"] for k, v in last_ok.items()},
            "last_failed": {k: {"ts_utc": v["ts_utc"], "error": v.get("error")} for k, v in last_failed.items()},
            "stuck": stuck}
