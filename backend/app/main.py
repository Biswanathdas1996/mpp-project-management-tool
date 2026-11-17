"""FastAPI application entry point."""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .api import admin, ai, analytics, auth, exports, governance, mapping, programs, snapshots, tenants, users
from .config import get_settings
from .db import Base, engine, session_scope
from .kpi.engine import REGISTRY
from .models import KPIDefinition, Tenant, User
from .queue import queue_health
from .security import hash_password
from .storage import get_storage

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pma")


def bootstrap() -> None:
    """Create schema (when not managed by Alembic), seed KPI definitions, create first tenant/admin.

    Safe to run concurrently (several uvicorn/RQ workers start at once): a unique-constraint race
    simply means another process seeded first, so we retry and find the rows already present.
    """
    if settings.is_sqlite or settings.env != "production":
        Base.metadata.create_all(engine)
    for attempt in range(3):
        try:
            _seed()
            return
        except IntegrityError:
            log.info("Bootstrap race (attempt %s): another process seeded first", attempt + 1)


def _seed() -> None:
    with session_scope() as db:
        existing = {(d.code, d.version) for d in db.scalars(select(KPIDefinition))}
        for d in REGISTRY.values():
            if (d.code, d.version) not in existing:
                db.add(KPIDefinition(code=d.code, version=d.version, name=d.name, category=d.category,
                                     formula=d.formula, source_fields=d.source_fields, widget=d.widget, phase=d.phase,
                                     unit=d.unit, description=d.description, reference=d.reference))
        if db.scalar(select(User).limit(1)) is None:
            pwd = settings.bootstrap_admin_password
            if not pwd:
                if settings.env == "production":
                    raise RuntimeError("PMA_BOOTSTRAP_ADMIN_PASSWORD must be set for the first production start")
                pwd = secrets.token_urlsafe(12) + "9a"
                log.warning("=" * 72)
                log.warning("Bootstrap admin created: %s / %s  (change it after first login)",
                            settings.bootstrap_admin_email, pwd)
                log.warning("=" * 72)
            tenant = db.scalar(select(Tenant).limit(1))
            if tenant is None:
                tenant = Tenant(name=settings.bootstrap_tenant_name, slug="default", branding={},
                                ai_mode=settings.ai_default_mode)
                db.add(tenant)
                db.flush()
            db.add(User(tenant_id=tenant.id, email=settings.bootstrap_admin_email.lower(), full_name="Administrator",
                        role="admin", is_platform_admin=True, password_hash=hash_password(pwd)))


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    if settings.queue_backend == "inline":
        # Jobs run in-process: start the JVM on the main thread so worker threads only attach to it.
        try:
            from .parser.mpp_parser import mpxj_classes

            mpxj_classes()
        except Exception as exc:  # pragma: no cover
            log.error("MPXJ/JVM unavailable — uploads will fail until Java 11+ is installed: %s", exc)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", docs_url=f"{settings.api_prefix}/docs",
              openapi_url=f"{settings.api_prefix}/openapi.json", redoc_url=None, lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.env == "production":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith(settings.api_prefix):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # pragma: no cover
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


for r in (auth.router, users.router, tenants.router, programs.router, snapshots.router, mapping.router,
          analytics.router, governance.router, ai.router, exports.router, admin.router):
    app.include_router(r, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health")
def health():
    return {"status": "ok"}


@app.get(f"{settings.api_prefix}/ready")
def ready():
    checks = {}
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False
    checks["storage"] = get_storage().healthy()
    q = queue_health()
    checks["queue"] = q["ok"]
    ok = all(checks.values())
    return JSONResponse({"ready": ok, "checks": checks, "queue": q}, status_code=200 if ok else 503)


# Optional: serve the built SPA from the API process (single-container deployments / local runs).
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and _dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
