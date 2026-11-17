"""Data profiling of a parsed plan + deterministic (heuristic) mapping proposal.

The profile is the JSON fed to AI discovery; the heuristic proposal is used when AI is off and as
a fallback/validation reference when the AI proposal is invalid.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

FIELD_GROUPS = {
    "baseline": ["baseline_start", "baseline_finish"],
    "actuals": ["actual_start", "actual_finish"],
    "progress": ["percent_complete"],
    "duration": ["duration_days"],
    "work": ["work_hours", "baseline_work_hours", "actual_work_hours"],
    "cost": ["cost", "baseline_cost", "actual_cost"],
    "earned_value": ["bcws", "bcwp", "acwp"],
    "logic": ["predecessors", "successors"],
    "constraints": ["constraint_type"],
    "deadlines": ["deadline"],
    "slack": ["total_slack_days", "free_slack_days"],
    "critical": ["is_critical"],
    "resources": ["resource_names"],
    "notes": ["notes"],
}


def _populated(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, (list, dict, str)):
        return len(v) > 0
    return True


def leaf_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in tasks if not t.get("is_summary") and t.get("outline_level", 0) > 0]


def build_profile(tasks: list[dict[str, Any]], resources: list[dict[str, Any]], props: dict[str, Any],
                  custom_field_defs: list[dict[str, Any]], populated_fields: list[str],
                  calendars: list[dict[str, Any]]) -> dict[str, Any]:
    leaves = leaf_tasks(tasks)
    n = len(leaves) or 1
    coverage: dict[str, float] = {}
    for f in {f for fs in FIELD_GROUPS.values() for f in fs}:
        coverage[f] = round(100.0 * sum(1 for t in leaves if _populated(t.get(f))) / n, 1)
    groups = {g: round(max(coverage[f] for f in fs), 1) for g, fs in FIELD_GROUPS.items()}

    levels = Counter(t.get("outline_level", 0) for t in tasks if t.get("outline_level", 0) > 0)
    summary_levels = Counter(t.get("outline_level", 0) for t in tasks if t.get("is_summary") and t.get("outline_level", 0) > 0)
    level_names: dict[int, list[str]] = defaultdict(list)
    for t in tasks:
        lvl = t.get("outline_level", 0)
        if t.get("is_summary") and 0 < lvl <= 3 and len(level_names[lvl]) < 25:
            level_names[lvl].append(t.get("name", ""))

    # Custom fields: candidate track/milestone fields (low-cardinality text, flags)
    cf_values: dict[str, Counter] = defaultdict(Counter)
    for t in tasks:
        for k, v in (t.get("custom_fields") or {}).items():
            if v is not None and v != "":
                cf_values[k][str(v)] += 1
    custom_fields = []
    for k, cnt in cf_values.items():
        total = sum(cnt.values())
        custom_fields.append({
            "field": k,
            "populated_tasks": total,
            "coverage_pct": round(100.0 * total / max(len(tasks), 1), 1),
            "distinct_values": len(cnt),
            "top_values": [v for v, _ in cnt.most_common(12)],
            "is_flag_like": set(cnt.keys()) <= {"True", "False", "Yes", "No", "1", "0"},
        })
    custom_fields.sort(key=lambda c: -c["populated_tasks"])

    ms_flag = sum(1 for t in tasks if t.get("is_milestone"))
    quality_gaps: list[dict[str, Any]] = []

    def gap(code: str, severity: str, message: str, count: int | None = None):
        quality_gaps.append({"code": code, "severity": severity, "message": message, "count": count})

    no_baseline = sum(1 for t in leaves if not t.get("baseline_finish"))
    if no_baseline:
        gap("missing_baseline", "high" if no_baseline / n > 0.5 else "medium",
            f"{no_baseline} of {len(leaves)} tasks have no baseline finish.", no_baseline)
    no_pred = [t for t in leaves if not t.get("predecessors")]
    no_succ = [t for t in leaves if not t.get("successors")]
    if len(no_pred) > 1:
        gap("missing_predecessors", "medium", f"{len(no_pred)} tasks have no predecessors.", len(no_pred))
    if len(no_succ) > 1:
        gap("missing_successors", "medium", f"{len(no_succ)} tasks have no successors.", len(no_succ))
    no_res = sum(1 for t in leaves if not t.get("resource_names") and not t.get("is_milestone"))
    if no_res and coverage["resource_names"] > 0:
        gap("unassigned_tasks", "low", f"{no_res} tasks have no resource assigned.", no_res)
    if coverage["resource_names"] == 0:
        gap("no_resources", "info", "No resources/assignments in the file; resource KPIs unavailable.")
    if groups["cost"] == 0:
        gap("no_cost", "info", "No cost data; earned-value cost KPIs unavailable.")
    no_dates = sum(1 for t in leaves if not t.get("start") or not t.get("finish"))
    if no_dates:
        gap("missing_dates", "high", f"{no_dates} tasks have no start/finish date.", no_dates)
    bad_actual = sum(1 for t in leaves if t.get("percent_complete", 0) > 0 and not t.get("actual_start"))
    if bad_actual:
        gap("progress_without_actual_start", "low", f"{bad_actual} tasks show progress but no actual start.", bad_actual)
    if not props.get("status_date"):
        gap("no_status_date", "low", "Project status date is not set; as-of date must be supplied at upload.")

    return {
        "task_count": len(tasks),
        "leaf_task_count": len(leaves),
        "summary_task_count": sum(1 for t in tasks if t.get("is_summary")),
        "milestone_flag_count": ms_flag,
        "resource_count": len(resources),
        "max_outline_level": max(levels) if levels else 0,
        "tasks_per_level": {str(k): v for k, v in sorted(levels.items())},
        "summaries_per_level": {str(k): v for k, v in sorted(summary_levels.items())},
        "summary_names_by_level": {str(k): v for k, v in sorted(level_names.items())},
        "field_coverage_pct": dict(sorted(coverage.items())),
        "group_coverage_pct": groups,
        "custom_fields": custom_fields[:30],
        "custom_field_defs": custom_field_defs[:60],
        "populated_fields": populated_fields[:200],
        "calendars": [c.get("name") for c in calendars][:20],
        "project": {k: props.get(k) for k in ("title", "start", "finish", "status_date", "baseline_date",
                                                 "currency_symbol", "file_type")},
        "quality_gaps": quality_gaps,
    }


def heuristic_mapping(profile: dict[str, Any]) -> dict[str, Any]:
    """Deterministic mapping proposal used when AI is off or returns an invalid proposal."""
    summaries = {int(k): v for k, v in profile.get("summaries_per_level", {}).items()}
    rationale = []
    # Track rule: prefer a low-cardinality text custom field named like track/workstream/stream
    track_rule: dict[str, Any] | None = None
    for cf in profile.get("custom_fields", []):
        name = cf["field"].lower()
        if any(w in name for w in ("track", "workstream", "stream", "phase", "pillar")) and \
                2 <= cf["distinct_values"] <= 30 and not cf["is_flag_like"]:
            track_rule = {"type": "custom_field", "field": cf["field"]}
            rationale.append(f"Custom field '{cf['field']}' looks like a track field "
                             f"({cf['distinct_values']} distinct values).")
            break
    if track_rule is None:
        level = 1
        if summaries.get(1, 0) == 1 and summaries.get(2, 0) >= 2:
            level = 2  # single top-level summary (program node) → tracks one level below
            rationale.append("Single top-level summary detected; tracks taken from outline level 2.")
        else:
            rationale.append(f"Tracks taken from outline level 1 ({summaries.get(1, 0)} summary tasks).")
        track_rule = {"type": "outline_level", "level": level}

    # Milestone rule
    milestone_rule: dict[str, Any]
    flag_cf = next((cf for cf in profile.get("custom_fields", [])
                    if "milestone" in cf["field"].lower() and cf["populated_tasks"] > 0), None)
    if flag_cf:
        milestone_rule = {"type": "custom_field", "field": flag_cf["field"],
                          "value": "True" if flag_cf["is_flag_like"] else flag_cf["top_values"][0]}
        rationale.append(f"Milestones flagged by custom field '{flag_cf['field']}'.")
    elif profile.get("milestone_flag_count", 0) >= 2:
        milestone_rule = {"type": "flag"}
        rationale.append(f"{profile['milestone_flag_count']} tasks carry the MS Project milestone flag.")
    else:
        lvl = (track_rule.get("level", 1) + 1) if track_rule["type"] == "outline_level" else 1
        milestone_rule = {"type": "outline_level", "level": lvl}
        rationale.append(f"No milestone flags; summary tasks at outline level {lvl} used as milestones.")

    cov = profile.get("group_coverage_pct", {})
    planned = "baseline" if cov.get("baseline", 0) >= 50 else "auto"
    return {"track_rule": track_rule, "milestone_rule": milestone_rule, "planned_method": planned,
            "rationale": " ".join(rationale)}
