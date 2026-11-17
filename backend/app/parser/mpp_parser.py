"""MS Project parser: Python + MPXJ via JPype (decision recorded in docs/PROJECT_PLAN.md §3).

Reads .mpp (MPP8/9/12/14 — Project 98..2021+), .mpt, .mpx, MSPDI .xml and the other formats
MPXJ's UniversalProjectReader understands.  Password-protected .mpp files are read when the
uploader supplies the password; otherwise a structured parse-error report is returned.

Output is a plain-Python ``ParsedPlan`` so the rest of the system never touches Java objects.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..config import get_settings
from ..progress import NullProgress, Progress

log = logging.getLogger(__name__)
_jvm_lock = threading.Lock()
_J: dict[str, Any] = {}


class ParseError(Exception):
    """Structured parse failure → becomes the snapshot's parse-error report."""

    def __init__(self, code: str, message: str, hint: str = "", detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.detail = detail

    def report(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "hint": self.hint, "detail": self.detail[:2000]}


@dataclass
class ParsedPlan:
    file_format: str
    props: dict[str, Any]
    tasks: list[dict[str, Any]]
    resources: list[dict[str, Any]] = field(default_factory=list)
    assignments: list[dict[str, Any]] = field(default_factory=list)
    calendars: list[dict[str, Any]] = field(default_factory=list)
    custom_field_defs: list[dict[str, Any]] = field(default_factory=list)
    populated_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------------------------
# JVM bootstrap
# ----------------------------------------------------------------------------------------------
def _jvm() -> dict[str, Any]:
    if _J:
        return _J
    with _jvm_lock:
        if _J:
            return _J
        import jpype
        import jpype.imports  # noqa: F401  (enables java package imports)

        try:
            import mpxj  # noqa: F401  (adds the MPXJ jars to the classpath)
        except ImportError as exc:  # pragma: no cover
            raise ParseError("parser_unavailable", "MPXJ is not installed on the server",
                             "Install the 'mpxj' Python package and a Java 11+ runtime.") from exc
        if not jpype.isJVMStarted():
            jpype.startJVM(f"-Xmx{get_settings().jvm_max_heap}", "-Djava.awt.headless=true",
                           convertStrings=True)
        pkg = None
        for candidate in ("org.mpxj", "net.sf.mpxj"):
            try:
                jpype.JClass(f"{candidate}.reader.UniversalProjectReader")
                pkg = candidate
                break
            except Exception:
                continue
        if pkg is None:
            raise ParseError("parser_unavailable", "MPXJ classes could not be loaded")
        J = jpype.JClass
        _J.update(
            pkg=pkg,
            UniversalProjectReader=J(f"{pkg}.reader.UniversalProjectReader"),
            MPPReader=J(f"{pkg}.mpp.MPPReader"),
            TimeUnit=J(f"{pkg}.TimeUnit"),
            MPXJException=J(f"{pkg}.MPXJException"),
            DayOfWeek=J("java.time.DayOfWeek"),
            JException=jpype.JException,
        )
        try:
            _J["MSPDIWriter"] = J(f"{pkg}.mspdi.MSPDIWriter")
            _J["ProjectFile"] = J(f"{pkg}.ProjectFile")
            _J["Duration"] = J(f"{pkg}.Duration")
            _J["RelationType"] = J(f"{pkg}.RelationType")
            _J["TaskField"] = J(f"{pkg}.TaskField")
        except Exception:  # pragma: no cover
            pass
        log.info("MPXJ loaded from package %s", pkg)
        return _J


def mpxj_classes() -> dict[str, Any]:
    return _jvm()


# ----------------------------------------------------------------------------------------------
# Value converters (handle both java.time and legacy java.util.Date MPXJ versions)
# ----------------------------------------------------------------------------------------------
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _d(value: Any) -> date | None:
    if value is None:
        return None
    try:
        s = str(value.toString())
    except Exception:
        s = str(value)
    m = _ISO.match(s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if hasattr(value, "getTime"):
        return datetime.fromtimestamp(int(value.getTime()) / 1000).date()
    return None


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if hasattr(value, "doubleValue"):
            return float(value.doubleValue())
        if hasattr(value, "getAmount"):
            return float(value.getAmount())
        return float(value)
    except Exception:
        return None


def _s(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value)
    return s if s != "" else None


def _b(value: Any) -> bool:
    if value is None:
        return False
    try:
        return bool(value.booleanValue()) if hasattr(value, "booleanValue") else bool(value)
    except Exception:
        return False


def _call(obj: Any, *names: str) -> Any:
    for n in names:
        fn = getattr(obj, n, None)
        if fn is not None:
            try:
                return fn()
            except Exception:
                continue
    return None


class _Conv:
    def __init__(self, props: Any):
        self.props = props
        self.TU = _J["TimeUnit"]

    def days(self, dur: Any) -> float | None:
        if dur is None:
            return None
        try:
            return float(dur.convertUnits(self.TU.DAYS, self.props).getDuration())
        except Exception:
            return _f(_call(dur, "getDuration"))

    def hours(self, dur: Any) -> float | None:
        if dur is None:
            return None
        try:
            return float(dur.convertUnits(self.TU.HOURS, self.props).getDuration())
        except Exception:
            return None


# ----------------------------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------------------------
_CUSTOM_RE = re.compile(r"^(TEXT|NUMBER|FLAG|DATE|COST|DURATION|START|FINISH|OUTLINE_CODE)\d+$")


def _classify_exception(exc: Exception, has_password: bool) -> ParseError:
    msg = str(exc)
    low = msg.lower()
    if "password" in low or "encrypt" in low:
        if has_password:
            return ParseError("wrong_password", "The supplied password could not open this file.",
                              "Check the password and try again.", msg)
        return ParseError("password_protected", "This file is password protected.",
                          "Re-upload and provide the file password, or save an unprotected copy from MS Project.",
                          msg)
    if "unsupported" in low or "not supported" in low:
        return ParseError("unsupported_format", "This MS Project file version is not supported.",
                          "Save the plan from MS Project as .mpp (2007+) or as XML (MSPDI) and re-upload.",
                          msg)
    return ParseError("corrupt_file", "The file could not be parsed. It may be corrupt or truncated.",
                      "Open the file in MS Project, use Save As to create a clean copy, and re-upload.", msg)


def parse_plan_bytes(data: bytes, filename: str, password: str | None = None,
                     progress: Progress | None = None) -> ParsedPlan:
    suffix = os.path.splitext(filename)[1].lower() or ".mpp"
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return parse_plan_file(path, password, progress)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _attach_daemon() -> None:
    """Worker threads must attach to the JVM as daemons, otherwise JVM shutdown blocks process exit."""
    if threading.current_thread() is threading.main_thread():
        return
    try:
        import jpype

        jpype.JClass("java.lang.Thread").attachAsDaemon()
    except Exception:  # pragma: no cover
        pass


def _sniff(head: bytes) -> str:
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "OLE2 compound document (binary .mpp/.mpt)"
    if head.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
        return "XML document (MSPDI / PMXML)"
    if head.startswith(b"MPX"):
        return "MPX text file"
    return "unrecognised signature, letting MPXJ auto-detect"


def parse_plan_file(path: str, password: str | None = None, progress: Progress | None = None) -> ParsedPlan:
    pr = progress or NullProgress()
    t0 = time.monotonic()
    pr.info("parse", "Starting Java parser (MPXJ)", pct=6)
    J = _jvm()
    _attach_daemon()
    pr.info("parse", f"MPXJ ready (package {J['pkg']})", pct=8)
    size = os.path.getsize(path)
    if size == 0:
        raise ParseError("empty_file", "The uploaded file is empty.")
    with open(path, "rb") as fh:
        head = fh.read(16)
    is_ole = head.startswith(b"\xd0\xcf\x11\xe0")
    pr.info("parse", f"File signature: {_sniff(head)}", size=size)
    project = None
    try:
        if password and is_ole:
            pr.info("parse", "Opening password-protected file with MPPReader", pct=10)
            reader = J["MPPReader"]()
            reader.setReadPassword(password)
            project = reader.read(path)
        else:
            pr.info("parse", "Decoding file with UniversalProjectReader (large plans can take a while)", pct=10)
            project = J["UniversalProjectReader"]().read(path)
    except J["JException"] as exc:  # Java exception
        raise _classify_exception(exc, bool(password)) from None
    except Exception as exc:  # pragma: no cover
        raise _classify_exception(exc, bool(password)) from None
    if project is None:
        raise ParseError("unsupported_format", "The file is not a recognised project schedule.",
                         "Upload an MS Project .mpp, .mpt, .mpx or MSPDI .xml file.")
    pr.ok("parse", f"File decoded in {time.monotonic() - t0:.1f}s", pct=25)
    return _extract(project, pr)


def _extract(project: Any, pr: Progress | None = None) -> ParsedPlan:
    pr = pr or NullProgress()
    J = _J
    pp = project.getProjectProperties()
    conv = _Conv(pp)
    warnings: list[str] = []

    file_type = _s(_call(pp, "getFileType")) or "unknown"
    mpp_type = _s(_call(pp, "getMppFileType"))
    file_format = f"{file_type}{(' (MPP' + mpp_type + ')') if mpp_type and file_type.upper() == 'MPP' else ''}"

    props = {
        "title": _s(_call(pp, "getProjectTitle")) or _s(_call(pp, "getName")),
        "name": _s(_call(pp, "getName")),
        "author": _s(_call(pp, "getAuthor")),
        "manager": _s(_call(pp, "getManager")),
        "company": _s(_call(pp, "getCompany")),
        "start": _iso(_d(_call(pp, "getStartDate"))),
        "finish": _iso(_d(_call(pp, "getFinishDate"))),
        "status_date": _iso(_d(_call(pp, "getStatusDate"))),
        "current_date": _iso(_d(_call(pp, "getCurrentDate"))),
        "baseline_date": _iso(_d(_call(pp, "getBaselineDate"))),
        "currency_symbol": _s(_call(pp, "getCurrencySymbol")),
        "currency_code": _s(_call(pp, "getCurrencyCode")),
        "minutes_per_day": _f(_call(pp, "getMinutesPerDay")),
        "application": _s(_call(pp, "getFileApplication")),
        "last_saved": _iso(_d(_call(pp, "getLastSaved"))),
        "file_type": file_type,
    }
    pr.info("parse", f"Format: {file_format}"
            + (f", title \"{props['title']}\"" if props.get("title") else "")
            + (f", status date {props['status_date']}" if props.get("status_date") else ", no status date"),
            pct=27)

    # Custom field definitions (aliases)
    cf_defs: list[dict[str, Any]] = []
    alias_by_field: dict[str, str] = {}
    try:
        for cf in project.getCustomFields():
            ft = cf.getFieldType()
            alias = _s(cf.getAlias())
            if ft is None:
                continue
            fname = str(ft.name()) if hasattr(ft, "name") else str(ft)
            if alias:
                alias_by_field[fname] = alias
            cf_defs.append({"field": fname, "alias": alias,
                            "entity": str(ft.getFieldTypeClass()) if hasattr(ft, "getFieldTypeClass") else None})
    except Exception as exc:  # pragma: no cover
        warnings.append(f"Custom field definitions unreadable: {exc}")
        pr.warn("parse", f"Custom field definitions unreadable: {exc}")
    pr.info("parse", f"{len(cf_defs)} custom field definition(s), {len(alias_by_field)} with aliases", pct=28)

    # Which task fields are populated (feeds AI discovery profile)
    populated: list[str] = []
    custom_fields_to_read: list[Any] = []
    try:
        for ft in project.getTasks().getPopulatedFields():
            name = str(ft.name())
            populated.append(name)
            if _CUSTOM_RE.match(name):
                custom_fields_to_read.append(ft)
    except Exception:
        warnings.append("Populated-field detection unavailable in this MPXJ version; custom fields skipped.")
        pr.warn("parse", "Populated-field detection unavailable; custom fields skipped")
    populated.sort()
    pr.info("parse", f"{len(populated)} populated task fields, {len(custom_fields_to_read)} custom fields to read",
            pct=29)

    # Tasks
    tasks: list[dict[str, Any]] = []
    all_tasks = list(project.getTasks())
    total = len(all_tasks)
    pr.info("parse", f"Reading {total:,} tasks", pct=30, total=total)
    step = max(50, total // 10)  # ~10 progress lines for the task loop
    t_loop = time.monotonic()
    for idx, t in enumerate(all_tasks, 1):
        if idx % step == 0 and idx < total:
            pr.info("parse", f"Tasks {idx:,} / {total:,}", pct=30 + 30 * idx / total, done=idx, total=total)
        uid = t.getUniqueID()
        if uid is None:
            continue
        uid = int(uid)
        name = _s(t.getName())
        if uid == 0 and (name is None or t.getOutlineLevel() in (None, 0)):
            # Project summary task — keep it (it carries project-level baseline/cost) but flag level 0
            pass
        parent = t.getParentTask()
        preds = []
        for rel in (t.getPredecessors() or []):
            other = _call(rel, "getPredecessorTask", "getTargetTask")
            if other is None or other.getUniqueID() is None:
                continue
            preds.append({"uid": int(other.getUniqueID()), "type": _s(rel.getType()),
                          "lag_days": conv.days(rel.getLag())})
        succs = []
        for rel in (t.getSuccessors() or []):
            other = _call(rel, "getSuccessorTask", "getTargetTask")
            if other is None or other.getUniqueID() is None:
                continue
            succs.append({"uid": int(other.getUniqueID()), "type": _s(rel.getType()),
                          "lag_days": conv.days(rel.getLag())})
        resource_names = []
        for a in (t.getResourceAssignments() or []):
            r = a.getResource()
            if r is not None and _s(r.getName()):
                resource_names.append(_s(r.getName()))
        custom: dict[str, Any] = {}
        for ft in custom_fields_to_read:
            try:
                v = t.get(ft)
            except Exception:
                continue
            if v is None:
                continue
            fname = str(ft.name())
            key = alias_by_field.get(fname, fname.title().replace("_", ""))
            dv = _d(v) if fname.startswith(("DATE", "START", "FINISH")) else None
            if dv:
                custom[key] = dv.isoformat()
            elif fname.startswith("DURATION"):
                custom[key] = conv.days(v)
            elif fname.startswith(("NUMBER", "COST")):
                custom[key] = _f(v)
            elif fname.startswith("FLAG"):
                custom[key] = _b(v)
            else:
                custom[key] = _s(v)
        ctype = _s(t.getConstraintType())
        cal = t.getCalendar()
        notes = _s(_call(t, "getNotes"))
        pct = _f(t.getPercentageComplete()) or 0.0
        tasks.append({
            "unique_id": uid,
            "task_id": int(t.getID()) if t.getID() is not None else None,
            "parent_unique_id": int(parent.getUniqueID()) if parent is not None and parent.getUniqueID() is not None else None,
            "wbs": _s(t.getWBS()),
            "outline_number": _s(t.getOutlineNumber()),
            "outline_level": int(t.getOutlineLevel()) if t.getOutlineLevel() is not None else 0,
            "name": name or "",
            "is_summary": _b(t.getSummary()),
            "is_milestone": _b(t.getMilestone()),
            "is_active": True if _call(t, "getActive") is None else _b(_call(t, "getActive")),
            "is_critical": _b(_call(t, "getCritical")),
            "start": _d(t.getStart()),
            "finish": _d(t.getFinish()),
            "baseline_start": _d(t.getBaselineStart()),
            "baseline_finish": _d(t.getBaselineFinish()),
            "actual_start": _d(t.getActualStart()),
            "actual_finish": _d(t.getActualFinish()),
            "early_start": _d(_call(t, "getEarlyStart")),
            "late_start": _d(_call(t, "getLateStart")),
            "percent_complete": max(0.0, min(100.0, pct)),
            "physical_percent_complete": _f(_call(t, "getPhysicalPercentComplete")),
            "duration_days": conv.days(t.getDuration()),
            "baseline_duration_days": conv.days(t.getBaselineDuration()),
            "actual_duration_days": conv.days(t.getActualDuration()),
            "remaining_duration_days": conv.days(t.getRemainingDuration()),
            "work_hours": conv.hours(t.getWork()),
            "baseline_work_hours": conv.hours(t.getBaselineWork()),
            "actual_work_hours": conv.hours(t.getActualWork()),
            "remaining_work_hours": conv.hours(t.getRemainingWork()),
            "cost": _f(t.getCost()),
            "baseline_cost": _f(t.getBaselineCost()),
            "actual_cost": _f(t.getActualCost()),
            "remaining_cost": _f(t.getRemainingCost()),
            "bcws": _f(_call(t, "getBCWS")),
            "bcwp": _f(_call(t, "getBCWP")),
            "acwp": _f(_call(t, "getACWP")),
            "constraint_type": ctype,
            "constraint_date": _d(_call(t, "getConstraintDate")),
            "deadline": _d(_call(t, "getDeadline")),
            "total_slack_days": conv.days(_call(t, "getTotalSlack")),
            "free_slack_days": conv.days(_call(t, "getFreeSlack")),
            "predecessors": preds,
            "successors": succs,
            "resource_names": resource_names,
            "calendar_name": _s(cal.getName()) if cal is not None else None,
            "notes": notes[:8000] if notes else None,
            "custom_fields": custom,
        })

    pr.ok("parse", f"Read {len(tasks):,} tasks in {time.monotonic() - t_loop:.1f}s "
                   f"({sum(1 for x in tasks if x['is_summary']):,} summary, "
                   f"{sum(1 for x in tasks if x['is_milestone']):,} milestones, "
                   f"{sum(1 for x in tasks if x['baseline_finish']):,} with baseline)", pct=60)

    # Resources
    resources: list[dict[str, Any]] = []
    for r in project.getResources():
        if r.getUniqueID() is None or not _s(r.getName()):
            continue
        resources.append({
            "unique_id": int(r.getUniqueID()),
            "name": _s(r.getName()) or "",
            "type": _s(_call(r, "getType")),
            "group": _s(_call(r, "getGroup")),
            "email": _s(_call(r, "getEmailAddress")),
            "max_units": _f(_call(r, "getMaxUnits")),
            "standard_rate": _f(_call(r, "getStandardRate")),
            "work_hours": conv.hours(_call(r, "getWork")),
            "actual_work_hours": conv.hours(_call(r, "getActualWork")),
            "cost": _f(_call(r, "getCost")),
            "is_overallocated": _b(_call(r, "getOverAllocated")),
            "peak_units": _f(_call(r, "getPeakUnits")),
        })

    pr.info("parse", f"Read {len(resources):,} resources", pct=62)

    assignments: list[dict[str, Any]] = []
    for a in project.getResourceAssignments():
        task = a.getTask()
        if task is None or task.getUniqueID() is None:
            continue
        res = a.getResource()
        assignments.append({
            "task_unique_id": int(task.getUniqueID()),
            "resource_unique_id": int(res.getUniqueID()) if res is not None and res.getUniqueID() is not None else None,
            "units": _f(_call(a, "getUnits")),
            "work_hours": conv.hours(_call(a, "getWork")),
            "actual_work_hours": conv.hours(_call(a, "getActualWork")),
            "remaining_work_hours": conv.hours(_call(a, "getRemainingWork")),
            "cost": _f(_call(a, "getCost")),
            "start": _d(_call(a, "getStart")),
            "finish": _d(_call(a, "getFinish")),
        })

    pr.info("parse", f"Read {len(assignments):,} resource assignments", pct=64)

    calendars: list[dict[str, Any]] = []
    try:
        DOW = J["DayOfWeek"]
        for c in project.getCalendars():
            working = []
            for d in DOW.values():
                try:
                    if c.isWorkingDay(d):
                        working.append(str(d.name())[:3].title())
                except Exception:
                    pass
            exc_count = 0
            try:
                exc_count = int(c.getCalendarExceptions().size())
            except Exception:
                pass
            calendars.append({"name": _s(c.getName()), "unique_id": _f(c.getUniqueID()),
                              "working_days": working, "exceptions": exc_count})
    except Exception as exc:  # pragma: no cover
        warnings.append(f"Calendars unreadable: {exc}")
        pr.warn("parse", f"Calendars unreadable: {exc}")
    pr.info("parse", f"Read {len(calendars)} calendar(s)", pct=65)

    if not tasks:
        raise ParseError("no_tasks", "The file was read but contains no tasks.",
                         "Check that the correct plan was exported.")
    return ParsedPlan(file_format=file_format, props=props, tasks=tasks, resources=resources,
                      assignments=assignments, calendars=calendars, custom_field_defs=cf_defs,
                      populated_fields=populated, warnings=warnings)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None
