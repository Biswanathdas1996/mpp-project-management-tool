"""Reference executive dashboard (plan §Dashboard reference spec) assembled from computed data."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..kpi.engine import REGISTRY, compute_all
from ..models import AttentionItem, Decision, Insight, KPIValue, MappingConfig, Program, Risk, Snapshot, Track
from .context import build_context, ordered_snapshots
from .schedule_math import rollup

PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _logo_url(program: Program, which: str) -> str | None:
    pb = (program.branding or {}).get(which) or (program.tenant.branding or {}).get(which)
    if not pb:
        return None
    owner = "programs" if (program.branding or {}).get(which) else "tenants"
    oid = program.id if owner == "programs" else program.tenant_id
    return f"/api/branding/{owner}/{oid}/{which}"


def kpi_values(db: Session, snapshot: Snapshot) -> dict[str, KPIValue]:
    return {k.code: k for k in db.scalars(select(KPIValue).where(KPIValue.snapshot_id == snapshot.id))}


def approved_kpi_codes(db: Session, program: Program) -> set[str] | None:
    m = db.scalar(select(MappingConfig).where(MappingConfig.program_id == program.id, MappingConfig.status == "approved")
                  .order_by(MappingConfig.version.desc()).limit(1))
    if m is None or not m.approved_kpis:
        return None
    return set(m.approved_kpis)


def kv_dict(k: KPIValue | None) -> dict[str, Any] | None:
    if k is None:
        return None
    d = REGISTRY.get(k.code)
    return {"code": k.code, "name": d.name if d else k.code, "category": d.category if d else None,
            "formula": d.formula if d else None, "widget": d.widget if d else None, "unit": d.unit if d else None,
            "phase": d.phase if d else None, "version": k.kpi_version, "available": k.available, "reason": k.reason,
            "value": k.value, "display": k.display, "details": k.details, "drill_count": len(k.drill_uids or [])}


def derive_attention(ctx, milestones, decisions, risks, today: date) -> list[dict[str, Any]]:
    """Engine-derived attention items: overdue or at-risk items needing action."""
    items: list[dict[str, Any]] = []
    for m in milestones:
        if m.status == "completed":
            continue
        h = m.health or {}
        if h.get("kind") == "overdue":
            items.append({"source": "engine", "category": "overdue_milestone", "severity": "Critical",
                          "title": f"Milestone {m.number:02d} overdue: {m.name}",
                          "description": f"Finish date {m.finish} passed; {m.percent_complete:.0f}% complete.",
                          "due_date": _iso(m.finish), "related_task_uids": [m.task_unique_id]})
        elif m.status == "critical_delay":
            items.append({"source": "engine", "category": "critical_delay", "severity": "High",
                          "title": f"Milestone {m.number:02d} critically delayed: {m.name}",
                          "description": f"{m.variance_pts:+.1f} pts vs plan ({m.percent_complete:.0f}% vs "
                                         f"{m.planned_percent:.0f}% planned).",
                          "due_date": _iso(m.finish), "related_task_uids": [m.task_unique_id]})
        elif m.status == "delay" and h.get("urgency") in ("high", "critical"):
            items.append({"source": "engine", "category": "at_risk", "severity": "Medium",
                          "title": f"Milestone {m.number:02d} at risk: {m.name}",
                          "description": f"Delayed ({m.variance_pts:+.1f} pts) and {h.get('label', '').lower()}.",
                          "due_date": _iso(m.finish), "related_task_uids": [m.task_unique_id]})
    overdue = [t for t in ctx.open_leaves if t.finish and t.finish < ctx.as_of]
    if overdue:
        items.append({"source": "engine", "category": "overdue_tasks", "severity": "High" if len(overdue) > 5 else "Medium",
                      "title": f"{len(overdue)} overdue task{'s' if len(overdue) != 1 else ''}",
                      "description": "Open tasks past their finish date: " + ", ".join(t.name for t in overdue[:5])
                                     + ("…" if len(overdue) > 5 else ""),
                      "due_date": None, "related_task_uids": [t.unique_id for t in overdue][:500]})
    missed = [t for t in ctx.all_leaves if t.deadline and ((t.finish and t.finish > t.deadline) or
                                                           (t.deadline < ctx.as_of and (t.percent_complete or 0) < 100))]
    if missed:
        items.append({"source": "engine", "category": "missed_deadline", "severity": "High",
                      "title": "1 task misses its deadline" if len(missed) == 1
                      else f"{len(missed)} tasks miss their deadline",
                      "description": ", ".join(t.name for t in missed[:5]), "due_date": None,
                      "related_task_uids": [t.unique_id for t in missed][:500]})
    for d in decisions:
        if d.status == "Pending" and d.review_status == "approved" and d.needed_by and d.needed_by < today:
            items.append({"source": "engine", "category": "overdue_decision", "severity": "High",
                          "title": f"Decision overdue: {d.title}",
                          "description": f"Needed by {d.needed_by}; owner {d.owner or '—'}.",
                          "due_date": _iso(d.needed_by), "related_task_uids": d.related_task_uids or []})
    for r in risks:
        if r.status != "Closed" and r.review_status == "approved" and r.due_date and r.due_date < today:
            items.append({"source": "engine", "category": "overdue_mitigation",
                          "severity": "High" if r.severity in ("Critical", "High") else "Medium",
                          "title": f"Mitigation overdue: {r.title}",
                          "description": f"Due {r.due_date}; owner {r.owner or '—'}.", "due_date": _iso(r.due_date),
                          "related_task_uids": r.related_task_uids or []})
    items.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
    return items


def governance_payload(db: Session, program: Program, include_drafts: bool = False):
    q_r = select(Risk).where(Risk.program_id == program.id)
    q_d = select(Decision).where(Decision.program_id == program.id)
    q_a = select(AttentionItem).where(AttentionItem.program_id == program.id)
    if not include_drafts:
        q_r, q_d, q_a = (q.where(m.review_status == "approved") for q, m in
                         ((q_r, Risk), (q_d, Decision), (q_a, AttentionItem)))
    return list(db.scalars(q_r)), list(db.scalars(q_d)), list(db.scalars(q_a))


def risk_dict(r: Risk) -> dict[str, Any]:
    return {"id": r.id, "title": r.title, "title_ar": r.title_ar, "description": r.description, "severity": r.severity,
            "likelihood": r.likelihood, "impact": r.impact, "mitigation": r.mitigation, "owner": r.owner,
            "due_date": _iso(r.due_date), "status": r.status, "source": r.source, "review_status": r.review_status,
            "related_task_uids": r.related_task_uids or [], "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def decision_dict(d: Decision) -> dict[str, Any]:
    return {"id": d.id, "title": d.title, "title_ar": d.title_ar, "description": d.description, "kind": d.kind,
            "priority": d.priority, "status": d.status, "owner": d.owner, "needed_by": _iso(d.needed_by),
            "decided_at": _iso(d.decided_at), "source": d.source, "review_status": d.review_status,
            "related_task_uids": d.related_task_uids or [], "created_at": d.created_at.isoformat(),
            "updated_at": d.updated_at.isoformat() if d.updated_at else None}


def attention_dict(a: AttentionItem) -> dict[str, Any]:
    return {"id": a.id, "title": a.title, "title_ar": a.title_ar, "description": a.description, "severity": a.severity,
            "status": a.status, "owner": a.owner, "due_date": _iso(a.due_date), "category": a.category,
            "source": a.source, "review_status": a.review_status, "related_task_uids": a.related_task_uids or [],
            "created_at": a.created_at.isoformat()}


def milestone_dict(m, tracks: dict[int, Track]) -> dict[str, Any]:
    tr = tracks.get(m.track_id)
    return {"id": m.id, "number": m.number, "name": m.name, "task_unique_id": m.task_unique_id,
            "track_id": m.track_id, "track_number": tr.number if tr else None, "track_name": tr.name if tr else None,
            "start": _iso(m.start), "finish": _iso(m.finish), "baseline_start": _iso(m.baseline_start),
            "baseline_finish": _iso(m.baseline_finish), "percent_complete": m.percent_complete,
            "planned_percent": m.planned_percent, "variance_pts": m.variance_pts, "status": m.status,
            "health": m.health, "slippage_days": m.slippage_days, "is_critical": m.is_critical}


def trend_series(db: Session, program: Program, upto: Snapshot) -> dict[str, Any]:
    snaps = [s for s in ordered_snapshots(db, program.id)
             if (s.as_of_date, s.version_no) <= (upto.as_of_date, upto.version_no)]
    if not snaps:
        return {"points": [], "cycles_reported": 0}
    vals = db.execute(select(KPIValue.snapshot_id, KPIValue.code, KPIValue.value).where(
        KPIValue.snapshot_id.in_([s.id for s in snaps]),
        KPIValue.code.in_(("program_completion", "planned_to_date")))).all()
    by: dict[int, dict[str, float]] = {}
    for sid, code, v in vals:
        by.setdefault(sid, {})[code] = v
    cycle = max(program.reporting_cycle_days or 7, 1)
    first = snaps[0].as_of_date
    per_cycle: dict[int, Snapshot] = {}
    for s in snaps:
        per_cycle[(s.as_of_date - first).days // cycle] = s  # latest snapshot within each reporting cycle
    points = [{"snapshot_id": s.id, "version_no": s.version_no, "as_of": _iso(s.as_of_date), "cycle": c + 1,
               "planned": by.get(s.id, {}).get("planned_to_date"), "actual": by.get(s.id, {}).get("program_completion")}
              for c, s in sorted(per_cycle.items())]
    return {"points": points, "cycles_reported": len(points), "cycle_days": cycle,
            "cycle_label": {7: "weekly", 14: "fortnightly", 30: "monthly", 31: "monthly"}.get(cycle, f"{cycle}-day")}


def build_gantt(milestones: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    starts = [date.fromisoformat(m["start"]) for m in milestones if m["start"]]
    fins = [date.fromisoformat(m["finish"]) for m in milestones if m["finish"]]
    if not starts or not fins:
        return {"months": [], "items": [], "today": _iso(as_of)}
    s = min(starts + [as_of]).replace(day=1)
    f = max(fins + [as_of])
    months = []
    d = s
    while d <= f:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        months.append({"key": d.strftime("%Y-%m"), "label": d.strftime("%b %Y"), "start": _iso(d),
                       "end": _iso(nxt - timedelta(days=1))})
        d = nxt
    items = [{"milestone_id": m["id"], "number": m["number"], "name": m["name"], "track_number": m["track_number"],
              "start": m["start"], "finish": m["finish"], "percent_complete": m["percent_complete"],
              "planned_percent": m["planned_percent"], "status": m["status"],
              "is_point": m["start"] == m["finish"]} for m in milestones if m["start"] and m["finish"]]
    return {"months": months, "items": items, "today": _iso(as_of), "range": {"start": months[0]["start"],
                                                                              "end": months[-1]["end"]}}


def build_dashboard(db: Session, program: Program, snapshot: Snapshot) -> dict[str, Any]:
    today = date.today()
    ctx = build_context(db, program, snapshot, today=today)
    kv = kpi_values(db, snapshot)
    live = {c: r for c, (_, r) in compute_all(ctx, live_only=True).items()}  # governance KPIs are live
    tracks_db = {t.id: t for t in db.scalars(select(Track).where(Track.program_id == program.id))}

    def val(code):
        if code in live:
            r = live[code]
            return {"value": r.value, "display": r.display, "details": r.details, "available": r.available}
        k = kv.get(code)
        return {"value": k.value, "display": k.display, "details": k.details or {}, "available": k.available} if k else \
            {"value": None, "display": None, "details": {}, "available": False}

    pc = val("program_completion")
    at = val("active_tracks")
    tm = val("total_milestones")
    tl = val("active_track_timeline")
    nm = val("next_milestone")
    dr = val("decisions_required")
    hr = val("high_risks")
    on = val("milestones_on_track")
    ns = val("milestones_not_started")

    track_rows = [{"id": t.id, "number": t.number, "label": f"Track {t.number:02d}", "name": t.name,
                   "name_ar": tracks_db[t.id].name_ar if t.id in tracks_db else None, "status": t.status,
                   "actual": t.actual, "planned": t.planned, "variance": round(t.actual - t.planned, 2),
                   "start": _iso(t.start), "finish": _iso(t.finish), "source_label": t.source_label,
                   "leaf_count": t.leaf_count, "started": t.started} for t in ctx.tracks]
    avg_progress = round(sum(t["actual"] for t in track_rows) / len(track_rows), 1) if track_rows else 0.0
    active_views = [t for t in ctx.tracks if t.started]
    active_act, active_pln, _ = rollup([x for t in active_views for x in t.tasks], ctx.planned) if active_views else (0.0, 0.0, 0)
    ms_rows = [milestone_dict(m, tracks_db) for m in ctx.milestones]

    risks, decisions, attention = governance_payload(db, program)
    trend = trend_series(db, program, snapshot)
    covered = sum(1 for t in ctx.tracks if t.leaf_count > 0 and t.start)
    latest_pt = trend["points"][-1] if trend["points"] else {"planned": pc["details"].get("planned"), "actual": pc["value"]}
    behind = round((latest_pt.get("planned") or 0) - (latest_pt.get("actual") or 0), 1)
    ai_summary = db.scalar(select(Insight).where(Insight.snapshot_id == snapshot.id, Insight.kind == "executive_summary")
                           .order_by(Insight.created_at.desc()).limit(1))
    tenant = program.tenant
    brand = {**(tenant.branding or {}), **{k: v for k, v in (program.branding or {}).items() if v}}

    timeline_det = tl["details"] or {}
    return {
        "program_id": program.id,
        "snapshot": {"id": snapshot.id, "version_no": snapshot.version_no, "as_of": _iso(snapshot.as_of_date),
                     "filename": snapshot.filename, "planned_method": snapshot.planned_method_used,
                     "rebaselined": snapshot.rebaselined, "warnings": snapshot.warnings or [],
                     "kpi_engine_version": snapshot.kpi_engine_version},
        "header": {
            "client_name": program.client_name or tenant.name, "client_name_ar": program.client_name_ar or tenant.name_ar,
            "program_name": program.name, "program_name_ar": program.name_ar,
            "title": f"{program.name} - Executive Dashboard",
            "subtitle": program.subtitle or "", "location": program.location or brand.get("location"),
            "as_of": _iso(snapshot.as_of_date), "client_logo_url": _logo_url(program, "client_logo"),
            "vendor_logo_url": _logo_url(program, "vendor_logo"),
            "support_email": brand.get("support_email"), "contact_url": brand.get("contact_url"),
            "primary_color": brand.get("primary_color"),
        },
        "kpi_strip": {"tracks": len(track_rows), "active": at["value"] or 0, "avg_progress": avg_progress,
                      "milestones": tm["value"] or 0},
        "cards": {
            "program_completion": {"value": pc["value"], "tag": pc["details"].get("tag"), "planned": pc["details"].get("planned"),
                                   "variance_pts": pc["details"].get("variance_pts"), "kpi": "program_completion"},
            "active_tracks": {"value": at["value"], "total": at["details"].get("total"),
                              "pending": at["details"].get("pending_activation"), "kpi": "active_tracks"},
            "total_milestones": {"value": tm["value"], "tracks_covered": tm["details"].get("tracks_covered"),
                                 "by_status": tm["details"].get("by_status", {}), "kpi": "total_milestones"},
            "on_track": {"value": on["value"], "of": tm["value"], "kpi": "milestones_on_track"},
            "not_started": {"value": ns["value"], "of": tm["value"], "kpi": "milestones_not_started"},
            "decisions_required": {"value": dr["value"], "high_priority": dr["details"].get("high_priority", 0),
                                   "kpi": "decisions_required"},
            "high_risks": {"value": hr["value"], "tracked": hr["details"].get("tracked", 0), "kpi": "high_risks"},
            "active_track_timeline": {"value": tl["value"], "available": tl["available"], **timeline_det,
                                      "kpi": "active_track_timeline"},
            "next_milestone": {"available": nm["available"], **(nm["details"] or {}), "kpi": "next_milestone"},
        },
        "tracks": track_rows,
        "active_track_progress": {"percent": active_act, "planned": active_pln, "active_tracks": len(active_views),
                                  "total_tracks": len(track_rows)},
        "milestones": ms_rows,
        "gantt": build_gantt(ms_rows, snapshot.as_of_date),
        "trend": {**trend, "summary": {"planned": latest_pt.get("planned"), "actual": latest_pt.get("actual"),
                                       "behind_pts": behind, "tracks_covered": covered, "tracks_total": len(track_rows)}},
        "decisions": sorted([decision_dict(d) for d in decisions],
                            key=lambda d: (d["status"] != "Pending", PRIORITY_ORDER.get(d["priority"], 9))),
        "risks": sorted([risk_dict(r) for r in risks if r.status != "Closed"],
                        key=lambda r: SEVERITY_ORDER.get(r["severity"], 9)),
        "attention": {"derived": derive_attention(ctx, ctx.milestones, decisions, risks, today),
                      "items": [attention_dict(a) for a in attention if a.status != "Resolved"]},
        "ai_summary": {"id": ai_summary.id, "content": ai_summary.content, "model": ai_summary.model,
                       "created_at": ai_summary.created_at.isoformat(), "flags": ai_summary.guardrail_flags}
        if ai_summary else None,
    }
