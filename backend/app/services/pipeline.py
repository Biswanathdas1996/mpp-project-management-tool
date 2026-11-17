"""Snapshot ingestion & processing pipeline.

upload → hash duplicate check → object storage → queue → parse (MPXJ) → store raw data →
profile → AI discovery (or heuristic) → [mapping wizard on first upload] → apply mapping →
planned-to-date → diff (vs previous & vs baseline) → KPI engine → alerts → AI insights (async).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..ai.provider import AIUnavailable
from ..ai.service import AIService
from ..audit import audit
from ..config import get_settings
from ..db import session_scope
from ..kpi.engine import ENGINE_VERSION, REGISTRY, compute_all
from ..models import (
    Assignment,
    KPIValue,
    MappingConfig,
    Program,
    Resource,
    Snapshot,
    SnapshotStatus,
    Task,
    TaskDiff,
    User,
)
from ..parser.mpp_parser import ParseError, parse_plan_bytes
from ..progress import Progress, ProgressStream
from . import auto_mapping
from ..queue import enqueue
from ..storage import get_storage
from .alerts import evaluate_alerts
from .context import build_context, previous_snapshot
from .diff import detect_rebaseline, diff_tasks, diff_vs_baseline
from .mapping import apply_mapping, approve_mapping, first_snapshot_frozen
from .profiling import build_profile, heuristic_mapping

log = logging.getLogger(__name__)
ALLOWED_EXT = {".mpp", ".mpt", ".mpx", ".xml", ".mspdi", ".xer", ".pmxml", ".pp", ".gan", ".planner"}

TASK_COLUMNS = [c.key for c in Task.__table__.columns if c.key not in ("id", "snapshot_id", "track_id",
                                                                        "is_mapped_milestone", "planned_percent")]


# ----------------------------------------------------------------------------------------------
# Upload
# ----------------------------------------------------------------------------------------------
def create_snapshot_from_upload(db: Session, program: Program, user: User, filename: str, data: bytes,
                                as_of: date | None, password: str | None, max_bytes: int) -> Snapshot:
    import os

    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Upload .mpp, .mpt, .mpx or MSPDI .xml")
    if len(data) == 0:
        raise HTTPException(422, "File is empty")
    if len(data) > max_bytes:
        raise HTTPException(413, f"File exceeds {max_bytes // (1024 * 1024)} MB")
    digest = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(Snapshot).where(Snapshot.program_id == program.id, Snapshot.file_hash == digest))
    if dup is not None:
        raise HTTPException(409, {"code": "duplicate", "message": f"Identical file already uploaded as snapshot "
                                  f"v{dup.version_no} ({dup.filename})", "snapshot_id": dup.id})
    version = (db.scalar(select(func.max(Snapshot.version_no)).where(Snapshot.program_id == program.id)) or 0) + 1
    key = f"tenant-{program.tenant_id}/program-{program.id}/v{version:04d}-{digest[:12]}{ext}"
    get_storage().put(key, data)
    snap = Snapshot(program_id=program.id, version_no=version, as_of_date=as_of,
                    as_of_source="user" if as_of else "pending", filename=filename[:400], file_hash=digest,
                    file_size=len(data), storage_key=key, status=SnapshotStatus.queued.value,
                    uploaded_by_id=user.id)
    db.add(snap)
    db.flush()
    audit(db, "snapshot.upload", user=user, entity_type="snapshot", entity_id=snap.id, program_id=program.id,
          details={"filename": filename, "size": len(data), "hash": digest, "as_of": str(as_of) if as_of else None})
    db.commit()
    pr = Progress(snap.id, f"v{version} {filename}")
    pr.ok("upload", f"Received {filename} ({len(data) / 1048576:.2f} MB), stored as v{version}", pct=2)
    pr.info("queue", "Queued for processing", pct=3)  # before enqueue: the worker continues this sequence
    snap.job_id = enqueue("app.jobs.process_snapshot_job", snap.id, password)
    db.commit()
    return snap


# ----------------------------------------------------------------------------------------------
# Parse + discovery
# ----------------------------------------------------------------------------------------------
def _clean_rule(rule: dict[str, Any]) -> dict[str, Any]:
    t = rule.get("type")
    keep = {"outline_level": ("type", "level"), "custom_field": ("type", "field", "value"), "flag": ("type",)}.get(t, ("type",))
    return {k: rule[k] for k in keep if rule.get(k) is not None}


def _validate_ai_mapping(c: dict[str, Any], profile: dict[str, Any],
                         fallback: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate each AI rule against the file independently; an invalid rule (e.g. a hallucinated custom
    field) is replaced by the deterministic heuristic rule while the valid parts of the proposal are kept."""
    cf_names = {cf["field"] for cf in profile.get("custom_fields", [])}
    levels = {int(k) for k in profile.get("tasks_per_level", {})}

    def ok(rule, kind):
        t = rule.get("type")
        if t == "outline_level":
            return rule.get("level") in levels
        if t == "custom_field":
            return rule.get("field") in cf_names
        return t == "flag" and kind == "milestone"

    out = {"planned_method": c.get("planned_method", "auto"), "rationale": c.get("mapping_rationale", "")}
    notes: list[str] = []
    for key, kind in (("track_rule", "track"), ("milestone_rule", "milestone")):
        rule = _clean_rule(c.get(key) or {})
        if ok(rule, kind):
            out[key] = rule
        else:
            out[key] = fallback[key]
            notes.append(f"AI {kind} rule {rule} does not fit this file; heuristic rule {fallback[key]} used.")
    return out, notes


