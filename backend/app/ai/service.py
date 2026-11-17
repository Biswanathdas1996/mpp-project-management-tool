"""AI orchestration: facts → (redact) → provider → validate → guardrails → cache → log.

The application is fully usable with AI off: every caller handles ``AIUnavailable``.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from pydantic import ValidationError
from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..kpi.engine import REGISTRY
from ..models import (
    AIRequestLog,
    AttentionItem,
    Decision,
    Insight,
    KPIValue,
    Milestone,
    Program,
    Resource,
    Risk,
    Snapshot,
    Task,
    TaskDiff,
    Tenant,
    User,
)
from .conform import conform, describe_errors
from .prompts import BASE_SYSTEM, PROMPT_VERSION, TASKS
from .provider import AIUnavailable, get_provider
from .redact import Redactor
from .schemas import KIND_SCHEMAS

# Output-token budget per kind (cost/latency control); discovery enumerates many KPI codes.
MAX_TOKENS = {"discovery": 8192, "draft_governance": 4096}
# Hosted models occasionally return an empty or off-schema reply; a third try with a repair turn
# recovers almost all of those.
AI_ATTEMPTS = 3


class StreamSink(Protocol):
    """Receives a live view of the model's reply (e.g. to show it in the processing log)."""

    def begin(self, attempt: int, repair: bool) -> None: ...
    def token(self, delta: str, channel: str) -> None: ...
    def end(self, ok: bool, note: str) -> None: ...
NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?")


def _json_default(o: Any):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def _dumps(o: Any) -> str:
    return json.dumps(o, default=_json_default, ensure_ascii=False, sort_keys=True)


def _task_brief(t: Task) -> dict[str, Any]:
    return {"uid": t.unique_id, "name": t.name, "wbs": t.wbs, "start": t.start, "finish": t.finish,
            "baseline_finish": t.baseline_finish, "pct": round(t.percent_complete or 0, 1),
            "planned_pct": round(t.planned_percent or 0, 1), "critical": t.is_critical,
            "total_slack_days": t.total_slack_days, "resources": (t.resource_names or [])[:3]}


