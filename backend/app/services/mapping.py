"""Mapping layer: turn raw plan tasks into Tracks (01..n) and Milestones using a MappingConfig.

Track rule      outline_level → each summary task at level L is a track; descendants belong to it.
                custom_field  → each distinct value of the field is a track (value inherited down
                                the outline when a child task has no value).
Milestone rule  flag          → MS Project milestone flag.
                outline_level → tasks at level L.
                custom_field  → tasks whose field equals the configured value (flags: truthy).
Tracks are matched across snapshots by key so numbering stays stable when structure changes;
new tracks are appended (n+1…), vanished tracks keep their number but get no tasks.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import MappingConfig, Milestone, Program, Snapshot, Task, Track
from .schedule_math import classify_status, health_chip, planned_dates, planned_percent, rollup

_TRUTHY = {"true", "yes", "1", "y"}


def _cf_match(value: Any, expected: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value is True if str(expected).lower() in _TRUTHY or expected in (None, "") else not value
    if expected in (None, ""):
        return str(value).strip() != ""
    return str(value).strip().lower() == str(expected).strip().lower()


def resolve_tracks(tasks: list[Task], rule: dict[str, Any]) -> tuple[dict[int, str], dict[str, dict[str, Any]]]:
    """Return (task_uid → track_key, track_key → {name, source_label, order, anchor_uid})."""
    by_uid = {t.unique_id: t for t in tasks}
    ordered = sorted(tasks, key=lambda t: (t.task_id if t.task_id is not None else 10**9, t.unique_id))
    assign: dict[int, str] = {}
    meta: dict[str, dict[str, Any]] = {}
    rtype = rule.get("type", "outline_level")

    if rtype == "custom_field":
        field = rule.get("field", "")
        cache: dict[int, str | None] = {}

        def value_of(t: Task) -> str | None:
            if t.unique_id in cache:
                return cache[t.unique_id]
            v = (t.custom_fields or {}).get(field)
            if (v is None or v == "") and t.parent_unique_id is not None and t.parent_unique_id in by_uid:
                v = value_of(by_uid[t.parent_unique_id])
            cache[t.unique_id] = None if v in (None, "") else str(v).strip()
            return cache[t.unique_id]

        for t in ordered:
            if t.outline_level == 0:
                continue
            v = value_of(t)
            if v is None:
                continue
            key = f"cf:{field}:{v}"
            assign[t.unique_id] = key
            if key not in meta:
                meta[key] = {"name": v, "source_label": f"Custom field: {field}", "order": len(meta),
                             "anchor_uid": None}
        return assign, meta

    level = int(rule.get("level", 1))
    anchor_cache: dict[int, int | None] = {}

    def anchor(t: Task) -> int | None:
        if t.unique_id in anchor_cache:
            return anchor_cache[t.unique_id]
        if t.outline_level == level:
            res = t.unique_id
        elif t.outline_level < level or t.parent_unique_id is None or t.parent_unique_id not in by_uid:
            res = None
        else:
            res = anchor(by_uid[t.parent_unique_id])
        anchor_cache[t.unique_id] = res
        return res

    for t in ordered:
        a = anchor(t)
        if a is None:
            continue
        key = f"uid:{a}"
        assign[t.unique_id] = key
        if key not in meta:
            at = by_uid[a]
            meta[key] = {"name": at.name, "source_label": f"Outline level {level} summary",
                         "order": len(meta), "anchor_uid": a}
    return assign, meta


def is_milestone_task(t: Task, rule: dict[str, Any]) -> bool:
    rtype = rule.get("type", "flag")
    if t.outline_level == 0:
        return False
    if rtype == "flag":
        return bool(t.is_milestone)
    if rtype == "outline_level":
        return t.outline_level == int(rule.get("level", 2))
    if rtype == "custom_field":
        return _cf_match((t.custom_fields or {}).get(rule.get("field", "")), rule.get("value"))
    return False


def descendants_map(tasks: list[Task]) -> dict[int, list[Task]]:
    children: dict[int, list[Task]] = {}
    for t in tasks:
        if t.parent_unique_id is not None:
            children.setdefault(t.parent_unique_id, []).append(t)
    out: dict[int, list[Task]] = {}

    def collect(uid: int) -> list[Task]:
        if uid in out:
            return out[uid]
        res: list[Task] = []
        for c in children.get(uid, []):
            res.append(c)
            res.extend(collect(c.unique_id))
        out[uid] = res
        return res

    for t in tasks:
        collect(t.unique_id)
    return out


def first_snapshot_frozen(db: Session, program_id: int, snapshot: Snapshot) -> dict[int, tuple[date | None, date | None]]:
    """Dates from the program's first processed snapshot, used as a frozen baseline."""
    first = db.scalar(
        select(Snapshot).where(Snapshot.program_id == program_id, Snapshot.status.in_(("ready", "processing")),
                               Snapshot.id != snapshot.id)
        .order_by(Snapshot.as_of_date, Snapshot.version_no).limit(1)
    )
    if first is None or (first.as_of_date and snapshot.as_of_date and first.as_of_date > snapshot.as_of_date):
        return {}
    rows = db.execute(select(Task.unique_id, Task.start, Task.finish).where(Task.snapshot_id == first.id)).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def choose_planned_method(configured: str, tasks: list[Task], frozen: dict[int, Any]) -> str:
    if configured in ("baseline", "first_snapshot", "linear"):
        return configured
    leaves = [t for t in tasks if not t.is_summary and t.outline_level > 0]
    with_bl = sum(1 for t in leaves if t.baseline_start and t.baseline_finish)
    if leaves and with_bl / len(leaves) >= 0.5:
        return "baseline"
    if frozen:
        return "first_snapshot"
    return "linear"