def _try_auto_approve(db: Session, program, snap: Snapshot, pending: MappingConfig, proposal: dict[str, Any],
                      heuristic: dict[str, Any], proposed_kpis: list[dict[str, Any]], profile: dict[str, Any],
                      ai_answered: bool, ai_fallbacks: int, pr: Progress) -> MappingConfig | None:
    """Approve the first mapping of a programme without an admin when logic and AI agree and the result
    passes structural checks (see services/auto_mapping.py). Returns the approved config, or None."""
    mode = get_settings().mapping_auto_approve
    tasks = list(db.scalars(select(Task).where(Task.snapshot_id == snap.id)))
    decision = auto_mapping.evaluate(tasks, proposal, heuristic, ai_answered, ai_fallbacks, mode)
    for c in decision.checks:
        pr.info("mapping", f"Check: {c}")
    if not decision.approve:
        for r in decision.reasons:
            pr.warn("mapping", f"Needs review: {r}")
        return None
    # KPI set: what the proposal suggests, limited to what this file's data can actually support.
    supported = {k["code"] for k in kpis_supported_by_profile(profile)}
    kpis = [k["code"] for k in proposed_kpis if k.get("code") in supported] or sorted(supported)
    m = approve_mapping(db, program.id, track_rule=proposal["track_rule"], milestone_rule=proposal["milestone_rule"],
                        planned_method=proposal.get("planned_method", "auto"), approved_kpis=kpis,
                        approved_by_id=None, proposed_by=pending.proposed_by or "heuristic")
    audit(db, "mapping.auto_approve", entity_type="mapping", entity_id=m.id, program_id=program.id,
          tenant_id=program.tenant_id, details={"version": m.version, "track_rule": m.track_rule,
                                                "milestone_rule": m.milestone_rule, "mode": mode,
                                                "checks": decision.checks, "snapshot_id": snap.id})
    db.commit()
    names = ", ".join(t["name"] for t in decision.preview.get("tracks", [])[:8])
    pr.ok("mapping", f"Mapping approved automatically (v{m.version}): {len(decision.preview.get('tracks', []))} "
                     f"tracks ({names}), {decision.preview.get('milestone_count', 0)} milestones. "
                     f"An admin can still adjust it in the mapping wizard.", pct=84)
    return m


def kpis_supported_by_profile(profile: dict[str, Any]) -> list[dict[str, str]]:
    g = profile.get("group_coverage_pct", {})
    need = {
        "cost": g.get("cost", 0) > 0, "resources": profile.get("resource_count", 0) > 0,
        "baseline": g.get("baseline", 0) > 0, "critical": g.get("critical", 0) > 0,
        "slack": g.get("slack", 0) > 0, "deadlines": g.get("deadlines", 0) > 0, "work": g.get("work", 0) > 0,
    }
    rule = {"spi": "baseline", "schedule_variance_days": "baseline", "milestone_slippage": "baseline", "bei": "baseline",
            "milestone_hit_rate": "baseline", "critical_path": "critical", "slack": "slack", "near_critical": "slack",
            "missed_deadlines": "deadlines", "work_planned_vs_actual": "work", "negative_slack": "slack"}
    out = []
    for d in REGISTRY.values():
        if d.reference:
            continue
        req = "cost" if d.category == "cost" and d.code != "work_planned_vs_actual" else \
            "resources" if d.category == "resources" else rule.get(d.code)
        if req is None or need.get(req, False):
            out.append({"code": d.code, "rationale": f"Supported: {req or 'core schedule fields'} present"})
    return out


