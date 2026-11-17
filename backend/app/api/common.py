from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Program, Snapshot, User
from ..security import get_program_for_user


def get_snapshot_for_user(db: Session, snapshot_id: int, user: User) -> tuple[Snapshot, Program]:
    snap = db.get(Snapshot, snapshot_id)
    if snap is None:
        raise HTTPException(404, "Snapshot not found")
    program = get_program_for_user(db, snap.program_id, user)
    return snap, program


def latest_ready(db: Session, program_id: int) -> Snapshot | None:
    return db.scalar(select(Snapshot).where(Snapshot.program_id == program_id, Snapshot.status == "ready")
                     .order_by(Snapshot.as_of_date.desc(), Snapshot.version_no.desc()).limit(1))


def require_ready(snap: Snapshot) -> None:
    if snap.status != "ready":
        raise HTTPException(409, f"Snapshot is {snap.status}; dashboard not available yet")
