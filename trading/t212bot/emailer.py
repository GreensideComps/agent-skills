"""Email delivery for the daily report: providers, retries, ledger, de-duplication.

Providers (no third-party packages - stdlib only):
  resend  HTTPS API (api.resend.com). Works from cloud sessions, where outbound
          SMTP ports are blocked (verified 2026-10-13). Supports an
          Idempotency-Key, so a crash after sending cannot cause a duplicate.
  smtp    smtplib with STARTTLS/SSL, for a persistent machine where SMTP is
          allowed (e.g. iCloud/Gmail with an app-specific password).
  outbox  writes the message to trading/reports/outbox/*.eml (dry run / no
          credentials). Never counts as "delivered".

Configuration (environment variables; secrets never stored in the repo):
  REPORT_EMAIL_PROVIDER   resend | smtp | outbox      (default: outbox)
  REPORT_EMAIL_TO         recipient address
  REPORT_EMAIL_FROM       sender, e.g. "T212 Bot <onboarding@resend.dev>"
  RESEND_API_KEY          for provider=resend
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_SSL=1|0   for provider=smtp

Reliability:
  * delivery ledger trading/reports/delivery_log.jsonl records every attempt,
    success and failure (status: sent | failed | skipped_duplicate | outbox)
  * the ledger is checked before sending: a report already delivered for the
    same date/kind/recipient is never sent again unless forced
  * an exclusive lock file prevents two jobs sending at once; a lock older
    than LOCK_STALE_MIN is treated as left over from a crash and recovered
  * transient errors (network, HTTP 429/5xx) retry with exponential backoff;
    permanent errors (other 4xx, auth) fail immediately
"""
from __future__ import annotations

import hashlib
import json
import os
import smtplib
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ROOT

REPORTS = ROOT / "reports"
LEDGER = REPORTS / "delivery_log.jsonl"
LOCK = REPORTS / ".email.lock"
LOCK_STALE_MIN = 30
UK = ZoneInfo("Europe/London")


class PermanentEmailError(RuntimeError):
    pass


class TransientEmailError(RuntimeError):
    pass


@dataclass
class Email:
    subject: str
    text: str
    html: str
    to: str
    sender: str
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)  # (filename, data, mime)


@dataclass
class EmailConfig:
    provider: str
    to: str | None
    sender: str | None
    resend_key: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_ssl: bool = False

    def __repr__(self):
        return f"EmailConfig(provider={self.provider!r}, to={'set' if self.to else None}, sender={'set' if self.sender else None}, secrets=<redacted>)"

    def problems(self) -> list[str]:
        p = []
        if self.provider not in ("resend", "smtp", "outbox"):
            p.append(f"unknown REPORT_EMAIL_PROVIDER {self.provider!r}")
        if self.provider != "outbox":
            if not self.to:
                p.append("REPORT_EMAIL_TO not set")
            if not self.sender:
                p.append("REPORT_EMAIL_FROM not set")
        if self.provider == "resend" and not self.resend_key:
            p.append("RESEND_API_KEY not set")
        if self.provider == "smtp" and not (self.smtp_host and self.smtp_user and self.smtp_password):
            p.append("SMTP_HOST/SMTP_USER/SMTP_PASSWORD not all set")
        return p


def load_config(env: dict | None = None) -> EmailConfig:
    e = os.environ if env is None else env
    return EmailConfig(
        provider=(e.get("REPORT_EMAIL_PROVIDER") or "outbox").strip().lower(),
        to=e.get("REPORT_EMAIL_TO") or None, sender=e.get("REPORT_EMAIL_FROM") or None,
        resend_key=e.get("RESEND_API_KEY") or None,
        smtp_host=e.get("SMTP_HOST") or None, smtp_port=int(e.get("SMTP_PORT") or 587),
        smtp_user=e.get("SMTP_USER") or None, smtp_password=e.get("SMTP_PASSWORD") or None,
        smtp_ssl=(e.get("SMTP_SSL") or "0") in ("1", "true", "True"))


