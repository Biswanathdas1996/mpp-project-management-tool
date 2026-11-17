"""Mapping wizard API: proposal → preview → approve (incl. approved KPI set) → recompute."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..kpi.engine import REGISTRY
from ..models import MappingConfig, Snapshot, Task, User
from ..queue import enqueue
from ..security import get_program_for_user, require_admin, require_viewer
from ..services.mapping import approve_mapping, preview_mapping

router = APIRouter(prefix="/programs/{program_id}/mapping", tags=["mapping"])


class Rule(BaseModel):
    type: Literal["outline_level", "custom_field", "flag"]
    level: int | None = None
    field: str | None = None
    value: str | None = None

    def clean(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class PreviewIn(BaseModel):
    snapshot_id: int | None = None
    track_rule: Rule
    milestone_rule: Rule


class ApproveIn(BaseModel):
    track_rule: Rule
    milestone_rule: Rule
    planned_method: Literal["auto", "baseline", "first_snapshot", "linear"] = "auto"
    track_names: dict[str, str] = {}
    excluded_track_keys: list[str] = []
    approved_kpis: list[str] = []


def mapping_out(m: MappingConfig) -> dict:
    return {"id": m.id, "version": m.version, "status": m.status, "track_rule": m.track_rule,
            "milestone_rule": m.milestone_rule, "planned_method": m.planned_method, "track_names": m.track_names or {},
            "excluded_track_keys": m.excluded_track_keys or [], "approved_kpis": m.approved_kpis or [],
            "proposed_kpis": m.proposed_kpis or [], "proposed_by": m.proposed_by, "rationale": m.rationale,
            "source_snapshot_id": m.source_snapshot_id, "approved_at": m.approved_at.isoformat() if m.approved_at else None,
            "auto_approved": m.status in ("approved", "superseded") and m.approved_at is not None and m.approved_by_id is None,
            "created_at": m.created_at.isoformat()}


@router.get("")
def get_mapping(program_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    get_program_for_user(db, program_id, user)
    rows = list(db.scalars(select(MappingConfig).where(MappingConfig.program_id == program_id)
                           .order_by(MappingConfig.version.desc())))
    approved = next((m for m in rows if m.status == "approved"), None)
    proposed = next((m for m in rows if m.status == "proposed"), None)
    latest_snap = db.scalar(select(Snapshot).where(Snapshot.program_id == program_id,
                                                   Snapshot.status.in_(("awaiting_mapping", "ready")))
                            .order_by(Snapshot.version_no.desc()).limit(1))
    profile = (latest_snap.profile or {}) if latest_snap else {}
    return {"approved": mapping_out(approved) if approved else None, "proposed": mapping_out(proposed) if proposed else None,
            "history": [mapping_out(m) for m in rows],
            "snapshot_id": latest_snap.id if latest_snap else None,
            "profile": profile,
            "kpi_catalogue": [{"code": d.code, "name": d.name, "category": d.category, "reference": d.reference,
                               "phase": d.phase, "formula": d.formula} for d in REGISTRY.values()]}


@router.post("/preview")
def preview(program_id: int, body: PreviewIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    get_program_for_user(db, program_id, user)
    snap_id = body.snapshot_id or db.scalar(select(func.max(Snapshot.id)).where(
        Snapshot.program_id == program_id, Snapshot.status.in_(("awaiting_mapping", "ready"))))
    snap = db.get(Snapshot, snap_id) if snap_id else None
    if snap is None or snap.program_id != program_id:
        raise HTTPException(404, "No parsed snapshot to preview against")
    tasks = list(db.scalars(select(Task).where(Task.snapshot_id == snap.id)))
    return {"snapshot_id": snap.id, **preview_mapping(tasks, body.track_rule.clean(), body.milestone_rule.clean())}


@router.post("/approve")
def approve(program_id: int, body: ApproveIn, request: Request, admin: User = Depends(require_admin),
            db: Session = Depends(get_db)):
    get_program_for_user(db, program_id, admin)
    unknown = [c for c in body.approved_kpis if c not in REGISTRY]
    if unknown:
        raise HTTPException(422, f"Unknown KPI codes: {unknown}")
    if body.track_rule.type == "flag":
        raise HTTPException(422, "Tracks must be defined by outline level or custom field")
    if body.track_rule.type == "outline_level" and not body.track_rule.level:
        raise HTTPException(422, "Track outline level required")
    if body.track_rule.type == "custom_field" and not body.track_rule.field:
        raise HTTPException(422, "Track custom field required")
    m = approve_mapping(db, program_id, track_rule=body.track_rule.clean(), milestone_rule=body.milestone_rule.clean(),
                        planned_method=body.planned_method, approved_kpis=body.approved_kpis,
                        track_names=body.track_names, excluded_track_keys=body.excluded_track_keys,
                        approved_by_id=admin.id)
    audit(db, "mapping.approve", user=admin, entity_type="mapping", entity_id=m.id, program_id=program_id,
          request=request, details={"version": m.version, "track_rule": m.track_rule, "milestone_rule": m.milestone_rule,
                                    "planned_method": m.planned_method, "kpis": len(m.approved_kpis)})
    db.commit()
    enqueue("app.jobs.recompute_program_job", program_id)
    return mapping_out(m)


@router.put("/kpis")
def update_approved_kpis(program_id: int, body: dict, request: Request, admin: User = Depends(require_admin),
                         db: Session = Depends(get_db)):
    """Change the approved KPI set without touching the mapping rules (no recompute needed)."""
    get_program_for_user(db, program_id, admin)
    codes = body.get("approved_kpis") or []
    unknown = [c for c in codes if c not in REGISTRY]
    if unknown:
        raise HTTPException(422, f"Unknown KPI codes: {unknown}")
    m = db.scalar(select(MappingConfig).where(MappingConfig.program_id == program_id, MappingConfig.status == "approved")
                  .order_by(MappingConfig.version.desc()).limit(1))
    if m is None:
        raise HTTPException(409, "Approve a mapping first")
    m.approved_kpis = codes
    audit(db, "mapping.kpis", user=admin, entity_type="mapping", entity_id=m.id, program_id=program_id,
          request=request, details={"count": len(codes)})
    db.commit()
    return mapping_out(m)
