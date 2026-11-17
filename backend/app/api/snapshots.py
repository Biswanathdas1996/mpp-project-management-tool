from __future__ import annotations

import asyncio
import json
import time
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import progress
from ..audit import audit
from ..config import get_settings
from ..db import get_db, session_scope
from ..models import Snapshot, SnapshotStatus, User
from ..queue import enqueue
from ..security import get_program_for_user, require_admin, require_editor, require_viewer
from ..services.pipeline import create_snapshot_from_upload
from ..storage import get_storage
from .common import get_snapshot_for_user

router = APIRouter(tags=["snapshots"])


def snapshot_out(s: Snapshot) -> dict:
    disc = (s.profile or {}).get("discovery") or {}
    return {"id": s.id, "program_id": s.program_id, "version_no": s.version_no,
            "as_of": s.as_of_date.isoformat() if s.as_of_date else None, "as_of_source": s.as_of_source,
            "filename": s.filename, "file_size": s.file_size, "file_hash": s.file_hash, "file_format": s.file_format,
            "status": s.status, "status_message": s.status_message, "error_report": s.error_report,
            "warnings": s.warnings or [], "task_count": s.task_count, "has_baseline": s.has_baseline,
            "planned_method": s.planned_method_used, "rebaselined": s.rebaselined,
            "kpi_engine_version": s.kpi_engine_version, "mapping_config_id": s.mapping_config_id,
            "uploaded_at": s.uploaded_at.isoformat(), "processed_at": s.processed_at.isoformat() if s.processed_at else None,
            "project": s.project_props or {}, "discovery_source": disc.get("source")}


