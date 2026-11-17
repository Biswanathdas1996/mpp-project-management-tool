"""Builds the KPIContext for a snapshot from the database."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..kpi.engine import KPIContext, TrackView
from ..models import (
    Assignment,
    Decision,
    KPIValue,
    Milestone,
    Program,
    Resource,
    Risk,
    Snapshot,
    Task,
    TaskDiff,
    Track,
)
from .schedule_math import classify_status, is_leaf, rollup

HISTORY_CODES = ("program_completion", "planned_to_date", "burn_up", "schedule_variance_days")


def ordered_snapshots(db: Session, program_id: int, statuses=("ready",)) -> list[Snapshot]:
    return list(db.scalars(
        select(Snapshot).where(Snapshot.program_id == program_id, Snapshot.status.in_(statuses))
        .order_by(Snapshot.as_of_date, Snapshot.version_no)
    ))


def previous_snapshot(db: Session, snapshot: Snapshot, statuses=("ready",)) -> Snapshot | None:
    return db.scalar(
        select(Snapshot).where(
            Snapshot.program_id == snapshot.program_id,
            Snapshot.status.in_(statuses),
            Snapshot.id != snapshot.id,
            or_(Snapshot.as_of_date < snapshot.as_of_date,
                and_(Snapshot.as_of_date == snapshot.as_of_date, Snapshot.version_no < snapshot.version_no)),
        ).order_by(Snapshot.as_of_date.desc(), Snapshot.version_no.desc()).limit(1)
    )


def build_track_views(db: Session, program: Program, tasks: list[Task], planned: dict[int, float]) -> list[TrackView]:
    by_track: dict[int, list[Task]] = {}
    for t in tasks:
        if t.track_id is not None:
            by_track.setdefault(t.track_id, []).append(t)
    if not by_track:
        return []
    tracks = db.scalars(select(Track).where(Track.id.in_(by_track.keys())).order_by(Track.number)).all()
    out = []
    for tr in tracks:
        ts = by_track[tr.id]
        act, pln, n = rollup(ts, planned)
        leaves = [t for t in ts if is_leaf(t)] or ts
        starts = [t.start for t in leaves if t.start]
        fins = [t.finish for t in leaves if t.finish]
        started = any(t.actual_start for t in leaves) or act > 0
        out.append(TrackView(
            id=tr.id, number=tr.number, name=tr.name, source_label=tr.source_label, tasks=ts,
            actual=act, planned=pln, leaf_count=n, start=min(starts) if starts else None,
            finish=max(fins) if fins else None, started=started,
            status=classify_status(act, pln, started, program.thresholds),
        ))
    return out


def diff_to_dict(d: TaskDiff) -> dict[str, Any]:
    return {c: getattr(d, c) for c in ("task_unique_id", "base_unique_id", "match_method", "match_score",
                                        "change_type", "task_name", "track_id", "is_milestone", "changes",
                                        "start_delta_days", "finish_delta_days", "progress_delta",
                                        "old_status", "new_status")}


def build_context(db: Session, program: Program, snapshot: Snapshot, today: date | None = None) -> KPIContext:
    tasks = list(db.scalars(select(Task).where(Task.snapshot_id == snapshot.id)))
    planned = {t.unique_id: (t.planned_percent or 0.0) for t in tasks}
    tracks = build_track_views(db, program, tasks, planned)
    milestones = list(db.scalars(select(Milestone).where(Milestone.snapshot_id == snapshot.id).order_by(Milestone.number)))
    resources = list(db.scalars(select(Resource).where(Resource.snapshot_id == snapshot.id)))
    assignments = list(db.scalars(select(Assignment).where(Assignment.snapshot_id == snapshot.id)))

    prior = [s for s in ordered_snapshots(db, program.id)
             if s.id != snapshot.id and (s.as_of_date, s.version_no) < (snapshot.as_of_date, snapshot.version_no)]
    history = []
    if prior:
        vals = db.execute(select(KPIValue.snapshot_id, KPIValue.code, KPIValue.value, KPIValue.details)
                          .where(KPIValue.snapshot_id.in_([s.id for s in prior]), KPIValue.code.in_(HISTORY_CODES))).all()
        by_snap: dict[int, dict[str, Any]] = {}
        for sid, code, value, details in vals:
            by_snap.setdefault(sid, {})[code] = (value, details or {})
        history = [{"snapshot_id": s.id, "as_of": s.as_of_date, "values": by_snap.get(s.id, {})} for s in prior]

    prev = prior[-1] if prior else None
    prev_tasks = list(db.scalars(select(Task).where(Task.snapshot_id == prev.id))) if prev else []
    n = int((program.thresholds or {}).get("stalled_snapshots", 3))
    stalled_history = []
    for s in prior[-(max(n - 1, 1)):]:
        rows = db.execute(select(Task.unique_id, Task.percent_complete).where(Task.snapshot_id == s.id)).all()
        stalled_history.append({r[0]: r[1] for r in rows})

    first_leaf_count = first_total_duration = None
    if prior:
        first = prior[0]
        rows = db.execute(select(Task.duration_days).where(Task.snapshot_id == first.id, Task.is_summary.is_(False),
                                                           Task.outline_level > 0)).all()
        first_leaf_count = len(rows)
        first_total_duration = float(sum(r[0] or 0 for r in rows))

    diffs = [diff_to_dict(d) for d in db.scalars(
        select(TaskDiff).where(TaskDiff.snapshot_id == snapshot.id, TaskDiff.compare_to == "previous"))]

    risks = list(db.scalars(select(Risk).where(Risk.program_id == program.id)))
    decisions = list(db.scalars(select(Decision).where(Decision.program_id == program.id)))
    rebase_events = sum(1 for s in prior if s.rebaselined) + (1 if snapshot.rebaselined else 0)

    return KPIContext(
        as_of=snapshot.as_of_date, tasks=tasks, planned=planned, tracks=tracks, milestones=milestones,
        thresholds=program.thresholds or {}, planned_method=snapshot.planned_method_used or "linear",
        resources=resources, assignments=assignments, history=history, prev_tasks=prev_tasks,
        stalled_history=stalled_history, diffs_prev=diffs, first_leaf_count=first_leaf_count,
        first_total_duration=first_total_duration, rebaselined=snapshot.rebaselined,
        rebaseline_events=rebase_events, reporting_cycle_days=program.reporting_cycle_days,
        risks=risks, decisions=decisions, today=today or date.today(),
    )