def _mapping_drift_warnings(db: Session, snap: Snapshot, approved: MappingConfig, proposal: dict[str, Any],
                            profile: dict[str, Any]) -> list[str]:
    """Warn only on real structural change — never because the admin deliberately chose a mapping that
    differs from discovery's suggestion.

    1. The approved rules no longer fit this file (outline level or custom field disappeared).
    2. The deterministic (heuristic) proposal for this file differs from the one for the previous upload,
       i.e. the plan's structure changed. AI proposals are not compared: model output can vary run to run.
    """
    out: list[str] = []
    levels = {int(k) for k in profile.get("tasks_per_level", {})}
    cfs = {cf["field"] for cf in profile.get("custom_fields", [])}
    for label, rule in (("track", approved.track_rule or {}), ("milestone", approved.milestone_rule or {})):
        if rule.get("type") == "outline_level" and rule.get("level") not in levels:
            out.append(f"Approved {label} rule uses outline level {rule.get('level')}, which no longer exists in "
                       f"this file; review the mapping.")
        if rule.get("type") == "custom_field" and rule.get("field") not in cfs:
            out.append(f"Approved {label} rule uses custom field '{rule.get('field')}', which is empty in this "
                       f"file; review the mapping.")
    prev = db.scalar(select(Snapshot).where(Snapshot.program_id == snap.program_id, Snapshot.id != snap.id,
                                            Snapshot.status.in_(("ready", "awaiting_mapping")))
                     .order_by(Snapshot.uploaded_at.desc()).limit(1))
    prev_disc = ((prev.profile or {}).get("discovery") or {}) if prev else {}
    prev_prop = prev_disc.get("heuristic") or (prev_disc.get("proposal") if prev_disc.get("proposal_source") == "heuristic" else None)
    if prev_prop and (prev_prop.get("track_rule") != proposal["track_rule"]
                      or prev_prop.get("milestone_rule") != proposal["milestone_rule"]):
        out.append(f"Plan structure changed since the previous upload (discovery now suggests tracks "
                   f"{proposal['track_rule']}, milestones {proposal['milestone_rule']}); review the mapping.")
    return out


