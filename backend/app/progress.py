"""Live processing progress for snapshots.

Every pipeline step calls ``Progress.emit(...)``. Each event is
  * logged to the console (logger ``pma.progress``), and
  * appended to a per-snapshot event buffer that the API streams to the UI over SSE.

The buffer lives in process memory for the inline queue backend, and in a Redis list when jobs
run in separate RQ worker processes, so the API process can read what a worker wrote.
Events are append-only with a sequence number; readers poll "everything after seq N".
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from .config import get_settings

log = logging.getLogger("pma.progress")

_TTL_SECONDS = 24 * 3600   # Redis buffer lifetime
_MAX_EVENTS = 2000         # per snapshot (task-level progress is throttled well below this)
_MAX_SNAPSHOTS = 50        # in-memory buffers kept (oldest evicted)

_lock = threading.Lock()
_mem: OrderedDict[int, list[dict[str, Any]]] = OrderedDict()


def _key(snapshot_id: int) -> str:
    return f"pma:snapshot-events:{snapshot_id}"


def _redis():
    from .queue import _rq_queue

    return _rq_queue().connection


def _use_redis() -> bool:
    return get_settings().queue_backend == "rq"


# ----------------------------------------------------------------------------------------------
# Buffer access
# ----------------------------------------------------------------------------------------------
def reset(snapshot_id: int) -> None:
    """Clear a snapshot's events (called when a (re)processing run starts)."""
    if _use_redis():
        try:
            _redis().delete(_key(snapshot_id))
        except Exception:  # pragma: no cover - progress must never break processing
            log.debug("progress reset failed", exc_info=True)
        return
    with _lock:
        _mem.pop(snapshot_id, None)


def _append(snapshot_id: int, event: dict[str, Any]) -> None:
    if _use_redis():
        try:
            r = _redis()
            pipe = r.pipeline()
            pipe.rpush(_key(snapshot_id), json.dumps(event, default=str))
            pipe.ltrim(_key(snapshot_id), -_MAX_EVENTS, -1)
            pipe.expire(_key(snapshot_id), _TTL_SECONDS)
            pipe.execute()
        except Exception:  # pragma: no cover
            log.debug("progress publish failed", exc_info=True)
        return
    with _lock:
        buf = _mem.setdefault(snapshot_id, [])
        _mem.move_to_end(snapshot_id)
        buf.append(event)
        if len(buf) > _MAX_EVENTS:
            del buf[: len(buf) - _MAX_EVENTS]
        while len(_mem) > _MAX_SNAPSHOTS:
            _mem.popitem(last=False)


def read_since(snapshot_id: int, after_seq: int = 0) -> list[dict[str, Any]]:
    """Events with ``seq > after_seq``, oldest first."""
    if _use_redis():
        try:
            raw = _redis().lrange(_key(snapshot_id), 0, -1)
        except Exception:  # pragma: no cover
            return []
        events = [json.loads(x) for x in raw]
    else:
        with _lock:
            events = list(_mem.get(snapshot_id, []))
    return [e for e in events if e.get("seq", 0) > after_seq]


