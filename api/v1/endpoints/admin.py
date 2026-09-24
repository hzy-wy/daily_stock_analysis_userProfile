"""Multi-user administrator authentication, user management and audit API."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from api.auth_dispatch import auth_worker
from api.deps import require_permission
from src.auth import ADMIN_COOKIE_NAME, get_client_ip
from src.services.identity_service import (
    ADMIN_AUDIENCE,
    AuthenticationError,
    AuthorizationError,
    IdentityError,
    Principal,
    get_identity_service,
    is_multi_user_mode,
)


router = APIRouter()


class AdminLoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class InvitationCreateRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    role: str = Field(default="member", max_length=64)
    expires_hours: int = Field(default=72, alias="expiresHours", ge=1, le=720)

    model_config = {"populate_by_name": True}


class UserStatusRequest(BaseModel):
    status: str = Field(max_length=24)


class UserRoleRequest(BaseModel):
    role: str = Field(max_length=64)


def _secure_cookie(request: Request) -> bool:
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        return request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    return request.url.scheme == "https"


@router.get("/auth/status", summary="Get administrator session status")
@auth_worker
def admin_auth_status(request: Request):
    if not is_multi_user_mode():
        return {
            "authMode": "legacy",
            "loggedIn": False,
            "user": None,
        }
    service = get_identity_service()
    service.ensure_ready()
    principal = service.principal_from_token(
        request.cookies.get(ADMIN_COOKIE_NAME, ""),
        ADMIN_AUDIENCE,
    )
    return {
        "authMode": "multi_user",
        "loggedIn": principal is not None,
        "user": (
            {
                "id": principal.user_id,
                "displayName": principal.display_name,
                "roles": sorted(principal.roles),
                "permissions": sorted(principal.permissions),
            }
            if principal
            else None
        ),
    }


@router.post("/auth/login", summary="Create an administrator session")
@auth_worker
def admin_auth_login(request: Request, body: AdminLoginRequest):
    if not is_multi_user_mode():
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": "Multi-user admin login is not enabled"},
        )
    service = get_identity_service()
    service.ensure_ready()
    if not service.has_owner():
        return JSONResponse(
            status_code=503,
            content={
                "error": "bootstrap_required",
                "message": "Run python -m src.auth bootstrap_owner --username owner",
            },
        )
    try:
        token, principal = service.authenticate(
            identifier=body.identifier,
            password=body.password,
            audience=ADMIN_AUDIENCE,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthenticationError as exc:
        return JSONResponse(
            status_code=429 if exc.code == "rate_limited" else 401,
            content={"error": exc.code, "message": exc.message},
        )
    except AuthorizationError as exc:
        return JSONResponse(
            status_code=403,
            content={"error": exc.code, "message": exc.message},
        )
    response = JSONResponse(
        content={
            "ok": True,
            "user": {
                "id": principal.user_id,
                "displayName": principal.display_name,
                "roles": sorted(principal.roles),
                "permissions": sorted(principal.permissions),
            },
        }
    )
    try:
        max_age_hours = int(os.getenv("ADMIN_SESSION_MAX_AGE_HOURS", "4"))
    except ValueError:
        max_age_hours = 4
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        path="/",
        max_age=max(1, max_age_hours) * 3600,
    )
    return response


@router.post("/auth/logout", summary="Revoke the current administrator session")
@auth_worker
def admin_auth_logout(request: Request):
    get_identity_service().revoke_session(
        request.cookies.get(ADMIN_COOKIE_NAME, ""),
        ADMIN_AUDIENCE,
        reason="logout",
    )
    response = Response(status_code=204)
    response.delete_cookie(key=ADMIN_COOKIE_NAME, path="/")
    return response


@router.get("/users", summary="List platform users")
@auth_worker
def list_users(
    _principal: Principal = Depends(require_permission("users.manage")),
):
    return {"users": get_identity_service().list_users()}


@router.post("/invitations", summary="Invite a user")
@auth_worker
def create_invitation(
    body: InvitationCreateRequest,
    principal: Principal = Depends(require_permission("users.manage")),
):
    try:
        invitation = get_identity_service().create_invitation(
            identifier=body.identifier,
            role_key=body.role,
            invited_by_user_id=principal.user_id,
            expires_hours=body.expires_hours,
        )
    except IdentityError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "message": exc.message},
        )
    return invitation


@router.put("/users/{user_id}/status", summary="Change a user account status")
@auth_worker
def update_user_status(
    user_id: str,
    body: UserStatusRequest,
    principal: Principal = Depends(require_permission("users.manage")),
):
    try:
        return get_identity_service().set_user_status(
            target_user_id=user_id,
            status=body.status,
            actor=principal,
        )
    except IdentityError as exc:
        return JSONResponse(
            status_code=400 if exc.code != "user_not_found" else 404,
            content={"error": exc.code, "message": exc.message},
        )


@router.put("/users/{user_id}/role", summary="Replace a user's platform role")
@auth_worker
def update_user_role(
    user_id: str,
    body: UserRoleRequest,
    principal: Principal = Depends(require_permission("users.manage")),
):
    try:
        return get_identity_service().set_user_role(
            target_user_id=user_id,
            role_key=body.role,
            actor=principal,
        )
    except IdentityError as exc:
        return JSONResponse(
            status_code=400 if exc.code != "user_not_found" else 404,
            content={"error": exc.code, "message": exc.message},
        )


@router.get("/audit-logs", summary="Read security and administrative audit logs")
@auth_worker
def list_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    _principal: Principal = Depends(require_permission("audit.read")),
):
    return {"items": get_identity_service().list_audit_logs(limit=limit)}