# ---------------------------------------------------------------- providers

def send_resend(msg: Email, cfg: EmailConfig, idem_key: str, http=None) -> str:
    payload = {"from": msg.sender, "to": [msg.to], "subject": msg.subject, "text": msg.text, "html": msg.html}
    if msg.attachments:
        import base64
        payload["attachments"] = [{"filename": n, "content": base64.b64encode(d).decode()} for n, d, _ in msg.attachments]
    body = json.dumps(payload).encode()
    headers = {"Authorization": f"Bearer {cfg.resend_key}", "Content-Type": "application/json",
               "Idempotency-Key": idem_key, "User-Agent": "t212bot-report/1.0"}
    if http is not None:
        status, text = http("https://api.resend.com/emails", headers, body)
    else:
        req = urllib.request.Request("https://api.resend.com/emails", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, text = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            status, text = e.code, (e.read() or b"").decode("utf-8", "replace")
        except Exception as e:
            raise TransientEmailError(f"network: {type(e).__name__}") from None
    if 200 <= status < 300:
        try:
            return json.loads(text).get("id", "")
        except Exception:
            return ""
    if status == 429 or status >= 500:
        raise TransientEmailError(f"resend HTTP {status}: {text[:200]}")
    raise PermanentEmailError(f"resend HTTP {status}: {text[:200]}")


def _mime(msg: Email) -> EmailMessage:
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = msg.subject, msg.sender, msg.to
    m.set_content(msg.text)
    m.add_alternative(msg.html, subtype="html")
    for n, d, mime in msg.attachments:
        maintype, subtype = mime.split("/", 1)
        m.add_attachment(d, maintype=maintype, subtype=subtype, filename=n)
    return m


def send_smtp(msg: Email, cfg: EmailConfig, idem_key: str, smtp_factory=None) -> str:
    m = _mime(msg)
    m["Message-ID"] = f"<{idem_key}@t212bot>"
    try:
        if smtp_factory:
            s = smtp_factory(cfg)
        elif cfg.smtp_ssl:
            s = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
            s.starttls(context=ssl.create_default_context())
        with s:
            s.login(cfg.smtp_user, cfg.smtp_password)
            s.send_message(m)
    except smtplib.SMTPAuthenticationError as e:
        raise PermanentEmailError(f"smtp auth failed: {e.smtp_code}") from None
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as e:
        raise PermanentEmailError(f"smtp refused: {type(e).__name__}") from None
    except (OSError, smtplib.SMTPException) as e:
        raise TransientEmailError(f"smtp: {type(e).__name__}: {str(e)[:120]}") from None
    return m["Message-ID"]


def send_outbox(msg: Email, root: Path, idem_key: str) -> str:
    d = root / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{idem_key[:16]}.eml"
    p.write_bytes(bytes(_mime(msg)))
    return str(p)


# ---------------------------------------------------------------- ledger / lock / schedule

def idempotency_key(report_date: str, kind: str, to: str | None) -> str:
    return hashlib.sha256(f"{report_date}|{kind}|{(to or '').lower()}".encode()).hexdigest()


def ledger_records(root: Path = REPORTS) -> list[dict]:
    p = root / "delivery_log.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def ledger_append(rec: dict, root: Path = REPORTS) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "delivery_log.jsonl", "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def already_sent(key: str, root: Path = REPORTS) -> dict | None:
    for r in reversed(ledger_records(root)):
        if r.get("key") == key and r.get("status") == "sent":
            return r
    return None


def last_delivery(root: Path = REPORTS, kind: str = "daily") -> dict | None:
    recs = [r for r in ledger_records(root) if r.get("kind") == kind and r.get("status") in ("sent", "failed", "outbox")]
    return recs[-1] if recs else None


class LockBusy(RuntimeError):
    pass


class SendLock:
    def __init__(self, root: Path = REPORTS, stale_min: int = LOCK_STALE_MIN, clock=time.time):
        self.path, self.stale, self.clock = root / ".email.lock", stale_min * 60, clock
        self.recovered = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({"pid": os.getpid(), "t": self.clock()}).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    t = json.loads(self.path.read_text()).get("t", 0)
                except Exception:
                    t = 0
                if self.clock() - t > self.stale:
                    self.path.unlink(missing_ok=True)   # left behind by a crashed job
                    self.recovered = True
                    continue
                raise LockBusy(f"another report job holds {self.path}")
        raise LockBusy("could not acquire lock")

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def due(now_utc: datetime, report_time: str, tz: str = "Europe/London") -> tuple[bool, date]:
    """Is the configured local report time reached? Returns (due, local_date). DST-aware."""
    local = now_utc.astimezone(ZoneInfo(tz))
    hh, mm = (int(x) for x in report_time.split(":"))
    return local.time() >= dtime(hh, mm), local.date()


# ---------------------------------------------------------------- deliver

@dataclass
class DeliveryResult:
    status: str          # sent | failed | skipped_duplicate | outbox | config_error
    provider: str
    detail: str
    attempts: int
    key: str
    provider_id: str = ""


def deliver(msg: Email, cfg: EmailConfig, report_date: str, kind: str = "daily", force: bool = False,
            root: Path = REPORTS, max_attempts: int = 4, sleep=time.sleep, http=None, smtp_factory=None,
            now=lambda: datetime.now(timezone.utc)) -> DeliveryResult:
    key = idempotency_key(report_date, kind, cfg.to)
    base = {"report_date": report_date, "kind": kind, "provider": cfg.provider, "key": key,
            "to_hash": hashlib.sha256((cfg.to or "").lower().encode()).hexdigest()[:12]}

    def log(status, detail, attempts, pid=""):
        ledger_append({**base, "ts_utc": now().isoformat(timespec="seconds"), "status": status, "detail": detail[:300],
                       "attempts": attempts, "provider_id": pid}, root)
        return DeliveryResult(status, cfg.provider, detail, attempts, key, pid)

    problems = cfg.problems()
    if problems:
        return log("config_error", "; ".join(problems), 0)
    if not force and cfg.provider != "outbox":
        prev = already_sent(key, root)
        if prev:
            return log("skipped_duplicate", f"already delivered at {prev['ts_utc']} (id {prev.get('provider_id', '')})", 0, prev.get("provider_id", ""))
    with SendLock(root) as lock:
        if lock.recovered:
            ledger_append({**base, "ts_utc": now().isoformat(timespec="seconds"), "status": "lock_recovered",
                           "detail": "stale lock from an interrupted job was cleared", "attempts": 0}, root)
        if not force and cfg.provider != "outbox" and already_sent(key, root):   # re-check inside the lock
            return log("skipped_duplicate", "delivered by a concurrent job", 0)
        if cfg.provider == "outbox":
            pid = send_outbox(msg, root, key)
            return log("outbox", f"written to {pid} - NOT emailed (no provider configured)", 1, pid)
        last_err = ""
        for attempt in range(1, max_attempts + 1):
            try:
                if cfg.provider == "resend":
                    pid = send_resend(msg, cfg, key, http=http)
                else:
                    pid = send_smtp(msg, cfg, key, smtp_factory=smtp_factory)
                return log("sent", "accepted by provider", attempt, pid)
            except PermanentEmailError as e:
                return log("failed", f"permanent: {e}", attempt)
            except TransientEmailError as e:
                last_err = str(e)
                ledger_append({**base, "ts_utc": now().isoformat(timespec="seconds"), "status": "retry",
                               "detail": last_err[:300], "attempts": attempt}, root)
                if attempt < max_attempts:
                    sleep(min(2 ** attempt, 60))
        return log("failed", f"transient errors exhausted after {max_attempts} attempts: {last_err}", max_attempts)
