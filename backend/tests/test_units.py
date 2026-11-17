"""Unit tests: diff matching edge cases, schedule maths, AI redaction & grounding guardrails."""
from __future__ import annotations

from datetime import date

from app.ai.redact import Redactor
from app.ai.service import grounding_check
from app.services.diff import detect_rebaseline, diff_tasks, match_tasks
from app.services.schedule_math import classify_status, health_chip, linear_percent, rollup


def T(uid, name, wbs=None, **kw):
    base = {"unique_id": uid, "name": name, "wbs": wbs, "outline_number": wbs, "outline_level": kw.pop("lvl", 2),
            "parent_unique_id": kw.pop("parent", None), "start": date(2026, 1, 1), "finish": date(2026, 1, 31),
            "baseline_start": None, "baseline_finish": None, "percent_complete": 0.0, "duration_days": 20.0,
            "actual_start": None, "actual_finish": None, "predecessors": [], "resource_names": [], "is_critical": False,
            "is_milestone": False, "is_active": True, "constraint_type": None, "deadline": None, "track_id": None}
    base.update(kw)
    return base


# ------------------------------------------------------------------------------------------- diff
def test_match_by_uid():
    pairs = match_tasks([T(1, "Design"), T(2, "Build")], [T(1, "Design"), T(2, "Build")])
    assert {m for _, _, m, _ in pairs} == {"uid"}


def test_uid_reuse_falls_back_to_wbs_and_fuzzy():
    # Plan rebuilt: UIDs renumbered, names/WBS kept -> must still match the right tasks.
    prev = [T(1, "Requirements analysis", "1.1"), T(2, "Solution design", "1.2"), T(3, "Build", "1.3")]
    cur = [T(1, "Build", "1.3"), T(2, "Requirements analysis", "1.1"), T(3, "Solution design", "1.2")]
    pairs = match_tasks(cur, prev)
    matched = {c["name"]: p["name"] for c, p, _, _ in pairs if c and p}
    assert matched == {"Build": "Build", "Requirements analysis": "Requirements analysis", "Solution design": "Solution design"}


def test_fuzzy_rename_detected():
    prev = [T(10, "Bilingual EN/AR content")]
    cur = [T(99, "Bilingual EN / AR content")]
    pairs = match_tasks(cur, prev)
    assert pairs[0][2] == "fuzzy"


def test_added_removed_renamed_moved_progress():
    prev = [T(1, "Alpha"), T(2, "Beta"), T(3, "Gamma", percent_complete=10.0)]
    cur = [T(1, "Alpha renamed"), T(3, "Gamma", percent_complete=40.0, finish=date(2026, 2, 10)), T(4, "Delta")]
    rows = {r["change_type"]: r for r in diff_tasks(cur, prev, date(2026, 1, 15), date(2026, 1, 8))}
    assert "added" in rows and "removed" in rows and "renamed" in rows
    gamma = next(r for r in diff_tasks(cur, prev, date(2026, 1, 15), date(2026, 1, 8)) if r["task_name"] == "Gamma")
    assert gamma["finish_delta_days"] == 10 and gamma["progress_delta"] == 30


def test_unchanged_tasks_not_reported():
    t = [T(1, "Same")]
    assert diff_tasks(t, [dict(t[0])], date(2026, 1, 1), date(2026, 1, 1)) == []


def test_rebaseline_detection():
    prev = [T(i, f"t{i}", baseline_finish=date(2026, 1, 31)) for i in range(10)]
    cur = [T(i, f"t{i}", baseline_finish=date(2026, 3, 31) if i < 3 else date(2026, 1, 31)) for i in range(10)]
    assert detect_rebaseline(cur, prev)
    assert not detect_rebaseline(prev, prev)


# ------------------------------------------------------------------------------------------- maths
class _T:
    def __init__(self, uid, pct, dur, summary=False):
        self.unique_id, self.percent_complete, self.duration_days = uid, pct, dur
        self.baseline_duration_days, self.is_summary, self.outline_level = None, summary, 2


def test_linear_percent_bounds():
    s, f = date(2026, 1, 1), date(2026, 1, 11)
    assert linear_percent(s, f, date(2025, 12, 31)) == 0
    assert linear_percent(s, f, date(2026, 1, 6)) == 50
    assert linear_percent(s, f, date(2026, 2, 1)) == 100
    assert linear_percent(s, s, s) == 100


def test_rollup_is_duration_weighted_and_ignores_summaries():
    tasks = [_T(1, 100, 30), _T(2, 0, 10), _T(3, 50, 999, summary=True)]
    act, pln, n = rollup(tasks, {1: 100, 2: 100})
    assert (act, pln, n) == (75.0, 100.0, 2)


def test_status_thresholds():
    assert classify_status(100, 100, True) == "completed"
    assert classify_status(0, 0, False) == "not_started"
    assert classify_status(48, 50, True) == "on_track"
    assert classify_status(40, 50, True) == "delay"
    assert classify_status(20, 50, True) == "critical_delay"
    assert classify_status(0, 30, False) == "critical_delay"


def test_health_chip():
    asof = date(2026, 1, 10)
    assert health_chip(100, None, None, asof, True)["label"] == "COMPLETE"
    assert health_chip(0, date(2026, 1, 20), date(2026, 2, 1), asof, False)["label"] == "STARTS IN 10D"
    assert health_chip(50, date(2026, 1, 1), date(2026, 1, 15), asof, True)["label"] == "DUE IN 5D"
    over = health_chip(50, date(2026, 1, 1), date(2026, 1, 5), asof, True)
    assert over["label"] == "OVERDUE 5D" and over["urgency"] == "critical"


# ------------------------------------------------------------------------------------------- AI guardrails
def test_redaction_is_reversible_and_keeps_dates():
    r = Redactor(["Sara Al-Harbi"])
    text = "Owner Sara Al-Harbi (sara@ministry.gov.sa, +966 50 123 4567) due 2026-11-20."
    red = r.redact_text(text)
    assert "Sara" not in red and "@" not in red and "+966" not in red and "2026-11-20" in red
    assert r.restore(red) == text


def test_grounding_flags_invented_numbers():
    facts = {"kpis": {"program_completion": {"value": 64.12}}, "milestones": [{"pct": 82.0}]}
    assert grounding_check({"summary": "Programme is 64.1% complete; milestone at 82%."}, facts) == []
    flags = grounding_check({"summary": "Programme will finish 37.5% over budget."}, facts)
    assert flags == ["ungrounded_number:37.5"]
