"""Generate a realistic weekly series of MS Project schedules (MSPDI .xml) for UAT / smoke tests.

The files are genuine MS Project XML written by MPXJ — MS Project opens them natively and PMA parses
them through exactly the same MPXJ path as .mpp uploads.  They model a 7-track programme over four
weekly status dates with progress, slippage on two tracks, one task added, one renamed and one
removed, so every dashboard element, diff type and KPI family is exercised.

Usage:  python scripts/generate_sample_plans.py [output_dir]
"""
from __future__ import annotations

import sys
import zlib
from datetime import date, timedelta
from pathlib import Path

import jpype
import jpype.imports  # noqa: F401
import mpxj  # noqa: F401

if not jpype.isJVMStarted():
    jpype.startJVM(convertStrings=True)

from java.lang import Double, Integer  # noqa: E402
from java.time import LocalDateTime  # noqa: E402
from org.mpxj import ConstraintType, Duration, ProjectFile, Relation, RelationType, TimeUnit  # noqa: E402
from org.mpxj.mspdi import MSPDIWriter  # noqa: E402

START = date(2026, 6, 1)
STATUS_DATES = [date(2026, 10, 19), date(2026, 10, 26), date(2026, 11, 2), date(2026, 11, 9)]

# track name, performance factor (actual vs plan), weekly slip (days), phases[(phase, [(task, dur_days, resource)])]
TRACKS = [
    ("Programme Governance & PMO", 1.0, 0, [
        ("Mobilisation", [("Programme charter", 10, "PMO Lead"), ("Governance framework", 10, "PMO Lead"),
                          ("Steering committee setup", 5, "Programme Director")]),
        ("Steady-state PMO", [("Reporting cadence & dashboards", 15, "PMO Analyst"),
                              ("Benefits realisation plan", 20, "PMO Lead"), ("Quarterly assurance review", 10, "PMO Analyst")]),
    ]),
    ("Infrastructure & Cloud", 0.97, 0, [
        ("Landing zone", [("Cloud tenancy & networking", 15, "Cloud Architect"), ("Identity & access baseline", 10, "Security Engineer"),
                          ("Landing zone hardening", 10, "Cloud Architect")]),
        ("Environments", [("Dev/Test environments", 15, "DevOps Engineer"), ("Pre-production environment", 15, "DevOps Engineer"),
                          ("Production environment", 20, "Cloud Architect")]),
    ]),
    ("Core Platform Development", 0.82, 3, [
        ("Foundation services", [("Platform architecture", 15, "Solution Architect"), ("API gateway", 20, "Backend Developer"),
                                 ("Case management service", 30, "Backend Developer")]),
        ("Business services", [("Payments integration", 25, "Backend Developer"), ("Notifications service", 15, "Backend Developer"),
                               ("Workflow engine", 30, "Solution Architect")]),
        ("Release 1", [("System integration testing", 20, "QA Lead"), ("Performance testing", 10, "QA Lead"),
                       ("Release 1 go-live readiness", 5, "Programme Director")]),
    ]),
    ("Data & Analytics", 0.9, 1, [
        ("Data platform", [("Data lake build", 25, "Data Engineer"), ("Master data model", 20, "Data Architect")]),
        ("Insights", [("Executive KPI reports", 20, "Data Engineer"), ("Self-service analytics", 25, "Data Architect")]),
    ]),
    ("Citizen Services Portal", 0.62, 4, [
        ("Design", [("Service design research", 15, "UX Designer"), ("Information architecture", 10, "UX Designer"),
                    ("Visual design system", 15, "UX Designer")]),
        ("Build", [("Portal front-end", 30, "Frontend Developer"), ("Bilingual EN/AR content", 20, "Content Lead"),
                   ("Accessibility remediation", 10, "Frontend Developer")]),
    ]),
    ("Change Management & Training", 1.05, 0, [
        ("Change readiness", [("Stakeholder analysis", 10, "Change Lead"), ("Change impact assessment", 15, "Change Lead")]),
        ("Training", [("Training needs analysis", 10, "Training Lead"), ("Train-the-trainer", 15, "Training Lead"),
                      ("End-user training", 25, "Training Lead")]),
    ]),
    ("Security & Compliance Accreditation", 1.0, 0, [
        ("Accreditation", [("Security accreditation pack", 20, "Security Engineer"), ("Penetration test", 10, "Security Engineer"),
                           ("Accreditation board", 5, "Programme Director")]),
    ]),
]
TRACK_OFFSETS = [0, 5, 20, 35, 30, 60, 175]  # working-day offset of each track start from programme start
RATES = {"PMO Lead": 120, "PMO Analyst": 80, "Programme Director": 200, "Cloud Architect": 160, "Security Engineer": 150,
         "DevOps Engineer": 130, "Solution Architect": 170, "Backend Developer": 110, "QA Lead": 100,
         "Data Engineer": 115, "Data Architect": 150, "UX Designer": 105, "Frontend Developer": 105,
         "Content Lead": 85, "Change Lead": 110, "Training Lead": 90}