def process_snapshot(snapshot_id: int, password: str | None = None) -> None:
    with session_scope() as db:
        snap = db.get(Snapshot, snapshot_id)
        if snap is None:
            return
        program = snap.program
        pr = Progress(snap.id, f"v{snap.version_no} {snap.filename}", fresh=False)
        snap.status = SnapshotStatus.parsing.value
        snap.status_message = "Parsing file"
        db.commit()
        pr.info("parse", "Worker picked up the job", pct=4)
        try:
            data = get_storage().get(snap.storage_key)
            pr.info("parse", f"Loaded {len(data) / 1048576:.2f} MB from storage", pct=5)
            plan = parse_plan_bytes(data, snap.filename, password, progress=pr)
        except ParseError as exc:
            snap.status = SnapshotStatus.failed.value
            snap.error_report = exc.report()
            snap.status_message = exc.message
            audit(db, "snapshot.parse_failed", entity_type="snapshot", entity_id=snap.id, program_id=program.id,
                  tenant_id=program.tenant_id, details=exc.report())
            pr.error("parse", f"{exc.message} {exc.hint}".strip(), code=exc.code)
            pr.error("done", "Processing failed", final=True, status=snap.status)
            return
        except Exception as exc:  # pragma: no cover
            log.exception("Unexpected parse failure")
            snap.status = SnapshotStatus.failed.value
            snap.error_report = {"code": "internal_error", "message": "Unexpected error while parsing",
                                 "detail": f"{type(exc).__name__}: {exc}"[:2000], "hint": "Contact support."}
            pr.error("parse", f"Unexpected error: {type(exc).__name__}: {exc}"[:500])
            pr.error("done", "Processing failed", final=True, status=snap.status)
            return
        for w in plan.warnings:
            pr.warn("parse", w)

        # as-of date: user value > project status date > upload date
        if snap.as_of_date is None:
            sd = plan.props.get("status_date")
            if sd:
                snap.as_of_date, snap.as_of_source = date.fromisoformat(sd), "status_date"
            else:
                snap.as_of_date, snap.as_of_source = snap.uploaded_at.date(), "upload"
                plan.warnings.append("No status date in file and none supplied; upload date used as as-of date.")
                pr.warn("store", "No status date in file and none supplied; using the upload date")
        pr.info("store", f"As-of date {snap.as_of_date} (source: {snap.as_of_source})", pct=66)
        snap.file_format = plan.file_format
        snap.project_props = plan.props
        snap.calendars = plan.calendars
        snap.custom_field_defs = plan.custom_field_defs
        snap.task_count = len(plan.tasks)

        db.execute(delete(Task).where(Task.snapshot_id == snap.id))
        db.execute(delete(Resource).where(Resource.snapshot_id == snap.id))
        db.execute(delete(Assignment).where(Assignment.snapshot_id == snap.id))
        db.execute(Task.__table__.insert(), [{**{k: t.get(k) for k in TASK_COLUMNS}, "snapshot_id": snap.id}
                                              for t in plan.tasks])
        if plan.resources:
            db.execute(Resource.__table__.insert(), [{**r, "snapshot_id": snap.id} for r in plan.resources])
        if plan.assignments:
            db.execute(Assignment.__table__.insert(), [{**a, "snapshot_id": snap.id} for a in plan.assignments])
        snap.has_baseline = any(t.get("baseline_finish") for t in plan.tasks if not t.get("is_summary"))
        pr.ok("store", f"Saved {len(plan.tasks):,} tasks, {len(plan.resources):,} resources, "
                       f"{len(plan.assignments):,} assignments, baseline {'present' if snap.has_baseline else 'absent'}",
              pct=70)

        pr.info("profile", "Profiling plan structure and field coverage", pct=72)
        profile = build_profile(plan.tasks, plan.resources, plan.props, plan.custom_field_defs,
                                plan.populated_fields, plan.calendars)
        levels = profile.get("tasks_per_level", {})
        pr.ok("profile", f"{len(levels)} outline level(s), {len(profile.get('custom_fields', []))} populated "
                         f"custom field(s)", pct=74)
        snap.status_message = "AI discovery"
        db.commit()

        # ---- AI discovery on every upload (before the dashboard is built) -------------------------
        proposal = heuristic_mapping(profile)
        heuristic = dict(proposal)  # deterministic: used for structure-drift detection across uploads
        source = "heuristic"
        proposed_kpis = kpis_supported_by_profile(profile)
        discovery: dict[str, Any] = {"source": "heuristic", "insight_id": None}
        ai_answered, ai_fallbacks = False, 0
        pr.info("discovery", f"Heuristic proposal: tracks {proposal['track_rule']}, "
                             f"milestones {proposal['milestone_rule']}", pct=76)
        ai = AIService(db, program.tenant)
        if not ai.enabled:
            pr.info("discovery", "AI discovery disabled for this tenant; using the heuristic proposal", pct=80)
        if ai.enabled:
            try:
                pr.info("discovery", "Asking the AI model to propose a mapping…", pct=77)
                ins = ai.discovery(program, snap, profile, stream=ProgressStream(pr, "discovery"))
                validated, notes = _validate_ai_mapping(ins.content, profile, proposal)
                discovery = {"source": "ai", "insight_id": ins.id, "summary": ins.content.get("data_quality_summary"),
                             "structure_notes": ins.content.get("structure_notes"),
                             "ideas": ins.content.get("additional_kpi_ideas", []),
                             "gaps": ins.content.get("gaps", []), "flags": ins.guardrail_flags}
                if ins.content.get("kpis"):
                    proposed_kpis = ins.content["kpis"]
                proposal, source = validated, ("ai" if len(notes) < 2 else "heuristic")
                ai_answered, ai_fallbacks = True, len(notes)
                discovery["flags"] = list(discovery.get("flags") or []) + notes
                for n in notes:
                    pr.warn("discovery", n)
                pr.ok("discovery", f"AI proposal received ({len(proposed_kpis)} KPIs suggested); using "
                                   f"{source} mapping", pct=82)
            except AIUnavailable as exc:
                log.info("AI discovery unavailable for snapshot %s: %s", snap.id, exc)
                pr.warn("discovery", "AI discovery unavailable; falling back to the heuristic proposal", pct=82)
                plan.warnings.append("AI discovery could not produce a valid proposal (details in the AI call log); "
                                     "the deterministic proposal was used.")
        profile["discovery"] = {**discovery, "proposal": proposal, "proposed_kpis": proposed_kpis,
                                "proposal_source": source, "heuristic": heuristic}
        snap.profile = profile
        snap.warnings = plan.warnings

        approved = db.scalar(select(MappingConfig).where(MappingConfig.program_id == program.id,
                                                         MappingConfig.status == "approved")
                             .order_by(MappingConfig.version.desc()).limit(1))
        if approved is None:
            pending = db.scalar(select(MappingConfig).where(MappingConfig.program_id == program.id,
                                                            MappingConfig.status == "proposed")
                                .order_by(MappingConfig.version.desc()).limit(1))
            next_ver = (db.scalar(select(func.max(MappingConfig.version)).where(MappingConfig.program_id == program.id)) or 0) + 1
            if pending is None:
                pending = MappingConfig(program_id=program.id, version=next_ver, status="proposed")
                db.add(pending)
            pending.track_rule = proposal["track_rule"]
            pending.milestone_rule = proposal["milestone_rule"]
            pending.planned_method = proposal.get("planned_method", "auto")
            pending.proposed_by = source
            pending.rationale = proposal.get("rationale")
            pending.proposed_kpis = proposed_kpis
            pending.source_snapshot_id = snap.id
            db.flush()
            approved = _try_auto_approve(db, program, snap, pending, proposal, heuristic, proposed_kpis, profile,
                                         ai_answered, ai_fallbacks, pr)
        if approved is None:
            snap.status = SnapshotStatus.awaiting_mapping.value
            snap.status_message = "Waiting for an admin to approve the mapping"
            audit(db, "mapping.proposed", entity_type="mapping", program_id=program.id, tenant_id=program.tenant_id,
                  details={"source": source, "snapshot_id": snap.id})
            pr.warn("mapping", "No approved mapping yet: proposal saved for an admin to review", pct=100)
            pr.emit("done", "Parsed. Waiting for an admin to approve the mapping", "warn", final=True,
                    status=snap.status)
            return
        drift = _mapping_drift_warnings(db, snap, approved, heuristic, profile)
        for w in drift:
            pr.warn("mapping", w)
        snap.warnings = snap.warnings + drift
        snap.mapping_config_id = approved.id
        db.commit()
        pr.info("mapping", f"Using approved mapping v{approved.version}", pct=84)
        compute_snapshot(db, snap, progress=pr)
        waiting = db.scalar(select(func.count(Snapshot.id)).where(
            Snapshot.program_id == program.id, Snapshot.status == SnapshotStatus.awaiting_mapping.value))
        if waiting:  # earlier uploads that were parked before this programme had a mapping
            enqueue("app.jobs.recompute_program_job", program.id)


