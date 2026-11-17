from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..models import MappingConfig, Program, Snapshot, Track, User
from ..security import get_program_for_user, require_admin, require_viewer
from .common import latest_ready

router = APIRouter(prefix="/programs", tags=["programs"])


class ProgramIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    name_ar: str | None = None
    client_name: str | None = None
    client_name_ar: str | None = None
    subtitle: str | None = None
    location: str | None = None
    description: str | None = None
    reporting_cycle_days: int = Field(default=7, ge=1, le=92)


class ProgramUpdate(BaseModel):
    name: str | None = None
    name_ar: str | None = None
    client_name: str | None = None
    client_name_ar: str | None = None
    subtitle: str | None = None
    location: str | None = None
    description: str | None = None
    reporting_cycle_days: int | None = Field(default=None, ge=1, le=92)
    thresholds: dict | None = None
    is_archived: bool | None = None


def program_out(db: Session, p: Program) -> dict:
    latest = latest_ready(db, p.id)
    mapping = db.scalar(select(MappingConfig).where(MappingConfig.program_id == p.id)
                        .order_by(MappingConfig.version.desc()).limit(1))
    counts = dict(db.execute(select(Snapshot.status, func.count()).where(Snapshot.program_id == p.id)
                             .group_by(Snapshot.status)).all())
    return {"id": p.id, "name": p.name, "name_ar": p.name_ar, "client_name": p.client_name,
            "client_name_ar": p.client_name_ar, "subtitle": p.subtitle, "location": p.location,
            "description": p.description, "reporting_cycle_days": p.reporting_cycle_days, "thresholds": p.thresholds,
            "is_archived": p.is_archived, "created_at": p.created_at.isoformat(),
            "has_client_logo": bool((p.branding or {}).get("client_logo")),
            "has_vendor_logo": bool((p.branding or {}).get("vendor_logo")),
            "latest_snapshot": {"id": latest.id, "version_no": latest.version_no,
                                "as_of": latest.as_of_date.isoformat()} if latest else None,
            "snapshot_counts": counts,
            "mapping_status": mapping.status if mapping else None,
            "track_count": db.scalar(select(func.count(Track.id)).where(Track.program_id == p.id)) or 0}


@router.get("")
def list_programs(include_archived: bool = False, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    q = select(Program).where(Program.tenant_id == user.tenant_id)
    if not include_archived:
        q = q.where(Program.is_archived.is_(False))
    return [program_out(db, p) for p in db.scalars(q.order_by(Program.name))]


@router.post("", status_code=201)
def create_program(body: ProgramIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = Program(tenant_id=admin.tenant_id, created_by_id=admin.id, **body.model_dump())
    db.add(p)
    db.flush()
    audit(db, "program.create", user=admin, entity_type="program", entity_id=p.id, program_id=p.id, request=request,
          details={"name": p.name})
    db.commit()
    return program_out(db, p)


@router.get("/{program_id}")
def get_program(program_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    return program_out(db, get_program_for_user(db, program_id, user))


@router.patch("/{program_id}")
def update_program(program_id: int, body: ProgramUpdate, request: Request, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    p = get_program_for_user(db, program_id, admin)
    ch = body.model_dump(exclude_unset=True)
    if "thresholds" in ch and ch["thresholds"] is not None:
        th = {**(p.thresholds or {})}
        for k in ("delay_pts", "critical_pts", "stalled_snapshots", "near_critical_days", "long_duration_days"):
            if k in ch["thresholds"]:
                try:
                    th[k] = float(ch["thresholds"][k])
                except (TypeError, ValueError):
                    raise HTTPException(422, f"Threshold {k} must be numeric") from None
        if th.get("critical_pts", -15) > th.get("delay_pts", -5):
            raise HTTPException(422, "critical_pts must be ≤ delay_pts")
        p.thresholds = th
        ch.pop("thresholds")
    for k, v in ch.items():
        setattr(p, k, v)
    audit(db, "program.update", user=admin, entity_type="program", entity_id=p.id, program_id=p.id, request=request,
          details=body.model_dump(exclude_unset=True))
    db.commit()
    return program_out(db, p)


@router.delete("/{program_id}", status_code=204)
def delete_program(program_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = get_program_for_user(db, program_id, admin)
    audit(db, "program.delete", user=admin, entity_type="program", entity_id=p.id, program_id=p.id, request=request,
          details={"name": p.name})
    db.delete(p)
    db.commit()


@router.get("/{program_id}/tracks")
def list_tracks(program_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    get_program_for_user(db, program_id, user)
    return [{"id": t.id, "number": t.number, "key": t.key, "name": t.name, "name_ar": t.name_ar,
             "source_label": t.source_label} for t in db.scalars(select(Track).where(Track.program_id == program_id)
                                                                 .order_by(Track.number))]


@router.patch("/{program_id}/tracks/{track_id}")
def rename_track(program_id: int, track_id: int, body: dict, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    get_program_for_user(db, program_id, admin)
    t = db.get(Track, track_id)
    if t is None or t.program_id != program_id:
        raise HTTPException(404)
    if body.get("name_ar") is not None:
        t.name_ar = str(body["name_ar"])[:300]
    audit(db, "track.update", user=admin, entity_type="track", entity_id=t.id, program_id=program_id,
          request=request, details=body)
    db.commit()
    return {"ok": True}
