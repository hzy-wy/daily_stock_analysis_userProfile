"""Request-scoped authenticated actor context.

Business persistence code uses this context only to stamp ownership.  Access
control still happens at the API/service boundary; callers must never treat a
client supplied owner identifier as authoritative.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional


_current_user_id: ContextVar[Optional[str]] = ContextVar("dsa_current_user_id", default=None)
_current_actor_type: ContextVar[str] = ContextVar("dsa_current_actor_type", default="system")


def set_actor_context(user_id: Optional[str], actor_type: str = "user") -> tuple[Token, Token]:
    """Bind an authenticated actor for the current async/thread context."""

    return (
        _current_user_id.set(user_id),
        _current_actor_type.set(actor_type),
    )


def reset_actor_context(tokens: tuple[Token, Token]) -> None:
    """Restore the previous actor context."""

    user_token, type_token = tokens
    _current_user_id.reset(user_token)
    _current_actor_type.reset(type_token)


def get_current_user_id() -> Optional[str]:
    """Return the authenticated user id, if the current operation has one."""

    return _current_user_id.get()


def get_current_actor_type() -> str:
    """Return ``user``, ``service_account`` or ``system``."""

    return _current_actor_type.get()