def build_facts(db: Session, program: Program, snapshot: Snapshot, max_chars: int) -> dict[str, Any]:
    kpis = db.scalars(select(KPIValue).where(KPIValue.snapshot_id == snapshot.id, KPIValue.available.is_(True))).all()
    kpi_facts = {}
    for k in kpis:
        det = {kk: vv for kk, vv in (k.details or {}).items() if not isinstance(vv, (list, dict))}
        kpi_facts[k.code] = {"value": k.value, "display": k.display, **det}
    ms = db.scalars(select(Milestone).where(Milestone.snapshot_id == snapshot.id).order_by(Milestone.number)).all()
    tasks = db.scalars(select(Task).where(Task.snapshot_id == snapshot.id)).all()
    leaves = [t for t in tasks if not t.is_summary and t.outline_level > 0]
    as_of = snapshot.as_of_date
    overdue = [t for t in leaves if t.finish and t.finish < as_of and (t.percent_complete or 0) < 100]
    late = [t for t in leaves if (t.percent_complete or 0) == 0 and (t.baseline_start or t.start) and
            (t.baseline_start or t.start) < as_of]
    critical = [t for t in leaves if t.is_critical and (t.percent_complete or 0) < 100]
    diffs = db.scalars(select(TaskDiff).where(TaskDiff.snapshot_id == snapshot.id, TaskDiff.compare_to == "previous")).all()
    diffs = sorted(diffs, key=lambda d: -(abs(d.finish_delta_days or 0) + (50 if d.is_milestone else 0)))
    from ..services.context import build_track_views
    planned = {t.unique_id: t.planned_percent or 0 for t in tasks}
    tracks = build_track_views(db, program, list(tasks), planned)
    facts = {
        "program": {"name": program.name, "as_of": as_of, "reporting_cycle_days": program.reporting_cycle_days,
                    "planned_method": snapshot.planned_method_used, "rebaselined": snapshot.rebaselined},
        "kpis": kpi_facts,
        "tracks": [{"number": t.number, "name": t.name, "actual_pct": t.actual, "planned_pct": t.planned,
                    "variance_pts": round(t.actual - t.planned, 1), "status": t.status, "start": t.start,
                    "finish": t.finish} for t in tracks],
        "milestones": [{"number": m.number, "name": m.name, "status": m.status, "pct": m.percent_complete,
                        "planned_pct": m.planned_percent, "variance_pts": m.variance_pts, "start": m.start,
                        "finish": m.finish, "baseline_finish": m.baseline_finish, "slippage_days": m.slippage_days,
                        "uid": m.task_unique_id, "health": (m.health or {}).get("label")} for m in ms],
        "overdue_tasks": [_task_brief(t) for t in sorted(overdue, key=lambda t: t.finish)[:25]],
        "late_start_tasks": [_task_brief(t) for t in late[:20]],
        "open_critical_tasks": [_task_brief(t) for t in critical[:25]],
        "changes": [{"uid": d.task_unique_id or d.base_unique_id, "name": d.task_name, "type": d.change_type,
                     "finish_delta_days": d.finish_delta_days, "progress_delta": d.progress_delta,
                     "status": f"{d.old_status}->{d.new_status}" if d.old_status else None,
                     "milestone": d.is_milestone} for d in diffs[:40]],
        "governance": {
            "risks": [{"title": r.title, "severity": r.severity, "status": r.status, "due": r.due_date}
                      for r in db.scalars(select(Risk).where(Risk.program_id == program.id, Risk.review_status == "approved"))][:30],
            "decisions": [{"title": d.title, "priority": d.priority, "status": d.status, "needed_by": d.needed_by}
                          for d in db.scalars(select(Decision).where(Decision.program_id == program.id,
                                                                     Decision.review_status == "approved"))][:30],
        },
    }
    # Cost/latency control: shrink until within the configured budget
    for key, keep in (("changes", 20), ("open_critical_tasks", 12), ("overdue_tasks", 12), ("late_start_tasks", 8),
                      ("milestones", 40), ("changes", 8)):
        if len(_dumps(facts)) <= max_chars:
            break
        facts[key] = facts[key][:keep]
    return facts


