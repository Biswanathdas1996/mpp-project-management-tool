from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..models import Tenant, User
from ..security import (
    Email,
    create_access_token,
    find_user_by_email,
    get_current_user,
    hash_password,
    oidc_build_login_url,
    oidc_exchange,
    oidc_role_from_claims,
    validate_password_strength,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
_attempts: dict[str, list[float]] = defaultdict(list)


class LoginIn(BaseModel):
    email: Email
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "tenant_id": u.tenant_id,
            "tenant_name": u.tenant.name, "tenant_name_ar": u.tenant.name_ar, "is_platform_admin": u.is_platform_admin,
            "locale": u.locale, "sso": u.password_hash is None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None, "is_active": u.is_active}


def _throttle(key: str) -> None:
    now = time.time()
    _attempts[key] = [t for t in _attempts[key] if now - t < 900]
    if len(_attempts[key]) >= 10:
        raise HTTPException(429, "Too many login attempts; try again in 15 minutes")


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '-'}:{body.email.lower()}"
    _throttle(key)
    user = find_user_by_email(db, body.email)
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        _attempts[key].append(time.time())
        audit(db, "auth.login_failed", details={"email": body.email.lower()}, request=request,
              tenant_id=user.tenant_id if user else None)
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    _attempts.pop(key, None)
    user.last_login_at = datetime.now(timezone.utc)
    audit(db, "auth.login", user=user, request=request)
    db.commit()
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/logout")
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1  # revokes every outstanding token for this user
    audit(db, "auth.logout", user=user, request=request)
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(body: PasswordChangeIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    validate_password_strength(body.new_password)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit(db, "auth.password_changed", user=user, request=request)
    db.commit()
    return {"access_token": create_access_token(user), "token_type": "bearer"}


@router.patch("/me")
def update_me(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if "locale" in body and body["locale"] in ("en", "ar"):
        user.locale = body["locale"]
    if "full_name" in body and isinstance(body["full_name"], str):
        user.full_name = body["full_name"][:200]
    db.commit()
    return user_out(user)


# ---------------------------------------------------------------------------------------- OIDC SSO
@router.get("/oidc/config")
def oidc_config():
    return {"enabled": settings.oidc_enabled and bool(settings.oidc_issuer and settings.oidc_client_id)}


@router.get("/oidc/login")
def oidc_login(tenant: str | None = None):
    if not settings.oidc_enabled:
        raise HTTPException(404, "SSO is not enabled")
    return RedirectResponse(oidc_build_login_url(tenant))


@router.get("/oidc/callback")
def oidc_callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    if not settings.oidc_enabled:
        raise HTTPException(404, "SSO is not enabled")
    claims, tenant_slug = oidc_exchange(code, state)
    email = (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").lower()
    if not email:
        raise HTTPException(400, "SSO identity has no email claim")
    user = db.scalar(select(User).where(User.oidc_subject == claims["sub"])) or find_user_by_email(db, email)
    role = oidc_role_from_claims(claims)
    if user is None:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug)) if tenant_slug else None
        if tenant is None:
            tenant = db.scalar(select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.id).limit(1))
        user = User(tenant_id=tenant.id, email=email, full_name=claims.get("name") or email, password_hash=None,
                    role=role, oidc_subject=claims["sub"])
        db.add(user)
        db.flush()
        audit(db, "auth.sso_provisioned", user=user, request=request, details={"role": role})
    else:
        if not user.is_active:
            raise HTTPException(403, "Account disabled")
        user.oidc_subject = claims["sub"]
        if settings.oidc_role_claim in claims:  # IdP is the source of truth for roles when it sends them
            user.role = role
    user.last_login_at = datetime.now(timezone.utc)
    audit(db, "auth.sso_login", user=user, request=request)
    db.commit()
    token = create_access_token(user)
    return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/sso-callback#token={token}")
