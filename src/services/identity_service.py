"""Database-backed identity, session, RBAC, invitation and audit service."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from src.storage import (
    ApiKeyRecord,
    AuditLogRecord,
    AuthIdentityRecord,
    AuthSessionRecord,
    DatabaseManager,
    DatabaseSchemaMigration,
    InvitationRecord,
    PasswordCredentialRecord,
    PermissionRecord,
    RolePermissionRecord,
    RoleRecord,
    SecurityEventRecord,
    ServiceAccountRecord,
    UserRecord,
    UserRoleAssignmentRecord,
    UserWatchlistRecord,
    utc_naive_now,
)


APP_AUDIENCE = "app"
ADMIN_AUDIENCE = "admin"
ACTIVE_USER_STATUS = "active"
PASSWORD_MIN_LENGTH = 12
LOGIN_WINDOW_MINUTES = 5
LOGIN_MAX_FAILURES = 5

PERMISSIONS: dict[str, str] = {
    "workspace.use": "Use the authenticated product workspace",
    "analysis.run": "Run stock and market analysis",
    "analysis.read.own": "Read owned analysis reports",
    "chat.use": "Use owned Agent chat sessions",
    "portfolio.manage.own": "Manage owned portfolio accounts",
    "alerts.manage.own": "Manage owned alert rules",
    "signals.read.own": "Read owned decision signals",
    "backtest.run": "Run backtests for owned data",
    "usage.read.own": "Read own LLM usage",
    "admin.access": "Create and use an administrator session",
    "users.manage": "Invite, suspend and assign roles to users",
    "system.configure": "Read and change global configuration and secrets",
    "system.status": "Read operational system status",
    "audit.read": "Read administrative and security audit logs",
    "tasks.manage.any": "Inspect or cancel tasks across users",
    "usage.read.any": "Read platform-wide LLM usage",
}

ROLE_DEFINITIONS: dict[str, tuple[str, set[str]]] = {
    "member": (
        "Member",
        {
            "workspace.use",
            "analysis.run",
            "analysis.read.own",
            "chat.use",
            "portfolio.manage.own",
            "alerts.manage.own",
            "signals.read.own",
            "backtest.run",
            "usage.read.own",
        },
    ),
    "auditor": (
        "Auditor",
        {"admin.access", "audit.read"},
    ),
    "platform_admin": (
        "Platform administrator",
        {
            "workspace.use",
            "analysis.run",
            "analysis.read.own",
            "chat.use",
            "portfolio.manage.own",
            "alerts.manage.own",
            "signals.read.own",
            "backtest.run",
            "usage.read.own",
            "admin.access",
            "users.manage",
            "system.configure",
            "system.status",
            "audit.read",
            "tasks.manage.any",
            "usage.read.any",
        },
    ),
    "platform_owner": ("Platform owner", {"*"}),
}


_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)
_DUMMY_PASSWORD_HASH = _PASSWORD_HASHER.hash("dsa-dummy-password-verifier")


class IdentityError(Exception):
    """Base identity error with a stable API code."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class AuthenticationError(IdentityError):
    """Invalid credentials or unavailable account."""


class AuthorizationError(IdentityError):
    """Authenticated principal lacks an operation permission."""