def apply_mapping(db: Session, program: Program, snapshot: Snapshot, mapping: MappingConfig) -> dict[str, Any]:
    tasks: list[Task] = list(db.scalars(select(Task).where(Task.snapshot_id == snapshot.id)))
    as_of = snapshot.as_of_date
    thresholds = program.thresholds or {}

    # ---- Tracks -------------------------------------------------------------------------------
    assign, meta = resolve_tracks(tasks, mapping.track_rule or {"type": "outline_level", "level": 1})
    excluded = set(mapping.excluded_track_keys or [])
    existing = {t.key: t for t in db.scalars(select(Track).where(Track.program_id == program.id))}
    by_name: dict[str, Track] = {}
    for t in existing.values():
        by_name.setdefault(t.name.strip().lower(), t)
    next_no = max([t.number for t in existing.values()], default=0) + 1
    key_to_track: dict[str, Track] = {}
    claimed: set[int] = set()
    for key, m in sorted(meta.items(), key=lambda kv: kv[1]["order"]):
        if key in excluded:
            continue
        tr = existing.get(key)
        if tr is None or tr.id in claimed:
            # Fallback when the anchor UID changed (plan rebuilt / UIDs renumbered): same-named track
            cand = by_name.get((m["name"] or "").strip().lower())
            tr = cand if cand is not None and cand.id not in claimed and cand.key not in meta else None
        display = (mapping.track_names or {}).get(key) or m["name"]
        if tr is None:
            tr = Track(program_id=program.id, number=next_no, key=key, name=display,
                       source_label=m["source_label"], first_seen_snapshot_id=snapshot.id)
            next_no += 1
            db.add(tr)
        else:
            tr.name = display
            tr.source_label = m["source_label"]
        tr.last_seen_snapshot_id = snapshot.id
        if tr.id is not None:
            claimed.add(tr.id)
        key_to_track[key] = tr
    db.flush()

    # ---- Planned-to-date ------------------------------------------------------------------------
    frozen = first_snapshot_frozen(db, program.id, snapshot)
    method = choose_planned_method(mapping.planned_method or "auto", tasks, frozen)
    planned: dict[int, float] = {}
    for t in tasks:
        tr = key_to_track.get(assign.get(t.unique_id, ""))
        t.track_id = tr.id if tr else None
        t.is_mapped_milestone = is_milestone_task(t, mapping.milestone_rule or {"type": "flag"})
        t.planned_percent = planned_percent(t, as_of, method, frozen) if as_of else None
        planned[t.unique_id] = t.planned_percent or 0.0
    snapshot.planned_method_used = method

    # ---- Milestones -------------------------------------------------------------------------------
    db.execute(delete(Milestone).where(Milestone.snapshot_id == snapshot.id))
    desc = descendants_map(tasks)
    track_by_id = {tr.id: tr for tr in key_to_track.values()}
    ms_tasks = [t for t in tasks if t.is_mapped_milestone and t.track_id is not None]
    ms_tasks.sort(key=lambda t: (track_by_id[t.track_id].number, t.start or date.max, t.task_id or 0))
    for i, t in enumerate(ms_tasks, start=1):
        scope = [t] + desc.get(t.unique_id, [])
        if t.is_summary:
            act, pln, _ = rollup(scope, planned)
        else:
            act, pln = t.percent_complete or 0.0, planned.get(t.unique_id, 0.0)
        started = bool(t.actual_start) or act > 0
        status = classify_status(act, pln, started, thresholds)
        bs, bf, _src = planned_dates(t, method, frozen)
        slip = (t.finish - bf).days if (t.finish and bf) else None
        db.add(Milestone(
            snapshot_id=snapshot.id, program_id=program.id, track_id=t.track_id, task_unique_id=t.unique_id,
            number=i, name=t.name, start=t.start, finish=t.finish, baseline_start=bs, baseline_finish=bf,
            percent_complete=round(act, 2), planned_percent=round(pln, 2), variance_pts=round(act - pln, 2),
            status=status, health=health_chip(act, t.start, t.finish, as_of, started) if as_of else {},
            slippage_days=slip, is_critical=bool(t.is_critical),
        ))
    db.flush()
    return {"tracks": len(key_to_track), "milestones": len(ms_tasks), "planned_method": method,
            "unmapped_tasks": sum(1 for t in tasks if t.track_id is None and t.outline_level > 0)}