# ----------------------------------------------------------------------------------------------
# Emitter
# ----------------------------------------------------------------------------------------------
class Progress:
    """Emits ordered progress events for one processing run of one snapshot.

    ``stage`` groups events in the UI (upload, parse, store, profile, discovery, mapping, compute, done).
    ``level`` is info | ok | warn | error. ``pct`` (0-100) is an optional overall progress hint.
    """

    def __init__(self, snapshot_id: int, label: str | None = None, fresh: bool = True):
        self.snapshot_id = snapshot_id
        self.label = label or f"snapshot {snapshot_id}"
        self._t0 = time.monotonic()
        self._stage_t0 = self._t0
        self._stage: str | None = None
        existing = [] if fresh else read_since(snapshot_id)
        self._seq = existing[-1]["seq"] if existing else 0
        # run id lets stream readers notice that a new (re)processing run replaced the buffer
        self.run = existing[-1].get("run") if existing else uuid.uuid4().hex[:8]
        if fresh:
            reset(snapshot_id)

    def emit(self, stage: str, message: str, level: str = "info", pct: float | None = None,
             quiet: bool = False, **data: Any) -> None:
        now = time.monotonic()
        if stage != self._stage:
            self._stage, self._stage_t0 = stage, now
        self._seq += 1
        event = {
            "seq": self._seq,
            "run": self.run,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "elapsed_ms": int((now - self._t0) * 1000),
            "stage": stage,
            "level": level,
            "message": message,
            "pct": None if pct is None else round(max(0.0, min(100.0, pct)), 1),
            "data": data or None,
        }
        pylevel = {"warn": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO)
        if not quiet:
                log.log(pylevel, "[%s] %-9s %6.2fs %s%s", self.label, stage, now - self._t0, message,
                    f" ({pct:.0f}%)" if pct is not None else "")
        _append(self.snapshot_id, event)

    # convenience wrappers
    def info(self, stage: str, message: str, **kw: Any) -> None:
        self.emit(stage, message, "info", **kw)

    def ok(self, stage: str, message: str, **kw: Any) -> None:
        self.emit(stage, message, "ok", **kw)

    def warn(self, stage: str, message: str, **kw: Any) -> None:
        self.emit(stage, message, "warn", **kw)

    def error(self, stage: str, message: str, **kw: Any) -> None:
        self.emit(stage, message, "error", **kw)

    def stage_seconds(self) -> float:
        return time.monotonic() - self._stage_t0


class NullProgress(Progress):
    """No-op reporter (used by callers that don't track a snapshot, e.g. tests / CLI parsing)."""

    def __init__(self):  # noqa: D401 - intentionally skips buffer setup
        self.snapshot_id = 0
        self.label = "-"
        self.run = ""
        self._seq = 0
        self._t0 = self._stage_t0 = time.monotonic()
        self._stage = None

    def emit(self, *a: Any, **kw: Any) -> None:
        return None


class ProgressStream:
    """Forwards a model's streamed reply into the progress log as ``level="stream"`` events.

    Deltas are batched (one event per ``interval`` seconds) so a long reply costs a few hundred events,
    not one per token. Each attempt is its own stream id; the UI concatenates the deltas of a stream
    into one live block. Stream events are not written to the console log.
    """

    def __init__(self, progress: Progress, stage: str, interval: float = 0.3):
        self.progress = progress
        self.stage = stage
        self.interval = interval
        self.sid = ""
        self._buf: list[str] = []
        self._channel = "content"
        self._last = 0.0
        self._chars = 0

    def _flush(self) -> None:
        if self._buf:
            self.progress.emit(self.stage, "", "stream", quiet=True, sid=self.sid, channel=self._channel,
                               delta="".join(self._buf))
            self._buf = []
        self._last = time.monotonic()

    def begin(self, attempt: int, repair: bool) -> None:
        self.sid = f"{self.stage}-{self.progress.run}-{attempt}"
        self._buf, self._chars, self._channel = [], 0, "content"
        self._last = time.monotonic()
        title = ("Cached answer" if attempt == 0 else
                 f"{'Correcting the reply' if repair else 'Generating'} (attempt {attempt})")
        self.progress.emit(self.stage, "", "stream", quiet=True, sid=self.sid, start=True, attempt=attempt,
                           title=title)

    def token(self, delta: str, channel: str) -> None:
        if channel != self._channel:
            self._flush()
            self._channel = channel
        self._buf.append(delta)
        self._chars += len(delta)
        if time.monotonic() - self._last >= self.interval:
            self._flush()

    def end(self, ok: bool, note: str) -> None:
        self._flush()
        self.progress.emit(self.stage, "", "stream", quiet=True, sid=self.sid, done=True, ok=ok, note=note[:300])
