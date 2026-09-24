# -*- coding: utf-8 -*-
"""
Auth middleware: protect /api/v1/* when admin auth is enabled.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool

from src.auth import ADMIN_COOKIE_NAME, APP_COOKIE_NAME, COOKIE_NAME, is_auth_enabled, verify_session
from src.guest_access import is_guest_access_enabled
from src.request_context import reset_actor_context, set_actor_context
from src.services.identity_service import (
    ADMIN_AUDIENCE,
    APP_AUDIENCE,
    get_identity_service,
    is_multi_user_mode,
)

logger = logging.getLogger(__name__)

EXEMPT_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/status",
    "/api/v1/auth/invitations/accept",
    "/api/v1/admin/auth/login",
    "/api/v1/admin/auth/status",
    "/api/health",
    "/api/v1/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
})

MULTI_USER_LOGOUT_PATHS = frozenset({
    "/api/v1/auth/logout",
    "/api/v1/admin/auth/logout",
})

GUEST_GET_EXACT_PATHS = frozenset({
    "/api/v1/agent/models",
    "/api/v1/agent/status",
    "/api/v1/agent/skills",
    "/api/v1/agent/strategies",
    "/api/v1/stocks/market-dashboard",
    "/api/v1/alphasift/status",
    "/api/v1/alphasift/strategies",
    "/api/v1/alphasift/hotspots",
})

GUEST_POST_EXACT_PATHS = frozenset({
    "/api/v1/agent/chat/stream",
    "/api/v1/alphasift/screen",
    "/api/v1/alphasift/screen/tasks",
})


def _path_exempt(path: str) -> bool:
    """Check if path is exempt from auth."""
    normalized = path.rstrip("/") or "/"
    return normalized in EXEMPT_PATHS


def _guest_path_allowed(path: str, method: str) -> bool:
    """Allow only real-market reads and explicitly ephemeral guest actions."""

    normalized = path.rstrip("/") or "/"
    upper_method = method.upper()
    if upper_method in {"GET", "HEAD", "OPTIONS"}:
        if normalized in GUEST_GET_EXACT_PATHS:
            return True
        if normalized.startswith("/api/v1/alphasift/hotspots/"):
            return True
        if normalized.startswith("/api/v1/alphasift/screen/tasks/"):
            return True
        if normalized.startswith("/api/v1/stocks/"):
            return normalized.endswith("/quote") or normalized.endswith("/history")
        return False
    if upper_method == "POST":
        if normalized in GUEST_POST_EXACT_PATHS:
            return True
        if normalized.startswith("/api/v1/agent/chat/stream/") and normalized.endswith("/cancel"):
            return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Require valid session for /api/v1/* when auth is enabled."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):
        auth_enabled = is_auth_enabled()
        multi_user = is_multi_user_mode()
        # A cached legacy toggle must never bypass explicit multi-user auth.
        if not auth_enabled and not multi_user:
            return await call_next(request)

        path = request.url.path
        if multi_user:
            origin_error = self._validate_mutation_origin(request)
            if origin_error is not None:
                return origin_error
            if (path.rstrip("/") or "/") in MULTI_USER_LOGOUT_PATHS:
                return await call_next(request)
        if _path_exempt(path):
            return await call_next(request)

        if not path.startswith("/api/v1/"):
            return await call_next(request)

        if multi_user:
            return await self._dispatch_multi_user(request, call_next)

        cookie_val = request.cookies.get(COOKIE_NAME)
        if not cookie_val or not verify_session(cookie_val):
            if is_guest_access_enabled() and _guest_path_allowed(path, request.method):
                request.state.guest_access = True
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": "Login required",
                },
            )

        return await call_next(request)

    async def _dispatch_multi_user(self, request: Request, call_next: Callable):
        """Authenticate a database session and bind its principal to the request."""

        service = await run_in_threadpool(get_identity_service)
        await run_in_threadpool(service.ensure_ready)
        if not await run_in_threadpool(service.has_owner):
            return JSONResponse(
                status_code=503,
                content={
                    "error": "bootstrap_required",
                    "message": (
                        "Multi-user authentication requires a platform owner. "
                        "Run: python -m src.auth bootstrap_owner --username owner"
                    ),
                },
            )

        is_admin_path = request.url.path.startswith("/api/v1/admin/")
        audience = ADMIN_AUDIENCE if is_admin_path else APP_AUDIENCE
        cookie_name = ADMIN_COOKIE_NAME if is_admin_path else APP_COOKIE_NAME
        token = request.cookies.get(cookie_name)
        principal = await run_in_threadpool(service.principal_from_token, token or "", audience)
        if principal is None:
            if (
                not is_admin_path
                and is_guest_access_enabled()
                and _guest_path_allowed(request.url.path, request.method)
            ):
                request.state.guest_access = True
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "Login required"},
            )

        permission = self._required_permission(request.url.path, request.method)
        if permission and not principal.has_permission(permission):
            return JSONResponse(
                status_code=403,
                content={
                    "error": "forbidden",
                    "message": "You do not have permission to perform this operation",
                },
            )

        request.state.principal = principal
        actor_tokens = set_actor_context(principal.user_id, "user")
        try:
            response = await call_next(request)
            if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and (
                is_admin_path or permission
            ):
                await run_in_threadpool(
                    service.audit,
                    actor_type="user",
                    actor_id=principal.user_id,
                    action=f"api.{request.method.lower()}",
                    resource_type="endpoint",
                    resource_id=request.url.path,
                    outcome="success" if response.status_code < 400 else "failure",
                    request_id=request.headers.get("x-request-id"),
                    ip_address=request.client.host if request.client else None,
                    details={"statusCode": response.status_code},
                )
            return response
        finally:
            reset_actor_context(actor_tokens)

    @staticmethod
    def _required_permission(path: str, method: str = "GET") -> str | None:
        """Apply deny-by-default gates to global high-risk route families."""

        if path.startswith("/api/v1/system/") or path == "/api/v1/system":
            return "system.configure"
        if path == "/api/v1/auth/settings":
            return "system.configure"
        if path.startswith("/api/v1/alphasift/install"):
            return "system.configure"
        if (
            path.startswith("/api/v1/intelligence/sources")
            and method.upper() not in {"GET", "HEAD", "OPTIONS"}
        ):
            return "system.configure"
        feature_permissions = (
            ("/api/v1/agent", "chat.use"),
            ("/api/v1/history", "analysis.read.own"),
            ("/api/v1/backtest", "backtest.run"),
            ("/api/v1/usage", "usage.read.own"),
            ("/api/v1/portfolio", "portfolio.manage.own"),
            ("/api/v1/alerts", "alerts.manage.own"),
            ("/api/v1/decision-signals", "signals.read.own"),
        )
        for prefix, permission in feature_permissions:
            if path == prefix or path.startswith(f"{prefix}/"):
                return permission
        if path == "/api/v1/analysis" or path.startswith("/api/v1/analysis/"):
            return (
                "analysis.read.own"
                if method.upper() in {"GET", "HEAD", "OPTIONS"}
                else "analysis.run"
            )
        return None

    @staticmethod
    def _validate_mutation_origin(request: Request) -> JSONResponse | None:
        """Reject cross-origin browser mutations that rely on session cookies."""

        if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return None
        origin = (request.headers.get("origin") or "").rstrip("/")
        if not origin:
            return None
        forwarded_proto = request.headers.get("x-forwarded-proto")
        forwarded_host = request.headers.get("x-forwarded-host")
        trust_forwarded = os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true"
        if trust_forwarded and forwarded_proto and forwarded_host:
            expected_origin = f"{forwarded_proto.split(',')[0].strip()}://{forwarded_host.split(',')[0].strip()}"
        else:
            expected_origin = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
        if origin == expected_origin.rstrip("/"):
            return None
        return JSONResponse(
            status_code=403,
            content={"error": "invalid_origin", "message": "Cross-origin mutation rejected"},
        )


def add_auth_middleware(app):
    """Add auth middleware to protect API routes.

    The middleware is always registered; whether auth is enforced is determined
    at request time by is_auth_enabled() so the decision stays consistent across
    any runtime configuration reload.
    """
    app.add_middleware(AuthMiddleware)
