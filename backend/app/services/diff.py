"""Snapshot diff algorithm (plan §6).

Matching, in order:
  1. Unique ID — accepted unless the pair is clearly a different task (UID reuse after a plan was
     rebuilt/copy-pasted): name similarity < 50 AND WBS differs.  If < 40 % of UID pairs look
     sane, UIDs are treated as unreliable for the whole file and step 1 is skipped.
  2. WBS/outline number exact + name similarity ≥ 60.
  3. Fuzzy name (token-sort ratio ≥ 85) among remaining tasks, preferring same parent name;
     greedy by best score, one-to-one.
Unmatched current → added; unmatched previous → removed.
For each pair: renamed, date_moved (start/finish deltas), progress, status transition, duration,
baseline change, logic change, resource change, moved (parent change), (de)activated, milestone
flag toggled, critical flag toggled.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from rapidfuzz import fuzz

from .schedule_math import classify_status

COMPARED_FIELDS = ("start", "finish", "baseline_start", "baseline_finish", "duration_days",
                   "percent_complete", "actual_start", "actual_finish", "is_critical", "is_milestone",
                   "is_active", "constraint_type", "deadline")


def _get(t: Any, f: str) -> Any:
    return t.get(f) if isinstance(t, dict) else getattr(t, f, None)


_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def _norm(s: str | None) -> str:
    """Lower-case, punctuation-insensitive form ("EN/AR" == "EN / AR"); keeps Arabic letters."""
    return " ".join(_NON_WORD.sub(" ", (s or "").lower()).split())


def _name_sim(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    if a == b:
        return 100.0 if a else 0.0
    if not a or not b:
        return 0.0
    return float(fuzz.token_sort_ratio(a, b))


def _ser(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date) else v


def task_state(t: Any, as_of: date | None) -> str:
    pct = _get(t, "percent_complete") or 0.0
    if pct >= 99.999:
        return "completed"
    if pct > 0 or _get(t, "actual_start"):
        return "in_progress"
    return "not_started"


def match_tasks(current: list[Any], previous: list[Any]) -> list[tuple[Any | None, Any | None, str, float]]:
    cur = [t for t in current if (_get(t, "outline_level") or 0) > 0]
    prev = [t for t in previous if (_get(t, "outline_level") or 0) > 0]
    prev_by_uid = {_get(t, "unique_id"): t for t in prev}
    pairs: list[tuple[Any | None, Any | None, str, float]] = []
    used_prev: set[int] = set()
    unmatched_cur: list[Any] = []

    uid_pairs = [(c, prev_by_uid[_get(c, "unique_id")]) for c in cur if _get(c, "unique_id") in prev_by_uid]
    sane = [p for p in uid_pairs if _name_sim(_get(p[0], "name"), _get(p[1], "name")) >= 50
            or (_get(p[0], "wbs") and _get(p[0], "wbs") == _get(p[1], "wbs"))]
    uids_reliable = not uid_pairs or len(sane) / len(uid_pairs) >= 0.4
    sane_ids = {id(c) for c, _ in sane}

    for c in cur:
        p = prev_by_uid.get(_get(c, "unique_id")) if uids_reliable else None
        if p is not None and id(c) in sane_ids:
            pairs.append((c, p, "uid", 100.0))
            used_prev.add(id(p))
        else:
            unmatched_cur.append(c)

    # 2. WBS / outline number
    remaining_prev = [p for p in prev if id(p) not in used_prev]
    by_wbs: dict[str, list[Any]] = {}
    for p in remaining_prev:
        for key in {_get(p, "wbs"), _get(p, "outline_number")} - {None, ""}:
            by_wbs.setdefault(key, []).append(p)
    still: list[Any] = []
    for c in unmatched_cur:
        cands = []
        for key in {_get(c, "wbs"), _get(c, "outline_number")} - {None, ""}:
            cands.extend(p for p in by_wbs.get(key, []) if id(p) not in used_prev)
        best, score = None, 0.0
        for p in cands:
            s = _name_sim(_get(c, "name"), _get(p, "name"))
            if s > score:
                best, score = p, s
        if best is not None and score >= 60:
            pairs.append((c, best, "wbs", score))
            used_prev.add(id(best))
        else:
            still.append(c)

    # 3. Fuzzy name, one-to-one greedy
    remaining_prev = [p for p in prev if id(p) not in used_prev]
    parent_name_cur = {(_get(t, "unique_id")): _get(t, "name") for t in current}
    parent_name_prev = {(_get(t, "unique_id")): _get(t, "name") for t in previous}
    cands: list[tuple[float, int, int]] = []
    if still and remaining_prev and len(still) * len(remaining_prev) <= 4_000_000:
        for i, c in enumerate(still):
            cn = _get(c, "name")
            for j, p in enumerate(remaining_prev):
                s = _name_sim(cn, _get(p, "name"))
                if s >= 85:
                    pc = parent_name_cur.get(_get(c, "parent_unique_id"))
                    pp = parent_name_prev.get(_get(p, "parent_unique_id"))
                    bonus = 5.0 if pc and pp and _name_sim(pc, pp) >= 85 else 0.0
                    cands.append((s + bonus, i, j))
    cands.sort(reverse=True)
    used_i: set[int] = set()
    used_j: set[int] = set()
    for s, i, j in cands:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        pairs.append((still[i], remaining_prev[j], "fuzzy", min(s, 100.0)))
    for i, c in enumerate(still):
        if i not in used_i:
            pairs.append((c, None, "none", 0.0))
    for j, p in enumerate(remaining_prev):
        if j not in used_j:
            pairs.append((None, p, "none", 0.0))
    return pairs


def diff_tasks(current: list[Any], previous: list[Any], as_of_cur: date | None, as_of_prev: date | None,
               planned_cur: dict[int, float] | None = None, planned_prev: dict[int, float] | None = None,
               thresholds: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return change records (only tasks that changed)."""
    out: list[dict[str, Any]] = []
    prev_names = {_get(t, "unique_id"): _get(t, "name") for t in previous}
    cur_names = {_get(t, "unique_id"): _get(t, "name") for t in current}
    for c, p, method, score in match_tasks(current, previous):
        if c is not None and p is None:
            out.append(_rec(c, None, "added", method, score, {}, None))
            continue
        if c is None and p is not None:
            out.append(_rec(None, p, "removed", method, score, {}, None))
            continue
        changes: dict[str, Any] = {}
        if (_get(c, "name") or "") != (_get(p, "name") or ""):
            changes["name"] = {"old": _get(p, "name"), "new": _get(c, "name")}
        for f in COMPARED_FIELDS:
            a, b = _get(p, f), _get(c, f)
            if isinstance(a, float) or isinstance(b, float):
                if round(a or 0.0, 2) == round(b or 0.0, 2):
                    continue
            elif a == b:
                continue
            changes[f] = {"old": _ser(a), "new": _ser(b)}
        pp, cp = _get(p, "parent_unique_id"), _get(c, "parent_unique_id")
        if prev_names.get(pp) != cur_names.get(cp):
            changes["parent"] = {"old": prev_names.get(pp), "new": cur_names.get(cp)}
        pred_old = sorted(x.get("uid") for x in (_get(p, "predecessors") or []))
        pred_new = sorted(x.get("uid") for x in (_get(c, "predecessors") or []))
        if pred_old != pred_new and method == "uid":
            changes["predecessors"] = {"old": pred_old, "new": pred_new}
        ro, rn = sorted(_get(p, "resource_names") or []), sorted(_get(c, "resource_names") or [])
        if ro != rn:
            changes["resources"] = {"old": ro, "new": rn}
        so, sn = task_state(p, as_of_prev), task_state(c, as_of_cur)
        if planned_cur is not None and planned_prev is not None:
            so = classify_status(_get(p, "percent_complete") or 0, planned_prev.get(_get(p, "unique_id"), 0),
                                 bool(_get(p, "actual_start")), thresholds)
            sn = classify_status(_get(c, "percent_complete") or 0, planned_cur.get(_get(c, "unique_id"), 0),
                                 bool(_get(c, "actual_start")), thresholds)
        status = (so, sn) if so != sn else None
        if not changes and status is None:
            continue
        if "name" in changes:
            ctype = "renamed"
        elif status is not None:
            ctype = "status"
        elif "start" in changes or "finish" in changes:
            ctype = "date_moved"
        elif "percent_complete" in changes:
            ctype = "progress"
        elif "parent" in changes:
            ctype = "moved"
        else:
            ctype = "modified"
        out.append(_rec(c, p, ctype, method, score, changes, status))
    return out


