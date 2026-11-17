"""Alerts (v2): KPI threshold rules evaluated after every snapshot; in-app, email or webhook."""
from __future__ import annotations

import logging
import operator
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Alert, AlertRule, Program, Snapshot

log = logging.getLogger(__name__)
OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq, "!=": operator.ne}


def _send_email(to: str, subject: str, body: str) -> str:
    s = get_settings()
    if not s.smtp_host:
        return "email_not_configured"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_tls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return "sent"
    except Exception as exc:
        log.warning("Alert email failed: %s", exc)
        return "failed"


def _send_webhook(url: str, payload: dict[str, Any]) -> str:
    try:
        r = httpx.post(url, json=payload, timeout=10)
        return "sent" if r.status_code < 300 else f"failed_{r.status_code}"
    except Exception as exc:
        log.warning("Alert webhook failed: %s", exc)
        return "failed"


def evaluate_alerts(db: Session, program: Program, snap: Snapshot, results: dict[str, Any]) -> list[Alert]:
    rules = db.scalars(select(AlertRule).where(
        AlertRule.tenant_id == program.tenant_id, AlertRule.enabled.is_(True),
        or_(AlertRule.program_id.is_(None), AlertRule.program_id == program.id))).all()
    created = []
    for rule in rules:
        r = results.get(rule.kpi_code)
        if r is None or not r.available or r.value is None:
            continue
        op = OPS.get(rule.operator)
        if op is None or not op(r.value, rule.threshold):
            continue
        title = f"{program.name}: {rule.name}"
        msg = (f"KPI '{rule.kpi_code}' = {r.display or r.value} ({rule.operator} {rule.threshold}) "
               f"in snapshot v{snap.version_no} as of {snap.as_of_date}.")
        status = "in_app"
        if rule.channel == "email" and rule.target:
            status = _send_email(rule.target, title, msg)
        elif rule.channel == "webhook" and rule.target:
            status = _send_webhook(rule.target, {"title": title, "message": msg, "program_id": program.id,
                                                 "snapshot_id": snap.id, "kpi": rule.kpi_code, "value": r.value})
        a = Alert(tenant_id=program.tenant_id, rule_id=rule.id, program_id=program.id, snapshot_id=snap.id,
                  title=title, message=msg, value=r.value, delivery_status=status)
        db.add(a)
        created.append(a)
    return created
