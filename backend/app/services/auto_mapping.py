"""Decide whether a first-upload mapping proposal can be approved without an admin.

Two independent opinions are compared: the deterministic heuristic (profiling.heuristic_mapping) and the
AI proposal. When they agree, or only one exists, the chosen rules are applied to the actual tasks and
must pass structural checks. Anything doubtful is left for the mapping wizard; nothing here invents rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..models import Task
from .mapping import preview_mapping

MIN_TRACKS, MAX_TRACKS = 2, 40
MIN_TRACK_COVERAGE = 0.80   # share of (non-root) tasks that must fall into some track
MAX_DOMINANT_TRACK = 0.90   # one track holding nearly everything means the level is too high


@dataclass
class AutoDecision:
    approve: bool
    reasons: list[str] = field(default_factory=list)   # why not (empty when approved)
    checks: list[str] = field(default_factory=list)    # what was verified (shown in the processing log)
    preview: dict[str, Any] = field(default_factory=dict)


def _same_rule(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    def norm(r):
        r = r or {}
        return (r.get("type"), r.get("level") if r.get("type") == "outline_level" else None,
                (r.get("field") or "").lower() if r.get("type") == "custom_field" else None,
                str(r.get("value") or "").lower() if r.get("type") == "custom_field" else None)
    return norm(a) == norm(b)


def evaluate(tasks: list[Task], proposal: dict[str, Any], heuristic: dict[str, Any], ai_answered: bool,
             ai_rule_fallbacks: int, mode: Literal["off", "confident", "always"]) -> AutoDecision:
    """``ai_answered``: the AI returned a valid proposal; ``ai_rule_fallbacks``: how many of its rules did not
    fit the file and were replaced by the rule-based ones (then there is no independent agreement)."""
    if mode == "off":
        return AutoDecision(False, ["automatic approval is turned off (PMA_MAPPING_AUTO_APPROVE=off)"])
    d = AutoDecision(True)

    # 1) Agreement between the rule-based and the AI proposal
    if mode == "confident" and ai_answered:
        if ai_rule_fallbacks:
            d.approve = False
            d.reasons.append("part of the AI proposal did not fit this file and was replaced by the rule-based rule")
        for key, label in (("track_rule", "tracks"), ("milestone_rule", "milestones")):
            if _same_rule(proposal.get(key), heuristic.get(key)):
                d.checks.append(f"AI and rule-based logic agree on {label}: {proposal.get(key)}")
            elif key == "track_rule":
                d.approve = False
                d.reasons.append(f"AI and rule-based logic disagree on tracks "
                                 f"({proposal.get(key)} vs {heuristic.get(key)})")
            else:
                d.checks.append(f"AI chose milestones {proposal.get(key)} (rule-based: {heuristic.get(key)})")
    elif mode == "confident":
        d.checks.append("AI not available: relying on the rule-based proposal and structural checks")

    # 2) Structural checks on the real tasks
    if proposal.get("track_rule", {}).get("type") not in ("outline_level", "custom_field"):
        d.approve = False
        d.reasons.append("tracks must come from an outline level or a custom field")
        return d
    pv = preview_mapping(tasks, proposal["track_rule"], proposal["milestone_rule"])
    d.preview = pv
    n_tracks = len(pv["tracks"])
    considered = sum(1 for t in tasks if t.outline_level > 0) or 1
    mapped = sum(t["task_count"] for t in pv["tracks"])
    # The programme root above an outline-level-2 rule is legitimately outside every track.
    roots = sum(1 for t in tasks if t.outline_level == 1) if proposal["track_rule"].get("type") == "outline_level" \
        and proposal["track_rule"].get("level", 1) > 1 else 0
    coverage = min(1.0, mapped / max(1, considered - roots))
    biggest = max((t["task_count"] for t in pv["tracks"]), default=0) / max(1, mapped)

    def check(ok: bool, good: str, bad: str):
        if ok:
            d.checks.append(good)
        else:
            d.approve = False
            d.reasons.append(bad)

    check(MIN_TRACKS <= n_tracks <= MAX_TRACKS, f"{n_tracks} tracks found",
          f"{n_tracks} tracks found (expected {MIN_TRACKS}-{MAX_TRACKS})")
    check(coverage >= MIN_TRACK_COVERAGE, f"{coverage:.0%} of tasks fall into a track",
          f"only {coverage:.0%} of tasks fall into a track (need {MIN_TRACK_COVERAGE:.0%})")
    check(n_tracks < 2 or biggest <= MAX_DOMINANT_TRACK, f"largest track holds {biggest:.0%} of tasks",
          f"one track holds {biggest:.0%} of all tasks; the track level is probably too high")
    check(pv["milestone_count"] >= 1, f"{pv['milestone_count']} milestones found", "no milestones found")
    return d