@dataclass(frozen=True)
class Principal:
    """Authenticated request principal."""

    user_id: str
    display_name: str
    audience: str
    session_id: str
    roles: frozenset[str]
    permissions: frozenset[str]
    mfa_level: int = 0

    def has_permission(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions

    def has_any_role(self, roles: Iterable[str]) -> bool:
        return bool(self.roles.intersection(roles))


def auth_mode() -> str:
    """Resolve explicit auth mode while preserving the legacy toggle contract."""

    configured = (os.getenv("AUTH_MODE") or "").strip().lower()
    if configured in {"disabled", "legacy", "multi_user"}:
        return configured
    legacy_enabled = (os.getenv("ADMIN_AUTH_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return "legacy" if legacy_enabled else "disabled"


def is_multi_user_mode() -> bool:
    return auth_mode() == "multi_user"


def normalize_identifier(value: str) -> str:
    """Normalize username/email identifiers without changing display names."""

    return (value or "").strip().casefold()


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identifier_hash(value: str) -> str:
    return hashlib.sha256(normalize_identifier(value).encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class IdentityService:
    """Identity boundary for interactive users and service accounts."""

    _seed_lock = threading.RLock()
    _ready_databases: "weakref.WeakSet[DatabaseManager]" = weakref.WeakSet()

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager.get_instance()

    def ensure_ready(self) -> None:
        """Seed stable RBAC rows, import a legacy owner and backfill ownership."""

        with self._seed_lock:
            if self.db in self._ready_databases:
                return
            self._seed_authorization()
            if is_multi_user_mode():
                owner_id = self._import_legacy_owner_if_available()
                if owner_id:
                    self._backfill_private_ownership(owner_id)
                    self._migrate_owner_watchlist_once(owner_id)
            self._ready_databases.add(self.db)

    def _seed_authorization(self) -> None:
        with self.db.get_session() as session:
            permissions_by_key: dict[str, PermissionRecord] = {}
            for key, description in PERMISSIONS.items():
                row = session.scalar(select(PermissionRecord).where(PermissionRecord.key == key))
                if row is None:
                    row = PermissionRecord(key=key, description=description)
                    session.add(row)
                    session.flush()
                permissions_by_key[key] = row

            wildcard = session.scalar(select(PermissionRecord).where(PermissionRecord.key == "*"))
            if wildcard is None:
                wildcard = PermissionRecord(key="*", description="All platform permissions")
                session.add(wildcard)
                session.flush()
            permissions_by_key["*"] = wildcard

            for role_key, (role_name, role_permissions) in ROLE_DEFINITIONS.items():
                role = session.scalar(select(RoleRecord).where(RoleRecord.key == role_key))
                if role is None:
                    role = RoleRecord(key=role_key, name=role_name, is_system=True)
                    session.add(role)
                    session.flush()
                else:
                    role.name = role_name
                    role.is_system = True
                desired_permission_ids = {
                    permissions_by_key[permission_key].id
                    for permission_key in role_permissions
                }
                existing_assignments = session.scalars(
                    select(RolePermissionRecord).where(
                        RolePermissionRecord.role_id == role.id
                    )
                ).all()
                existing_permission_ids = {
                    assignment.permission_id for assignment in existing_assignments
                }
                for assignment in existing_assignments:
                    if assignment.permission_id not in desired_permission_ids:
                        session.delete(assignment)
                for permission_id in desired_permission_ids - existing_permission_ids:
                    session.add(
                        RolePermissionRecord(
                            role_id=role.id,
                            permission_id=permission_id,
                        )
                    )
            session.commit()

    def _credential_path(self) -> Path:
        db_path = os.getenv("DATABASE_PATH", "./data/stock_analysis.db")
        return Path(db_path).resolve().parent / ".admin_password_hash"

    def _import_legacy_owner_if_available(self) -> Optional[str]:
        owner_id = self.get_owner_user_id()
        if owner_id:
            return owner_id

        credential_path = self._credential_path()
        if not credential_path.is_file():
            return None
        raw_hash = credential_path.read_text(encoding="utf-8").strip()
        if ":" not in raw_hash:
            return None
        try:
            salt_value, digest_value = raw_hash.split(":", 1)
            if not base64.standard_b64decode(salt_value) or not base64.standard_b64decode(digest_value):
                return None
        except (ValueError, TypeError, binascii.Error):
            return None

        identifier = normalize_identifier(
            os.getenv("MULTI_USER_LEGACY_OWNER_USERNAME", "owner")
        )
        try:
            return self._create_user(
                identifier=identifier,
                display_name="Deployment Owner",
                password_hash=raw_hash,
                algorithm="legacy_pbkdf2_sha256_100000",
                role_key="platform_owner",
                is_bootstrap_owner=True,
            )["id"]
        except IdentityError as exc:
            if exc.code != "identifier_exists":
                raise
            # A concurrent bootstrap may have created the owner between the
            # initial check and insert.  An arbitrary existing member with the
            # configured legacy username must never be treated as the owner.
            owner_id = self.get_owner_user_id()
            if owner_id:
                return owner_id
            raise IdentityError(
                "legacy_identifier_conflict",
                (
                    "旧管理员迁移用户名已被非 Owner 账号占用；"
                    "请修改 MULTI_USER_LEGACY_OWNER_USERNAME 后重试"
                ),
            ) from exc

    def bootstrap_owner(self, *, identifier: str, password: str, display_name: str) -> dict:
        """Create the first owner from a trusted CLI/local workflow."""

        self._seed_authorization()
        if self.get_owner_user_id():
            raise IdentityError("owner_exists", "平台所有者已经存在")
        legacy_owner_id = self._import_legacy_owner_if_available()
        if legacy_owner_id:
            self._backfill_private_ownership(legacy_owner_id)
            self._migrate_owner_watchlist_once(legacy_owner_id)
            raise IdentityError(
                "owner_exists",
                "检测到旧管理员凭据，已将其导入为平台所有者",
            )
        self.validate_new_password(password)
        user = self._create_user(
            identifier=identifier,
            display_name=display_name,
            password_hash=_PASSWORD_HASHER.hash(password),
            algorithm="argon2id",
            role_key="platform_owner",
            is_bootstrap_owner=True,
        )
        self._backfill_private_ownership(user["id"])
        self._migrate_owner_watchlist_once(user["id"])
        self.audit(
            actor_type="system",
            actor_id=None,
            action="identity.bootstrap_owner",
            resource_type="user",
            resource_id=user["id"],
            details={"identifier": normalize_identifier(identifier)},
        )
        return user

    @staticmethod
    def validate_new_password(password: str) -> None:
        if len(password or "") < PASSWORD_MIN_LENGTH:
            raise IdentityError(
                "weak_password",
                f"密码至少需要 {PASSWORD_MIN_LENGTH} 位",
            )
        if len(password.encode("utf-8")) > 1024:
            raise IdentityError("password_too_long", "密码长度超出安全限制")

    def _create_user(
        self,
        *,
        identifier: str,
        display_name: str,
        password_hash: str,
        algorithm: str,
        role_key: str,
        is_bootstrap_owner: bool = False,
    ) -> dict:
        normalized = normalize_identifier(identifier)
        if not normalized:
            raise IdentityError("identifier_required", "用户名或邮箱不能为空")
        if len(normalized) > 255:
            raise IdentityError("identifier_too_long", "用户名或邮箱过长")
        display = (display_name or normalized).strip()[:100]

        with self.db.get_session() as session:
            if session.scalar(
                select(AuthIdentityRecord.id).where(
                    AuthIdentityRecord.provider == "local",
                    AuthIdentityRecord.identifier_normalized == normalized,
                )
            ):
                raise IdentityError("identifier_exists", "该用户名或邮箱已存在")
            role = session.scalar(select(RoleRecord).where(RoleRecord.key == role_key))
            if role is None:
                raise IdentityError("invalid_role", "角色不存在")
            user = UserRecord(
                display_name=display,
                status=ACTIVE_USER_STATUS,
                is_bootstrap_owner=is_bootstrap_owner,
            )
            session.add(user)
            session.flush()
            session.add(
                AuthIdentityRecord(
                    user_id=user.id,
                    provider="local",
                    provider_subject=normalized,
                    identifier_normalized=normalized,
                    is_primary=True,
                    verified_at=utc_naive_now(),
                )
            )
            session.add(
                PasswordCredentialRecord(
                    user_id=user.id,
                    password_hash=password_hash,
                    algorithm=algorithm,
                )
            )
            session.add(
                UserRoleAssignmentRecord(
                    user_id=user.id,
                    role_id=role.id,
                    scope_type="platform",
                    scope_id="*",
                    granted_by_user_id=None,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if is_bootstrap_owner:
                    raise IdentityError("owner_exists", "平台所有者已经存在") from exc
                raise IdentityError("identifier_exists", "该用户名或邮箱已存在") from exc
            return {
                "id": user.id,
                "displayName": user.display_name,
                "status": user.status,
                "roles": [role_key],
            }

    def create_invitation(
        self,
        *,
        identifier: str,
        role_key: str,
        invited_by_user_id: str,
        expires_hours: int = 72,
    ) -> dict:
        """Create an invitation and return the raw token exactly once."""

        self.ensure_ready()
        normalized = normalize_identifier(identifier)
        if not normalized:
            raise IdentityError("identifier_required", "邀请标识不能为空")
        if role_key not in ROLE_DEFINITIONS or role_key == "platform_owner":
            raise IdentityError("invalid_role", "邀请角色不允许")
        raw_token = secrets.token_urlsafe(36)
        now = _utc_now()
        with self.db.get_session() as session:
            existing_identity = session.scalar(
                select(AuthIdentityRecord.id).where(
                    AuthIdentityRecord.provider == "local",
                    AuthIdentityRecord.identifier_normalized == normalized,
                )
            )
            if existing_identity:
                raise IdentityError("identifier_exists", "该用户已经存在")
            invitation = InvitationRecord(
                identifier_normalized=normalized,
                role_key=role_key,
                token_hash=_token_hash(raw_token),
                invited_by_user_id=invited_by_user_id,
                expires_at=now + timedelta(hours=max(1, expires_hours)),
            )
            session.add(invitation)
            session.commit()
            invitation_id = invitation.id
            invitation_expires_at = invitation.expires_at
        self.audit(
            actor_type="user",
            actor_id=invited_by_user_id,
            action="identity.invitation.create",
            resource_type="invitation",
            resource_id=invitation_id,
            details={"identifier": normalized, "role": role_key},
        )
        return {
            "id": invitation_id,
            "identifier": normalized,
            "role": role_key,
            "token": raw_token,
            "expiresAt": invitation_expires_at.isoformat(),
        }

    def accept_invitation(self, *, token: str, password: str, display_name: str) -> dict:
        self.ensure_ready()
        self.validate_new_password(password)
        now = _utc_now()
        token_digest = _token_hash(token or "")
        with self.db.get_session() as session:
            invitation = session.scalar(
                select(InvitationRecord).where(InvitationRecord.token_hash == token_digest)
            )
            if (
                invitation is None
                or invitation.accepted_at is not None
                or invitation.revoked_at is not None
                or invitation.expires_at <= now
            ):
                raise IdentityError("invalid_invitation", "邀请无效或已过期")
            identifier = invitation.identifier_normalized
            role_key = invitation.role_key
            invitation_id = invitation.id

        user = self._create_user(
            identifier=identifier,
            display_name=display_name,
            password_hash=_PASSWORD_HASHER.hash(password),
            algorithm="argon2id",
            role_key=role_key,
        )
        with self.db.get_session() as session:
            invitation = session.get(InvitationRecord, invitation_id)
            if invitation is not None:
                invitation.accepted_at = now
                session.commit()
        self.audit(
            actor_type="user",
            actor_id=user["id"],
            action="identity.invitation.accept",
            resource_type="user",
            resource_id=user["id"],
            details={"role": role_key},
        )
        return user

    def has_owner(self) -> bool:
        self.ensure_ready()
        return self.get_owner_user_id() is not None

    def get_owner_user_id(self) -> Optional[str]:
        with self.db.get_session() as session:
            return session.scalar(
                select(UserRoleAssignmentRecord.user_id)
                .join(RoleRecord, RoleRecord.id == UserRoleAssignmentRecord.role_id)
                .join(UserRecord, UserRecord.id == UserRoleAssignmentRecord.user_id)
                .where(
                    RoleRecord.key == "platform_owner",
                    UserRecord.status == ACTIVE_USER_STATUS,
                    UserRecord.deleted_at.is_(None),
                )
                .limit(1)
            )

    def _backfill_private_ownership(self, owner_user_id: str) -> None:
        table_names = (
            "analysis_history",
            "backtest_summaries",
            "portfolio_accounts",
            "conversation_messages",
            "conversation_summaries",
            "agent_provider_turns",
            "llm_usage",
            "alert_rules",
            "decision_signals",
        )
        with self.db._engine.begin() as connection:
            for table_name in table_names:
                connection.execute(
                    text(
                        f'UPDATE "{table_name}" SET owner_user_id = :owner_id '
                        'WHERE owner_user_id IS NULL'
                    ),
                    {"owner_id": owner_user_id},
                )

    def _migrate_owner_watchlist_once(self, owner_user_id: str) -> None:
        """Copy legacy STOCK_LIST into the owner's UI watchlist exactly once."""

        migration_version = f"2026-08-24-owner-watchlist-{owner_user_id}"
        with self.db.get_session() as session:
            if session.get(DatabaseSchemaMigration, migration_version) is not None:
                return
            from src.services.stock_list_parser import split_stock_list, watchlist_match_key

            codes = split_stock_list(os.getenv("STOCK_LIST", ""))
            for index, code in enumerate(codes):
                normalized = watchlist_match_key(code)
                if not normalized:
                    continue
                exists = session.scalar(
                    select(UserWatchlistRecord.id).where(
                        UserWatchlistRecord.user_id == owner_user_id,
                        UserWatchlistRecord.stock_code == normalized,
                    )
                )
                if not exists:
                    session.add(
                        UserWatchlistRecord(
                            user_id=owner_user_id,
                            stock_code=normalized,
                            display_code=code,
                            sort_order=index,
                        )
                    )
            session.add(
                DatabaseSchemaMigration(
                    version=migration_version,
                    description="Copied legacy STOCK_LIST to the platform owner's user watchlist",
                )
            )
            session.commit()

    def authenticate(
        self,
        *,
        identifier: str,
        password: str,
        audience: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> tuple[str, Principal]:
        """Verify credentials and issue a revocable opaque session."""

        self.ensure_ready()
        normalized = normalize_identifier(identifier)
        if audience not in {APP_AUDIENCE, ADMIN_AUDIENCE}:
            raise AuthenticationError("invalid_audience", "登录入口无效")
        if not normalized or not password:
            raise AuthenticationError("invalid_credentials", "用户名或密码错误")
        identifier_digest = _identifier_hash(normalized)
        now = _utc_now()
        if self._recent_failure_count(identifier_digest, ip_address, now) >= LOGIN_MAX_FAILURES:
            raise AuthenticationError("rate_limited", "登录尝试过于频繁，请稍后再试")

        with self.db.get_session() as session:
            identity = session.scalar(
                select(AuthIdentityRecord).where(
                    AuthIdentityRecord.provider == "local",
                    AuthIdentityRecord.identifier_normalized == normalized,
                )
            )
            user = session.get(UserRecord, identity.user_id) if identity else None
            credential = session.get(PasswordCredentialRecord, user.id) if user else None
            if credential and credential.locked_until and credential.locked_until > now:
                self._record_security_event(
                    event_type="login.blocked",
                    user_id=user.id,
                    identifier_hash=identifier_digest,
                    ip_address=ip_address,
                    outcome="blocked",
                )
                raise AuthenticationError("rate_limited", "登录尝试过于频繁，请稍后再试")

            valid = False
            needs_upgrade = False
            if credential is not None:
                valid = self._verify_password(password, credential)
                needs_upgrade = valid and credential.algorithm != "argon2id"
            else:
                try:
                    _PASSWORD_HASHER.verify(_DUMMY_PASSWORD_HASH, password)
                except VerificationError:
                    pass

            if user is None or credential is None or not valid or user.status != ACTIVE_USER_STATUS:
                if credential is not None:
                    credential.failed_attempts = int(credential.failed_attempts or 0) + 1
                    if credential.failed_attempts >= LOGIN_MAX_FAILURES:
                        credential.locked_until = now + timedelta(minutes=LOGIN_WINDOW_MINUTES)
                    session.commit()
                self._record_security_event(
                    event_type="login.failure",
                    user_id=user.id if user else None,
                    identifier_hash=identifier_digest,
                    ip_address=ip_address,
                    outcome="failure",
                )
                raise AuthenticationError("invalid_credentials", "用户名或密码错误")

            roles, permissions = self._roles_and_permissions(session, user.id)
            if audience == APP_AUDIENCE and "workspace.use" not in permissions and "*" not in permissions:
                self._record_security_event(
                    event_type="login.workspace_denied",
                    user_id=user.id,
                    identifier_hash=identifier_digest,
                    ip_address=ip_address,
                    outcome="denied",
                )
                raise AuthorizationError("workspace_required", "该账号没有产品工作区权限")
            if audience == ADMIN_AUDIENCE and "admin.access" not in permissions and "*" not in permissions:
                self._record_security_event(
                    event_type="login.admin_denied",
                    user_id=user.id,
                    identifier_hash=identifier_digest,
                    ip_address=ip_address,
                    outcome="denied",
                )
                raise AuthorizationError("admin_required", "该账号没有管理员后台权限")

            if needs_upgrade or _PASSWORD_HASHER.check_needs_rehash(credential.password_hash):
                credential.password_hash = _PASSWORD_HASHER.hash(password)
                credential.algorithm = "argon2id"
                credential.must_change = False
                credential.password_changed_at = now
            credential.failed_attempts = 0
            credential.locked_until = None
            user.last_login_at = now
            session.commit()
            user_id = user.id
            display_name = user.display_name
            token_version = int(user.token_version or 1)

        raw_token, session_id = self._create_session_record(
            user_id=user_id,
            audience=audience,
            token_version=token_version,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        principal = Principal(
            user_id=user_id,
            display_name=display_name,
            audience=audience,
            session_id=session_id,
            roles=frozenset(roles),
            permissions=frozenset(permissions),
        )
        self._record_security_event(
            event_type="login.success",
            user_id=user_id,
            identifier_hash=identifier_digest,
            ip_address=ip_address,
            outcome="success",
        )
        return raw_token, principal

    @staticmethod
    def _verify_password(password: str, credential: PasswordCredentialRecord) -> bool:
        if credential.algorithm == "argon2id":
            try:
                return bool(_PASSWORD_HASHER.verify(credential.password_hash, password))
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False
        if credential.algorithm == "legacy_pbkdf2_sha256_100000":
            try:
                salt_b64, stored_b64 = credential.password_hash.split(":", 1)
                salt = base64.standard_b64decode(salt_b64)
                stored = base64.standard_b64decode(stored_b64)
                computed = hashlib.pbkdf2_hmac(
                    "sha256",
                    password.encode("utf-8"),
                    salt=salt,
                    iterations=100_000,
                )
                return hmac.compare_digest(computed, stored)
            except (ValueError, TypeError, binascii.Error):
                return False
        return False

    def _recent_failure_count(
        self,
        identifier_digest: str,
        ip_address: Optional[str],
        now: datetime,
    ) -> int:
        """Return the stricter of the identifier and client-IP failure windows."""

        since = now - timedelta(minutes=LOGIN_WINDOW_MINUTES)
        with self.db.get_session() as session:
            base_conditions = (
                SecurityEventRecord.event_type == "login.failure",
                SecurityEventRecord.created_at >= since,
            )
            identifier_count = int(
                session.scalar(
                    select(func.count(SecurityEventRecord.id)).where(
                        *base_conditions,
                        SecurityEventRecord.identifier_hash == identifier_digest,
                    )
                )
                or 0
            )
            if not ip_address:
                return identifier_count
            ip_count = int(
                session.scalar(
                    select(func.count(SecurityEventRecord.id)).where(
                        *base_conditions,
                        SecurityEventRecord.ip_address == ip_address[:64],
                    )
                )
                or 0
            )
            return max(identifier_count, ip_count)

    def _create_session_record(
        self,
        *,
        user_id: str,
        audience: str,
        token_version: int,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> tuple[str, str]:
        raw_token = secrets.token_urlsafe(48)
        now = _utc_now()
        if audience == ADMIN_AUDIENCE:
            absolute_hours = _positive_int_env("ADMIN_SESSION_MAX_AGE_HOURS", 4)
            idle_minutes = _positive_int_env("ADMIN_SESSION_IDLE_MINUTES", 30)
        else:
            absolute_hours = _positive_int_env("USER_SESSION_MAX_AGE_HOURS", 24)
            idle_minutes = _positive_int_env("USER_SESSION_IDLE_MINUTES", 480)
        record = AuthSessionRecord(
            token_hash=_token_hash(raw_token),
            user_id=user_id,
            audience=audience,
            token_version=token_version,
            ip_address=(ip_address or "")[:64] or None,
            user_agent=(user_agent or "")[:500] or None,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=absolute_hours),
            idle_expires_at=now + timedelta(minutes=idle_minutes),
        )
        with self.db.get_session() as session:
            session.add(record)
            session.commit()
            session_id = record.id
        return raw_token, session_id

    def principal_from_token(self, token: str, audience: str) -> Optional[Principal]:
        """Resolve a valid session and refresh its idle window."""

        if not token or audience not in {APP_AUDIENCE, ADMIN_AUDIENCE}:
            return None
        self.ensure_ready()
        now = _utc_now()
        with self.db.get_session() as session:
            auth_session = session.scalar(
                select(AuthSessionRecord).where(
                    AuthSessionRecord.token_hash == _token_hash(token),
                    AuthSessionRecord.audience == audience,
                )
            )
            if (
                auth_session is None
                or auth_session.revoked_at is not None
                or auth_session.expires_at <= now
                or auth_session.idle_expires_at <= now
            ):
                return None
            user = session.get(UserRecord, auth_session.user_id)
            if (
                user is None
                or user.status != ACTIVE_USER_STATUS
                or user.deleted_at is not None
                or int(user.token_version or 1) != int(auth_session.token_version or 1)
            ):
                return None
            roles, permissions = self._roles_and_permissions(session, user.id)
            if audience == APP_AUDIENCE and "workspace.use" not in permissions and "*" not in permissions:
                return None
            if audience == ADMIN_AUDIENCE and "admin.access" not in permissions and "*" not in permissions:
                return None
            idle_minutes = (
                _positive_int_env("ADMIN_SESSION_IDLE_MINUTES", 30)
                if audience == ADMIN_AUDIENCE
                else _positive_int_env("USER_SESSION_IDLE_MINUTES", 480)
            )
            if not auth_session.last_seen_at or now - auth_session.last_seen_at >= timedelta(minutes=1):
                auth_session.last_seen_at = now
                auth_session.idle_expires_at = min(
                    auth_session.expires_at,
                    now + timedelta(minutes=idle_minutes),
                )
                session.commit()
            return Principal(
                user_id=user.id,
                display_name=user.display_name,
                audience=audience,
                session_id=auth_session.id,
                roles=frozenset(roles),
                permissions=frozenset(permissions),
                mfa_level=int(auth_session.mfa_level or 0),
            )

    @staticmethod
    def _roles_and_permissions(session, user_id: str) -> tuple[set[str], set[str]]:
        now = _utc_now()
        role_rows = session.execute(
            select(RoleRecord.id, RoleRecord.key)
            .join(UserRoleAssignmentRecord, UserRoleAssignmentRecord.role_id == RoleRecord.id)
            .where(
                UserRoleAssignmentRecord.user_id == user_id,
                UserRoleAssignmentRecord.valid_from <= now,
                (
                    UserRoleAssignmentRecord.expires_at.is_(None)
                    | (UserRoleAssignmentRecord.expires_at > now)
                ),
            )
        ).all()
        roles = {row.key for row in role_rows}
        role_ids = [row.id for row in role_rows]
        if not role_ids:
            return roles, set()
        permissions = set(
            session.scalars(
                select(PermissionRecord.key)
                .join(RolePermissionRecord, RolePermissionRecord.permission_id == PermissionRecord.id)
                .where(RolePermissionRecord.role_id.in_(role_ids))
            ).all()
        )
        return roles, permissions

    def revoke_session(self, token: str, audience: str, reason: str = "logout") -> bool:
        if not token:
            return False
        now = _utc_now()
        with self.db.get_session() as session:
            record = session.scalar(
                select(AuthSessionRecord).where(
                    AuthSessionRecord.token_hash == _token_hash(token),
                    AuthSessionRecord.audience == audience,
                )
            )
            if record is None:
                return False
            record.revoked_at = now
            record.revoke_reason = reason[:100]
            session.commit()
            return True

    def revoke_user_sessions(
        self,
        user_id: str,
        *,
        reason: str,
        except_session_id: Optional[str] = None,
    ) -> int:
        now = _utc_now()
        with self.db.get_session() as session:
            rows = session.scalars(
                select(AuthSessionRecord).where(
                    AuthSessionRecord.user_id == user_id,
                    AuthSessionRecord.revoked_at.is_(None),
                )
            ).all()
            count = 0
            for row in rows:
                if except_session_id and row.id == except_session_id:
                    continue
                row.revoked_at = now
                row.revoke_reason = reason[:100]
                count += 1
            session.commit()
            return count

    def change_password(
        self,
        *,
        principal: Principal,
        current_password: str,
        new_password: str,
    ) -> None:
        self.validate_new_password(new_password)
        with self.db.get_session() as session:
            credential = session.get(PasswordCredentialRecord, principal.user_id)
            if credential is None or not self._verify_password(current_password, credential):
                raise AuthenticationError("invalid_current_password", "当前密码错误")
            credential.password_hash = _PASSWORD_HASHER.hash(new_password)
            credential.algorithm = "argon2id"
            credential.must_change = False
            credential.failed_attempts = 0
            credential.locked_until = None
            credential.password_changed_at = _utc_now()
            session.commit()
        self.revoke_user_sessions(
            principal.user_id,
            reason="password_changed",
            except_session_id=principal.session_id,
        )
        self.audit(
            actor_type="user",
            actor_id=principal.user_id,
            action="identity.password.change",
            resource_type="user",
            resource_id=principal.user_id,
        )

    def reset_password_from_trusted_cli(
        self,
        *,
        identifier: str,
        new_password: str,
    ) -> dict:
        """Reset one local user's password from a trusted server terminal."""

        self.ensure_ready()
        self.validate_new_password(new_password)
        normalized = normalize_identifier(identifier)
        with self.db.get_session() as session:
            identity = session.scalar(
                select(AuthIdentityRecord).where(
                    AuthIdentityRecord.provider == "local",
                    AuthIdentityRecord.identifier_normalized == normalized,
                )
            )
            user = session.get(UserRecord, identity.user_id) if identity else None
            credential = (
                session.get(PasswordCredentialRecord, user.id) if user else None
            )
            if user is None or credential is None or user.deleted_at is not None:
                raise IdentityError("user_not_found", "用户不存在")
            credential.password_hash = _PASSWORD_HASHER.hash(new_password)
            credential.algorithm = "argon2id"
            credential.must_change = False
            credential.failed_attempts = 0
            credential.locked_until = None
            credential.password_changed_at = _utc_now()
            user.token_version = int(user.token_version or 1) + 1
            user.updated_at = _utc_now()
            user_id = user.id
            display_name = user.display_name
            session.commit()
        self.revoke_user_sessions(user_id, reason="trusted_cli_password_reset")
        self.audit(
            actor_type="system",
            actor_id=None,
            action="identity.password.reset_cli",
            resource_type="user",
            resource_id=user_id,
            details={"identifier": normalized},
        )
        return {"id": user_id, "displayName": display_name}

    def list_users(self) -> list[dict]:
        self.ensure_ready()
        with self.db.get_session() as session:
            users = session.scalars(
                select(UserRecord).where(UserRecord.deleted_at.is_(None)).order_by(UserRecord.created_at)
            ).all()
            result = []
            for user in users:
                identity = session.scalar(
                    select(AuthIdentityRecord).where(
                        AuthIdentityRecord.user_id == user.id,
                        AuthIdentityRecord.is_primary.is_(True),
                    )
                )
                roles, _ = self._roles_and_permissions(session, user.id)
                result.append(
                    {
                        "id": user.id,
                        "displayName": user.display_name,
                        "identifier": identity.identifier_normalized if identity else None,
                        "status": user.status,
                        "roles": sorted(roles),
                        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
                        "createdAt": user.created_at.isoformat() if user.created_at else None,
                    }
                )
            return result

    def set_user_status(self, *, target_user_id: str, status: str, actor: Principal) -> dict:
        if status not in {"active", "suspended", "locked"}:
            raise IdentityError("invalid_status", "账号状态无效")
        if target_user_id == actor.user_id and status != "active":
            raise IdentityError("self_suspend_forbidden", "不能停用当前管理员账号")
        with self.db.get_session() as session:
            user = session.get(UserRecord, target_user_id)
            if user is None or user.deleted_at is not None:
                raise IdentityError("user_not_found", "用户不存在")
            roles, _ = self._roles_and_permissions(session, user.id)
            if "platform_owner" in roles and status != "active":
                raise IdentityError("owner_suspend_forbidden", "不能停用平台所有者")
            user.status = status
            user.updated_at = _utc_now()
            session.commit()
        if status != "active":
            self.revoke_user_sessions(target_user_id, reason=f"user_{status}")
        self.audit(
            actor_type="user",
            actor_id=actor.user_id,
            action="identity.user.status",
            resource_type="user",
            resource_id=target_user_id,
            details={"status": status},
        )
        return {"id": target_user_id, "status": status}

    def set_user_role(self, *, target_user_id: str, role_key: str, actor: Principal) -> dict:
        if role_key not in ROLE_DEFINITIONS or role_key == "platform_owner":
            raise IdentityError("invalid_role", "角色不允许分配")
        with self.db.get_session() as session:
            user = session.get(UserRecord, target_user_id)
            role = session.scalar(select(RoleRecord).where(RoleRecord.key == role_key))
            owner_role = session.scalar(select(RoleRecord).where(RoleRecord.key == "platform_owner"))
            if user is None or role is None:
                raise IdentityError("user_not_found", "用户不存在")
            if owner_role and session.scalar(
                select(UserRoleAssignmentRecord.id).where(
                    UserRoleAssignmentRecord.user_id == target_user_id,
                    UserRoleAssignmentRecord.role_id == owner_role.id,
                )
            ):
                raise IdentityError("owner_role_protected", "平台所有者角色不能通过该接口修改")
            assignments = session.scalars(
                select(UserRoleAssignmentRecord).where(
                    UserRoleAssignmentRecord.user_id == target_user_id,
                    UserRoleAssignmentRecord.scope_type == "platform",
                )
            ).all()
            for assignment in assignments:
                session.delete(assignment)
            session.flush()
            session.add(
                UserRoleAssignmentRecord(
                    user_id=target_user_id,
                    role_id=role.id,
                    scope_type="platform",
                    scope_id="*",
                    granted_by_user_id=actor.user_id,
                )
            )
            session.commit()
        self.revoke_user_sessions(target_user_id, reason="role_changed")
        self.audit(
            actor_type="user",
            actor_id=actor.user_id,
            action="identity.user.role",
            resource_type="user",
            resource_id=target_user_id,
            details={"role": role_key},
        )
        return {"id": target_user_id, "roles": [role_key]}

    def list_audit_logs(self, limit: int = 100) -> list[dict]:
        with self.db.get_session() as session:
            rows = session.scalars(
                select(AuditLogRecord)
                .order_by(AuditLogRecord.id.desc())
                .limit(max(1, min(limit, 500)))
            ).all()
            return [
                {
                    "id": row.id,
                    "actorType": row.actor_type,
                    "actorId": row.actor_id,
                    "action": row.action,
                    "resourceType": row.resource_type,
                    "resourceId": row.resource_id,
                    "outcome": row.outcome,
                    "requestId": row.request_id,
                    "ipAddress": row.ip_address,
                    "details": json.loads(row.details_json) if row.details_json else None,
                    "createdAt": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def audit(
        self,
        *,
        actor_type: str,
        actor_id: Optional[str],
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        outcome: str = "success",
        request_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        with self.db.get_session() as session:
            session.add(
                AuditLogRecord(
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    outcome=outcome,
                    request_id=request_id,
                    ip_address=ip_address,
                    details_json=json.dumps(details, ensure_ascii=False) if details else None,
                )
            )
            session.commit()

    def _record_security_event(
        self,
        *,
        event_type: str,
        user_id: Optional[str],
        identifier_hash: Optional[str],
        ip_address: Optional[str],
        outcome: str,
        details: Optional[dict] = None,
    ) -> None:
        with self.db.get_session() as session:
            session.add(
                SecurityEventRecord(
                    event_type=event_type,
                    user_id=user_id,
                    identifier_hash=identifier_hash,
                    ip_address=(ip_address or "")[:64] or None,
                    outcome=outcome,
                    details_json=json.dumps(details, ensure_ascii=False) if details else None,
                )
            )
            session.commit()


def get_identity_service() -> IdentityService:
    """Return an identity service bound to the active database singleton."""

    return IdentityService(DatabaseManager.get_instance())


def current_user_scope() -> Optional[str]:
    """Return the authenticated data scope in multi-user mode."""

    if not is_multi_user_mode():
        return None
    from src.request_context import get_current_user_id

    return get_current_user_id()


def persistence_owner_user_id() -> Optional[str]:
    """Resolve ownership for new private records.

    Interactive requests use their authenticated principal.  Existing global
    schedules retain the historical deployment-owner behavior until scheduled
    jobs gain explicit service-account ownership.
    """

    if not is_multi_user_mode():
        return None
    from src.request_context import get_current_user_id

    current = get_current_user_id()
    if current:
        return current
    return get_identity_service().get_owner_user_id()
