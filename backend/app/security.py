"""Authentication (local JWT + OIDC SSO), role-based access control and tenant scoping."""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Program, Role, User

settings = get_settings()
bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {Role.super_viewer.value: 1, Role.pmo_editor.value: 2, Role.admin.value: 3}


# ----------------------------------------------------------------------------------------------
# Passwords
# ----------------------------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode())
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if not any(c.isdigit() for c in password):
        problems.append("a digit")
    if not any(c.isalpha() for c in password):
        problems.append("a letter")
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Password needs " + ", ".join(problems))


# ----------------------------------------------------------------------------------------------
# Tokens
# ----------------------------------------------------------------------------------------------
def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "tid": user.tenant_id,
        "role": user.role,
        "tv": user.token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "iss": "pma",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"], issuer="pma")
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    token = creds.credentials if creds else request.query_params.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_access_token(token)
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or user.token_version != payload.get("tv"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session no longer valid")
    if not user.tenant.is_active and not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant is disabled")
    request.state.user = user
    return user


def require_role(minimum: Role):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK[minimum.value]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role {minimum.value}")
        return user

    return _dep


require_viewer = require_role(Role.super_viewer)
require_editor = require_role(Role.pmo_editor)
require_admin = require_role(Role.admin)


def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform administrator only")
    return user


def get_program_for_user(db: Session, program_id: int, user: User) -> Program:
    """Tenant isolation: a program is only visible within its own tenant."""
    program = db.get(Program, program_id)
    if not program or program.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Program not found")
    return program


# ----------------------------------------------------------------------------------------------
# OIDC (authorization code + PKCE), stateless state carried in a signed JWT
# ----------------------------------------------------------------------------------------------
_oidc_cache: dict[str, Any] = {}


def oidc_metadata() -> dict[str, Any]:
    cached = _oidc_cache.get("meta")
    if cached and cached[0] > time.time():
        return cached[1]
    url = settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    meta = resp.json()
    _oidc_cache["meta"] = (time.time() + 3600, meta)
    return meta


def oidc_build_login_url(tenant_slug: str | None) -> str:
    meta = oidc_metadata()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    nonce = secrets.token_urlsafe(16)
    state = jwt.encode(
        {"v": verifier, "n": nonce, "t": tenant_slug, "exp": int(time.time()) + 600},
        settings.secret_key,
        algorithm="HS256",
    )
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return str(httpx.URL(meta["authorization_endpoint"], params=params))


def oidc_exchange(code: str, state: str) -> tuple[dict[str, Any], str | None]:
    try:
        st = jwt.decode(state, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(400, "Invalid SSO state") from exc
    meta = oidc_metadata()
    resp = httpx.post(
        meta["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.oidc_redirect_uri,
            "client_id": settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret,
            "code_verifier": st["v"],
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(400, f"SSO token exchange failed: {resp.text[:200]}")
    id_token = resp.json().get("id_token")
    if not id_token:
        raise HTTPException(400, "SSO provider returned no id_token")
    jwks = jwt.PyJWKClient(meta["jwks_uri"])
    key = jwks.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        key.key,
        algorithms=["RS256", "ES256", "PS256"],
        audience=settings.oidc_client_id,
        issuer=meta.get("issuer", settings.oidc_issuer),
    )
    if claims.get("nonce") != st["n"]:
        raise HTTPException(400, "SSO nonce mismatch")
    return claims, st.get("t")


def oidc_role_from_claims(claims: dict[str, Any]) -> str:
    values = claims.get(settings.oidc_role_claim) or claims.get("groups") or []
    if isinstance(values, str):
        values = [values]
    admin = {v.strip() for v in settings.oidc_admin_values.split(",") if v.strip()}
    editor = {v.strip() for v in settings.oidc_editor_values.split(",") if v.strip()}
    if admin.intersection(values):
        return Role.admin.value
    if editor.intersection(values):
        return Role.pmo_editor.value
    return settings.oidc_default_role


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


# ----------------------------------------------------------------------------------------------
# Email type: accepts internal/enterprise domains (e.g. *.local, *.corp) that EmailStr rejects
# ----------------------------------------------------------------------------------------------
import re as _re  # noqa: E402
from typing import Annotated  # noqa: E402

from pydantic import AfterValidator  # noqa: E402

_EMAIL_RE = _re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


def _check_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 255 or not _EMAIL_RE.match(v):
        raise ValueError("Invalid email address")
    return v


Email = Annotated[str, AfterValidator(_check_email)]