def _days(a: date | None, b: date | None) -> float | None:
    return float((b - a).days) if a and b else None


def _rec(c: Any, p: Any, ctype: str, method: str, score: float, changes: dict[str, Any],
         status: tuple[str, str] | None) -> dict[str, Any]:
    ref = c if c is not None else p
    rec = {
        "task_unique_id": _get(c, "unique_id") if c is not None else None,
        "base_unique_id": _get(p, "unique_id") if p is not None else None,
        "match_method": method,
        "match_score": round(score, 1),
        "change_type": ctype,
        "task_name": _get(ref, "name") or "",
        "track_id": _get(ref, "track_id"),
        "is_milestone": bool(_get(ref, "is_mapped_milestone") or _get(ref, "is_milestone")),
        "changes": changes,
        "start_delta_days": _days(_get(p, "start"), _get(c, "start")) if c is not None and p is not None else None,
        "finish_delta_days": _days(_get(p, "finish"), _get(c, "finish")) if c is not None and p is not None else None,
        "progress_delta": round((_get(c, "percent_complete") or 0) - (_get(p, "percent_complete") or 0), 2)
        if c is not None and p is not None else None,
        "old_status": status[0] if status else None,
        "new_status": status[1] if status else None,
    }
    if rec["start_delta_days"] == 0:
        rec["start_delta_days"] = None
    if rec["finish_delta_days"] == 0:
        rec["finish_delta_days"] = None
    if rec["progress_delta"] == 0:
        rec["progress_delta"] = None
    return rec


