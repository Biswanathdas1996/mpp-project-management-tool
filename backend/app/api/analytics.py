"""Dashboard, KPI catalogue, drill-down, change tracking (diff/compare), milestone history, trends."""
from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..kpi.engine import REGISTRY, catalogue, compute_all
from ..models import KPIValue, Milestone, Snapshot, Task, TaskDiff, Track, User
from ..security import get_program_for_user, require_viewer
from ..services.context import build_context, diff_to_dict, ordered_snapshots
from ..services.dashboard import approved_kpi_codes, build_dashboard, kv_dict
from ..services.diff import diff_tasks
from ..services.mapping import descendants_map
from .common import get_snapshot_for_user, latest_ready, require_ready

router = APIRouter(tags=["analytics"])


def task_out(t: Task) -> dict[str, Any]:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"unique_id": t.unique_id, "task_id": t.task_id, "wbs": t.wbs, "outline_number": t.outline_number,
            "outline_level": t.outline_level, "name": t.name, "is_summary": t.is_summary, "is_milestone": t.is_milestone,
            "is_mapped_milestone": t.is_mapped_milestone, "is_critical": t.is_critical, "is_active": t.is_active,
            "start": iso(t.start), "finish": iso(t.finish), "baseline_start": iso(t.baseline_start),
            "baseline_finish": iso(t.baseline_finish), "actual_start": iso(t.actual_start),
            "actual_finish": iso(t.actual_finish), "percent_complete": t.percent_complete,
            "planned_percent": t.planned_percent, "duration_days": t.duration_days,
            "baseline_duration_days": t.baseline_duration_days, "remaining_duration_days": t.remaining_duration_days,
            "work_hours": t.work_hours, "actual_work_hours": t.actual_work_hours, "cost": t.cost,
            "baseline_cost": t.baseline_cost, "actual_cost": t.actual_cost, "total_slack_days": t.total_slack_days,
            "free_slack_days": t.free_slack_days, "constraint_type": t.constraint_type,
            "constraint_date": iso(t.constraint_date), "deadline": iso(t.deadline), "predecessors": t.predecessors,
            "successors": t.successors, "resource_names": t.resource_names, "track_id": t.track_id,
            "calendar_name": t.calendar_name, "notes": t.notes, "custom_fields": t.custom_fields,
            "parent_unique_id": t.parent_unique_id}


@router.get("/kpi-catalogue")
def kpi_catalogue(_: User = Depends(require_viewer)):
    return catalogue()


@router.get("/programs/{program_id}/dashboard")
def dashboard(program_id: int, snapshot_id: int | None = None, user: User = Depends(require_viewer),
              db: Session = Depends(get_db)):
    program = get_program_for_user(db, program_id, user)
    if snapshot_id:
        snap, _ = get_snapshot_for_user(db, snapshot_id, user)
        if snap.program_id != program.id:
            raise HTTPException(404)
    else:
        snap = latest_ready(db, program.id)
        if snap is None:
            raise HTTPException(404, "No processed snapshot yet — upload a plan and approve the mapping")
    require_ready(snap)
    return build_dashboard(db, program, snap)


