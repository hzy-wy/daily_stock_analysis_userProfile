# -*- coding: utf-8 -*-
"""Anonymous guest-access policy and in-memory AI quota enforcement.

Guest access is intentionally sessionless.  This module never creates a user,
database row, cookie, or durable usage record.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_GUEST_AI_REQUESTS: dict[str, Deque[float]] = defaultdict(deque)
_GUEST_AI_REQUESTS_LOCK = threading.Lock()


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def is_guest_access_enabled() -> bool:
    """Return whether the normal product may be opened without a login."""

    return os.getenv("GUEST_ACCESS_ENABLED", "false").strip().lower() in _TRUE_VALUES


def get_guest_ai_requests_per_hour() -> int:
    """Return the bounded per-client anonymous AI request allowance."""

    return _env_int("GUEST_AI_REQUESTS_PER_HOUR", 20, minimum=1, maximum=1000)


def get_guest_ai_max_history_messages() -> int:
    """Return how many browser-supplied turns may be used as transient context."""

    return _env_int("GUEST_AI_MAX_HISTORY_MESSAGES", 10, minimum=0, maximum=30)


def consume_guest_ai_quota(client_key: str, *, now: float | None = None) -> tuple[bool, int]:
    """Consume one in-memory hourly quota unit and return ``(allowed, remaining)``.

    The state is process-local by design: it protects a small private test
    deployment without writing visitor identifiers or counters to storage.
    """

    current = time.monotonic() if now is None else now
    cutoff = current - 3600.0
    limit = get_guest_ai_requests_per_hour()
    normalized_key = (client_key or "unknown")[:256]

    with _GUEST_AI_REQUESTS_LOCK:
        requests = _GUEST_AI_REQUESTS[normalized_key]
        while requests and requests[0] <= cutoff:
            requests.popleft()
        if len(requests) >= limit:
            return False, 0
        requests.append(current)
        return True, max(0, limit - len(requests))


def reset_guest_ai_quota() -> None:
    """Clear process-local quota state (used by deterministic tests)."""

    with _GUEST_AI_REQUESTS_LOCK:
        _GUEST_AI_REQUESTS.clear()
