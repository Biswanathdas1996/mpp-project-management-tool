from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..models import User
from ..security import Email, find_user_by_email, hash_password, require_admin, validate_password_strength
from .auth import user_out

router = APIRouter(prefix="/users", tags=["users"])
RoleT = Literal["admin", "pmo_editor", "super_viewer"]


class UserCreate(BaseModel):
    email: Email
    full_name: str = ""
    role: RoleT = "super_viewer"
    password: str | None = None  # omit for SSO-only accounts


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: RoleT | None = None
    is_active: bool | None = None
    password: str | None = None


def _get(db: Session, user_id: int, admin: User) -> User:
    u = db.get(User, user_id)
    if u is None or u.tenant_id != admin.tenant_id:
        raise HTTPException(404, "User not found")
    return u


@router.get("")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).where(User.tenant_id == admin.tenant_id).order_by(User.email))]


@router.post("", status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if find_user_by_email(db, body.email):
        raise HTTPException(409, "A user with this email already exists")
    if body.password:
        validate_password_strength(body.password)
    u = User(tenant_id=admin.tenant_id, email=body.email.lower(), full_name=body.full_name, role=body.role,
             password_hash=hash_password(body.password) if body.password else None)
    db.add(u)
    db.flush()
    audit(db, "user.create", user=admin, entity_type="user", entity_id=u.id, request=request,
          details={"email": u.email, "role": u.role})
    db.commit()
    return user_out(u)


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    u = _get(db, user_id, admin)
    changes = body.model_dump(exclude_unset=True)
    if u.id == admin.id and (changes.get("role") not in (None, "admin") or changes.get("is_active") is False):
        raise HTTPException(400, "You cannot demote or disable your own account")
    if "full_name" in changes:
        u.full_name = body.full_name or ""
    if body.role:
        u.role = body.role
        u.token_version += 1
    if body.is_active is not None:
        u.is_active = body.is_active
        u.token_version += 1
    if body.password:
        validate_password_strength(body.password)
        u.password_hash = hash_password(body.password)
        u.token_version += 1
    audit(db, "user.update", user=admin, entity_type="user", entity_id=u.id, request=request,
          details={k: v for k, v in changes.items() if k != "password"} | ({"password": "reset"} if body.password else {}))
    db.commit()
    return user_out(u)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = _get(db, user_id, admin)
    if u.id == admin.id:
        raise HTTPException(400, "You cannot delete your own account")
    audit(db, "user.delete", user=admin, entity_type="user", entity_id=u.id, request=request, details={"email": u.email})
    db.delete(u)
    db.commit()