@router.get("/snapshots/{snapshot_id}/kpis")
def snapshot_kpis(snapshot_id: int, all: bool = False, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    """Extended KPI catalogue values; filtered to the admin-approved set unless ?all=true."""
    snap, program = get_snapshot_for_user(db, snapshot_id, user)
    require_ready(snap)
    rows = {k.code: k for k in db.scalars(select(KPIValue).where(KPIValue.snapshot_id == snap.id))}
    ctx = build_context(db, program, snap)
    live = compute_all(ctx, live_only=True)
    approved = approved_kpi_codes(db, program)
    out = []
    for code, d in REGISTRY.items():
        if not all and approved is not None and code not in approved and not d.reference:
            continue
        if code in live:
            r = live[code][1]
            item = {"code": code, "name": d.name, "category": d.category, "formula": d.formula, "widget": d.widget,
                    "unit": d.unit, "phase": d.phase, "version": d.version, "available": r.available, "reason": r.reason,
                    "value": r.value, "display": r.display, "details": r.details, "drill_count": len(r.drill_uids)}
        else:
            item = kv_dict(rows.get(code)) or {"code": code, "name": d.name, "category": d.category,
                                               "available": False, "reason": "Not computed for this snapshot"}
        item["reference"] = d.reference
        item["source_fields"] = d.source_fields
        item["approved"] = approved is None or code in approved or d.reference
        out.append(item)
    return {"snapshot_id": snap.id, "engine_version": snap.kpi_engine_version, "approved_set": sorted(approved) if approved else None,
            "kpis": out}


@router.get("/snapshots/{snapshot_id}/drill")
def drill(snapshot_id: int, kpi: str | None = None, track_id: int | None = None, milestone_id: int | None = None,
          uids: str | None = None, user: User = Depends(require_viewer),
          db: Session = Depends(get_db)):
    """Every number drills down to its underlying tasks."""
    snap, _ = get_snapshot_for_user(db, snapshot_id, user)
    q = select(Task).where(Task.snapshot_id == snap.id)
    title = "Tasks"
    if kpi:
        k = db.scalar(select(KPIValue).where(KPIValue.snapshot_id == snap.id, KPIValue.code == kpi))
        ids = list(k.drill_uids or []) if k else []
        q = q.where(Task.unique_id.in_(ids)) if ids else q.where(False)
        title = REGISTRY[kpi].name if kpi in REGISTRY else kpi
    elif milestone_id:
        m = db.get(Milestone, milestone_id)
        if m is None or m.snapshot_id != snap.id:
            raise HTTPException(404)
        tasks = list(db.scalars(select(Task).where(Task.snapshot_id == snap.id)))
        desc = descendants_map(tasks)
        ids = [m.task_unique_id] + [t.unique_id for t in desc.get(m.task_unique_id, [])]
        q = q.where(Task.unique_id.in_(ids))
        title = f"Milestone {m.number:02d} · {m.name}"
    elif track_id:
        tr = db.get(Track, track_id)
        q = q.where(Task.track_id == track_id)
        title = f"Track {tr.number:02d} · {tr.name}" if tr else "Track"
    elif uids:
        try:
            ids = [int(x) for x in uids.split(",") if x.strip()][:5000]
        except ValueError:
            raise HTTPException(422, "uids must be comma-separated integers") from None
        q = q.where(Task.unique_id.in_(ids))
    tasks = list(db.scalars(q.order_by(Task.task_id)))
    return {"title": title, "count": len(tasks), "tasks": [task_out(t) for t in tasks[:5000]]}


@router.get("/snapshots/{snapshot_id}/tasks")
def list_tasks(snapshot_id: int, search: str | None = None, track_id: int | None = None, leaf_only: bool = False,
               offset: int = 0, limit: int = Query(200, le=2000), user: User = Depends(require_viewer),
               db: Session = Depends(get_db)):
    snap, _ = get_snapshot_for_user(db, snapshot_id, user)
    q = select(Task).where(Task.snapshot_id == snap.id)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Task.name.ilike(like), Task.wbs.ilike(like)))
    if track_id:
        q = q.where(Task.track_id == track_id)
    if leaf_only:
        q = q.where(Task.is_summary.is_(False))
    tasks = list(db.scalars(q.order_by(Task.task_id).offset(offset).limit(limit)))
    return {"tasks": [task_out(t) for t in tasks], "offset": offset, "limit": limit}


def _summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    c = Counter(r["change_type"] for r in rows)
    return {"total": len(rows), "by_type": dict(c),
            "renamed": sum(1 for r in rows if "name" in (r.get("changes") or {})),
            "slipped": sum(1 for r in rows if (r.get("finish_delta_days") or 0) > 0),
            "pulled_in": sum(1 for r in rows if (r.get("finish_delta_days") or 0) < 0),
            "net_finish_days": sum(r.get("finish_delta_days") or 0 for r in rows),
            "milestones_changed": sum(1 for r in rows if r.get("is_milestone")),
            "status_transitions": dict(Counter(f"{r['old_status']}→{r['new_status']}" for r in rows if r.get("old_status")))}


