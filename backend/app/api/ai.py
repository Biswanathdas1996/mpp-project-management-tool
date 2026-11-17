"""AI insights API. Every endpoint degrades gracefully when AI is off (503 + clear message)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.provider import AIUnavailable
from ..ai.service import AIService
from ..audit import audit
from ..db import get_db
from ..models import AIRequestLog, AttentionItem, Decision, Insight, Risk, User
from ..security import require_admin, require_editor, require_viewer
from .common import get_snapshot_for_user, require_ready

router = APIRouter(tags=["ai"])
Kind = Literal["executive_summary", "change_narrative", "root_cause", "forecast", "draft_governance"]


def insight_out(i: Insight) -> dict:
    return {"id": i.id, "kind": i.kind, "snapshot_id": i.snapshot_id, "question": i.question, "content": i.content,
            "guardrail_flags": i.guardrail_flags or [], "provider": i.provider, "model": i.model,
            "prompt_version": i.prompt_version, "latency_ms": i.latency_ms, "created_at": i.created_at.isoformat()}


@router.get("/ai/status")
def ai_status(user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    svc = AIService(db, user.tenant)
    return {"enabled": svc.enabled, "mode": user.tenant.ai_mode, "model": svc.model,
            "redaction": user.tenant.ai_redact and svc.provider.is_external}


@router.get("/snapshots/{snapshot_id}/insights")
def list_insights(snapshot_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    snap, _ = get_snapshot_for_user(db, snapshot_id, user)
    rows = db.scalars(select(Insight).where(Insight.snapshot_id == snap.id).order_by(Insight.created_at.desc()))
    latest: dict[str, Insight] = {}
    qa = []
    for i in rows:
        if i.kind == "qa":
            qa.append(i)
        elif i.kind not in latest:
            latest[i.kind] = i
    return {"latest": {k: insight_out(v) for k, v in latest.items()}, "qa": [insight_out(i) for i in qa[:50]]}


@router.post("/snapshots/{snapshot_id}/insights/{kind}")
def generate_insight(snapshot_id: int, kind: Kind, request: Request, force: bool = False,
                     user: User = Depends(require_editor), db: Session = Depends(get_db)):
    snap, program = get_snapshot_for_user(db, snapshot_id, user)
    require_ready(snap)
    svc = AIService(db, user.tenant)
    started = datetime.now(timezone.utc)
    try:
        ins = svc.insight(kind, program, snap, user=user, force=force)
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    created = {"risks": 0, "decisions": 0, "attention": 0}
    created_at = ins.created_at if ins.created_at.tzinfo else ins.created_at.replace(tzinfo=timezone.utc)
    fresh = created_at >= started - timedelta(seconds=1)  # a cache hit must not create the drafts twice
    skipped = 0
    if kind == "draft_governance" and fresh:
        # AI drafts → human review (review_status=draft) → approved.  Guardrail: drop drafts that duplicate
        # an existing item (fuzzy title match), since the model may ignore the "do not duplicate" instruction.
        c = ins.content
        today = date.today()
        existing = {m: [x.title.lower() for x in db.scalars(select(m).where(m.program_id == program.id))]
                    for m in (Risk, Decision, AttentionItem)}

        def dup(model, title: str) -> bool:
            nonlocal skipped
            hit = any(fuzz.token_sort_ratio(title.lower(), e) >= 88 for e in existing[model])
            skipped += hit
            existing[model].append(title.lower())
            return hit

        c["risks"] = [r for r in c.get("risks", []) if not dup(Risk, r["title"])]
        c["decisions"] = [d for d in c.get("decisions", []) if not dup(Decision, d["title"])]
        c["attention"] = [a for a in c.get("attention", []) if not dup(AttentionItem, a["title"])]
        for r in c.get("risks", []):
            db.add(Risk(program_id=program.id, title=r["title"], description=r["description"], severity=r["severity"],
                        mitigation=r["mitigation"], owner=r.get("owner"),
                        due_date=today + timedelta(days=r["due_in_days"]) if r.get("due_in_days") is not None else None,
                        related_task_uids=r.get("related_task_uids", []), source="ai", review_status="draft",
                        origin_snapshot_id=snap.id, created_by_id=user.id))
            created["risks"] += 1
        for d in c.get("decisions", []):
            db.add(Decision(program_id=program.id, title=d["title"], description=d["description"], kind=d.get("kind", "decision"),
                            priority=d["priority"], owner=d.get("owner"),
                            needed_by=today + timedelta(days=d["needed_in_days"]) if d.get("needed_in_days") is not None else None,
                            related_task_uids=d.get("related_task_uids", []), source="ai", review_status="draft",
                            origin_snapshot_id=snap.id, created_by_id=user.id))
            created["decisions"] += 1
        for a in c.get("attention", []):
            db.add(AttentionItem(program_id=program.id, title=a["title"], description=a["description"],
                                 severity=a["severity"], related_task_uids=a.get("related_task_uids", []),
                                 source="ai", review_status="draft", origin_snapshot_id=snap.id,
                                 created_by_id=user.id))
            created["attention"] += 1
    audit(db, f"ai.{kind}", user=user, entity_type="insight", entity_id=ins.id, program_id=program.id,
          request=request, details={"drafts": created} if kind == "draft_governance" else {})
    db.commit()
    return {**insight_out(ins), "drafts_created": created, "duplicates_skipped": skipped}


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@router.post("/snapshots/{snapshot_id}/ask")
def ask(snapshot_id: int, body: AskIn, request: Request, user: User = Depends(require_viewer),
        db: Session = Depends(get_db)):
    snap, program = get_snapshot_for_user(db, snapshot_id, user)
    require_ready(snap)
    try:
        ins = AIService(db, user.tenant).ask(program, snap, body.question, user)
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    audit(db, "ai.qa", user=user, entity_type="insight", entity_id=ins.id, program_id=program.id, request=request,
          details={"question": body.question[:200]})
    db.commit()
    return insight_out(ins)


@router.get("/snapshots/{snapshot_id}/discovery")
def discovery(snapshot_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    snap, _ = get_snapshot_for_user(db, snapshot_id, user)
    disc = (snap.profile or {}).get("discovery") or {}
    ins = db.get(Insight, disc["insight_id"]) if disc.get("insight_id") else None
    return {"profile": {k: v for k, v in (snap.profile or {}).items() if k != "discovery"}, "discovery": disc,
            "insight": insight_out(ins) if ins else None}


@router.get("/ai/logs")
def ai_logs(limit: int = 200, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIRequestLog).where(AIRequestLog.tenant_id == admin.tenant_id)
                      .order_by(AIRequestLog.created_at.desc()).limit(min(limit, 1000)))
    return [{"id": r.id, "kind": r.kind, "provider": r.provider, "model": r.model, "status": r.status,
             "redacted": r.redacted, "redaction_count": r.redaction_count, "prompt_chars": r.prompt_chars,
             "response_chars": r.response_chars, "prompt_tokens": r.prompt_tokens,
             "completion_tokens": r.completion_tokens, "latency_ms": r.latency_ms, "error": r.error,
             "program_id": r.program_id, "snapshot_id": r.snapshot_id, "created_at": r.created_at.isoformat()}
            for r in rows]
