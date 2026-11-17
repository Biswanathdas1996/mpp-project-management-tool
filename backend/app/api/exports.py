from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..models import Program, Task, TaskDiff, User
from ..security import require_viewer
from ..services.context import diff_to_dict
from ..services.dashboard import build_dashboard
from ..services.export import export_excel, export_pdf, export_pptx
from ..storage import get_storage
from .analytics import snapshot_kpis, task_out
from .common import get_snapshot_for_user, require_ready

router = APIRouter(tags=["export"])
MEDIA = {"pdf": "application/pdf",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}


def _logos(program: Program) -> dict[str, bytes | None]:
    out: dict[str, bytes | None] = {}
    for which in ("client_logo", "vendor_logo"):
        ref = (program.branding or {}).get(which) or (program.tenant.branding or {}).get(which)
        out[which] = None
        if ref and not ref.split("|", 1)[1].endswith("svg+xml"):
            try:
                out[which] = get_storage().get(ref.split("|", 1)[0])
            except Exception:
                pass
    return out


@router.get("/snapshots/{snapshot_id}/export/{fmt}")
def export(snapshot_id: int, fmt: Literal["pdf", "xlsx", "pptx"], request: Request,
           user: User = Depends(require_viewer), db: Session = Depends(get_db)):
    snap, program = get_snapshot_for_user(db, snapshot_id, user)
    require_ready(snap)
    dash = build_dashboard(db, program, snap)
    kpis = snapshot_kpis(snapshot_id, all=False, user=user, db=db)["kpis"]
    if fmt == "pdf":
        data = export_pdf(dash, kpis, _logos(program))
    elif fmt == "pptx":
        data = export_pptx(dash, _logos(program))
    else:
        tasks = [task_out(t) for t in db.scalars(select(Task).where(Task.snapshot_id == snap.id).order_by(Task.task_id))]
        diffs = [diff_to_dict(d) for d in db.scalars(select(TaskDiff).where(TaskDiff.snapshot_id == snap.id,
                                                                            TaskDiff.compare_to == "previous"))]
        data = export_excel(dash, kpis, tasks, diffs)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", program.name).strip("_") or "program"
    fname = f"{safe}_dashboard_v{snap.version_no}_{snap.as_of_date}.{fmt}"
    audit(db, f"export.{fmt}", user=user, entity_type="snapshot", entity_id=snap.id, program_id=program.id,
          request=request)
    db.commit()
    return Response(data, media_type=MEDIA[fmt], headers={"Content-Disposition": f'attachment; filename="{fname}"'})
