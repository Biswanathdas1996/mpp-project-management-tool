"""Schema-validated AI outputs (JSON in → schema-validated JSON out)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RuleOut(BaseModel):
    type: Literal["outline_level", "custom_field", "flag"]
    level: int | None = Field(default=None, ge=1, le=10)
    field: str | None = None
    value: str | None = None


class KPIProposal(BaseModel):
    code: str
    rationale: str = Field(max_length=200)


class KPIIdea(BaseModel):
    name: str = Field(max_length=120)
    rationale: str = Field(max_length=400)
    required_fields: list[str] = Field(default_factory=list, max_length=10)


class DiscoveryOut(BaseModel):
    data_quality_summary: str = Field(max_length=2000)
    structure_notes: str = Field(max_length=1500)
    track_rule: RuleOut
    milestone_rule: RuleOut
    planned_method: Literal["auto", "baseline", "first_snapshot", "linear"]
    mapping_rationale: str = Field(max_length=1500)
    kpis: list[KPIProposal] = Field(max_length=80)
    additional_kpi_ideas: list[KPIIdea] = Field(default_factory=list, max_length=10)
    gaps: list[str] = Field(default_factory=list, max_length=20)


class ExecSummaryOut(BaseModel):
    headline: str = Field(max_length=200)
    summary: str = Field(max_length=2500)
    highlights: list[str] = Field(max_length=8)
    concerns: list[str] = Field(max_length=8)
    recommendations: list[str] = Field(max_length=8)


class KeyChange(BaseModel):
    title: str = Field(max_length=200)
    detail: str = Field(max_length=600)
    impact: Literal["low", "medium", "high"]


class ChangeNarrativeOut(BaseModel):
    narrative: str = Field(max_length=2500)
    key_changes: list[KeyChange] = Field(max_length=12)


class Cause(BaseModel):
    milestone: str = Field(max_length=300)
    cause: str = Field(max_length=600)
    evidence_task_uids: list[int] = Field(default_factory=list, max_length=20)
    confidence: Literal["low", "medium", "high"]


class RootCauseOut(BaseModel):
    summary: str = Field(max_length=1500)
    causes: list[Cause] = Field(max_length=12)


class ForecastOut(BaseModel):
    forecast_narrative: str = Field(max_length=2000)
    likely_finish_window: str = Field(max_length=120)
    confidence: Literal["low", "medium", "high"]
    assumptions: list[str] = Field(max_length=8)
    risks_to_forecast: list[str] = Field(max_length=8)


class DraftRisk(BaseModel):
    title: str = Field(max_length=200)
    description: str = Field(max_length=800)
    severity: Literal["Critical", "High", "Medium", "Low"]
    mitigation: str = Field(max_length=800)
    owner: str | None = Field(default=None, max_length=120)
    due_in_days: int | None = Field(default=None, ge=0, le=365)
    related_task_uids: list[int] = Field(default_factory=list, max_length=20)


class DraftDecision(BaseModel):
    title: str = Field(max_length=200)
    description: str = Field(max_length=800)
    priority: Literal["High", "Medium", "Low"]
    kind: Literal["decision", "support"] = "decision"
    owner: str | None = Field(default=None, max_length=120)
    needed_in_days: int | None = Field(default=None, ge=0, le=365)
    related_task_uids: list[int] = Field(default_factory=list, max_length=20)


class DraftAttention(BaseModel):
    title: str = Field(max_length=200)
    description: str = Field(max_length=800)
    severity: Literal["Critical", "High", "Medium", "Low"]
    related_task_uids: list[int] = Field(default_factory=list, max_length=20)


class DraftGovernanceOut(BaseModel):
    risks: list[DraftRisk] = Field(max_length=10)
    decisions: list[DraftDecision] = Field(max_length=10)
    attention: list[DraftAttention] = Field(max_length=10)


class QAOut(BaseModel):
    answer: str = Field(max_length=3000)
    cited_task_uids: list[int] = Field(default_factory=list, max_length=30)
    confidence: Literal["low", "medium", "high"]
    cannot_answer: bool = False


KIND_SCHEMAS: dict[str, type[BaseModel]] = {
    "discovery": DiscoveryOut,
    "executive_summary": ExecSummaryOut,
    "change_narrative": ChangeNarrativeOut,
    "root_cause": RootCauseOut,
    "forecast": ForecastOut,
    "draft_governance": DraftGovernanceOut,
    "qa": QAOut,
}
