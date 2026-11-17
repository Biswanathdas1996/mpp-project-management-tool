"""Audit log helper (v1: every state-changing action is recorded)."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, User


def audit(
    db: Session,
    action: str,
    *,
    user: User | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    program_id: int | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
    tenant_id: int | None = None,
) -> None:
    ip = None
    if request is not None:
        fwd = request.headers.get("x-forwarded-for")
        ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
    db.add(
        AuditLog(
            tenant_id=tenant_id if tenant_id is not None else (user.tenant_id if user else None),
            user_id=user.id if user else None,
            user_email=user.email if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            program_id=program_id,
            details=details or {},
            ip=ip,
        )
    )
