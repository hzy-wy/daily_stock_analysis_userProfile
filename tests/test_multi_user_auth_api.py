# -*- coding: utf-8 -*-
"""HTTP contract tests for separate multi-user login audiences and RBAC gates."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.middlewares.auth import add_auth_middleware
from api.middlewares.auth import AuthMiddleware
from api.v1.endpoints import admin, auth
from src.auth import ADMIN_COOKIE_NAME, APP_COOKIE_NAME
from src.config import Config
from src.services.identity_service import IdentityService
from src.storage import DatabaseManager


@pytest.fixture()
def multi_user_app(tmp_path):
    previous_auth_mode = os.environ.get("AUTH_MODE")
    previous_database_path = os.environ.get("DATABASE_PATH")
    os.environ["AUTH_MODE"] = "multi_user"
    os.environ["DATABASE_PATH"] = str(tmp_path / "multi-user-api.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    service = IdentityService(db)
    owner = service.bootstrap_owner(
        identifier="owner",
        password="owner-password-123",
        display_name="Owner",
    )
    invitation = service.create_invitation(
        identifier="member",
        role_key="member",
        invited_by_user_id=owner["id"],
    )
    service.accept_invitation(
        token=invitation["token"],
        password="member-password-123",
        display_name="Member",
    )

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(admin.router, prefix="/api/v1/admin")

    @app.get("/api/v1/private")
    async def private_endpoint(request: Request):
        return {"userId": request.state.principal.user_id}

    @app.post("/api/v1/system/mutate")
    async def system_mutation():
        return {"ok": True}

    add_auth_middleware(app)
    try:
        yield app
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if previous_auth_mode is None:
            os.environ.pop("AUTH_MODE", None)
        else:
            os.environ["AUTH_MODE"] = previous_auth_mode
        if previous_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = previous_database_path


def test_app_and_admin_cookies_coexist_and_logout_independently(multi_user_app) -> None:
    with TestClient(multi_user_app) as client:
        app_login = client.post(
            "/api/v1/auth/login",
            json={"identifier": "owner", "password": "owner-password-123"},
        )
        assert app_login.status_code == 200
        assert client.cookies.get(APP_COOKIE_NAME)

        admin_login = client.post(
            "/api/v1/admin/auth/login",
            json={"identifier": "owner", "password": "owner-password-123"},
        )
        assert admin_login.status_code == 200
        assert client.cookies.get(ADMIN_COOKIE_NAME)
        assert client.cookies.get(APP_COOKIE_NAME)
        assert client.get("/api/v1/private").status_code == 200
        assert client.get("/api/v1/admin/users").status_code == 200

        assert client.post("/api/v1/admin/auth/logout").status_code == 204
        assert client.get("/api/v1/admin/users").status_code == 401
        assert client.get("/api/v1/private").status_code == 200


def test_logout_can_clear_an_expired_or_invalid_session_cookie(multi_user_app) -> None:
    """Logout must stay usable after a server-side session has expired."""

    with TestClient(multi_user_app) as client:
        client.cookies.set(APP_COOKIE_NAME, "expired-or-invalid")
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 204
        assert client.cookies.get(APP_COOKIE_NAME) is None


def test_member_cannot_create_admin_session_or_mutate_system(multi_user_app) -> None:
    with TestClient(multi_user_app) as client:
        assert client.post(
            "/api/v1/auth/login",
            json={"identifier": "member", "password": "member-password-123"},
        ).status_code == 200
        assert client.get("/api/v1/private").status_code == 200
        assert client.post("/api/v1/system/mutate").status_code == 403
        assert client.post(
            "/api/v1/admin/auth/login",
            json={"identifier": "member", "password": "member-password-123"},
        ).status_code == 403


def test_cross_origin_browser_login_is_rejected(multi_user_app) -> None:
    with TestClient(multi_user_app) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={"identifier": "owner", "password": "owner-password-123"},
        )
        assert response.status_code == 403
        assert response.json()["error"] == "invalid_origin"


def test_feature_routes_map_to_atomic_permissions() -> None:
    assert AuthMiddleware._required_permission(
        "/api/v1/analysis/tasks", "GET"
    ) == "analysis.read.own"
    assert AuthMiddleware._required_permission(
        "/api/v1/analysis/run", "POST"
    ) == "analysis.run"
    assert AuthMiddleware._required_permission(
        "/api/v1/portfolio/accounts", "POST"
    ) == "portfolio.manage.own"
    assert AuthMiddleware._required_permission(
        "/api/v1/agent/chat", "POST"
    ) == "chat.use"
