"""Async job queue: Redis + RQ in production, in-process thread pool for single-node/dev."""
from __future__ import annotations

import importlib
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from .config import get_settings

log = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None


def _resolve(path: str):
    mod, fn = path.rsplit(".", 1)
    return getattr(importlib.import_module(mod), fn)


def _run_inline(path: str, args, kwargs):
    try:
        _resolve(path)(*args, **kwargs)
    except Exception:  # pragma: no cover - logged for operators
        log.exception("Inline job %s failed", path)


@lru_cache
def _rq_queue():
    from redis import Redis
    from rq import Queue

    s = get_settings()
    return Queue(s.queue_name, connection=Redis.from_url(s.redis_url), default_timeout=s.job_timeout_seconds)


def enqueue(path: str, *args, **kwargs) -> str:
    s = get_settings()
    if s.queue_backend == "rq":
        job = _rq_queue().enqueue(path, *args, **kwargs, result_ttl=3600, failure_ttl=86400)
        return job.id
    global _executor
    if _executor is None:
        # one worker keeps SQLite writes serialised; Postgres deployments use RQ workers instead
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pma-job")
    _executor.submit(_run_inline, path, args, kwargs)
    return f"inline-{uuid.uuid4().hex[:12]}"


def queue_health() -> dict:
    s = get_settings()
    if s.queue_backend != "rq":
        return {"backend": "inline", "ok": True}
    try:
        q = _rq_queue()
        q.connection.ping()
        return {"backend": "rq", "ok": True, "queued": q.count}
    except Exception as exc:
        return {"backend": "rq", "ok": False, "error": str(exc)[:200]}