def diff_vs_baseline(current: list[Any]) -> list[dict[str, Any]]:
    """Per-task slippage against the task's own baseline (or frozen-first-snapshot dates)."""
    out = []
    for t in current:
        if (_get(t, "outline_level") or 0) == 0:
            continue
        bs, bf = _get(t, "baseline_start"), _get(t, "baseline_finish")
        s, f = _get(t, "start"), _get(t, "finish")
        sd, fd = _days(bs, s), _days(bf, f)
        if not bf and not bs:
            continue
        if not sd and not fd:
            continue
        out.append({
            "task_unique_id": _get(t, "unique_id"), "base_unique_id": _get(t, "unique_id"),
            "match_method": "uid", "match_score": 100.0, "change_type": "date_moved",
            "task_name": _get(t, "name") or "", "track_id": _get(t, "track_id"),
            "is_milestone": bool(_get(t, "is_mapped_milestone") or _get(t, "is_milestone")),
            "changes": {"start": {"old": _ser(bs), "new": _ser(s)}, "finish": {"old": _ser(bf), "new": _ser(f)}},
            "start_delta_days": sd or None, "finish_delta_days": fd or None, "progress_delta": None,
            "old_status": None, "new_status": None,
        })
    return out


def detect_rebaseline(current: list[Any], previous: list[Any]) -> bool:
    """True when ≥10 % of matched tasks with baselines in both snapshots changed baseline
    finish, or a baseline appeared where there was none."""
    both = changed = appeared = 0
    for c, p, _method, _score in match_tasks(current, previous):
        if c is None or p is None:
            continue
        cb, pb = _get(c, "baseline_finish"), _get(p, "baseline_finish")
        if cb and pb:
            both += 1
            if cb != pb:
                changed += 1
        elif cb and not pb:
            appeared += 1
    if both and changed / both >= 0.10:
        return True
    return appeared > 0 and appeared >= max(1, both * 0.10)
