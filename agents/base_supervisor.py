"""Common collector health Supervisor (injectable, no side effects on import)."""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from enum import Enum
from pathlib import Path


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    RATE_LIMITED = "RATE_LIMITED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    BLOCKED_FALLBACK = "BLOCKED_FALLBACK"


class RateLimited(Exception):
    def __init__(self, retry_after: float = 60):
        if (
            isinstance(retry_after, bool)
            or not isinstance(retry_after, (int, float))
            or not math.isfinite(retry_after)
            or retry_after < 0
        ):
            raise ValueError("retry_after must be a finite number >= 0")
        super().__init__("rate_limited")
        self.retry_after = float(retry_after)


class SessionExpired(Exception):
    pass


class Blocked(Exception):
    pass


class SupervisorStopped(Exception):
    pass


_REASONS = frozenset({
    "init", "ok", "rate_limited", "session_expired", "blocked", "fallback_used",
    "fallback_error", "fallback_rate_limited", "fallback_session_expired",
    "operation_error",
})

_KEYS = ("source", "state", "updated_at", "retry_at", "reason")


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


class Supervisor:
    def __init__(self, source: str, state_path=None, *, clock=None):
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")
        self._source = source
        self._clock = clock if clock is not None else time.time
        self._path = Path(state_path) if state_path is not None else None
        self._lock = threading.RLock()
        self._state = HealthState.HEALTHY
        self._updated_at = self._clock()
        self._retry_at = None
        self._reason = "init"
        if self._path is not None and self._path.exists():
            self._load()

    # -- persistence ---------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) != set(_KEYS):
                raise ValueError
            if data["source"] != self._source:
                raise ValueError
            state = HealthState(data["state"])
            if not _is_num(data["updated_at"]):
                raise ValueError
            if data["retry_at"] is not None and not _is_num(data["retry_at"]):
                raise ValueError
            if data["reason"] not in _REASONS:
                raise ValueError
        except (ValueError, TypeError, OSError):
            raise ValueError("invalid supervisor state file") from None
        self._state = state
        self._updated_at = data["updated_at"]
        self._retry_at = data["retry_at"]
        self._reason = data["reason"]

    def _save(self) -> None:
        if self._path is None:
            return
        payload = json.dumps(self.snapshot(), ensure_ascii=False)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=self._path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _record(self, state: HealthState, reason: str, retry_at=None) -> None:
        with self._lock:
            self._state = state
            self._reason = reason
            self._retry_at = retry_at
            self._updated_at = self._clock()
            self._save()

    # -- public --------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "source": self._source,
                "state": self._state.value,
                "updated_at": self._updated_at,
                "retry_at": self._retry_at,
                "reason": self._reason,
            }

    def run(self, operation, *, stop=None, fallback=None, max_retries=3):
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be an int >= 0")
        if stop is None:
            stop = threading.Event()
        attempt = 0
        while True:
            if stop.is_set():
                raise SupervisorStopped()
            try:
                result = operation()
            except SupervisorStopped:
                raise
            except RateLimited as exc:
                self._record(
                    HealthState.RATE_LIMITED, "rate_limited", self._clock() + exc.retry_after
                )
                if attempt >= max_retries:
                    raise
                if stop.wait(exc.retry_after):
                    raise SupervisorStopped() from None
                attempt += 1
                continue
            except SessionExpired:
                self._record(HealthState.SESSION_EXPIRED, "session_expired")
                raise
            except Blocked:
                self._record(HealthState.BLOCKED_FALLBACK, "blocked")
                if stop.is_set():
                    raise SupervisorStopped() from None
                return self._run_fallback(fallback)
            except Exception:
                self._record(self._state, "operation_error", self._retry_at)
                raise
            self._record(HealthState.HEALTHY, "ok")
            return result

    def _run_fallback(self, fallback):
        if fallback is None:
            raise Blocked()
        try:
            result = fallback()
        except RateLimited as exc:
            self._record(
                HealthState.RATE_LIMITED, "fallback_rate_limited", self._clock() + exc.retry_after
            )
            raise
        except SessionExpired:
            self._record(HealthState.SESSION_EXPIRED, "fallback_session_expired")
            raise
        except Exception:
            self._record(HealthState.BLOCKED_FALLBACK, "fallback_error")
            raise
        self._record(HealthState.BLOCKED_FALLBACK, "fallback_used")
        return result
