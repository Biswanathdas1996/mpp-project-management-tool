"""Deterministic schedule maths: planned-to-date, roll-ups, status & health classification.

Planned-to-date (plan §Mapping layer):
  1. baseline dates when present on the task;
  2. else the task's dates in the program's FIRST snapshot (frozen as baseline);
  3. else linear by the task's current start→finish duration.
Variance (pts) = actual % − planned %.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, Protocol


class TaskLike(Protocol):
    unique_id: int
    start: date | None
    finish: date | None
    baseline_start: date | None
    baseline_finish: date | None
    percent_complete: float
    duration_days: float | None
    baseline_duration_days: float | None
    is_summary: bool
    outline_level: int


def linear_percent(start: date | None, finish: date | None, as_of: date) -> float | None:
    if start is None or finish is None:
        return None
    if as_of < start:
        return 0.0
    if as_of >= finish:
        return 100.0
    span = (finish - start).days
    if span <= 0:
        return 100.0
    return round(100.0 * (as_of - start).days / span, 4)


def planned_dates(task: TaskLike, method: str, frozen: dict[int, tuple[date | None, date | None]] | None):
    """Return (start, finish, source) used for planned-to-date for one task."""
    if method in ("baseline", "auto") and task.baseline_start and task.baseline_finish:
        return task.baseline_start, task.baseline_finish, "baseline"
    if method in ("baseline", "first_snapshot", "auto") and frozen and task.unique_id in frozen:
        s, f = frozen[task.unique_id]
        if s and f:
            return s, f, "first_snapshot"
    return task.start, task.finish, "linear"


def planned_percent(task: TaskLike, as_of: date, method: str,
                    frozen: dict[int, tuple[date | None, date | None]] | None) -> float:
    s, f, _ = planned_dates(task, method, frozen)
    v = linear_percent(s, f, as_of)
    return 0.0 if v is None else v


def weight(task: TaskLike) -> float:
    d = task.baseline_duration_days if task.baseline_duration_days else task.duration_days
    return float(d) if d and d > 0 else 0.0


def is_leaf(task: TaskLike) -> bool:
    return (not task.is_summary) and task.outline_level > 0


def rollup(tasks: Iterable[TaskLike], planned: dict[int, float]) -> tuple[float, float, int]:
    """Duration-weighted actual % and planned % over leaf tasks. Returns (actual, planned, n)."""
    leaves = [t for t in tasks if is_leaf(t)]
    if not leaves:
        return 0.0, 0.0, 0
    weights = [weight(t) for t in leaves]
    total = sum(weights)
    if total <= 0:
        weights = [1.0] * len(leaves)
        total = float(len(leaves))
    act = sum(w * (t.percent_complete or 0.0) for w, t in zip(weights, leaves)) / total
    pln = sum(w * planned.get(t.unique_id, 0.0) for w, t in zip(weights, leaves)) / total
    return round(act, 2), round(pln, 2), len(leaves)


DEFAULT_THRESHOLDS = {"delay_pts": -5.0, "critical_pts": -15.0}


def classify_status(actual: float, planned: float, started: bool, thresholds: dict[str, Any] | None = None) -> str:
    """completed | not_started | on_track | delay | critical_delay."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if actual >= 99.999:
        return "completed"
    variance = actual - planned
    if actual <= 0 and not started:
        if planned <= 0:
            return "not_started"
    if variance >= th["delay_pts"]:
        return "on_track" if (actual > 0 or started) else "not_started"
    if variance >= th["critical_pts"]:
        return "delay"
    return "critical_delay"


def health_chip(actual: float, start: date | None, finish: date | None, as_of: date, started: bool) -> dict[str, Any]:
    """COMPLETE / DUE IN nD / STARTS IN nD / OVERDUE nD with an urgency level for colour."""
    if actual >= 99.999:
        return {"kind": "complete", "label": "COMPLETE", "days": 0, "urgency": "done"}
    if not started and actual <= 0 and start and start > as_of:
        days = (start - as_of).days
        urgency = "high" if days <= 7 else "medium" if days <= 30 else "low"
        return {"kind": "starts_in", "label": f"STARTS IN {days}D", "days": days, "urgency": urgency}
    if finish is None:
        return {"kind": "unknown", "label": "NO DATE", "days": None, "urgency": "low"}
    days = (finish - as_of).days
    if days < 0:
        return {"kind": "overdue", "label": f"OVERDUE {-days}D", "days": days, "urgency": "critical"}
    urgency = "high" if days <= 14 else "medium" if days <= 30 else "low"
    return {"kind": "due_in", "label": f"DUE IN {days}D", "days": days, "urgency": urgency}


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month) + 1