EMAILS = {n: n.lower().replace(" ", ".") + "@example.org" for n in RATES}


def stable_uid(task, *key: str) -> None:
    """MS Project never renumbers Unique IDs; mimic that so snapshots match by UID like real files."""
    task.setUniqueID(Integer(1000 + zlib.crc32("|".join(key).encode()) % 900000))


def add_workdays(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    while n != 0:
        d += timedelta(days=step)
        if d.weekday() < 5:
            n -= step
    return d


def ldt(d: date, h: int = 8) -> LocalDateTime:
    return LocalDateTime.of(d.year, d.month, d.day, h, 0)


def dur(days: float):
    return Duration.getInstance(float(days), TimeUnit.DAYS)


def work(hours: float):
    return Duration.getInstance(float(hours), TimeUnit.HOURS)


def lin(s: date, f: date, d: date) -> float:
    if d < s:
        return 0.0
    if d >= f:
        return 100.0
    return 100.0 * (d - s).days / max((f - s).days, 1)


def build(version: int, status: date, out: Path) -> None:
    pf = ProjectFile()
    cal = pf.addDefaultBaseCalendar()
    pf.setDefaultCalendar(cal)
    props = pf.getProjectProperties()
    props.setProjectTitle("National Digital Services Programme")
    props.setStartDate(ldt(START))
    props.setStatusDate(ldt(status, 17))
    props.setCompany("Ministry of Digital Government")
    props.setManager("Programme Director")
    props.setCurrencySymbol("$")

    resources = {}
    for name, rate in RATES.items():
        r = pf.addResource()
        r.setName(name)
        r.setEmailAddress(EMAILS[name])
        resources[name] = r

    weeks = version - 1
    prev_leaf = None
    all_leaf_records = []
    for ti, (tname, factor, slip_per_week, phases) in enumerate(TRACKS):
        ttask = pf.addTask()
        stable_uid(ttask, tname)
        ttask.setName(tname)
        ttask.setText(1, tname)
        cursor = add_workdays(START, TRACK_OFFSETS[ti])
        slip = slip_per_week * (weeks + 2)  # slippage accumulates on weak tracks
        track_leaves = []
        prev_in_track = None
        for pi, (pname, tasks) in enumerate(phases):
            ptask = ttask.addTask()
            stable_uid(ptask, tname, pname)
            ptask.setName(pname)
            ptask.setText(1, tname)
            phase_leaves = []
            task_list = list(tasks)
            # --- scenario changes across snapshots
            if tname == "Citizen Services Portal" and pname == "Build" and version >= 3:
                task_list.append(("WCAG AA accessibility audit", 5, "UX Designer"))  # added in v3
            if tname == "Data & Analytics" and pname == "Insights" and version >= 4:
                task_list = [t for t in task_list if t[0] != "Self-service analytics"]  # removed in v4
            for (lname, d, res) in task_list:
                orig_name = lname
                if version >= 2 and lname == "Bilingual EN/AR content":
                    lname = "Bilingual English/Arabic content"  # renamed in v2
                bs = cursor
                bf = add_workdays(bs, d - 1)
                cursor = add_workdays(bf, 1)
                s = add_workdays(bs, slip if bs > status - timedelta(days=60) else 0)
                f = add_workdays(s, d - 1 + (slip if factor < 0.9 else 0))
                planned = lin(bs, bf, status)
                pct = max(0.0, min(100.0, round(planned * factor + (2 * weeks if factor >= 1 else 0), 0)))
                if lin(s, f, status) == 0:
                    pct = 0.0
                if f < status and factor >= 0.95:
                    pct = 100.0
                t = ptask.addTask()
                stable_uid(t, tname, pname, orig_name)
                t.setName(lname)
                t.setText(1, tname)
                t.setStart(ldt(s))
                t.setFinish(ldt(f, 17))
                t.setDuration(dur((f - s).days * 5 / 7 + 1))
                t.setBaselineStart(ldt(bs))
                t.setBaselineFinish(ldt(bf, 17))
                t.setBaselineDuration(dur(d))
                t.setPercentageComplete(Double(pct))
                if pct > 0:
                    t.setActualStart(ldt(s))
                if pct >= 100:
                    t.setActualFinish(ldt(f, 17))
                hours = d * 8.0
                rate = RATES[res]
                t.setWork(work(hours))
                t.setBaselineWork(work(hours))
                t.setActualWork(work(hours * pct / 100))
                t.setRemainingWork(work(hours * (100 - pct) / 100))
                t.setBaselineCost(Double(hours * rate))
                overrun = 1.0 if factor >= 0.9 else 1.18
                t.setCost(Double(hours * rate * overrun))
                t.setActualCost(Double(hours * rate * pct / 100 * overrun))
                crit = tname in ("Core Platform Development", "Citizen Services Portal")
                t.setCritical(crit)
                t.setTotalSlack(dur(-2 if (crit and factor < 0.7) else 0 if crit else 8 + ti))
                t.setFreeSlack(dur(0 if crit else 3))
                if lname == "Release 1 go-live readiness":
                    t.setDeadline(ldt(add_workdays(bf, 5), 17))
                if lname == "Accreditation board":
                    t.setConstraintType(ConstraintType.START_NO_EARLIER_THAN)
                    t.setConstraintDate(ldt(bs))
                a = t.addResourceAssignment(resources[res])
                a.setWork(work(hours))
                a.setActualWork(work(hours * pct / 100))
                a.setRemainingWork(work(hours * (100 - pct) / 100))
                a.setStart(ldt(s))
                a.setFinish(ldt(f, 17))
                if prev_in_track is not None:
                    t.addPredecessor(Relation.Builder().predecessorTask(prev_in_track).type(RelationType.FINISH_START)
                                     .lag(dur(0)))
                prev_in_track = t
                phase_leaves.append((t, s, f, bs, bf, pct, d))
            # phase-end milestone (zero duration, MS Project milestone flag)
            ms = ptask.addTask()
            stable_uid(ms, tname, pname, "milestone")
            ms.setName(f"{pname} complete")
            ms.setText(1, tname)
            last = phase_leaves[-1]
            ms.setMilestone(True)
            ms.setStart(ldt(last[2], 17))
            ms.setFinish(ldt(last[2], 17))
            ms.setDuration(dur(0))
            ms.setBaselineStart(ldt(last[4], 17))
            ms.setBaselineFinish(ldt(last[4], 17))
            ms.setBaselineDuration(dur(0))
            done = all(x[5] >= 100 for x in phase_leaves)
            ms.setPercentageComplete(Double(100.0 if done else 0.0))
            if done:
                ms.setActualStart(ldt(last[2], 17))
                ms.setActualFinish(ldt(last[2], 17))
            ms.addPredecessor(Relation.Builder().predecessorTask(last[0]).type(RelationType.FINISH_START).lag(dur(0)))
            _summarise(ptask, phase_leaves)
            track_leaves.extend(phase_leaves)
        _summarise(ttask, track_leaves)
        all_leaf_records.extend(track_leaves)
        if prev_leaf is not None and ti == 2:
            first_core = track_leaves[0][0]
            first_core.addPredecessor(Relation.Builder().predecessorTask(prev_leaf).type(RelationType.FINISH_START)
                                      .lag(dur(0)))
        prev_leaf = track_leaves[-1][0]
    pf.getProjectProperties().setFinishDate(ldt(max(r[2] for r in all_leaf_records), 17))
    out.parent.mkdir(parents=True, exist_ok=True)
    MSPDIWriter().write(pf, str(out))


def _summarise(task, leaves):
    s = min(x[1] for x in leaves)
    f = max(x[2] for x in leaves)
    bs = min(x[3] for x in leaves)
    bf = max(x[4] for x in leaves)
    total = sum(x[6] for x in leaves)
    pct = sum(x[5] * x[6] for x in leaves) / total if total else 0
    task.setStart(ldt(s))
    task.setFinish(ldt(f, 17))
    task.setBaselineStart(ldt(bs))
    task.setBaselineFinish(ldt(bf, 17))
    task.setDuration(dur((f - s).days * 5 / 7 + 1))
    task.setBaselineDuration(dur(total))
    task.setPercentageComplete(Double(round(pct, 1)))
    if pct > 0:
        task.setActualStart(ldt(s))


if __name__ == "__main__":
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "samples")
    for i, sd in enumerate(STATUS_DATES, start=1):
        p = out_dir / f"NDSP_status_{sd.isoformat()}.xml"
        build(i, sd, p)
        print("wrote", p)