# ----------------------------------------------------------------------------------------------
# Compute (mapping → planned → diff → KPIs → alerts)
# ----------------------------------------------------------------------------------------------
def _persist_diffs(db: Session, snap: Snapshot, base_id: int | None, compare_to: str, rows: list[dict[str, Any]]):
    if rows:
        db.execute(TaskDiff.__table__.insert(), [{**r, "snapshot_id": snap.id, "base_snapshot_id": base_id,
                                                   "compare_to": compare_to} for r in rows])


class _Pseudo:
    """Task proxy that exposes frozen-first-snapshot dates as baseline (for 'vs baseline' diffs)."""

    def __init__(self, t: Task, frozen: tuple[date | None, date | None]):
        self._t = t
        self.baseline_start, self.baseline_finish = frozen

    def __getattr__(self, item):
        return getattr(self._t, item)


def compute_snapshot(db: Session, snap: Snapshot, cascade: bool = True, progress: Progress | None = None) -> None:
    program = snap.program
    pr = progress or Progress(snap.id, f"v{snap.version_no} {snap.filename}")
    snap.status = SnapshotStatus.processing.value
    snap.status_message = "Computing KPIs"
    db.commit()
    try:
        mapping = db.get(MappingConfig, snap.mapping_config_id)
        pr.info("compute", "Applying mapping (tracks, milestones, planned %)", pct=86)
        stats = apply_mapping(db, program, snap, mapping)
        pr.ok("compute", f"Mapped {stats['tracks']} tracks, {stats['milestones']} milestones "
                         f"(planned method: {stats['planned_method']})", pct=88)
        cur = list(db.scalars(select(Task).where(Task.snapshot_id == snap.id)))
        db.execute(delete(TaskDiff).where(TaskDiff.snapshot_id == snap.id))
        prev = previous_snapshot(db, snap)
        snap.rebaselined = False
        pr.info("compute", f"Diffing against previous snapshot v{prev.version_no}" if prev
                else "No previous snapshot to diff against", pct=89)
        if prev is not None:
            prev_tasks = list(db.scalars(select(Task).where(Task.snapshot_id == prev.id)))
            rows = diff_tasks(cur, prev_tasks, snap.as_of_date, prev.as_of_date,
                              {t.unique_id: t.planned_percent or 0 for t in cur},
                              {t.unique_id: t.planned_percent or 0 for t in prev_tasks}, program.thresholds)
            _persist_diffs(db, snap, prev.id, "previous", rows)
            snap.rebaselined = detect_rebaseline(cur, prev_tasks)
        if snap.has_baseline:
            _persist_diffs(db, snap, None, "baseline", diff_vs_baseline(cur))
        else:
            frozen = first_snapshot_frozen(db, program.id, snap)
            if frozen:
                proxies = [_Pseudo(t, frozen[t.unique_id]) for t in cur if t.unique_id in frozen]
                _persist_diffs(db, snap, None, "baseline", diff_vs_baseline(proxies))
        db.flush()
        if snap.rebaselined:
            pr.warn("compute", "Re-baseline detected vs the previous snapshot")

        pr.info("compute", f"Computing {len(REGISTRY)} KPIs", pct=92)
        ctx = build_context(db, program, snap)
        results = compute_all(ctx)
        n_avail = sum(1 for _, r in results.values() if r.available)
        pr.ok("compute", f"{n_avail} of {len(results)} KPIs available for this plan", pct=96)
        db.execute(delete(KPIValue).where(KPIValue.snapshot_id == snap.id))
        for code, (d, r) in results.items():
            db.add(KPIValue(snapshot_id=snap.id, code=code, kpi_version=d.version, available=r.available,
                            reason=r.reason, value=r.value, display=r.display, details=r.details,
                            drill_uids=r.drill_uids))
        snap.kpi_engine_version = ENGINE_VERSION
        snap.status = SnapshotStatus.ready.value
        snap.status_message = (f"{stats['tracks']} tracks, {stats['milestones']} milestones, "
                               f"planned method: {stats['planned_method']}")
        if stats["unmapped_tasks"]:
            snap.warnings = (snap.warnings or []) + [f"{stats['unmapped_tasks']} tasks are not under any track."]
        snap.processed_at = datetime.now(timezone.utc)
        db.flush()
        pr.info("compute", "Evaluating alert rules", pct=98)
        evaluate_alerts(db, program, snap, {c: r for c, (_, r) in results.items()})
        audit(db, "snapshot.processed", entity_type="snapshot", entity_id=snap.id, program_id=program.id,
              tenant_id=program.tenant_id, details=stats)
        db.commit()
        pr.ok("done", f"Snapshot ready: {snap.status_message}", pct=100, final=True, status=snap.status)
    except Exception as exc:
        db.rollback()
        log.exception("Snapshot compute failed")
        snap = db.get(Snapshot, snap.id)
        snap.status = SnapshotStatus.failed.value
        snap.error_report = {"code": "compute_error", "message": "KPI computation failed",
                             "detail": f"{type(exc).__name__}: {exc}"[:2000], "hint": "Contact support."}
        db.commit()
        pr.error("compute", f"KPI computation failed: {type(exc).__name__}: {exc}"[:500])
        pr.error("done", "Processing failed", final=True, status=snap.status)
        return

    if cascade:
        later = list(db.scalars(select(Snapshot).where(
            Snapshot.program_id == program.id, Snapshot.status == "ready", Snapshot.id != snap.id,
            Snapshot.as_of_date > snap.as_of_date).order_by(Snapshot.as_of_date, Snapshot.version_no)))
        for s in later:  # out-of-order upload: later snapshots' diffs/history depend on this one
            compute_snapshot(db, s, cascade=False)
    if AIService(db, program.tenant).enabled:
        enqueue("app.jobs.auto_insights_job", snap.id)


def recompute_program(program_id: int) -> None:
    with session_scope() as db:
        approved = db.scalar(select(MappingConfig).where(MappingConfig.program_id == program_id,
                                                         MappingConfig.status == "approved")
                             .order_by(MappingConfig.version.desc()).limit(1))
        if approved is None:
            return
        snaps = list(db.scalars(select(Snapshot).where(
            Snapshot.program_id == program_id,
            Snapshot.status.in_(("ready", "awaiting_mapping", "processing")))
            .order_by(Snapshot.as_of_date, Snapshot.version_no)))
        for s in snaps:  # demote so history is rebuilt strictly in as-of order
            s.status = SnapshotStatus.processing.value
            s.mapping_config_id = approved.id
        db.commit()
        for s in snaps:
            compute_snapshot(db, s, cascade=False)