@router.get("/snapshots/{snapshot_id}/diff")
def snapshot_diff(snapshot_id: int, compare_to: str = "previous", user: User = Depends(require_viewer),
                  db: Session = Depends(get_db)):
    """'What changed': vs previous snapshot, vs baseline, or vs any other snapshot id (compare)."""
    snap, program = get_snapshot_for_user(db, snapshot_id, user)
    require_ready(snap)
    base_info = None
    if compare_to in ("previous", "baseline"):
        rows = [diff_to_dict(d) for d in db.scalars(select(TaskDiff).where(TaskDiff.snapshot_id == snap.id,
                                                                           TaskDiff.compare_to == compare_to))]
        base_id = db.scalar(select(TaskDiff.base_snapshot_id).where(TaskDiff.snapshot_id == snap.id,
                                                                    TaskDiff.compare_to == compare_to).limit(1))
        if base_id:
            b = db.get(Snapshot, base_id)
            base_info = {"id": b.id, "version_no": b.version_no, "as_of": b.as_of_date.isoformat()} if b else None
    else:
        try:
            other_id = int(compare_to)
        except ValueError:
            raise HTTPException(422, "compare_to must be previous, baseline or a snapshot id") from None
        other, _ = get_snapshot_for_user(db, other_id, user)
        if other.program_id != program.id:
            raise HTTPException(422, "Snapshots belong to different programs")
        require_ready(other)
        cur = list(db.scalars(select(Task).where(Task.snapshot_id == snap.id)))
        base = list(db.scalars(select(Task).where(Task.snapshot_id == other.id)))
        rows = diff_tasks(cur, base, snap.as_of_date, other.as_of_date,
                          {t.unique_id: t.planned_percent or 0 for t in cur},
                          {t.unique_id: t.planned_percent or 0 for t in base}, program.thresholds)
        base_info = {"id": other.id, "version_no": other.version_no, "as_of": other.as_of_date.isoformat()}
    rows.sort(key=lambda r: (not r["is_milestone"], -abs(r.get("finish_delta_days") or 0)))
    return {"snapshot_id": snap.id, "compare_to": compare_to, "base": base_info, "rebaselined": snap.rebaselined,
            "summary": _summarise(rows), "changes": rows}


@router.get("/programs/{program_id}/milestone-history")
def milestone_history(program_id: int, task_uid: int | None = None, user: User = Depends(require_viewer),
                      db: Session = Depends(get_db)):
    """Milestone state across all snapshots (dates, %, status) — matched by Unique ID."""
    get_program_for_user(db, program_id, user)
    snaps = ordered_snapshots(db, program_id)
    sid = {s.id: s for s in snaps}
    q = select(Milestone).where(Milestone.program_id == program_id, Milestone.snapshot_id.in_(sid.keys()))
    if task_uid is not None:
        q = q.where(Milestone.task_unique_id == task_uid)
    series: dict[int, dict[str, Any]] = {}
    for m in db.scalars(q):
        s = sid[m.snapshot_id]
        e = series.setdefault(m.task_unique_id, {"task_unique_id": m.task_unique_id, "name": m.name, "points": []})
        e["name"] = m.name
        e["points"].append({"snapshot_id": s.id, "version_no": s.version_no, "as_of": s.as_of_date.isoformat(),
                            "start": m.start.isoformat() if m.start else None,
                            "finish": m.finish.isoformat() if m.finish else None,
                            "baseline_finish": m.baseline_finish.isoformat() if m.baseline_finish else None,
                            "percent_complete": m.percent_complete, "planned_percent": m.planned_percent,
                            "status": m.status, "slippage_days": m.slippage_days})
    for e in series.values():
        e["points"].sort(key=lambda p: (p["as_of"], p["version_no"]))
        fins = [p["finish"] for p in e["points"] if p["finish"]]
        e["finish_moves"] = len(set(fins)) - 1 if fins else 0
    return sorted(series.values(), key=lambda e: e["points"][-1]["finish"] or "")


@router.get("/programs/{program_id}/trends")
def trends(program_id: int, codes: str = "program_completion,planned_to_date,spi,schedule_variance_days",
           user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    get_program_for_user(db, program_id, user)
    snaps = ordered_snapshots(db, program_id)
    want = [c for c in codes.split(",") if c in REGISTRY][:20]
    vals = db.execute(select(KPIValue.snapshot_id, KPIValue.code, KPIValue.value).where(
        KPIValue.snapshot_id.in_([s.id for s in snaps]), KPIValue.code.in_(want))).all()
    by: dict[int, dict[str, Any]] = {}
    for sid, code, v in vals:
        by.setdefault(sid, {})[code] = v
    return {"codes": want, "names": {c: REGISTRY[c].name for c in want},
            "points": [{"snapshot_id": s.id, "version_no": s.version_no, "as_of": s.as_of_date.isoformat(),
                        "rebaselined": s.rebaselined, **by.get(s.id, {})} for s in snaps]}