def _numbers_in(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, str):
        for m in NUM.findall(obj):
            try:
                out.append(float(m.replace(",", ".")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_numbers_in(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_numbers_in(v))
    return out


def _fact_numbers(obj: Any, acc: set[float]) -> set[float]:
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, (int, float)):
        acc.add(round(float(obj), 1))
        acc.add(float(round(obj)))
    elif isinstance(obj, str):
        for n in _numbers_in(obj):
            acc.add(round(n, 1))
    elif isinstance(obj, (date, datetime)):
        for n in (obj.year, obj.month, obj.day):
            acc.add(float(n))
    elif isinstance(obj, dict):
        for v in obj.values():
            _fact_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _fact_numbers(v, acc)
    return acc


def grounding_check(output: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    """Flag numbers in narrative text that do not appear in the facts (hallucination guardrail)."""
    allowed = _fact_numbers(facts, set())
    flags = []
    text_fields = {k: v for k, v in output.items() if not k.endswith("uids")}
    for n in _numbers_in(text_fields):
        if abs(n) <= 12 and float(n).is_integer():
            continue  # small counts/ordinals ("3 milestones", "Q3")
        if 1900 <= n <= 2100:
            continue  # years
        if not any(abs(n - a) <= max(0.15, abs(a) * 0.005) for a in allowed):
            flags.append(f"ungrounded_number:{n:g}")
    return sorted(set(flags))[:20]


class AIService:
    def __init__(self, db: Session, tenant: Tenant):
        self.db = db
        self.tenant = tenant
        self.settings = get_settings()
        self.provider = get_provider(tenant.ai_mode or "off")
        self.model = tenant.ai_model or self.settings.ai_default_model

    @property
    def enabled(self) -> bool:
        return self.provider.name != "off"

    def _sensitive_terms(self, program: Program, snapshot: Snapshot | None) -> list[str]:
        terms: list[str] = []
        if snapshot is not None:
            terms += [r.name for r in self.db.scalars(select(Resource).where(Resource.snapshot_id == snapshot.id))]
        for model in (Risk, Decision, AttentionItem):
            terms += [o for (o,) in self.db.execute(select(model.owner).where(model.program_id == program.id)) if o]
        if program.client_name:
            terms.append(program.client_name)
        terms += [u.full_name for u in self.db.scalars(select(User).where(User.tenant_id == self.tenant.id)) if u.full_name]
        return terms

    def _check_quota(self) -> None:
        since = datetime.now(timezone.utc) - timedelta(days=1)
        n = self.db.scalar(select(func.count(AIRequestLog.id)).where(
            AIRequestLog.tenant_id == self.tenant.id, AIRequestLog.created_at >= since,
            AIRequestLog.status.in_(("ok", "invalid", "error"))))
        if (n or 0) >= self.settings.ai_daily_call_limit:
            raise AIUnavailable("Daily AI call limit reached for this tenant")

    def run(self, kind: str, program: Program, snapshot: Snapshot | None, payload: dict[str, Any], *,
            user: User | None = None, question: str | None = None, force: bool = False,
            valid_task_uids: set[int] | None = None, stream: "StreamSink | None" = None) -> Insight:
        schema_cls = KIND_SCHEMAS[kind]
        input_hash = hashlib.sha256((_dumps(payload) + (question or "") + PROMPT_VERSION + self.model +
                                     self.provider.name).encode()).hexdigest()
        if not force:
            cached = self.db.scalar(select(Insight).where(
                Insight.snapshot_id == (snapshot.id if snapshot else None), Insight.kind == kind,
                Insight.input_hash == input_hash).order_by(Insight.created_at.desc()).limit(1))
            if cached is not None:
                self._log(kind, program, snapshot, user, "cached", 0, 0, 0, None, False, 0)
                if stream:  # same input as an earlier run: show the stored answer instead of a live one
                    stream.begin(0, repair=False)
                    stream.token(json.dumps(cached.content, ensure_ascii=False, indent=2), "content")
                    stream.end(True, "reused the stored answer for this exact input")
                return cached
        if not self.enabled:
            raise AIUnavailable("AI is turned off for this tenant")
        self._check_quota()

        user_msg = {"task": TASKS[kind], "facts": payload}
        if question:
            user_msg["question"] = question[:1000]
        text = _dumps(user_msg)
        redactor = None
        if self.provider.is_external and self.tenant.ai_redact:
            redactor = Redactor(self._sensitive_terms(program, snapshot))
            text = redactor.redact_text(text)
        schema = schema_cls.model_json_schema()
        # End the message with the output shape: models anchor on the last thing they read, and a long
        # facts block at the end invites them to echo it back.
        required = schema.get("required", [])
        text += (f"\n\nRespond now with ONE JSON object whose top-level keys are: {', '.join(schema['properties'])} "
                 f"(required: {', '.join(required)}). Do not repeat the facts.")
        last_err = None
        resp = None
        parsed = None
        conversation: list[dict[str, str]] = [{"role": "user", "content": text}]
        for attempt in range(AI_ATTEMPTS):
            if stream:
                stream.begin(attempt + 1, repair=len(conversation) > 1)
            try:
                resp = self.provider.chat_json(BASE_SYSTEM, conversation, schema, self.model,
                                               MAX_TOKENS.get(kind, 3072), on_token=stream.token if stream else None)
            except AIUnavailable as exc:
                last_err = str(exc)
                if stream:
                    stream.end(False, last_err)
                self._log(kind, program, snapshot, user, "error", sum(len(m["content"]) for m in conversation),
                          0, 0, last_err, bool(redactor), redactor.count if redactor else 0)
                self.db.commit()
                if attempt == AI_ATTEMPTS - 1 or "limit" in last_err.lower():
                    raise
                continue  # transient transport/HTTP failure: try again
            try:
                parsed = conform(resp.text, schema_cls)
                if stream:
                    stream.end(True, f"{len(resp.text):,} chars in {resp.latency_ms / 1000:.1f}s")
                break
            except (ValueError, ValidationError) as exc:
                last_err = describe_errors(exc)
                if stream:
                    stream.end(False, last_err)
                if not resp.text.strip() and resp.done_reason == "length":
                    last_err += " (output token budget exhausted)"
                self._log(kind, program, snapshot, user, "invalid", sum(len(m["content"]) for m in conversation),
                          len(resp.text), resp.latency_ms, last_err, bool(redactor),
                          redactor.count if redactor else 0, resp)
                if resp.text.strip():
                    # Repair turn: show the model its own answer and exactly what is wrong with it.
                    conversation = [
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": resp.text[:6000]},
                        {"role": "user", "content": (
                            f"That answer does not match the required schema: {last_err}. Reply with ONLY the "
                            f"corrected JSON object, with top-level keys {', '.join(schema['properties'])}. "
                            f"Use exactly these key names and allowed values; do not copy the input facts.")},
                    ]
                else:
                    conversation = [{"role": "user", "content": text}]  # empty reply: just ask again
        if parsed is None:
            self.db.commit()
            raise AIUnavailable(f"Model returned invalid output {AI_ATTEMPTS} times: {last_err}")

        content = parsed.model_dump()
        if redactor:
            content = redactor.restore(content)
        flags = grounding_check(content, payload)
        content, uid_flags = self._validate_refs(kind, content, valid_task_uids)
        flags += uid_flags
        ins = Insight(program_id=program.id, snapshot_id=snapshot.id if snapshot else None, kind=kind,
                      input_hash=input_hash, question=question, content=content, guardrail_flags=flags,
                      provider=self.provider.name, model=self.model, prompt_version=PROMPT_VERSION,
                      latency_ms=resp.latency_ms, created_by_id=user.id if user else None)
        self.db.add(ins)
        self._log(kind, program, snapshot, user, "ok", len(text), len(resp.text), resp.latency_ms, None,
                  bool(redactor), redactor.count if redactor else 0, resp)
        self.db.commit()
        return ins

    def _validate_refs(self, kind: str, content: dict[str, Any], valid_uids: set[int] | None):
        flags: list[str] = []
        if valid_uids is not None:
            def clean(lst):
                bad = [u for u in lst if u not in valid_uids]
                if bad:
                    flags.append(f"unknown_task_uids:{','.join(map(str, bad[:10]))}")
                return [u for u in lst if u in valid_uids]
            for key in ("cited_task_uids",):
                if key in content:
                    content[key] = clean(content[key])
            for coll in ("causes", "risks", "decisions", "attention"):
                for item in content.get(coll, []) or []:
                    for key in ("evidence_task_uids", "related_task_uids"):
                        if key in item:
                            item[key] = clean(item[key])
        if kind == "qa" and valid_uids is not None:
            # Models often cite "uid: 123" in prose but leave the structured list empty: recover the
            # citations so the answer drills down to its tasks (only UIDs that exist in the snapshot).
            found = [int(x) for x in re.findall(r"\buid[:#\s]*?(\d+)", content.get("answer", ""), re.IGNORECASE)]
            merged = list(dict.fromkeys(list(content.get("cited_task_uids") or []) + found))
            content["cited_task_uids"] = [u for u in merged if u in valid_uids][:30]
        if kind == "discovery":
            kept = []
            for p in content.get("kpis", []):
                if p["code"] in REGISTRY:
                    kept.append(p)
                else:
                    flags.append(f"unknown_kpi:{p['code']}")
            content["kpis"] = kept
        return content, flags

    def _log(self, kind, program, snapshot, user, status, pchars, rchars, latency, error, redacted, rcount, resp=None):
        self.db.add(AIRequestLog(
            tenant_id=self.tenant.id, program_id=program.id if program else None,
            snapshot_id=snapshot.id if snapshot else None, user_id=user.id if user else None, kind=kind,
            provider=self.provider.name, model=self.model, redacted=redacted, redaction_count=rcount,
            prompt_chars=pchars, response_chars=rchars, latency_ms=latency, status=status, error=error,
            prompt_tokens=getattr(resp, "prompt_tokens", None), completion_tokens=getattr(resp, "completion_tokens", None),
        ))

    # ------------------------------------------------------------------------------ high-level ops
    def discovery(self, program: Program, snapshot: Snapshot, profile: dict[str, Any],
                  stream: StreamSink | None = None) -> Insight:
        payload = {"profile": profile,
                   "allowed_custom_fields": [cf["field"] for cf in profile.get("custom_fields", [])],
                   "allowed_outline_levels": sorted(int(k) for k in profile.get("tasks_per_level", {})),
                   "kpi_catalogue": [{"code": d.code, "name": d.name, "category": d.category,
                                      "source_fields": d.source_fields} for d in REGISTRY.values() if not d.reference],
                   "reference_kpis": [d.code for d in REGISTRY.values() if d.reference]}
        return self.run("discovery", program, snapshot, payload, stream=stream)

    def insight(self, kind: str, program: Program, snapshot: Snapshot, user: User | None = None,
                force: bool = False) -> Insight:
        facts = build_facts(self.db, program, snapshot, self.settings.ai_max_input_chars)
        if kind == "draft_governance":
            facts["existing_governance"] = {
                "risks": [r.title for r in self.db.scalars(select(Risk).where(Risk.program_id == program.id))],
                "decisions": [d.title for d in self.db.scalars(select(Decision).where(Decision.program_id == program.id))],
                "attention": [a.title for a in self.db.scalars(select(AttentionItem).where(AttentionItem.program_id == program.id))],
            }
        uids = {u for (u,) in self.db.execute(select(Task.unique_id).where(Task.snapshot_id == snapshot.id))}
        return self.run(kind, program, snapshot, facts, user=user, force=force, valid_task_uids=uids)

    @staticmethod
    def _retrieve(question: str, tasks: list[Task], limit: int = 40) -> list[dict[str, Any]]:
        """Q&A retrieval: open tasks of any track/summary named in the question (most slipped first), then
        tasks whose own names match the question."""
        q = question.lower()
        by_uid = {t.unique_id: t for t in tasks}
        children: dict[int, list[Task]] = {}
        for t in tasks:
            if t.parent_unique_id is not None:
                children.setdefault(t.parent_unique_id, []).append(t)

        def leaves_under(uid: int) -> list[Task]:
            out, stack = [], list(children.get(uid, []))
            while stack:
                c = stack.pop()
                if c.is_summary:
                    stack.extend(children.get(c.unique_id, []))
                else:
                    out.append(c)
            return out

        def slip(t: Task) -> float:
            return float((t.finish - t.baseline_finish).days) if t.finish and t.baseline_finish else 0.0

        picked: list[Task] = []
        for s in (t for t in tasks if t.is_summary and t.name and fuzz.partial_ratio(t.name.lower(), q) >= 90):
            open_leaves = [x for x in leaves_under(s.unique_id) if (x.percent_complete or 0) < 100]
            picked.extend(sorted(open_leaves, key=lambda x: (-slip(x), -(x.planned_percent or 0) + (x.percent_complete or 0))))
        named = sorted(tasks, key=lambda t: -fuzz.partial_ratio(q, (t.name or "").lower()))
        seen: set[int] = set()
        out = []
        for t in picked + named:
            if t.unique_id in seen:
                continue
            seen.add(t.unique_id)
            brief = _task_brief(t)
            brief["finish_slip_days_vs_baseline"] = slip(t)
            parent = by_uid.get(t.parent_unique_id) if t.parent_unique_id is not None else None
            brief["parent"] = parent.name if parent else None
            out.append(brief)
            if len(out) >= limit:
                break
        return out

    def ask(self, program: Program, snapshot: Snapshot, question: str, user: User | None) -> Insight:
        facts = build_facts(self.db, program, snapshot, self.settings.ai_max_input_chars // 2)
        tasks = self.db.scalars(select(Task).where(Task.snapshot_id == snapshot.id)).all()
        facts["relevant_tasks"] = self._retrieve(question, list(tasks))
        uids = {t.unique_id for t in tasks}
        return self.run("qa", program, snapshot, facts, user=user, question=question, valid_task_uids=uids, force=True)
