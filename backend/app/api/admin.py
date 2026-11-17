"""Audit log, portfolio roll-up (v2) and alerts (v2)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..kpi.engine import REGISTRY
from ..models import Alert, AlertRule, AuditLog, Decision, KPIValue, Program, Risk, User
from ..security import get_program_for_user, require_admin, require_viewer
from .common import latest_ready

router = APIRouter(tags=["admin"])


# ------------------------------------------------------------------------------------------- audit
@router.get("/audit")
def audit_log(program_id: int | None = None, action: str | None = None, user_email: str | None = None,
              limit: int = 200, offset: int = 0, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(AuditLog).where(AuditLog.tenant_id == admin.tenant_id)
    if program_id:
        q = q.where(AuditLog.program_id == program_id)
    if action:
        q = q.where(AuditLog.action.ilike(f"{action}%"))
    if user_email:
        q = q.where(AuditLog.user_email.ilike(f"%{user_email}%"))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditLog.created_at.desc()).offset(offset).limit(min(limit, 1000)))
    return {"total": total, "items": [{"id": r.id, "action": r.action, "user_email": r.user_email,
                                       "entity_type": r.entity_type, "entity_id": r.entity_id,
                                       "program_id": r.program_id, "details": r.details, "ip": r.ip,
                                       "created_at": r.created_at.isoformat()} for r in rows]}


# ------------------------------------------------------------------------------------------- portfolio
@router.get("/portfolio")
def portfolio(user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    """Portfolio roll-up across all programmes of the tenant (latest ready snapshot each)."""
    programs = list(db.scalars(select(Program).where(Program.tenant_id == user.tenant_id, Program.is_archived.is_(False))
                               .order_by(Program.name)))
    rows = []
    today = date.today()
    codes = ("program_completion", "planned_to_date", "schedule_variance_pts", "total_milestones",
             "milestones_critical_delay", "milestones_delayed", "spi", "overdue_tasks", "total_tracks", "active_tracks")
    for p in programs:
        snap = latest_ready(db, p.id)
        vals = {}
        if snap:
            vals = {k.code: k for k in db.scalars(select(KPIValue).where(KPIValue.snapshot_id == snap.id,
                                                                         KPIValue.code.in_(codes)))}
        risks = list(db.scalars(select(Risk).where(Risk.program_id == p.id, Risk.review_status == "approved",
                                                   Risk.status != "Closed")))
        decs = list(db.scalars(select(Decision).where(Decision.program_id == p.id, Decision.review_status == "approved",
                                                      Decision.status == "Pending")))
        g = lambda c: vals[c].value if c in vals and vals[c].available else None  # noqa: E731
        rows.append({
            "program_id": p.id, "name": p.name, "name_ar": p.name_ar, "client_name": p.client_name,
            "snapshot_id": snap.id if snap else None, "as_of": snap.as_of_date.isoformat() if snap else None,
            "completion": g("program_completion"), "planned": g("planned_to_date"),
            "variance_pts": g("schedule_variance_pts"), "spi": g("spi"), "milestones": g("total_milestones"),
            "critical_delays": g("milestones_critical_delay"), "delays": g("milestones_delayed"),
            "overdue_tasks": g("overdue_tasks"), "tracks": g("total_tracks"), "active_tracks": g("active_tracks"),
            "tag": (vals["program_completion"].details or {}).get("tag") if "program_completion" in vals else None,
            "open_risks": len(risks), "high_risks": sum(1 for r in risks if r.severity in ("High", "Critical")),
            "pending_decisions": len(decs),
            "overdue_decisions": sum(1 for d in decs if d.needed_by and d.needed_by < today),
        })
    with_data = [r for r in rows if r["completion"] is not None]
    agg = None
    if with_data:
        agg = {"programs": len(rows), "reporting": len(with_data),
               "avg_completion": round(sum(r["completion"] for r in with_data) / len(with_data), 1),
               "avg_planned": round(sum((r["planned"] or 0) for r in with_data) / len(with_data), 1),
               "critical_delays": sum(r["critical_delays"] or 0 for r in with_data),
               "high_risks": sum(r["high_risks"] for r in rows), "pending_decisions": sum(r["pending_decisions"] for r in rows),
               "behind_plan": sum(1 for r in with_data if (r["variance_pts"] or 0) < -5)}
    return {"summary": agg, "programs": rows}


# ------------------------------------------------------------------------------------------- alerts
class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    program_id: int | None = None
    kpi_code: str
    operator: Literal["<", "<=", ">", ">=", "==", "!="]
    threshold: float
    channel: Literal["in_app", "email", "webhook"] = "in_app"
    target: str | None = None
    enabled: bool = True


def rule_out(r: AlertRule) -> dict:
    return {"id": r.id, "name": r.name, "program_id": r.program_id, "kpi_code": r.kpi_code, "operator": r.operator,
            "threshold": r.threshold, "channel": r.channel, "target": r.target, "enabled": r.enabled,
            "kpi_name": REGISTRY[r.kpi_code].name if r.kpi_code in REGISTRY else r.kpi_code}


def _validate_rule(db: Session, body: RuleIn, admin: User):
    if body.kpi_code not in REGISTRY:
        raise HTTPException(422, "Unknown KPI code")
    if body.program_id:
        get_program_for_user(db, body.program_id, admin)
    if body.channel == "webhook" and not (body.target or "").startswith("https://"):
        raise HTTPException(422, "Webhook target must be an https:// URL")
    if body.channel == "email" and "@" not in (body.target or ""):
        raise HTTPException(422, "Email target required")


@router.get("/alert-rules")
def list_rules(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [rule_out(r) for r in db.scalars(select(AlertRule).where(AlertRule.tenant_id == admin.tenant_id))]


@router.post("/alert-rules", status_code=201)
def create_rule(body: RuleIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _validate_rule(db, body, admin)
    r = AlertRule(tenant_id=admin.tenant_id, **body.model_dump())
    db.add(r)
    db.flush()
    audit(db, "alert_rule.create", user=admin, entity_type="alert_rule", entity_id=r.id, request=request,
          details=body.model_dump())
    db.commit()
    return rule_out(r)


@router.put("/alert-rules/{rule_id}")
def update_rule(rule_id: int, body: RuleIn, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    r = db.get(AlertRule, rule_id)
    if r is None or r.tenant_id != admin.tenant_id:
        raise HTTPException(404)
    _validate_rule(db, body, admin)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit(db, "alert_rule.update", user=admin, entity_type="alert_rule", entity_id=r.id, request=request,
          details=body.model_dump())
    db.commit()
    return rule_out(r)


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(AlertRule, rule_id)
    if r is None or r.tenant_id != admin.tenant_id:
        raise HTTPException(404)
    audit(db, "alert_rule.delete", user=admin, entity_type="alert_rule", entity_id=r.id, request=request)
    db.delete(r)
    db.commit()


@router.get("/alerts")
def list_alerts(program_id: int | None = None, unacknowledged: bool = False, user: User = Depends(require_viewer),
                db: Session = Depends(get_db)):
    q = select(Alert).where(Alert.tenant_id == user.tenant_id)
    if program_id:
        q = q.where(or_(Alert.program_id == program_id))
    if unacknowledged:
        q = q.where(Alert.acknowledged.is_(False))
    return [{"id": a.id, "title": a.title, "message": a.message, "value": a.value, "program_id": a.program_id,
             "snapshot_id": a.snapshot_id, "delivery_status": a.delivery_status, "acknowledged": a.acknowledged,
             "created_at": a.created_at.isoformat()} for a in db.scalars(q.order_by(Alert.created_at.desc()).limit(300))]


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if a is None or a.tenant_id != user.tenant_id:
        raise HTTPException(404)
    a.acknowledged = True
    a.acknowledged_by_id = user.id
    db.commit()
    return {"ok": True}
