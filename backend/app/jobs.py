"""Queue job entry points (executed by RQ workers or the inline executor)."""
from __future__ import annotations

import logging

from .ai.provider import AIUnavailable
from .ai.service import AIService
from .db import session_scope
from .models import Snapshot
from .services.pipeline import process_snapshot, recompute_program

log = logging.getLogger(__name__)


def process_snapshot_job(snapshot_id: int, password: str | None = None) -> None:
    process_snapshot(snapshot_id, password)


def recompute_program_job(program_id: int) -> None:
    recompute_program(program_id)


def auto_insights_job(snapshot_id: int) -> None:
    """Pre-generate (and cache) the executive summary + change narrative for a new snapshot."""
    with session_scope() as db:
        snap = db.get(Snapshot, snapshot_id)
        if snap is None or snap.status != "ready":
            return
        ai = AIService(db, snap.program.tenant)
        for kind in ("executive_summary", "change_narrative"):
            try:
                ai.insight(kind, snap.program, snap)
            except AIUnavailable as exc:
                log.info("Auto insight %s skipped: %s", kind, exc)
                break


def insight_job(snapshot_id: int, kind: str, user_id: int | None, force: bool) -> None:
    from .models import User

    with session_scope() as db:
        snap = db.get(Snapshot, snapshot_id)
        if snap is None:
            return
        user = db.get(User, user_id) if user_id else None
        try:
            AIService(db, snap.program.tenant).insight(kind, snap.program, snap, user=user, force=force)
        except AIUnavailable as exc:
            log.info("Insight %s failed: %s", kind, exc)
