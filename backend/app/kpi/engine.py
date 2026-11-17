"""Deterministic KPI engine (plan §Core features 3 / §5 catalogue).

* Every KPI is a pure function of a ``KPIContext`` (snapshot data + mapping + history + governance).
* Every KPI has a code, a formula version and metadata (formula text, source fields, widget, phase).
  KPIValue rows record the version used, so a formula change never silently rewrites history.
* A KPI the data cannot support returns ``available=False`` with a reason instead of a number.
* Every result carries ``drill_uids`` — the Unique IDs of the tasks that make up the number.
AI never computes numbers; it only reads these results.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..services.schedule_math import is_leaf, linear_percent, months_between, rollup, weight

ENGINE_VERSION = "1.0.0"
MAX_DRILL = 5000


@dataclass
class KPIResult:
    value: float | None = None
    display: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    drill_uids: list[int] = field(default_factory=list)
    available: bool = True
    reason: str | None = None


def unavailable(reason: str) -> KPIResult:
    return KPIResult(available=False, reason=reason)


@dataclass
class KPIDef:
    code: str
    name: str
    category: str
    formula: str
    source_fields: list[str]
    widget: str
    phase: str
    unit: str | None
    reference: bool
    version: int
    description: str
    fn: Callable[[KPIContext], KPIResult]
    live: bool = False  # governance KPIs are recomputed live (data B changes between snapshots)


REGISTRY: dict[str, KPIDef] = {}


def kpi(code: str, name: str, category: str, formula: str, source_fields: list[str], widget: str,
        phase: str, unit: str | None = None, reference: bool = False, version: int = 1,
        description: str = "", live: bool = False):
    def deco(fn: Callable[[KPIContext], KPIResult]):
        REGISTRY[code] = KPIDef(code, name, category, formula, source_fields, widget, phase, unit,
                                reference, version, description, fn, live)
        return fn

    return deco


# ----------------------------------------------------------------------------------------------
# Context
# ----------------------------------------------------------------------------------------------
@dataclass
class TrackView:
    id: int
    number: int
    name: str
    source_label: str
    tasks: list[Any]
    actual: float = 0.0
    planned: float = 0.0
    leaf_count: int = 0
    start: date | None = None
    finish: date | None = None
    started: bool = False
    status: str = "not_started"


@dataclass
class KPIContext:
    as_of: date
    tasks: list[Any]
    planned: dict[int, float]
    tracks: list[TrackView]
    milestones: list[Any]
    thresholds: dict[str, Any]
    planned_method: str
    resources: list[Any] = field(default_factory=list)
    assignments: list[Any] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)  # prior snapshots, oldest first
    prev_tasks: list[Any] = field(default_factory=list)
    stalled_history: list[dict[int, float]] = field(default_factory=list)  # last n snapshots uid→pct
    diffs_prev: list[dict[str, Any]] = field(default_factory=list)
    first_leaf_count: int | None = None
    first_total_duration: float | None = None
    rebaselined: bool = False
    rebaseline_events: int = 0
    reporting_cycle_days: int = 7
    risks: list[Any] = field(default_factory=list)
    decisions: list[Any] = field(default_factory=list)
    today: date = field(default_factory=date.today)

    def __post_init__(self):
        self.by_uid = {t.unique_id: t for t in self.tasks}
        mapped = [t for t in self.tasks if t.track_id is not None]
        base = mapped if mapped else self.tasks
        self.leaves = [t for t in base if is_leaf(t) and t.is_active is not False]
        self.all_leaves = [t for t in self.tasks if is_leaf(t) and t.is_active is not False]
        self.open_leaves = [t for t in self.leaves if (t.percent_complete or 0) < 100]


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def _uids(ts) -> list[int]:
    return [t.unique_id for t in ts][:MAX_DRILL]


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 3) if b else None


def _sum(ts, attr) -> float:
    return float(sum((getattr(t, attr) or 0.0) for t in ts))


def _has(ts, attr, min_share=0.0) -> bool:
    if not ts:
        return False
    n = sum(1 for t in ts if getattr(t, attr) not in (None, 0, 0.0, [], ""))
    return n > 0 and n / len(ts) >= min_share


def _hist(ctx: KPIContext, code: str) -> list[tuple[date, float | None, dict[str, Any]]]:
    out = []
    for h in ctx.history:
        v = h["values"].get(code)
        if v is not None:
            out.append((h["as_of"], v[0], v[1]))
    return out


# ==============================================================================================
# REFERENCE DASHBOARD KPIs (MVP)
# ==============================================================================================
@kpi("program_completion", "Program Completion %", "reference",
     "Σ(wᵢ·%completeᵢ)/Σwᵢ over mapped leaf tasks; wᵢ = baseline duration (else duration)",
     ["percent_complete", "duration", "baseline_duration"], "kpi_card", "MVP", "%", reference=True)
def k_program_completion(ctx: KPIContext) -> KPIResult:
    act, pln, n = rollup(ctx.leaves, ctx.planned)
    if n == 0:
        return unavailable("No leaf tasks")
    var = round(act - pln, 2)
    th = ctx.thresholds
    tag = "On Track" if var >= th.get("delay_pts", -5) else "Delay" if var >= th.get("critical_pts", -15) else "Critical Delay"
    if act >= 99.999:
        tag = "Completed"
    return KPIResult(act, _pct(act), {"planned": pln, "variance_pts": var, "tag": tag, "leaf_tasks": n,
                                      "planned_method": ctx.planned_method}, _uids(ctx.leaves))


@kpi("planned_to_date", "Planned to date %", "reference",
     "Σ(wᵢ·planned%ᵢ)/Σwᵢ; planned% = linear position of as-of date in baseline→(first snapshot)→current dates",
     ["baseline_start", "baseline_finish", "start", "finish"], "trend", "MVP", "%", reference=True)
def k_planned(ctx: KPIContext) -> KPIResult:
    act, pln, n = rollup(ctx.leaves, ctx.planned)
    if n == 0:
        return unavailable("No leaf tasks")
    return KPIResult(pln, _pct(pln), {"method": ctx.planned_method}, _uids(ctx.leaves))


@kpi("schedule_variance_pts", "Schedule variance (pts)", "reference", "actual % − planned %",
     ["percent_complete", "baseline"], "chip", "MVP", "pts", reference=True)
def k_var(ctx: KPIContext) -> KPIResult:
    act, pln, n = rollup(ctx.leaves, ctx.planned)
    if n == 0:
        return unavailable("No leaf tasks")
    v = round(act - pln, 2)
    return KPIResult(v, f"{v:+.1f} pts", {"actual": act, "planned": pln}, _uids(ctx.leaves))


@kpi("active_tracks", "Active Tracks", "reference",
     "tracks with actual start or %complete>0 / total tracks", ["actual_start", "percent_complete"],
     "kpi_card", "MVP", "count", reference=True)
def k_active_tracks(ctx: KPIContext) -> KPIResult:
    total = len(ctx.tracks)
    if total == 0:
        return unavailable("No tracks mapped")
    active = [t for t in ctx.tracks if t.started]
    uids = [x.unique_id for tr in active for x in tr.tasks]
    return KPIResult(len(active), f"{len(active)}/{total}",
                     {"total": total, "pending_activation": total - len(active),
                      "active_track_ids": [t.id for t in active]}, uids[:MAX_DRILL])


@kpi("total_tracks", "Tracks", "reference", "count of mapped tracks", ["outline/custom field"], "kpi_strip",
     "MVP", "count", reference=True)
def k_tracks(ctx: KPIContext) -> KPIResult:
    return KPIResult(len(ctx.tracks), str(len(ctx.tracks)), {}, [])


def _ms_by(ctx, status: str | None = None):
    return [m for m in ctx.milestones if status is None or m.status == status]


@kpi("total_milestones", "Total Milestones", "reference", "count of mapped milestones",
     ["milestone flag/outline/custom field"], "kpi_card", "MVP", "count", reference=True)
def k_total_ms(ctx: KPIContext) -> KPIResult:
    ms = ctx.milestones
    counts = Counter(m.status for m in ms)
    tracks = len({m.track_id for m in ms})
    return KPIResult(len(ms), str(len(ms)), {"by_status": dict(counts), "tracks_covered": tracks},
                     [m.task_unique_id for m in ms])


for _code, _name, _status, _cap in [
    ("milestones_on_track", "On Track", "on_track", "milestones progressing"),
    ("milestones_not_started", "Not Started", "not_started", "milestones pending"),
    ("milestones_completed", "Completed milestones", "completed", "milestones completed"),
    ("milestones_delayed", "Delayed milestones", "delay", "milestones delayed"),
    ("milestones_critical_delay", "Critical-delay milestones", "critical_delay", "milestones critically delayed"),
]:
    def _make(status=_status, cap=_cap):
        def fn(ctx: KPIContext) -> KPIResult:
            ms = _ms_by(ctx, status)
            return KPIResult(len(ms), str(len(ms)), {"caption": cap, "of": len(ctx.milestones)},
                             [m.task_unique_id for m in ms])
        return fn

    kpi(_code, _name, "reference", f"count of milestones with status = {_status}",
        ["percent_complete", "planned %"], "kpi_card", "MVP", "count", reference=True)(_make())


@kpi("active_track_timeline", "Active Track Timeline", "reference",
     "months from earliest start to latest finish of active tracks; elapsed = (as-of − start)/(finish − start)",
     ["start", "finish"], "kpi_card", "MVP", "months", reference=True)
def k_timeline(ctx: KPIContext) -> KPIResult:
    active = [t for t in ctx.tracks if t.started] or ctx.tracks
    starts = [t.start for t in active if t.start]
    finishes = [t.finish for t in active if t.finish]
    if not starts or not finishes:
        return unavailable("Tracks have no dates")
    s, f = min(starts), max(finishes)
    total_m = months_between(s, f)
    cur_m = max(0, min(total_m, months_between(s, ctx.as_of))) if ctx.as_of >= s else 0
    elapsed = linear_percent(s, f, ctx.as_of) or 0.0
    return KPIResult(total_m, f"{total_m} months",
                     {"start": s.isoformat(), "finish": f.isoformat(), "month": cur_m, "of_months": total_m,
                      "elapsed_pct": round(elapsed, 1)},
                     [x.unique_id for tr in active for x in tr.tasks][:MAX_DRILL])


@kpi("next_milestone", "Next Milestone", "reference",
     "earliest not-completed milestone with start ≥ as-of (else the earliest open milestone)",
     ["start", "percent_complete"], "kpi_card", "MVP", None, reference=True)
def k_next_ms(ctx: KPIContext) -> KPIResult:
    open_ms = [m for m in ctx.milestones if m.status != "completed" and m.start]
    if not open_ms:
        return unavailable("No open milestones")
    upcoming = sorted([m for m in open_ms if m.start >= ctx.as_of], key=lambda m: m.start)
    m = upcoming[0] if upcoming else sorted(open_ms, key=lambda m: m.finish or date.max)[0]
    return KPIResult(None, m.name, {"milestone_id": m.id, "number": m.number, "name": m.name,
                                    "start": m.start.isoformat(), "finish": m.finish.isoformat() if m.finish else None,
                                    "days_to_start": (m.start - ctx.as_of).days}, [m.task_unique_id])


# ---------------------------------------------------------------------------- governance (live)
def _open_decisions(ctx):
    return [d for d in ctx.decisions if d.status == "Pending" and d.review_status == "approved"]


@kpi("decisions_required", "Decisions Required", "reference", "count of approved decisions with status Pending",
     ["governance.decisions"], "kpi_card", "MVP", "count", reference=True, live=True)
def k_decisions(ctx: KPIContext) -> KPIResult:
    open_d = _open_decisions(ctx)
    high = [d for d in open_d if d.priority == "High"]
    return KPIResult(len(open_d), str(len(open_d)), {"high_priority": len(high),
                                                     "decision_ids": [d.id for d in open_d]})


def _open_risks(ctx):
    return [r for r in ctx.risks if r.status != "Closed" and r.review_status == "approved"]


@kpi("high_risks", "High Risks", "reference", "count of open approved risks with severity High or Critical",
     ["governance.risks"], "kpi_card", "MVP", "count", reference=True, live=True)
def k_high_risks(ctx: KPIContext) -> KPIResult:
    risks = _open_risks(ctx)
    high = [r for r in risks if r.severity in ("High", "Critical")]
    return KPIResult(len(high), str(len(high)), {"tracked": len(risks), "risk_ids": [r.id for r in high]})


# ==============================================================================================
# EXTENDED CATALOGUE — SCHEDULE
# ==============================================================================================
@kpi("spi", "Schedule Performance Index (SPI)", "schedule",
     "BCWP/BCWS when cost-loaded; else duration-based EV%/PV% (Σw·%complete / Σw·planned%)",
     ["bcwp", "bcws", "percent_complete", "baseline"], "gauge", "v1", "index")
def k_spi(ctx: KPIContext) -> KPIResult:
    bac = _sum(ctx.leaves, "baseline_cost")
    if bac > 0:
        bcws = sum((t.baseline_cost or 0) * ctx.planned.get(t.unique_id, 0) / 100 for t in ctx.leaves)
        bcwp = sum((t.baseline_cost or 0) * (t.percent_complete or 0) / 100 for t in ctx.leaves)
        v = _ratio(bcwp, bcws)
        basis = "cost"
    else:
        act, pln, _ = rollup(ctx.leaves, ctx.planned)
        v = _ratio(act, pln)
        basis = "duration"
    if v is None:
        return unavailable("Nothing planned to date yet")
    return KPIResult(v, f"{v:.2f}", {"basis": basis, "status": "good" if v >= 0.95 else "warn" if v >= 0.85 else "bad"},
                     _uids(ctx.leaves))


def _project_dates(ctx):
    root = ctx.by_uid.get(0)
    fin = root.finish if root and root.finish else max((t.finish for t in ctx.all_leaves if t.finish), default=None)
    bfin = root.baseline_finish if root and root.baseline_finish else max(
        (t.baseline_finish for t in ctx.all_leaves if t.baseline_finish), default=None)
    st = root.start if root and root.start else min((t.start for t in ctx.all_leaves if t.start), default=None)
    bst = root.baseline_start if root and root.baseline_start else min(
        (t.baseline_start for t in ctx.all_leaves if t.baseline_start), default=None)
    return st, fin, bst, bfin


@kpi("schedule_variance_days", "Schedule variance (days)", "schedule",
     "forecast project finish − baseline project finish (calendar days; + = late)",
     ["finish", "baseline_finish"], "kpi_card", "v1", "days")
def k_sv_days(ctx: KPIContext) -> KPIResult:
    _, fin, _, bfin = _project_dates(ctx)
    if not fin or not bfin:
        return unavailable("No baseline finish")
    d = (fin - bfin).days
    late = [t for t in ctx.leaves if t.finish and t.baseline_finish and t.finish > t.baseline_finish]
    return KPIResult(d, f"{d:+d} d", {"forecast_finish": fin.isoformat(), "baseline_finish": bfin.isoformat()},
                     _uids(late))


@kpi("forecast_finish_vs_baseline", "Forecast finish vs baseline", "schedule",
     "project finish date vs baseline finish date", ["finish", "baseline_finish"], "kpi_card", "v1", "date")
def k_forecast(ctx: KPIContext) -> KPIResult:
    _, fin, _, bfin = _project_dates(ctx)
    if not fin:
        return unavailable("No finish date")
    d = (fin - bfin).days if bfin else None
    return KPIResult(d, fin.isoformat(), {"forecast_finish": fin.isoformat(),
                                          "baseline_finish": bfin.isoformat() if bfin else None, "delta_days": d})


@kpi("milestone_slippage", "Milestone slippage", "schedule",
     "per milestone: finish − baseline finish (days); cumulative = Σ positive slippage",
     ["finish", "baseline_finish"], "table", "v1", "days")
def k_ms_slip(ctx: KPIContext) -> KPIResult:
    rows = [{"milestone_id": m.id, "number": m.number, "name": m.name, "slippage_days": m.slippage_days}
            for m in ctx.milestones if m.slippage_days is not None]
    if not rows:
        return unavailable("Milestones have no baseline dates")
    cum = sum(max(0, r["slippage_days"]) for r in rows)
    return KPIResult(cum, f"{cum:.0f} d cumulative", {"rows": rows,
                                                       "slipped": sum(1 for r in rows if r["slippage_days"] > 0)},
                     [m.task_unique_id for m in ctx.milestones if (m.slippage_days or 0) > 0])


@kpi("bei", "Baseline Execution Index (BEI)", "schedule",
     "tasks completed / tasks with baseline finish ≤ as-of", ["baseline_finish", "percent_complete"],
     "gauge", "v1", "index")
def k_bei(ctx: KPIContext) -> KPIResult:
    due = [t for t in ctx.leaves if t.baseline_finish and t.baseline_finish <= ctx.as_of]
    if not due:
        return unavailable("No tasks baselined to finish by the as-of date")
    done = [t for t in ctx.leaves if (t.percent_complete or 0) >= 100]
    v = round(len(done) / len(due), 3)
    return KPIResult(v, f"{v:.2f}", {"completed": len(done), "baselined_due": len(due)}, _uids(due))


@kpi("milestone_hit_rate", "Milestone hit rate", "schedule",
     "milestones finished on/before baseline finish / milestones baselined to finish by as-of",
     ["baseline_finish", "actual_finish"], "gauge", "v1", "%")
def k_hit(ctx: KPIContext) -> KPIResult:
    due = [m for m in ctx.milestones if m.baseline_finish and m.baseline_finish <= ctx.as_of]
    if not due:
        return unavailable("No milestones due by as-of date")
    hit = [m for m in due if m.status == "completed" and m.finish and m.finish <= m.baseline_finish]
    v = round(100 * len(hit) / len(due), 1)
    return KPIResult(v, _pct(v), {"hit": len(hit), "due": len(due)}, [m.task_unique_id for m in due])


@kpi("critical_path", "Critical path length & changes", "schedule",
     "span (days) from earliest start to latest finish of open critical tasks; change = critical set Δ vs previous",
     ["critical", "start", "finish"], "kpi_card", "v1", "days")
def k_cp(ctx: KPIContext) -> KPIResult:
    crit = [t for t in ctx.all_leaves if t.is_critical and (t.percent_complete or 0) < 100]
    if not crit:
        return unavailable("No critical tasks flagged")
    s = min((t.start for t in crit if t.start), default=None)
    f = max((t.finish for t in crit if t.finish), default=None)
    length = (f - s).days if s and f else None
    prev_crit = {t.unique_id for t in ctx.prev_tasks if t.is_critical and not t.is_summary and (t.percent_complete or 0) < 100}
    cur = {t.unique_id for t in crit}
    return KPIResult(length, f"{length} d" if length is not None else "—",
                     {"critical_tasks": len(crit), "added": len(cur - prev_crit) if ctx.prev_tasks else None,
                      "removed": len(prev_crit - cur) if ctx.prev_tasks else None}, _uids(crit))


@kpi("slack", "Total / free slack", "schedule", "mean & min total slack and mean free slack over open leaf tasks",
     ["total_slack", "free_slack"], "kpi_card", "v1", "days")
def k_slack(ctx: KPIContext) -> KPIResult:
    ts = [t.total_slack_days for t in ctx.open_leaves if t.total_slack_days is not None]
    if not ts:
        return unavailable("No slack values")
    fs = [t.free_slack_days for t in ctx.open_leaves if t.free_slack_days is not None]
    return KPIResult(round(statistics.mean(ts), 1), f"{statistics.mean(ts):.1f} d avg",
                     {"min_total": round(min(ts), 1), "avg_free": round(statistics.mean(fs), 1) if fs else None},
                     _uids(ctx.open_leaves))


@kpi("near_critical", "Near-critical tasks", "schedule",
     "open non-critical tasks with 0 < total slack ≤ threshold (default 10 d)", ["total_slack", "critical"],
     "kpi_card", "v1", "count")
def k_near(ctx: KPIContext) -> KPIResult:
    th = ctx.thresholds.get("near_critical_days", 10)
    if not any(t.total_slack_days is not None for t in ctx.open_leaves):
        return unavailable("No slack values")
    near = [t for t in ctx.open_leaves if not t.is_critical and t.total_slack_days is not None and 0 < t.total_slack_days <= th]
    return KPIResult(len(near), str(len(near)), {"threshold_days": th}, _uids(near))


@kpi("upcoming_windows", "Tasks starting/finishing in next 30/60/90 d", "schedule",
     "count of open tasks with start/finish in (as-of, as-of+N]", ["start", "finish"], "table", "v1", "count")
def k_upcoming(ctx: KPIContext) -> KPIResult:
    res, uids = {}, set()
    for n in (30, 60, 90):
        end = ctx.as_of + timedelta(days=n)
        st = [t for t in ctx.open_leaves if t.start and ctx.as_of < t.start <= end]
        fi = [t for t in ctx.open_leaves if t.finish and ctx.as_of < t.finish <= end]
        res[f"start_{n}"] = len(st)
        res[f"finish_{n}"] = len(fi)
        if n == 30:
            uids.update(_uids(st + fi))
    return KPIResult(res["finish_30"], f"{res['start_30']} start / {res['finish_30']} finish (30d)", res, list(uids))


@kpi("overdue_tasks", "Overdue tasks", "schedule", "open leaf tasks with finish < as-of",
     ["finish", "percent_complete"], "kpi_card", "v1", "count")
def k_overdue(ctx: KPIContext) -> KPIResult:
    od = [t for t in ctx.open_leaves if t.finish and t.finish < ctx.as_of]
    return KPIResult(len(od), str(len(od)), {}, _uids(od))


@kpi("late_starts", "Late starts", "schedule",
     "tasks not started whose (baseline) start < as-of", ["start", "baseline_start", "actual_start"],
     "kpi_card", "v1", "count")
def k_late(ctx: KPIContext) -> KPIResult:
    late = [t for t in ctx.open_leaves if (t.percent_complete or 0) == 0 and not t.actual_start
            and ((t.baseline_start or t.start) and (t.baseline_start or t.start) < ctx.as_of)]
    return KPIResult(len(late), str(len(late)), {}, _uids(late))


@kpi("missed_deadlines", "Missed deadlines", "schedule",
     "tasks with deadline < finish, or deadline < as-of and not complete", ["deadline", "finish"],
     "kpi_card", "v1", "count")
def k_deadlines(ctx: KPIContext) -> KPIResult:
    with_dl = [t for t in ctx.all_leaves if t.deadline]
    if not with_dl:
        return unavailable("No deadlines set")
    missed = [t for t in with_dl if (t.finish and t.finish > t.deadline) or
              (t.deadline < ctx.as_of and (t.percent_complete or 0) < 100)]
    return KPIResult(len(missed), str(len(missed)), {"with_deadline": len(with_dl)}, _uids(missed))


_SOFT = {"AS_SOON_AS_POSSIBLE", "AS_LATE_AS_POSSIBLE", "ASAP", "ALAP", None, ""}
_HARD = {"MUST_START_ON", "MUST_FINISH_ON", "START_NO_LATER_THAN", "FINISH_NO_LATER_THAN", "MSO", "MFO",
         "SNLT", "FNLT"}


@kpi("constraint_count", "Constraint count", "schedule", "tasks whose constraint type ≠ ASAP/ALAP",
     ["constraint_type"], "kpi_card", "v1", "count")
def k_constraints(ctx: KPIContext) -> KPIResult:
    c = [t for t in ctx.all_leaves if (t.constraint_type or None) not in _SOFT]
    by = Counter(t.constraint_type for t in c)
    return KPIResult(len(c), str(len(c)), {"by_type": dict(by)}, _uids(c))


# ==============================================================================================
# PROGRESS
# ==============================================================================================
@kpi("planned_vs_actual_by_track", "Planned vs actual by track", "progress",
     "per track duration-weighted actual % vs planned %", ["percent_complete", "baseline"], "bar", "v1", "%")
def k_by_track(ctx: KPIContext) -> KPIResult:
    if not ctx.tracks:
        return unavailable("No tracks")
    rows = [{"track_id": t.id, "number": t.number, "name": t.name, "actual": t.actual, "planned": t.planned,
             "variance": round(t.actual - t.planned, 2)} for t in ctx.tracks]
    return KPIResult(None, f"{len(rows)} tracks", {"rows": rows})


@kpi("weekly_velocity", "Weekly velocity", "progress",
     "(program % now − program % previous snapshot) / weeks between snapshots",
     ["percent_complete (history)"], "trend", "v1", "pts/week")
def k_velocity(ctx: KPIContext) -> KPIResult:
    h = _hist(ctx, "program_completion")
    if not h:
        return unavailable("Needs at least two snapshots")
    act, _, _ = rollup(ctx.leaves, ctx.planned)
    prev_date, prev_val, _ = h[-1]
    weeks = max((ctx.as_of - prev_date).days / 7.0, 1 / 7)
    v = round((act - (prev_val or 0)) / weeks, 2)
    series = []
    for (d0, v0, _), (d1, v1, _) in zip(h, h[1:]):
        series.append({"as_of": d1.isoformat(), "velocity": round(((v1 or 0) - (v0 or 0)) / max((d1 - d0).days / 7, 1 / 7), 2)})
    series.append({"as_of": ctx.as_of.isoformat(), "velocity": v})
    avg = round(statistics.mean(s["velocity"] for s in series), 2)
    remaining = 100 - act
    weeks_to_go = math.ceil(remaining / avg) if avg > 0 else None
    return KPIResult(v, f"{v:+.2f} pts/wk", {"series": series, "avg": avg, "weeks_to_complete_at_avg": weeks_to_go})


def _planned_curve(ctx: KPIContext, points: int = 24):
    st, fin, bst, bfin = _project_dates(ctx)
    s, f = (bst or st), (bfin or fin)
    if not s or not f or f <= s:
        return []
    step = max(1, (f - s).days // points)
    out = []
    d = s
    leaves = ctx.leaves
    weights = [weight(t) for t in leaves]
    tot = sum(weights) or float(len(leaves))
    if sum(weights) == 0:
        weights = [1.0] * len(leaves)
    while d <= f + timedelta(days=step):
        val = 0.0
        for w, t in zip(weights, leaves):
            ps, pf = (t.baseline_start or t.start), (t.baseline_finish or t.finish)
            val += w * (linear_percent(ps, pf, d) or 0.0)
        out.append({"date": d.isoformat(), "planned": round(val / tot, 2)})
        d += timedelta(days=step)
    return out


@kpi("s_curve", "S-curve", "progress", "cumulative planned % over time (baseline) vs actual % per snapshot",
     ["baseline", "percent_complete (history)"], "line", "v1", "%")
def k_scurve(ctx: KPIContext) -> KPIResult:
    curve = _planned_curve(ctx)
    if not curve:
        return unavailable("No dates")
    act, _, _ = rollup(ctx.leaves, ctx.planned)
    actual = [{"date": d.isoformat(), "actual": v} for d, v, _ in _hist(ctx, "program_completion")]
    actual.append({"date": ctx.as_of.isoformat(), "actual": act})
    return KPIResult(act, _pct(act), {"planned": curve, "actual": actual})


@kpi("burn_up", "Burn-up", "progress", "completed leaf tasks vs total scope per snapshot",
     ["percent_complete", "task count (history)"], "line", "v1", "count")
def k_burnup(ctx: KPIContext) -> KPIResult:
    done = sum(1 for t in ctx.leaves if (t.percent_complete or 0) >= 100)
    series = [{"date": d.isoformat(), "completed": det.get("completed"), "scope": det.get("scope")}
              for d, _, det in _hist(ctx, "burn_up")]
    series.append({"date": ctx.as_of.isoformat(), "completed": done, "scope": len(ctx.leaves)})
    return KPIResult(done, f"{done}/{len(ctx.leaves)}", {"completed": done, "scope": len(ctx.leaves), "series": series},
                     _uids([t for t in ctx.leaves if (t.percent_complete or 0) >= 100]))


@kpi("duration_elapsed_vs_complete", "% duration elapsed vs % complete", "progress",
     "(as-of − project start)/(project finish − project start) vs program completion %",
     ["start", "finish", "percent_complete"], "kpi_card", "v1", "%")
def k_elapsed(ctx: KPIContext) -> KPIResult:
    st, fin, _, _ = _project_dates(ctx)
    if not st or not fin:
        return unavailable("No project dates")
    el = linear_percent(st, fin, ctx.as_of) or 0.0
    act, _, _ = rollup(ctx.leaves, ctx.planned)
    return KPIResult(round(el, 1), f"{el:.1f}% elapsed / {act:.1f}% complete",
                     {"elapsed_pct": round(el, 1), "complete_pct": act, "gap_pts": round(act - el, 1)})


@kpi("stalled_tasks", "Stalled tasks", "progress",
     "in-progress tasks whose % complete has not changed across the last n snapshots (default 3)",
     ["percent_complete (history)"], "table", "v1", "count")
def k_stalled(ctx: KPIContext) -> KPIResult:
    n = int(ctx.thresholds.get("stalled_snapshots", 3))
    if len(ctx.stalled_history) < n - 1:
        return unavailable(f"Needs {n} snapshots")
    hist = ctx.stalled_history[-(n - 1):]
    stalled = []
    for t in ctx.leaves:
        p = t.percent_complete or 0
        if 0 < p < 100 and all(h.get(t.unique_id) == p for h in hist):
            stalled.append(t)
    return KPIResult(len(stalled), str(len(stalled)), {"snapshots": n}, _uids(stalled))


# ==============================================================================================
# COST / EFFORT (earned value) — only when cost-loaded
# ==============================================================================================
def _ev(ctx: KPIContext):
    leaves = ctx.leaves
    bac = _sum(leaves, "baseline_cost")
    if bac <= 0:
        return None
    file_bcws = _sum(leaves, "bcws")
    file_bcwp = _sum(leaves, "bcwp")
    bcws = file_bcws if file_bcws > 0 else sum((t.baseline_cost or 0) * ctx.planned.get(t.unique_id, 0) / 100 for t in leaves)
    bcwp = file_bcwp if file_bcwp > 0 else sum((t.baseline_cost or 0) * (t.percent_complete or 0) / 100 for t in leaves)
    file_acwp = _sum(leaves, "acwp")
    acwp = file_acwp if file_acwp > 0 else _sum(leaves, "actual_cost")
    cpi = bcwp / acwp if acwp else None
    eac = bac / cpi if cpi else None
    return {"bac": bac, "bcws": bcws, "bcwp": bcwp, "acwp": acwp, "cpi": cpi, "spi": bcwp / bcws if bcws else None,
            "cv": bcwp - acwp, "sv": bcwp - bcws, "eac": eac, "etc": (eac - acwp) if eac is not None else None,
            "vac": (bac - eac) if eac is not None else None,
            "source": "file" if file_bcws > 0 else "computed"}


def _ev_kpi(code, name, formula, key, unit="currency", widget="kpi_card"):
    def fn(ctx: KPIContext) -> KPIResult:
        ev = _ev(ctx)
        if ev is None:
            return unavailable("No baseline cost in plan")
        v = ev[key]
        if v is None:
            return unavailable("No actual cost recorded")
        v = round(v, 3 if unit == "index" else 2)
        return KPIResult(v, f"{v:,.2f}" if unit == "index" else f"{v:,.0f}",
                         {k: (round(x, 2) if isinstance(x, float) else x) for k, x in ev.items()},
                         _uids([t for t in ctx.leaves if t.baseline_cost]))
    kpi(code, name, "cost", formula, ["baseline_cost", "actual_cost", "bcws", "bcwp", "acwp", "percent_complete"],
        widget, "v1", unit)(fn)


_ev_kpi("bcws", "BCWS (Planned Value)", "Σ baseline cost × planned% (or file BCWS)", "bcws")
_ev_kpi("bcwp", "BCWP (Earned Value)", "Σ baseline cost × %complete (or file BCWP)", "bcwp")
_ev_kpi("acwp", "ACWP (Actual Cost)", "Σ actual cost (or file ACWP)", "acwp")
_ev_kpi("cpi", "Cost Performance Index (CPI)", "BCWP / ACWP", "cpi", "index", "gauge")
_ev_kpi("cv", "Cost variance (CV)", "BCWP − ACWP", "cv")
_ev_kpi("sv_cost", "Schedule variance (cost)", "BCWP − BCWS", "sv")
_ev_kpi("eac", "Estimate at completion (EAC)", "BAC / CPI", "eac")
_ev_kpi("etc", "Estimate to complete (ETC)", "EAC − ACWP", "etc")
_ev_kpi("vac", "Variance at completion (VAC)", "BAC − EAC", "vac")
_ev_kpi("bac", "Budget at completion (BAC)", "Σ baseline cost", "bac")


@kpi("work_planned_vs_actual", "Work planned vs actual", "cost",
     "Σ baseline work, Σ work, Σ actual work, Σ remaining work (hours)",
     ["baseline_work", "work", "actual_work", "remaining_work"], "bar", "v1", "hours")
def k_work(ctx: KPIContext) -> KPIResult:
    if not _has(ctx.leaves, "work_hours"):
        return unavailable("No work (effort) data")
    d = {"baseline_work": _sum(ctx.leaves, "baseline_work_hours"), "work": _sum(ctx.leaves, "work_hours"),
         "actual_work": _sum(ctx.leaves, "actual_work_hours"), "remaining_work": _sum(ctx.leaves, "remaining_work_hours")}
    d = {k: round(v, 1) for k, v in d.items()}
    pct = round(100 * d["actual_work"] / d["work"], 1) if d["work"] else None
    d["work_complete_pct"] = pct
    return KPIResult(d["actual_work"], f"{d['actual_work']:,.0f} / {d['work']:,.0f} h", d,
                     _uids([t for t in ctx.leaves if t.work_hours]))


# ==============================================================================================
# RESOURCES
# ==============================================================================================
@kpi("resource_allocation", "Resource allocation", "resources",
     "per resource: assigned work hours, open task count, max units", ["assignments", "resources"],
     "table", "v1", "hours")
def k_alloc(ctx: KPIContext) -> KPIResult:
    if not ctx.resources:
        return unavailable("No resources in plan")
    open_uids = {t.unique_id for t in ctx.open_leaves}
    agg: dict[int, dict[str, Any]] = defaultdict(lambda: {"work": 0.0, "remaining": 0.0, "tasks": 0, "open_tasks": 0})
    for a in ctx.assignments:
        if a.resource_unique_id is None:
            continue
        g = agg[a.resource_unique_id]
        g["work"] += a.work_hours or 0
        g["remaining"] += a.remaining_work_hours or 0
        g["tasks"] += 1
        g["open_tasks"] += 1 if a.task_unique_id in open_uids else 0
    rows = []
    for r in ctx.resources:
        g = agg.get(r.unique_id, {"work": 0, "remaining": 0, "tasks": 0, "open_tasks": 0})
        rows.append({"resource": r.name, "type": r.type, "max_units": r.max_units, "work_hours": round(g["work"], 1),
                     "remaining_hours": round(g["remaining"], 1), "tasks": g["tasks"], "open_tasks": g["open_tasks"],
                     "overallocated": r.is_overallocated})
    rows.sort(key=lambda x: -x["work_hours"])
    return KPIResult(len(rows), f"{len(rows)} resources", {"rows": rows})


@kpi("over_allocation", "Over-allocated resources", "resources",
     "resources flagged over-allocated by MS Project or peak units > max units", ["resources"], "kpi_card", "v1", "count")
def k_over(ctx: KPIContext) -> KPIResult:
    if not ctx.resources:
        return unavailable("No resources in plan")
    over = [r for r in ctx.resources if r.is_overallocated or (r.peak_units and r.max_units and r.peak_units > r.max_units)]
    over_ids = {r.unique_id for r in over}
    uids = sorted({a.task_unique_id for a in ctx.assignments if a.resource_unique_id in over_ids})
    return KPIResult(len(over), str(len(over)), {"resources": [r.name for r in over]}, uids[:MAX_DRILL])


@kpi("unassigned_tasks", "Unassigned tasks", "resources", "open non-milestone leaf tasks with no resource assignment",
     ["assignments"], "kpi_card", "v1", "count")
def k_unassigned(ctx: KPIContext) -> KPIResult:
    if not ctx.resources:
        return unavailable("No resources in plan")
    un = [t for t in ctx.open_leaves if not t.resource_names and not t.is_milestone]
    return KPIResult(len(un), str(len(un)), {}, _uids(un))


@kpi("workload_by_owner", "Workload by owner", "resources",
     "remaining work hours and open tasks grouped by assigned resource", ["assignments"], "bar", "v1", "hours")
def k_workload(ctx: KPIContext) -> KPIResult:
    if not ctx.assignments:
        return unavailable("No assignments")
    names = {r.unique_id: r.name for r in ctx.resources}
    open_uids = {t.unique_id for t in ctx.open_leaves}
    agg: dict[str, dict[str, float]] = defaultdict(lambda: {"remaining_hours": 0.0, "open_tasks": 0})
    for a in ctx.assignments:
        if a.task_unique_id not in open_uids:
            continue
        n = names.get(a.resource_unique_id, "Unassigned")
        agg[n]["remaining_hours"] += a.remaining_work_hours or 0
        agg[n]["open_tasks"] += 1
    rows = sorted(({"owner": k, **{kk: round(vv, 1) for kk, vv in v.items()}} for k, v in agg.items()),
                  key=lambda r: -r["remaining_hours"])
    return KPIResult(len(rows), f"{len(rows)} owners", {"rows": rows})


# ==============================================================================================
# PLAN QUALITY
# ==============================================================================================
def _quality_sets(ctx: KPIContext):
    leaves = ctx.all_leaves
    first = min((t.start for t in leaves if t.start), default=None)
    last = max((t.finish for t in leaves if t.finish), default=None)
    no_pred = [t for t in leaves if not t.predecessors and t.start != first]
    no_succ = [t for t in leaves if not t.successors and t.finish != last]
    long_d = ctx.thresholds.get("long_duration_days", 44)
    rels = [p for t in leaves for p in (t.predecessors or [])]
    return {
        "missing_predecessors": no_pred,
        "missing_successors": no_succ,
        "missing_baseline": [t for t in leaves if not t.baseline_finish],
        "tasks_without_resources": [t for t in leaves if not t.resource_names and not t.is_milestone],
        "long_duration": [t for t in leaves if (t.duration_days or 0) > long_d and (t.percent_complete or 0) < 100],
        "hard_constraints": [t for t in leaves if (t.constraint_type or "") in _HARD],
        "negative_slack": [t for t in leaves if (t.total_slack_days or 0) < 0],
        "high_float": [t for t in leaves if (t.total_slack_days or 0) > long_d and (t.percent_complete or 0) < 100],
        "leads": [t for t in leaves if any((p.get("lag_days") or 0) < 0 for p in (t.predecessors or []))],
        "lags": [t for t in leaves if any((p.get("lag_days") or 0) > 0 for p in (t.predecessors or []))],
        "non_fs": [t for t in leaves if any((p.get("type") or "FINISH_START") not in ("FINISH_START", "FS")
                                            for p in (t.predecessors or []))],
        # DCMA check 9: actual dates after the status (as-of) date are invalid
        "invalid_dates": [t for t in leaves if (t.actual_start and t.actual_start > ctx.as_of) or
                          (t.actual_finish and t.actual_finish > ctx.as_of)],
        "relationship_count": len(rels),
    }


for _code, _name, _key, _formula in [
    ("missing_predecessors", "Missing predecessors", "missing_predecessors", "leaf tasks (except the first) with no predecessor"),
    ("missing_successors", "Missing successors", "missing_successors", "leaf tasks (except the last) with no successor"),
    ("missing_baseline", "Missing baseline", "missing_baseline", "leaf tasks with no baseline finish"),
    ("tasks_without_resources", "Tasks without resources", "tasks_without_resources", "non-milestone leaf tasks with no assignment"),
    ("long_duration_tasks", "Long-duration tasks", "long_duration", "open tasks with duration > 44 working days (DCMA)"),
    ("hard_constraints", "Hard constraints", "hard_constraints", "tasks with MSO/MFO/SNLT/FNLT constraints"),
    ("negative_slack", "Negative slack", "negative_slack", "tasks with total slack < 0"),
]:
    def _mkq(key=_key):
        def fn(ctx: KPIContext) -> KPIResult:
            sets = _quality_sets(ctx)
            items = sets[key]
            n = len(ctx.all_leaves) or 1
            return KPIResult(len(items), f"{len(items)} ({100 * len(items) / n:.0f}%)",
                             {"share_pct": round(100 * len(items) / n, 1)}, _uids(items))
        return fn
    kpi(_code, _name, "quality", _formula, ["predecessors", "successors", "baseline", "constraints", "slack"],
        "kpi_card", "v1", "count")(_mkq())


@kpi("logic_health_score", "Logic-health score", "quality",
     "DCMA-14-inspired: % of checks passed (missing logic ≤5%, leads 0%, lags ≤5%, FS ≥90%, hard constraints ≤5%, "
     "high float ≤5%, negative float 0%, long duration ≤5%, invalid dates 0%, resources ≤5% missing, missed tasks ≤5%, "
     "BEI ≥0.95)", ["predecessors", "successors", "lag", "constraint", "slack", "duration", "baseline"],
     "gauge", "v1", "score")
def k_logic(ctx: KPIContext) -> KPIResult:
    s = _quality_sets(ctx)
    n = len(ctx.all_leaves)
    if n == 0:
        return unavailable("No tasks")
    rels = max(s["relationship_count"], 1)
    missed = [t for t in ctx.all_leaves if t.baseline_finish and t.baseline_finish <= ctx.as_of and
              (not t.actual_finish or t.actual_finish > t.baseline_finish)]
    due = [t for t in ctx.all_leaves if t.baseline_finish and t.baseline_finish <= ctx.as_of]
    done = [t for t in ctx.all_leaves if (t.percent_complete or 0) >= 100]
    bei = len(done) / len(due) if due else None
    checks = [
        ("Missing logic ≤ 5%", 100 * len(set(_uids(s["missing_predecessors"])) | set(_uids(s["missing_successors"]))) / n <= 5),
        ("No leads", len(s["leads"]) == 0),
        ("Lags ≤ 5% of relationships", 100 * len(s["lags"]) / rels <= 5),
        ("FS relationships ≥ 90%", 100 * (1 - len(s["non_fs"]) / rels) >= 90 if s["relationship_count"] else False),
        ("Hard constraints ≤ 5%", 100 * len(s["hard_constraints"]) / n <= 5),
        ("High float ≤ 5%", 100 * len(s["high_float"]) / n <= 5),
        ("No negative float", len(s["negative_slack"]) == 0),
        ("Long durations ≤ 5%", 100 * len(s["long_duration"]) / n <= 5),
        ("No invalid dates", len(s["invalid_dates"]) == 0),
        ("Resources assigned (≤ 5% missing)", 100 * len(s["tasks_without_resources"]) / n <= 5),
        ("Missed tasks ≤ 5%", (100 * len(missed) / len(due) <= 5) if due else True),
        ("BEI ≥ 0.95", bei >= 0.95 if bei is not None else True),
    ]
    passed = sum(1 for _, ok in checks if ok)
    score = round(100 * passed / len(checks), 1)
    return KPIResult(score, f"{score:.0f}/100", {"checks": [{"check": c, "passed": ok} for c, ok in checks]})


# ==============================================================================================
# CHANGE (vs previous snapshot)
# ==============================================================================================
def _diff_count(ctx, *types):
    return [d for d in ctx.diffs_prev if d["change_type"] in types]


@kpi("change_summary", "Adds / removes / renames", "change", "count of diff records by change type vs previous snapshot",
     ["diff"], "table", "v1", "count")
def k_change(ctx: KPIContext) -> KPIResult:
    if not ctx.prev_tasks:
        return unavailable("First snapshot — nothing to compare")
    c = Counter(d["change_type"] for d in ctx.diffs_prev)
    renamed = sum(1 for d in ctx.diffs_prev if "name" in d["changes"])
    moved = sum(1 for d in ctx.diffs_prev if d.get("finish_delta_days") or d.get("start_delta_days"))
    det = {"added": c.get("added", 0), "removed": c.get("removed", 0), "renamed": renamed, "date_moves": moved,
           "status_transitions": c.get("status", 0), "progress_updates": sum(1 for d in ctx.diffs_prev if d.get("progress_delta"))}
    total = len(ctx.diffs_prev)
    return KPIResult(total, f"{total} changes", det,
                     [d["task_unique_id"] for d in ctx.diffs_prev if d["task_unique_id"] is not None][:MAX_DRILL])


@kpi("date_moves", "Date moves", "change", "matched tasks whose start or finish moved; net finish movement (days)",
     ["start", "finish (diff)"], "kpi_card", "v1", "count")
def k_date_moves(ctx: KPIContext) -> KPIResult:
    if not ctx.prev_tasks:
        return unavailable("First snapshot")
    mv = [d for d in ctx.diffs_prev if d.get("finish_delta_days") or d.get("start_delta_days")]
    net = sum(d.get("finish_delta_days") or 0 for d in mv)
    return KPIResult(len(mv), str(len(mv)), {"net_finish_days": net,
                                             "slipped": sum(1 for d in mv if (d.get("finish_delta_days") or 0) > 0),
                                             "pulled_in": sum(1 for d in mv if (d.get("finish_delta_days") or 0) < 0)},
                     [d["task_unique_id"] for d in mv][:MAX_DRILL])


@kpi("progress_delta", "Progress delta", "change", "program % complete now − previous snapshot",
     ["percent_complete (history)"], "chip", "v1", "pts")
def k_prog_delta(ctx: KPIContext) -> KPIResult:
    h = _hist(ctx, "program_completion")
    if not h:
        return unavailable("First snapshot")
    act, _, _ = rollup(ctx.leaves, ctx.planned)
    v = round(act - (h[-1][1] or 0), 2)
    return KPIResult(v, f"{v:+.1f} pts", {"previous": h[-1][1], "current": act},
                     [d["task_unique_id"] for d in ctx.diffs_prev if d.get("progress_delta")][:MAX_DRILL])


@kpi("status_transitions", "Status transitions", "change", "milestone/task status changes vs previous snapshot",
     ["status (diff)"], "table", "v1", "count")
def k_transitions(ctx: KPIContext) -> KPIResult:
    if not ctx.prev_tasks:
        return unavailable("First snapshot")
    tr = [d for d in ctx.diffs_prev if d.get("old_status") and d.get("new_status")]
    c = Counter(f"{d['old_status']}→{d['new_status']}" for d in tr)
    ms = [d for d in tr if d["is_milestone"]]
    return KPIResult(len(tr), str(len(tr)), {"by_transition": dict(c), "milestone_transitions": len(ms)},
                     [d["task_unique_id"] for d in tr][:MAX_DRILL])


@kpi("scope_growth", "Scope growth %", "change",
     "(leaf tasks now − leaf tasks in first snapshot)/first × 100; also total duration growth",
     ["task count", "duration (history)"], "kpi_card", "v1", "%")
def k_scope(ctx: KPIContext) -> KPIResult:
    if not ctx.first_leaf_count:
        return unavailable("First snapshot")
    n = len(ctx.all_leaves)
    v = round(100 * (n - ctx.first_leaf_count) / ctx.first_leaf_count, 1)
    dur = _sum(ctx.all_leaves, "duration_days")
    dg = round(100 * (dur - ctx.first_total_duration) / ctx.first_total_duration, 1) if ctx.first_total_duration else None
    return KPIResult(v, f"{v:+.1f}%", {"leaf_tasks_now": n, "leaf_tasks_first": ctx.first_leaf_count,
                                       "duration_growth_pct": dg},
                     [d["task_unique_id"] for d in ctx.diffs_prev if d["change_type"] == "added"][:MAX_DRILL])


@kpi("rebaseline_events", "Re-baseline events", "change", "snapshots where ≥10% of baselines changed",
     ["baseline (history)"], "kpi_card", "v1", "count")
def k_rebase(ctx: KPIContext) -> KPIResult:
    return KPIResult(ctx.rebaseline_events, str(ctx.rebaseline_events), {"this_snapshot": ctx.rebaselined})


@kpi("slippage_trend", "Slippage trend & volatility", "change",
     "series of forecast-finish − baseline-finish per snapshot; volatility = σ of finish moves (days) of matched tasks",
     ["finish", "baseline_finish (history)"], "line", "v1", "days")
def k_slip_trend(ctx: KPIContext) -> KPIResult:
    cur = k_sv_days(ctx)
    series = [{"date": d.isoformat(), "slippage_days": v} for d, v, _ in _hist(ctx, "schedule_variance_days") if v is not None]
    if cur.available:
        series.append({"date": ctx.as_of.isoformat(), "slippage_days": cur.value})
    moves = [d["finish_delta_days"] for d in ctx.diffs_prev if d.get("finish_delta_days")]
    vol = round(statistics.pstdev(moves), 2) if len(moves) >= 2 else 0.0
    if not series and not moves:
        return unavailable("No baseline / no history")
    return KPIResult(vol, f"σ {vol:.1f} d", {"series": series, "volatility_days": vol, "moves": len(moves)})


# ==============================================================================================
# GOVERNANCE (live)
# ==============================================================================================
@kpi("open_decisions", "Open / overdue decisions", "governance",
     "Pending decisions; overdue = needed-by < today", ["governance.decisions"], "kpi_card", "v1", "count", live=True)
def k_open_dec(ctx: KPIContext) -> KPIResult:
    od = _open_decisions(ctx)
    overdue = [d for d in od if d.needed_by and d.needed_by < ctx.today]
    return KPIResult(len(od), f"{len(od)} open / {len(overdue)} overdue", {"overdue": len(overdue),
                                                                           "overdue_ids": [d.id for d in overdue]})


@kpi("decision_ageing", "Decision ageing", "governance", "mean days since creation of pending decisions",
     ["governance.decisions"], "kpi_card", "v1", "days", live=True)
def k_ageing(ctx: KPIContext) -> KPIResult:
    od = _open_decisions(ctx)
    if not od:
        return KPIResult(0, "0 d", {"buckets": {}})
    ages = [(ctx.today - d.created_at.date()).days for d in od]
    buckets = {"0-7": sum(a <= 7 for a in ages), "8-30": sum(7 < a <= 30 for a in ages), ">30": sum(a > 30 for a in ages)}
    v = round(statistics.mean(ages), 1)
    return KPIResult(v, f"{v:.0f} d avg", {"buckets": buckets, "oldest_days": max(ages)})


@kpi("risks_by_severity", "Risks by severity", "governance", "open approved risks grouped by severity",
     ["governance.risks"], "bar", "v1", "count", live=True)
def k_risk_sev(ctx: KPIContext) -> KPIResult:
    r = _open_risks(ctx)
    c = Counter(x.severity for x in r)
    return KPIResult(len(r), f"{len(r)} open", {"by_severity": {k: c.get(k, 0) for k in ("Critical", "High", "Medium", "Low")}})


@kpi("overdue_mitigations", "Overdue mitigations", "governance", "open risks whose due date < today",
     ["governance.risks"], "kpi_card", "v1", "count", live=True)
def k_overdue_mit(ctx: KPIContext) -> KPIResult:
    r = [x for x in _open_risks(ctx) if x.due_date and x.due_date < ctx.today]
    return KPIResult(len(r), str(len(r)), {"risk_ids": [x.id for x in r]})


# ----------------------------------------------------------------------------------------------
def compute_all(ctx: KPIContext, only: set[str] | None = None, live_only: bool = False) -> dict[str, tuple[KPIDef, KPIResult]]:
    out: dict[str, tuple[KPIDef, KPIResult]] = {}
    for code, d in REGISTRY.items():
        if only is not None and code not in only and not d.reference:
            continue
        if live_only and not d.live:
            continue
        try:
            res = d.fn(ctx)
        except Exception as exc:  # a broken formula must never break the dashboard
            res = KPIResult(available=False, reason=f"Computation error: {type(exc).__name__}: {exc}")
        out[code] = (d, res)
    return out


def catalogue() -> list[dict[str, Any]]:
    return [{"code": d.code, "name": d.name, "category": d.category, "formula": d.formula,
             "source_fields": d.source_fields, "widget": d.widget, "phase": d.phase, "unit": d.unit,
             "reference": d.reference, "version": d.version, "live": d.live} for d in REGISTRY.values()]
