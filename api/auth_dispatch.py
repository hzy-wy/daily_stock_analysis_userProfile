"""Offload synchronous auth endpoints without racing credential mutations."""

from functools import wraps
from inspect import signature
from threading import RLock

from anyio import CapacityLimiter
from anyio.lowlevel import RunVar
from starlette.concurrency import run_in_threadpool


_auth_limiter = RunVar("auth_endpoint_limiter")
_auth_lock = RLock()


def _call_serialized(function, args, kwargs):
    # Also covers separate event loops and callers cancelled during worker execution.
    with _auth_lock:
        return function(*args, **kwargs)


def auth_worker(function):
    """Keep auth mutations serialized while waiting outside the ASGI event loop.

    The async admission gate prevents waiting requests from occupying all shared
    worker threads. The thread lock protects the complete check/write transaction.
    """
    @wraps(function)
    async def dispatch(*args, **kwargs):
        limiter = _auth_limiter.get(None)
        if limiter is None:
            limiter = CapacityLimiter(1)
            _auth_limiter.set(limiter)
        async with limiter:
            return await run_in_threadpool(_call_serialized, function, args, kwargs)

    # Resolve postponed annotations in the endpoint's module, not this module.
    dispatch.__signature__ = signature(function, eval_str=True)
    return dispatch