def preview_mapping(tasks: list[Task], track_rule: dict[str, Any], milestone_rule: dict[str, Any]) -> dict[str, Any]:
    """Mapping-wizard preview without persisting anything."""
    assign, meta = resolve_tracks(tasks, track_rule)
    counts: dict[str, int] = {}
    for k in assign.values():
        counts[k] = counts.get(k, 0) + 1
    ms = [t for t in tasks if is_milestone_task(t, milestone_rule) and t.unique_id in assign]
    tracks = [{"key": k, "number": i + 1, "name": m["name"], "source_label": m["source_label"],
               "task_count": counts.get(k, 0),
               "milestones": [t.name for t in ms if assign.get(t.unique_id) == k][:50]}
              for i, (k, m) in enumerate(sorted(meta.items(), key=lambda kv: kv[1]["order"]))]
    return {"tracks": tracks, "milestone_count": len(ms),
            "unmapped_tasks": sum(1 for t in tasks if t.unique_id not in assign and t.outline_level > 0)}


# ----------------------------------------------------------------------------------------------
# Approval (shared by the mapping wizard and automatic approval on upload)
# ----------------------------------------------------------------------------------------------
def approve_mapping(db: Session, program_id: int, *, track_rule: dict[str, Any], milestone_rule: dict[str, Any],
                    planned_method: str, approved_kpis: list[str], track_names: dict[str, str] | None = None,
                    excluded_track_keys: list[str] | None = None, approved_by_id: int | None = None,
                    proposed_by: str = "user") -> MappingConfig:
    """Supersede the current approved mapping and approve the pending proposal (or a new config) with
    these rules. ``approved_by_id=None`` marks an automatic approval. The caller commits and recomputes."""
    proposed = db.scalar(select(MappingConfig).where(MappingConfig.program_id == program_id,
                                                     MappingConfig.status == "proposed")
                         .order_by(MappingConfig.version.desc()).limit(1))
    for m in db.scalars(select(MappingConfig).where(MappingConfig.program_id == program_id,
                                                    MappingConfig.status == "approved")):
        m.status = "superseded"
    if proposed is None:
        next_ver = (db.scalar(select(func.max(MappingConfig.version))
                              .where(MappingConfig.program_id == program_id)) or 0) + 1
        proposed = MappingConfig(program_id=program_id, version=next_ver, proposed_by=proposed_by)
        db.add(proposed)
    m = proposed
    m.status = "approved"
    m.track_rule = track_rule
    m.milestone_rule = milestone_rule
    m.planned_method = planned_method
    m.track_names = track_names or {}
    m.excluded_track_keys = excluded_track_keys or []
    m.approved_kpis = approved_kpis
    m.approved_by_id = approved_by_id
    m.approved_at = datetime.now(timezone.utc)
    db.flush()
    return m
