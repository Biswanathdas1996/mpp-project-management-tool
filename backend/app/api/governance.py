"""Governance data (source B): risks, decisions/support requests, attention items.

NOTE: no `from __future__ import annotations` here — the dynamically registered routes need real
(evaluated) body annotations for FastAPI to build request models.

Manual entry, or AI-drafted → human review → approved.  Persists across snapshots.
"""

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..models import AttentionItem, Decision, Risk, User
from ..security import get_program_for_user, require_editor, require_viewer
from ..services.dashboard import attention_dict, decision_dict, risk_dict

router = APIRouter(prefix="/programs/{program_id}", tags=["governance"])

Sev = Literal["Critical", "High", "Medium", "Low"]
Pri = Literal["High", "Medium", "Low"]


class RiskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    title_ar: str | None = None
    description: str | None = None
    severity: Sev = "Medium"
    likelihood: str | None = None
    impact: str | None = None
    mitigation: str | None = None
    owner: str | None = None
    due_date: date | None = None
    status: Literal["Open", "Mitigating", "Closed"] = "Open"
    related_task_uids: list[int] = []


class DecisionIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    title_ar: str | None = None
    description: str | None = None
    kind: Literal["decision", "support"] = "decision"
    priority: Pri = "Medium"
    status: Literal["Pending", "Approved", "Rejected"] = "Pending"
    owner: str | None = None
    needed_by: date | None = None
    related_task_uids: list[int] = []


class AttentionIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    title_ar: str | None = None
    description: str | None = None
    severity: Sev = "Medium"
    status: Literal["Open", "Resolved"] = "Open"
    owner: str | None = None
    due_date: date | None = None
    category: str | None = None
    related_task_uids: list[int] = []


class ReviewIn(BaseModel):
    action: Literal["approve", "reject"]


KINDS = {
    "risks": (Risk, RiskIn, risk_dict),
    "decisions": (Decision, DecisionIn, decision_dict),
    "attention": (AttentionItem, AttentionIn, attention_dict),
}


def _get_item(db: Session, model, item_id: int, program_id: int):
    obj = db.get(model, item_id)
    if obj is None or obj.program_id != program_id:
        raise HTTPException(404, "Item not found")
    return obj


def _register(kind: str):
    model, schema, to_dict = KINDS[kind]

    @router.get(f"/{kind}", name=f"list_{kind}")
    def list_items(program_id: int, include_drafts: bool = True, user: User = Depends(require_viewer),
                   db: Session = Depends(get_db)):
        get_program_for_user(db, program_id, user)
        q = select(model).where(model.program_id == program_id)
        if not include_drafts:
            q = q.where(model.review_status == "approved")
        else:
            q = q.where(model.review_status != "rejected")
        return [to_dict(o) for o in db.scalars(q.order_by(model.created_at.desc()))]

    @router.post(f"/{kind}", status_code=201, name=f"create_{kind}")
    def create_item(program_id: int, body: schema, request: Request, user: User = Depends(require_editor),  # type: ignore[valid-type]
                    db: Session = Depends(get_db)):
        get_program_for_user(db, program_id, user)
        obj = model(program_id=program_id, source="manual", review_status="approved", created_by_id=user.id,
                    reviewed_by_id=user.id, reviewed_at=datetime.now(timezone.utc), **body.model_dump())
        if kind == "decisions" and obj.status != "Pending":
            obj.decided_at = date.today()
        db.add(obj)
        db.flush()
        audit(db, f"{kind}.create", user=user, entity_type=kind, entity_id=obj.id, program_id=program_id,
              request=request, details={"title": obj.title})
        db.commit()
        return to_dict(obj)

    @router.put(f"/{kind}/{{item_id}}", name=f"update_{kind}")
    def update_item(program_id: int, item_id: int, body: schema, request: Request,  # type: ignore[valid-type]
                    user: User = Depends(require_editor), db: Session = Depends(get_db)):
        get_program_for_user(db, program_id, user)
        obj = _get_item(db, model, item_id, program_id)
        before = to_dict(obj)
        data = body.model_dump()
        if kind == "decisions" and data["status"] != obj.status:
            obj.decided_at = date.today() if data["status"] != "Pending" else None
        for k, v in data.items():
            setattr(obj, k, v)
        changed = {k: {"old": before.get(k), "new": to_dict(obj).get(k)} for k in data
                   if before.get(k) != to_dict(obj).get(k)}
        audit(db, f"{kind}.update", user=user, entity_type=kind, entity_id=obj.id, program_id=program_id,
              request=request, details=changed)
        db.commit()
        return to_dict(obj)

    @router.post(f"/{kind}/{{item_id}}/review", name=f"review_{kind}")
    def review_item(program_id: int, item_id: int, body: ReviewIn, request: Request,
                    user: User = Depends(require_editor), db: Session = Depends(get_db)):
        get_program_for_user(db, program_id, user)
        obj = _get_item(db, model, item_id, program_id)
        if obj.review_status != "draft":
            raise HTTPException(409, "Only drafts can be reviewed")
        obj.review_status = "approved" if body.action == "approve" else "rejected"
        obj.reviewed_by_id = user.id
        obj.reviewed_at = datetime.now(timezone.utc)
        audit(db, f"{kind}.{body.action}", user=user, entity_type=kind, entity_id=obj.id, program_id=program_id,
              request=request, details={"title": obj.title, "source": obj.source})
        db.commit()
        return to_dict(obj)

    @router.delete(f"/{kind}/{{item_id}}", status_code=204, name=f"delete_{kind}")
    def delete_item(program_id: int, item_id: int, request: Request, user: User = Depends(require_editor),
                    db: Session = Depends(get_db)):
        get_program_for_user(db, program_id, user)
        obj = _get_item(db, model, item_id, program_id)
        audit(db, f"{kind}.delete", user=user, entity_type=kind, entity_id=obj.id, program_id=program_id,
              request=request, details={"title": obj.title})
        db.delete(obj)
        db.commit()


for _k in KINDS:
    _register(_k)
