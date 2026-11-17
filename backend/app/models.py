"""SQLAlchemy data model.

Entities (plan §4): Tenant, Program, MappingConfig, Track, Snapshot, Task, Milestone, TaskDiff,
KPIDefinition, KPIValue, Risk, Decision, AttentionItem, Insight, User/Role, plus supporting
Resource, Assignment, AuditLog, AIRequestLog, AlertRule, Alert.

Source data (A, from .mpp) lives in Snapshot/Task/Resource/Assignment and is immutable once
parsed.  Governance data (B) lives in Risk/Decision/AttentionItem, is program-scoped and persists
across snapshots.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    admin = "admin"
    pmo_editor = "pmo_editor"
    super_viewer = "super_viewer"


class SnapshotStatus(str, enum.Enum):
    queued = "queued"
    parsing = "parsing"
    awaiting_mapping = "awaiting_mapping"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class ReviewStatus(str, enum.Enum):
    draft = "draft"  # AI-drafted, waiting for human review
    approved = "approved"
    rejected = "rejected"


# ----------------------------------------------------------------------------------------------
# Tenancy & identity
# ----------------------------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    name_ar: Mapped[str | None] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    # Branding: client/vendor logos (storage keys), primary colour, support email, location.
    branding: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # AI: off | self_hosted | cloud ; switchable per tenant.
    ai_mode: Mapped[str] = mapped_column(String(20), default="off")
    ai_model: Mapped[str | None] = mapped_column(String(100))
    ai_redact: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    users: Mapped[list[User]] = relationship(back_populates="tenant")
    programs: Mapped[list[Program]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_user_email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.super_viewer.value)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(255), index=True)
    locale: Mapped[str] = mapped_column(String(5), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, default=0)

    tenant: Mapped[Tenant] = relationship(back_populates="users")


# ----------------------------------------------------------------------------------------------
# Programs, mapping, tracks
# ----------------------------------------------------------------------------------------------
class Program(Base):
    __tablename__ = "programs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    name_ar: Mapped[str | None] = mapped_column(String(200))
    client_name: Mapped[str | None] = mapped_column(String(200))
    client_name_ar: Mapped[str | None] = mapped_column(String(200))
    subtitle: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    reporting_cycle_days: Mapped[int] = mapped_column(Integer, default=7)
    # Program-level branding overrides (client logo etc.)
    branding: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Status thresholds in variance points (configurable per program)
    thresholds: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=lambda: {"delay_pts": -5.0, "critical_pts": -15.0, "stalled_snapshots": 3,
                               "near_critical_days": 10, "long_duration_days": 44}
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    tenant: Mapped[Tenant] = relationship(back_populates="programs")
    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="program", order_by="Snapshot.as_of_date", cascade="all, delete-orphan"
    )
    tracks: Mapped[list[Track]] = relationship(
        back_populates="program", order_by="Track.number", cascade="all, delete-orphan"
    )
    mapping_configs: Mapped[list[MappingConfig]] = relationship(
        back_populates="program", order_by="MappingConfig.version", cascade="all, delete-orphan"
    )


class MappingConfig(Base):
    """Per-program mapping produced by the wizard on first upload and reused afterwards.

    track_rule:     {"type": "outline_level", "level": 1}
                    {"type": "custom_field", "field": "Text1"}
    milestone_rule: {"type": "flag"} | {"type": "outline_level", "level": 2}
                    | {"type": "custom_field", "field": "Flag1", "value": "Yes"}
    planned_method: auto | baseline | first_snapshot | linear
    approved_kpis:  list of KPI codes the admin approved for this program.
    """

    __tablename__ = "mapping_configs"
    __table_args__ = (UniqueConstraint("program_id", "version", name="uq_mapping_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|approved|superseded
    track_rule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    milestone_rule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    planned_method: Mapped[str] = mapped_column(String(20), default="auto")
    track_names: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # key -> display name
    excluded_track_keys: Mapped[list[Any]] = mapped_column(JSON, default=list)
    approved_kpis: Mapped[list[Any]] = mapped_column(JSON, default=list)
    proposed_kpis: Mapped[list[Any]] = mapped_column(JSON, default=list)
    proposed_by: Mapped[str] = mapped_column(String(20), default="heuristic")  # ai|heuristic|user
    rationale: Mapped[str | None] = mapped_column(Text)
    source_snapshot_id: Mapped[int | None] = mapped_column(Integer)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    program: Mapped[Program] = relationship(back_populates="mapping_configs")


class Track(Base):
    """Delivery track, numbered 01..n and stable across snapshots (matched by key)."""

    __tablename__ = "tracks"
    __table_args__ = (UniqueConstraint("program_id", "key", name="uq_track_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(255))  # summary-task UID or custom-field value
    name: Mapped[str] = mapped_column(String(300))
    name_ar: Mapped[str | None] = mapped_column(String(300))
    source_label: Mapped[str] = mapped_column(String(200), default="")
    first_seen_snapshot_id: Mapped[int | None] = mapped_column(Integer)
    last_seen_snapshot_id: Mapped[int | None] = mapped_column(Integer)

    program: Mapped[Program] = relationship(back_populates="tracks")


# ----------------------------------------------------------------------------------------------
# Snapshots & parsed plan data (read-only source A)
# ----------------------------------------------------------------------------------------------
class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("program_id", "file_hash", name="uq_snapshot_hash"),
        UniqueConstraint("program_id", "version_no", name="uq_snapshot_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    as_of_date: Mapped[date | None] = mapped_column(Date, index=True)
    as_of_source: Mapped[str] = mapped_column(String(20), default="user")  # user|status_date|upload
    filename: Mapped[str] = mapped_column(String(400))
    file_hash: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(500))
    file_format: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default=SnapshotStatus.queued.value, index=True)
    status_message: Mapped[str | None] = mapped_column(Text)
    error_report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    project_props: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    calendars: Mapped[list[Any]] = mapped_column(JSON, default=list)
    custom_field_defs: Mapped[list[Any]] = mapped_column(JSON, default=list)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # data discovery
    has_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    planned_method_used: Mapped[str | None] = mapped_column(String(20))
    rebaselined: Mapped[bool] = mapped_column(Boolean, default=False)
    mapping_config_id: Mapped[int | None] = mapped_column(ForeignKey("mapping_configs.id", ondelete="SET NULL"))
    kpi_engine_version: Mapped[str | None] = mapped_column(String(20))
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[str | None] = mapped_column(String(100))

    program: Mapped[Program] = relationship(back_populates="snapshots")
    tasks: Mapped[list[Task]] = relationship(back_populates="snapshot", cascade="all, delete-orphan",
                                             passive_deletes=True)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "unique_id", name="uq_task_uid"),
        Index("ix_task_snapshot_track", "snapshot_id", "track_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    unique_id: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[int | None] = mapped_column(Integer)
    parent_unique_id: Mapped[int | None] = mapped_column(Integer)
    wbs: Mapped[str | None] = mapped_column(String(100))
    outline_number: Mapped[str | None] = mapped_column(String(100))
    outline_level: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(500), default="")
    is_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    start: Mapped[date | None] = mapped_column(Date)
    finish: Mapped[date | None] = mapped_column(Date)
    baseline_start: Mapped[date | None] = mapped_column(Date)
    baseline_finish: Mapped[date | None] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_finish: Mapped[date | None] = mapped_column(Date)
    early_start: Mapped[date | None] = mapped_column(Date)
    late_start: Mapped[date | None] = mapped_column(Date)
    percent_complete: Mapped[float] = mapped_column(Float, default=0.0)
    physical_percent_complete: Mapped[float | None] = mapped_column(Float)
    duration_days: Mapped[float | None] = mapped_column(Float)
    baseline_duration_days: Mapped[float | None] = mapped_column(Float)
    actual_duration_days: Mapped[float | None] = mapped_column(Float)
    remaining_duration_days: Mapped[float | None] = mapped_column(Float)
    work_hours: Mapped[float | None] = mapped_column(Float)
    baseline_work_hours: Mapped[float | None] = mapped_column(Float)
    actual_work_hours: Mapped[float | None] = mapped_column(Float)
    remaining_work_hours: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float)
    baseline_cost: Mapped[float | None] = mapped_column(Float)
    actual_cost: Mapped[float | None] = mapped_column(Float)
    remaining_cost: Mapped[float | None] = mapped_column(Float)
    bcws: Mapped[float | None] = mapped_column(Float)
    bcwp: Mapped[float | None] = mapped_column(Float)
    acwp: Mapped[float | None] = mapped_column(Float)
    constraint_type: Mapped[str | None] = mapped_column(String(60))
    constraint_date: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    total_slack_days: Mapped[float | None] = mapped_column(Float)
    free_slack_days: Mapped[float | None] = mapped_column(Float)
    predecessors: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{uid,type,lag_days}]
    successors: Mapped[list[Any]] = mapped_column(JSON, default=list)
    resource_names: Mapped[list[Any]] = mapped_column(JSON, default=list)
    calendar_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # ---- derived by mapping (recomputed if mapping changes; raw fields above never change) ----
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"))
    is_mapped_milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    planned_percent: Mapped[float | None] = mapped_column(Float)

    snapshot: Mapped[Snapshot] = relationship(back_populates="tasks")


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (UniqueConstraint("snapshot_id", "unique_id", name="uq_resource_uid"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    unique_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(300), default="")
    type: Mapped[str | None] = mapped_column(String(30))
    group: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255))
    max_units: Mapped[float | None] = mapped_column(Float)
    standard_rate: Mapped[float | None] = mapped_column(Float)
    work_hours: Mapped[float | None] = mapped_column(Float)
    actual_work_hours: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float)
    is_overallocated: Mapped[bool] = mapped_column(Boolean, default=False)
    peak_units: Mapped[float | None] = mapped_column(Float)


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    task_unique_id: Mapped[int] = mapped_column(Integer, index=True)
    resource_unique_id: Mapped[int | None] = mapped_column(Integer)
    units: Mapped[float | None] = mapped_column(Float)
    work_hours: Mapped[float | None] = mapped_column(Float)
    actual_work_hours: Mapped[float | None] = mapped_column(Float)
    remaining_work_hours: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float)
    start: Mapped[date | None] = mapped_column(Date)
    finish: Mapped[date | None] = mapped_column(Date)


class Milestone(Base):
    """Milestone state per snapshot (derived through MappingConfig)."""

    __tablename__ = "milestones"
    __table_args__ = (UniqueConstraint("snapshot_id", "task_unique_id", name="uq_ms_snapshot_task"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"))
    task_unique_id: Mapped[int] = mapped_column(Integer)
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500))
    start: Mapped[date | None] = mapped_column(Date)
    finish: Mapped[date | None] = mapped_column(Date)
    baseline_start: Mapped[date | None] = mapped_column(Date)
    baseline_finish: Mapped[date | None] = mapped_column(Date)
    percent_complete: Mapped[float] = mapped_column(Float, default=0)
    planned_percent: Mapped[float] = mapped_column(Float, default=0)
    variance_pts: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30))  # completed|on_track|delay|critical_delay|not_started
    health: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {kind, days, urgency}
    slippage_days: Mapped[float | None] = mapped_column(Float)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskDiff(Base):
    __tablename__ = "task_diffs"
    __table_args__ = (Index("ix_diff_snapshot_kind", "snapshot_id", "compare_to"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    base_snapshot_id: Mapped[int | None] = mapped_column(Integer)
    compare_to: Mapped[str] = mapped_column(String(20))  # previous | baseline
    task_unique_id: Mapped[int | None] = mapped_column(Integer)
    base_unique_id: Mapped[int | None] = mapped_column(Integer)
    match_method: Mapped[str | None] = mapped_column(String(20))  # uid | wbs | fuzzy | none
    match_score: Mapped[float | None] = mapped_column(Float)
    change_type: Mapped[str] = mapped_column(String(30))  # added|removed|renamed|date_moved|progress|status|modified
    task_name: Mapped[str] = mapped_column(String(500), default="")
    track_id: Mapped[int | None] = mapped_column(Integer)
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # field -> {old,new}
    start_delta_days: Mapped[float | None] = mapped_column(Float)
    finish_delta_days: Mapped[float | None] = mapped_column(Float)
    progress_delta: Mapped[float | None] = mapped_column(Float)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str | None] = mapped_column(String(30))


# ----------------------------------------------------------------------------------------------
# KPI engine
# ----------------------------------------------------------------------------------------------
class KPIDefinition(Base):
    __tablename__ = "kpi_definitions"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_kpi_code_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    formula: Mapped[str] = mapped_column(Text)
    source_fields: Mapped[list[Any]] = mapped_column(JSON, default=list)
    widget: Mapped[str] = mapped_column(String(40))
    phase: Mapped[str] = mapped_column(String(10))
    unit: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[bool] = mapped_column(Boolean, default=False)  # part of reference dashboard


class KPIValue(Base):
    __tablename__ = "kpi_values"
    __table_args__ = (UniqueConstraint("snapshot_id", "code", name="uq_kpivalue_snapshot_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(80))
    kpi_version: Mapped[int] = mapped_column(Integer, default=1)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(300))
    value: Mapped[float | None] = mapped_column(Float)
    display: Mapped[str | None] = mapped_column(String(200))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    drill_uids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ----------------------------------------------------------------------------------------------
# Governance data (source B) — persists across snapshots
# ----------------------------------------------------------------------------------------------
class _GovernanceMixin:
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    title_ar: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai | engine
    review_status: Mapped[str] = mapped_column(String(20), default=ReviewStatus.approved.value)
    related_task_uids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    origin_snapshot_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Risk(_GovernanceMixin, Base):
    __tablename__ = "risks"
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="Medium")  # Critical|High|Medium|Low
    likelihood: Mapped[str | None] = mapped_column(String(20))
    impact: Mapped[str | None] = mapped_column(String(20))
    mitigation: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="Open")  # Open|Mitigating|Closed
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Decision(_GovernanceMixin, Base):
    """Key support requests & decisions for the steering committee."""

    __tablename__ = "decisions"
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="decision")  # decision | support
    priority: Mapped[str] = mapped_column(String(10), default="Medium")  # High|Medium|Low
    status: Mapped[str] = mapped_column(String(20), default="Pending")  # Pending|Approved|Rejected
    needed_by: Mapped[date | None] = mapped_column(Date)
    decided_at: Mapped[date | None] = mapped_column(Date)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AttentionItem(_GovernanceMixin, Base):
    __tablename__ = "attention_items"
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="Medium")
    status: Mapped[str] = mapped_column(String(20), default="Open")  # Open|Resolved
    due_date: Mapped[date | None] = mapped_column(Date)
    category: Mapped[str | None] = mapped_column(String(40))  # overdue|at_risk|missed_deadline|...
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


# ----------------------------------------------------------------------------------------------
# AI
# ----------------------------------------------------------------------------------------------
class Insight(Base):
    """AI output, cached per snapshot + kind + input hash."""

    __tablename__ = "insights"
    __table_args__ = (Index("ix_insight_cache", "snapshot_id", "kind", "input_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    input_hash: Mapped[str] = mapped_column(String(64))
    question: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    guardrail_flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIRequestLog(Base):
    __tablename__ = "ai_request_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    program_id: Mapped[int | None] = mapped_column(Integer)
    snapshot_id: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)
    redaction_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_chars: Mapped[int] = mapped_column(Integer, default=0)
    response_chars: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20))  # ok|invalid|error|cached|blocked
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ----------------------------------------------------------------------------------------------
# Audit & alerts
# ----------------------------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    user_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    program_id: Mapped[int | None] = mapped_column(Integer, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    kpi_code: Mapped[str] = mapped_column(String(80))
    operator: Mapped[str] = mapped_column(String(4))  # < <= > >= == !=
    threshold: Mapped[float] = mapped_column(Float)
    channel: Mapped[str] = mapped_column(String(20), default="in_app")  # in_app|email|webhook
    target: Mapped[str | None] = mapped_column(String(500))  # email list or webhook URL
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"))
    program_id: Mapped[int | None] = mapped_column(Integer, index=True)
    snapshot_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    delivery_status: Mapped[str] = mapped_column(String(20), default="in_app")
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
