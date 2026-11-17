"""Tenant settings & branding (v2 multi-tenant), AI settings per tenant, platform tenant admin."""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.provider import get_provider
from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..models import Program, Tenant, User
from ..security import (Email, find_user_by_email, get_program_for_user, hash_password, require_admin,
                        require_platform_admin, require_viewer, validate_password_strength)
from ..storage import get_storage

router = APIRouter(tags=["tenant"])
LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "image/webp": "webp"}
WHICH = ("client_logo", "vendor_logo")


class TenantUpdate(BaseModel):
    name: str | None = None
    name_ar: str | None = None
    branding: dict | None = None  # primary_color, support_email, contact_url, location
    ai_mode: Literal["off", "self_hosted", "cloud"] | None = None
    ai_model: str | None = None
    ai_redact: bool | None = None


def tenant_out(t: Tenant) -> dict:
    s = get_settings()
    return {"id": t.id, "name": t.name, "name_ar": t.name_ar, "slug": t.slug,
            "branding": {k: v for k, v in (t.branding or {}).items() if k not in WHICH},
            "has_client_logo": bool((t.branding or {}).get("client_logo")),
            "has_vendor_logo": bool((t.branding or {}).get("vendor_logo")),
            "ai_mode": t.ai_mode, "ai_model": t.ai_model or s.ai_default_model, "ai_redact": t.ai_redact,
            "cloud_available": bool(s.ollama_cloud_api_key), "is_active": t.is_active}


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_branding(b: dict) -> dict:
    out = {}
    for k in ("primary_color", "support_email", "contact_url", "location"):
        if k in b and b[k] is not None:
            v = str(b[k]).strip()[:300]
            if k == "primary_color" and v and not _HEX.match(v):
                raise HTTPException(422, "primary_color must be #RRGGBB")
            out[k] = v
    return out


@router.get("/tenant")
def get_tenant(user: User = Depends(require_viewer)):
    return tenant_out(user.tenant)


@router.patch("/tenant")
def update_tenant(body: TenantUpdate, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = admin.tenant
    ch = body.model_dump(exclude_unset=True)
    if body.name:
        t.name = body.name
    if "name_ar" in ch:
        t.name_ar = body.name_ar
    if body.branding is not None:
        t.branding = {**{k: v for k, v in (t.branding or {}).items() if k in WHICH}, **_clean_branding(body.branding)}
    if body.ai_mode:
        if body.ai_mode == "cloud" and not get_settings().ollama_cloud_api_key:
            raise HTTPException(400, "Ollama Cloud API key is not configured on the server")
        t.ai_mode = body.ai_mode
    if "ai_model" in ch:
        t.ai_model = body.ai_model or None
    if body.ai_redact is not None:
        t.ai_redact = body.ai_redact
    audit(db, "tenant.update", user=admin, entity_type="tenant", entity_id=t.id, request=request, details=ch)
    db.commit()
    return tenant_out(t)


@router.get("/tenant/ai-health")
def ai_health(user: User = Depends(require_admin)):
    return get_provider(user.tenant.ai_mode).health()


def _save_logo(owner: str, oid: int, which: str, file: UploadFile) -> str:
    if which not in WHICH:
        raise HTTPException(404, "Unknown logo")
    ext = LOGO_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(415, "Logo must be PNG, JPEG, SVG or WebP")
    data = file.file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(413, "Logo must be ≤ 2 MB")
    if ext == "svg" and (b"<script" in data.lower() or b"javascript:" in data.lower()):
        raise HTTPException(422, "SVG contains script")
    key = f"branding/{owner}-{oid}/{which}.{ext}"
    get_storage().put(key, data, file.content_type)
    return f"{key}|{file.content_type}"


@router.post("/tenant/logo/{which}")
def upload_tenant_logo(which: str, request: Request, file: UploadFile = File(...), admin: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    t = admin.tenant
    t.branding = {**(t.branding or {}), which: _save_logo("tenant", t.id, which, file)}
    audit(db, "tenant.logo", user=admin, entity_type="tenant", entity_id=t.id, request=request, details={"which": which})
    db.commit()
    return tenant_out(t)


@router.post("/programs/{program_id}/logo/{which}")
def upload_program_logo(program_id: int, which: str, request: Request, file: UploadFile = File(...),
                        admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = get_program_for_user(db, program_id, admin)
    p.branding = {**(p.branding or {}), which: _save_logo("program", p.id, which, file)}
    audit(db, "program.logo", user=admin, entity_type="program", entity_id=p.id, program_id=p.id, request=request)
    db.commit()
    return {"ok": True}


@router.delete("/programs/{program_id}/logo/{which}")
def delete_program_logo(program_id: int, which: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = get_program_for_user(db, program_id, admin)
    p.branding = {k: v for k, v in (p.branding or {}).items() if k != which}
    db.commit()
    return {"ok": True}


@router.get("/branding/{owner}/{oid}/{which}")
def get_logo(owner: str, oid: int, which: str, db: Session = Depends(get_db)):
    """Logos are public assets (rendered in <img> tags and on the login page)."""
    if which not in WHICH or owner not in ("tenants", "programs"):
        raise HTTPException(404)
    obj = db.get(Tenant if owner == "tenants" else Program, oid)
    ref = (obj.branding or {}).get(which) if obj else None
    if not ref:
        raise HTTPException(404)
    key, ctype = ref.split("|", 1)
    return Response(get_storage().get(key), media_type=ctype,
                    headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff",
                             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


# ------------------------------------------------------------------------------- platform (multi-tenant)
class TenantCreate(BaseModel):
    name: str
    name_ar: str | None = None
    slug: str
    admin_email: Email
    admin_password: str
    admin_name: str = ""


@router.get("/platform/tenants")
def list_tenants(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return [tenant_out(t) for t in db.scalars(select(Tenant).order_by(Tenant.name))]


@router.post("/platform/tenants", status_code=201)
def create_tenant(body: TenantCreate, request: Request, padmin: User = Depends(require_platform_admin),
                  db: Session = Depends(get_db)):
    slug = re.sub(r"[^a-z0-9-]", "-", body.slug.lower()).strip("-")
    if not slug or db.scalar(select(Tenant).where(Tenant.slug == slug)):
        raise HTTPException(409, "Slug already in use")
    if find_user_by_email(db, body.admin_email):
        raise HTTPException(409, "Admin email already in use")
    validate_password_strength(body.admin_password)
    t = Tenant(name=body.name, name_ar=body.name_ar, slug=slug, branding={}, ai_mode="off")
    db.add(t)
    db.flush()
    db.add(User(tenant_id=t.id, email=body.admin_email.lower(), full_name=body.admin_name, role="admin",
                password_hash=hash_password(body.admin_password)))
    audit(db, "platform.tenant_create", user=padmin, entity_type="tenant", entity_id=t.id, request=request,
          details={"slug": slug})
    db.commit()
    return tenant_out(t)


@router.patch("/platform/tenants/{tenant_id}")
def toggle_tenant(tenant_id: int, body: dict, request: Request, padmin: User = Depends(require_platform_admin),
                  db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(404)
    if "is_active" in body:
        if t.id == padmin.tenant_id and not body["is_active"]:
            raise HTTPException(400, "Cannot disable your own tenant")
        t.is_active = bool(body["is_active"])
    audit(db, "platform.tenant_update", user=padmin, entity_type="tenant", entity_id=t.id, request=request, details=body)
    db.commit()
    return tenant_out(t)