def _parse_date(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(422, f"Invalid as-of date '{v}' (use YYYY-MM-DD)") from None


@router.post("/programs/{program_id}/snapshots", status_code=202)
async def upload_snapshots(program_id: int, request: Request, files: list[UploadFile] = File(...),
                           as_of: list[str] | None = Form(default=None), password: str | None = Form(default=None),
                           user: User = Depends(require_editor), db: Session = Depends(get_db)):
    """Single or bulk upload. ``as_of`` may be given once (applies to all) or once per file."""
    program = get_program_for_user(db, program_id, user)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    as_of = [a for a in (as_of or [])]
    if as_of and len(as_of) not in (1, len(files)):
        raise HTTPException(422, "Provide one as-of date, or one per file")
    results = []
    for i, f in enumerate(files):
        d = _parse_date(as_of[i] if len(as_of) == len(files) else (as_of[0] if as_of else None))
        data = await f.read(max_bytes + 1)
        try:
            snap = create_snapshot_from_upload(db, program, user, f.filename or "plan.mpp", data, d, password or None,
                                               max_bytes)
            results.append({"filename": f.filename, "ok": True, "snapshot": snapshot_out(snap)})
        except HTTPException as exc:
            db.rollback()
            results.append({"filename": f.filename, "ok": False, "status_code": exc.status_code, "error": exc.detail})
    if len(files) == 1 and not results[0]["ok"]:
        raise HTTPException(results[0]["status_code"], results[0]["error"])
    return {"results": results}


@router.get("/programs/{program_id}/snapshots")
def list_snapshots(program_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    get_program_for_user(db, program_id, user)
    snaps = db.scalars(select(Snapshot).where(Snapshot.program_id == program_id)
                       .order_by(Snapshot.as_of_date.desc().nullsfirst(), Snapshot.version_no.desc()))
    return [snapshot_out(s) for s in snaps]


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: int, user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    snap, _ = get_snapshot_for_user(db, snapshot_id, user)
    out = snapshot_out(snap)
    out["profile"] = snap.profile or {}
    out["calendars"] = snap.calendars or []
    out["custom_field_defs"] = snap.custom_field_defs or []
    return out


@router.get("/snapshots/{snapshot_id}/file")
def download_original(snapshot_id: int, request: Request, user: User = Depends(require_editor), db: Session = Depends(get_db)):
    snap, program = get_snapshot_for_user(db, snapshot_id, user)
    audit(db, "snapshot.download", user=user, entity_type="snapshot", entity_id=snap.id, program_id=program.id,
          request=request)
    db.commit()
    return Response(get_storage().get(snap.storage_key), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{snap.filename}"'})


@router.post("/snapshots/{snapshot_id}/reprocess", status_code=202)
def reprocess(snapshot_id: int, request: Request, password: str | None = Form(default=None),
              user: User = Depends(require_editor), db: Session = Depends(get_db)):
    """Re-run parsing (e.g. after supplying a password for a protected file)."""
    snap, program = get_snapshot_for_user(db, snapshot_id, user)
    if snap.status in (SnapshotStatus.parsing.value, SnapshotStatus.processing.value):
        raise HTTPException(409, "Snapshot is already being processed")
    snap.status = SnapshotStatus.queued.value
    snap.error_report = None
    audit(db, "snapshot.reprocess", user=user, entity_type="snapshot", entity_id=snap.id, program_id=program.id,
          request=request)
    db.commit()
    pr = progress.Progress(snap.id, f"v{snap.version_no} {snap.filename}")
    pr.info("queue", f"Reprocessing requested by {user.email}; queued", pct=3)
    snap.job_id = enqueue("app.jobs.process_snapshot_job", snap.id, password or None)
    db.commit()
    return snapshot_out(snap)


_ACTIVE = {SnapshotStatus.queued.value, SnapshotStatus.parsing.value, SnapshotStatus.processing.value}


@router.get("/snapshots/{snapshot_id}/events")
def snapshot_events(snapshot_id: int, after: int = 0, user: User = Depends(require_viewer),
                    db: Session = Depends(get_db)):
    """Processing log recorded so far (JSON). The UI uses the stream below; this is for polling/debugging."""
    snap, _ = get_snapshot_for_user(db, snapshot_id, user)
    return {"status": snap.status, "events": progress.read_since(snapshot_id, after)}


@router.get("/snapshots/{snapshot_id}/events/stream")
def stream_snapshot_events(snapshot_id: int, request: Request, after: int = 0,
                           user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    """Server-Sent Events: replays the processing log, then pushes new events as the job emits them.

    Event types: ``progress`` (one pipeline event), ``reset`` (a new processing run replaced the log),
    ``end`` (processing finished; the stream closes). A comment heartbeat is sent every 15 s.
    """
    get_snapshot_for_user(db, snapshot_id, user)
    db.close()  # don't hold a DB connection for the life of the stream

    def status_now() -> str | None:
        with session_scope() as s:
            row = s.get(Snapshot, snapshot_id)
            return row.status if row else None

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

    async def gen():
        last_seq, run = after, None
        last_send = last_status_check = time.monotonic()
        max_seconds = get_settings().job_timeout_seconds + 120
        started = time.monotonic()
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                return
            events = await asyncio.to_thread(progress.read_since, snapshot_id, 0)
            if events and run is not None and events[0].get("run") != run:
                last_seq = 0  # buffer was replaced by a new run
                yield sse("reset", {"run": events[0].get("run")})
            if events:
                run = events[0].get("run")
            final = False
            for e in events:
                if e["seq"] > last_seq:
                    last_seq = e["seq"]
                    yield sse("progress", e)
                    last_send = time.monotonic()
                    final = final or bool((e.get("data") or {}).get("final"))
            if final:
                yield sse("end", {"status": await asyncio.to_thread(status_now)})
                return
            now = time.monotonic()
            if now - last_status_check > 2:
                # job finished without a final event (e.g. server restart lost the in-memory log)
                last_status_check = now
                st = await asyncio.to_thread(status_now)
                if st is None or (st not in _ACTIVE and now - last_send > 3):
                    yield sse("end", {"status": st})
                    return
            if now - started > max_seconds:
                yield sse("end", {"status": "timeout"})
                return
            if now - last_send > 15:
                last_send = now
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


@router.delete("/snapshots/{snapshot_id}", status_code=204)
def delete_snapshot(snapshot_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Snapshots are immutable; an admin may only remove one entirely (audited)."""
    snap, program = get_snapshot_for_user(db, snapshot_id, user)
    key = snap.storage_key
    audit(db, "snapshot.delete", user=user, entity_type="snapshot", entity_id=snap.id, program_id=program.id,
          request=request, details={"filename": snap.filename, "version_no": snap.version_no})
    db.delete(snap)
    db.commit()
    try:
        get_storage().delete(key)
    except Exception:
        pass
    enqueue("app.jobs.recompute_program_job", program.id)
