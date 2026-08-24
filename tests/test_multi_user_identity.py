# -*- coding: utf-8 -*-
"""P0 integration tests for multi-user identity, session audiences and ownership."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import date

import pytest

from src.config import Config
from src.request_context import reset_actor_context, set_actor_context
from src.services.identity_service import (
    ADMIN_AUDIENCE,
    APP_AUDIENCE,
    AuthenticationError,
    AuthorizationError,
    IdentityError,
    IdentityService,
)
from src.storage import DatabaseManager, PasswordCredentialRecord


@pytest.fixture()
def identity_service(tmp_path):
    previous = {
        "AUTH_MODE": os.environ.get("AUTH_MODE"),
        "DATABASE_PATH": os.environ.get("DATABASE_PATH"),
        "STOCK_LIST": os.environ.get("STOCK_LIST"),
    }
    os.environ["AUTH_MODE"] = "multi_user"
    os.environ["DATABASE_PATH"] = str(tmp_path / "multi-user.db")
    os.environ["STOCK_LIST"] = "600519,00700"
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    service = IdentityService(db)
    service.bootstrap_owner(
        identifier="owner",
        password="owner-password-123",
        display_name="Owner",
    )
    try:
        yield service, db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _login(service: IdentityService, identifier: str, password: str, audience: str):
    return service.authenticate(
        identifier=identifier,
        password=password,
        audience=audience,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )


def _write_legacy_password_file(tmp_path, password: str) -> None:
    salt = b"legacy-owner-test-salt-32-bytes!"
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt=salt,
        iterations=100_000,
    )
    (tmp_path / ".admin_password_hash").write_text(
        f"{base64.standard_b64encode(salt).decode()}:{base64.standard_b64encode(digest).decode()}",
        encoding="utf-8",
    )


def test_legacy_owner_is_imported_and_password_hash_is_upgraded(tmp_path, monkeypatch) -> None:
    legacy_password = "legacy-password"
    _write_legacy_password_file(tmp_path, legacy_password)
    monkeypatch.setenv("AUTH_MODE", "multi_user")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "legacy-import.db"))
    monkeypatch.setenv("MULTI_USER_LEGACY_OWNER_USERNAME", "legacy-owner")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    try:
        db = DatabaseManager.get_instance()
        service = IdentityService(db)
        service.ensure_ready()
        owner_id = service.get_owner_user_id()
        assert owner_id

        _token, principal = _login(
            service,
            "legacy-owner",
            legacy_password,
            ADMIN_AUDIENCE,
        )
        assert principal.user_id == owner_id
        with db.get_session() as session:
            credential = session.get(PasswordCredentialRecord, owner_id)
            assert credential is not None
            assert credential.algorithm == "argon2id"
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()


def test_legacy_import_never_promotes_an_existing_member_by_username(tmp_path, monkeypatch) -> None:
    _write_legacy_password_file(tmp_path, "legacy-password")
    monkeypatch.setenv("AUTH_MODE", "multi_user")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "legacy-conflict.db"))
    monkeypatch.setenv("MULTI_USER_LEGACY_OWNER_USERNAME", "claimed-name")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    try:
        db = DatabaseManager.get_instance()
        service = IdentityService(db)
        service._seed_authorization()
        member = service._create_user(
            identifier="claimed-name",
            display_name="Existing member",
            password_hash="not-used-by-this-test",
            algorithm="argon2id",
            role_key="member",
        )

        with pytest.raises(IdentityError) as exc_info:
            service.ensure_ready()
        assert exc_info.value.code == "legacy_identifier_conflict"
        assert service.get_owner_user_id() is None
        assert member["roles"] == ["member"]
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()


def test_app_and_admin_sessions_have_separate_audiences(identity_service) -> None:
    service, _db = identity_service
    app_token, app_principal = _login(
        service, "owner", "owner-password-123", APP_AUDIENCE
    )
    admin_token, admin_principal = _login(
        service, "owner", "owner-password-123", ADMIN_AUDIENCE
    )

    assert app_principal.audience == APP_AUDIENCE
    assert admin_principal.audience == ADMIN_AUDIENCE
    assert service.principal_from_token(app_token, APP_AUDIENCE) is not None
    assert service.principal_from_token(admin_token, ADMIN_AUDIENCE) is not None
    assert service.principal_from_token(app_token, ADMIN_AUDIENCE) is None
    assert service.principal_from_token(admin_token, APP_AUDIENCE) is None

    assert service.revoke_session(admin_token, ADMIN_AUDIENCE)
    assert service.principal_from_token(admin_token, ADMIN_AUDIENCE) is None
    assert service.principal_from_token(app_token, APP_AUDIENCE) is not None


def test_invited_member_can_use_workspace_but_not_admin(identity_service) -> None:
    service, _db = identity_service
    _owner_token, owner = _login(
        service, "owner", "owner-password-123", ADMIN_AUDIENCE
    )
    invitation = service.create_invitation(
        identifier="member@example.com",
        role_key="member",
        invited_by_user_id=owner.user_id,
    )
    user = service.accept_invitation(
        token=invitation["token"],
        password="member-password-123",
        display_name="Member",
    )

    _member_token, member = _login(
        service, "member@example.com", "member-password-123", APP_AUDIENCE
    )
    assert member.user_id == user["id"]
    assert member.has_permission("workspace.use")
    with pytest.raises(AuthorizationError) as exc_info:
        _login(
            service,
            "member@example.com",
            "member-password-123",
            ADMIN_AUDIENCE,
        )
    assert exc_info.value.code == "admin_required"


def test_auditor_is_admin_audience_only_and_cannot_enter_workspace(identity_service) -> None:
    service, _db = identity_service
    _owner_token, owner = _login(
        service, "owner", "owner-password-123", ADMIN_AUDIENCE
    )
    invitation = service.create_invitation(
        identifier="auditor",
        role_key="auditor",
        invited_by_user_id=owner.user_id,
    )
    service.accept_invitation(
        token=invitation["token"],
        password="auditor-password-123",
        display_name="Auditor",
    )

    _token, auditor = _login(
        service, "auditor", "auditor-password-123", ADMIN_AUDIENCE
    )
    assert auditor.permissions == frozenset({"admin.access", "audit.read"})
    with pytest.raises(AuthorizationError) as exc_info:
        _login(service, "auditor", "auditor-password-123", APP_AUDIENCE)
    assert exc_info.value.code == "workspace_required"


def test_login_rate_limit_applies_independently_to_client_ip(identity_service) -> None:
    service, _db = identity_service
    for index in range(5):
        with pytest.raises(AuthenticationError) as exc_info:
            service.authenticate(
                identifier=f"unknown-user-{index}",
                password="definitely-wrong",
                audience=APP_AUDIENCE,
                ip_address="198.51.100.9",
                user_agent="pytest",
            )
        assert exc_info.value.code == "invalid_credentials"

    with pytest.raises(AuthenticationError) as exc_info:
        service.authenticate(
            identifier="another-unknown-user",
            password="definitely-wrong",
            audience=APP_AUDIENCE,
            ip_address="198.51.100.9",
            user_agent="pytest",
        )
    assert exc_info.value.code == "rate_limited"


def test_private_conversations_are_scoped_by_authenticated_user(identity_service) -> None:
    service, db = identity_service
    _owner_token, owner = _login(
        service, "owner", "owner-password-123", APP_AUDIENCE
    )
    owner_admin_token, owner_admin = _login(
        service, "owner", "owner-password-123", ADMIN_AUDIENCE
    )
    invitation = service.create_invitation(
        identifier="second-user",
        role_key="member",
        invited_by_user_id=owner_admin.user_id,
    )
    member_user = service.accept_invitation(
        token=invitation["token"],
        password="second-password-123",
        display_name="Second user",
    )

    owner_tokens = set_actor_context(owner.user_id, "user")
    try:
        db.save_conversation_message("shared-client-session", "user", "owner message")
        db.save_conversation_message("owner:private", "user", "owner private")
        db.upsert_conversation_summary(
            "shared-client-session", "owner summary", 1, 1, 10
        )
        assert db.get_conversation_history("shared-client-session") == [
            {"role": "user", "content": "owner message"}
        ]
        assert db.get_conversation_summary("shared-client-session")["summary"] == (
            "owner summary"
        )
    finally:
        reset_actor_context(owner_tokens)

    member_tokens = set_actor_context(member_user["id"], "user")
    try:
        assert db.get_conversation_history("shared-client-session") == []
        db.save_conversation_message("shared-client-session", "user", "member message")
        db.upsert_conversation_summary(
            "shared-client-session", "member summary", 3, 1, 10
        )
        assert db.get_conversation_history("shared-client-session") == [
            {"role": "user", "content": "member message"}
        ]
        assert db.get_conversation_summary("shared-client-session")["summary"] == (
            "member summary"
        )
        assert db.get_chat_sessions(
            session_prefix="owner", extra_session_ids=["owner:private"]
        ) == []
    finally:
        reset_actor_context(member_tokens)

    owner_tokens = set_actor_context(owner.user_id, "user")
    try:
        assert db.get_conversation_summary("shared-client-session")["summary"] == (
            "owner summary"
        )
    finally:
        reset_actor_context(owner_tokens)

    assert service.revoke_session(owner_admin_token, ADMIN_AUDIENCE)


def test_user_watchlists_do_not_overwrite_global_scheduler_list(identity_service) -> None:
    service, db = identity_service
    from src.repositories.watchlist_repo import UserWatchlistRepository

    _owner_token, owner = _login(
        service, "owner", "owner-password-123", APP_AUDIENCE
    )
    _admin_token, owner_admin = _login(
        service, "owner", "owner-password-123", ADMIN_AUDIENCE
    )
    invitation = service.create_invitation(
        identifier="watchlist-user",
        role_key="member",
        invited_by_user_id=owner_admin.user_id,
    )
    member = service.accept_invitation(
        token=invitation["token"],
        password="watchlist-password-123",
        display_name="Watchlist user",
    )
    repository = UserWatchlistRepository(db)

    owner_tokens = set_actor_context(owner.user_id, "user")
    try:
        assert repository.list_codes() == ["600519", "00700"]
    finally:
        reset_actor_context(owner_tokens)

    member_tokens = set_actor_context(member["id"], "user")
    try:
        assert repository.list_codes() == []
        repository.add(normalized_code="AAPL", display_code="AAPL")
        assert repository.list_codes() == ["AAPL"]
    finally:
        reset_actor_context(member_tokens)

    assert os.environ["STOCK_LIST"] == "600519,00700"


def test_portfolio_all_account_views_and_child_reads_are_owner_scoped(identity_service) -> None:
    service, db = identity_service
    from src.repositories.portfolio_repo import PortfolioRepository

    _admin_token, owner = _login(
        service, "owner", "owner-password-123", ADMIN_AUDIENCE
    )
    invitation = service.create_invitation(
        identifier="portfolio-member",
        role_key="member",
        invited_by_user_id=owner.user_id,
    )
    member = service.accept_invitation(
        token=invitation["token"],
        password="portfolio-password-123",
        display_name="Portfolio member",
    )
    repository = PortfolioRepository(db)
    event_date = date(2026, 8, 20)

    owner_tokens = set_actor_context(owner.user_id, "user")
    try:
        owner_account = repository.create_account(
            name="Owner account",
            broker=None,
            market="cn",
            base_currency="CNY",
        )
        repository.add_trade(
            account_id=owner_account.id,
            trade_uid="owner-trade",
            symbol="600519",
            market="cn",
            currency="CNY",
            trade_date=event_date,
            side="buy",
            quantity=1,
            price=100,
            fee=0,
            tax=0,
        )
        repository.add_cash_ledger(
            account_id=owner_account.id,
            event_date=event_date,
            direction="in",
            amount=100,
            currency="CNY",
        )
        repository.add_corporate_action(
            account_id=owner_account.id,
            symbol="600519",
            market="cn",
            currency="CNY",
            effective_date=event_date,
            action_type="cash_dividend",
            cash_dividend_per_share=1,
        )
        owner_account_id = int(owner_account.id)
    finally:
        reset_actor_context(owner_tokens)

    member_tokens = set_actor_context(member["id"], "user")
    try:
        member_account = repository.create_account(
            name="Member account",
            broker=None,
            market="us",
            base_currency="USD",
        )
        repository.add_trade(
            account_id=member_account.id,
            trade_uid="member-trade",
            symbol="AAPL",
            market="us",
            currency="USD",
            trade_date=event_date,
            side="buy",
            quantity=1,
            price=200,
            fee=0,
            tax=0,
        )
        repository.add_cash_ledger(
            account_id=member_account.id,
            event_date=event_date,
            direction="in",
            amount=200,
            currency="USD",
        )
        repository.add_corporate_action(
            account_id=member_account.id,
            symbol="AAPL",
            market="us",
            currency="USD",
            effective_date=event_date,
            action_type="cash_dividend",
            cash_dividend_per_share=1,
        )
        trades, total = repository.query_trades(
            account_id=None,
            date_from=None,
            date_to=None,
            symbols=None,
            side=None,
            page=1,
            page_size=20,
        )
        assert total == 1
        assert [row.symbol for row in trades] == ["AAPL"]
        assert repository.list_trades(owner_account_id, event_date) == []
        assert not repository.has_trade_uid(owner_account_id, "owner-trade")
        with pytest.raises(ValueError, match="Active account not found"):
            repository.add_trade(
                account_id=owner_account_id,
                trade_uid="cross-owner-write",
                symbol="000001",
                market="cn",
                currency="CNY",
                trade_date=event_date,
                side="buy",
                quantity=1,
                price=10,
                fee=0,
                tax=0,
            )
        cash_rows, cash_total = repository.query_cash_ledger(
            account_id=None,
            date_from=None,
            date_to=None,
            direction=None,
            page=1,
            page_size=20,
        )
        assert cash_total == 1
        assert [row.account_id for row in cash_rows] == [member_account.id]
        action_rows, action_total = repository.query_corporate_actions(
            account_id=None,
            date_from=None,
            date_to=None,
            symbols=None,
            action_type=None,
            page=1,
            page_size=20,
        )
        assert action_total == 1
        assert [row.account_id for row in action_rows] == [member_account.id]
    finally:
        reset_actor_context(member_tokens)

    owner_tokens = set_actor_context(owner.user_id, "user")
    try:
        trades, total = repository.query_trades(
            account_id=None,
            date_from=None,
            date_to=None,
            symbols=None,
            side=None,
            page=1,
            page_size=20,
        )
        assert total == 1
        assert [row.symbol for row in trades] == ["600519"]
        assert repository.list_trades(int(member_account.id), event_date) == []
    finally:
        reset_actor_context(owner_tokens)


def test_trusted_cli_password_reset_revokes_existing_sessions(identity_service) -> None:
    service, _db = identity_service
    old_token, _owner = _login(
        service, "owner", "owner-password-123", APP_AUDIENCE
    )

    service.reset_password_from_trusted_cli(
        identifier="owner",
        new_password="replacement-password-123",
    )

    assert service.principal_from_token(old_token, APP_AUDIENCE) is None
    with pytest.raises(AuthenticationError):
        _login(service, "owner", "owner-password-123", APP_AUDIENCE)
    new_token, principal = _login(
        service, "owner", "replacement-password-123", APP_AUDIENCE
    )
    assert principal.user_id
    assert service.principal_from_token(new_token, APP_AUDIENCE) is not None


def test_decision_outcomes_and_feedback_inherit_signal_owner(identity_service) -> None:
    service, db = identity_service
    from src.repositories.decision_signal_outcome_repo import (
        DecisionSignalOutcomeRepository,
    )
    from src.storage import DecisionSignalOutcomeRecord, DecisionSignalRecord

    _admin_token, owner = _login(
        service, "owner", "owner-password-123", ADMIN_AUDIENCE
    )
    invitation = service.create_invitation(
        identifier="outcome-member",
        role_key="member",
        invited_by_user_id=owner.user_id,
    )
    member = service.accept_invitation(
        token=invitation["token"],
        password="outcome-password-123",
        display_name="Outcome member",
    )
    with db.get_session() as session:
        owner_signal = DecisionSignalRecord(
            owner_user_id=owner.user_id,
            stock_code="600519",
            market="cn",
            source_type="manual",
            trigger_source="pytest",
            action="watch",
        )
        member_signal = DecisionSignalRecord(
            owner_user_id=member["id"],
            stock_code="AAPL",
            market="us",
            source_type="manual",
            trigger_source="pytest",
            action="watch",
        )
        session.add_all([owner_signal, member_signal])
        session.flush()
        session.add_all(
            [
                DecisionSignalOutcomeRecord(
                    signal_id=owner_signal.id,
                    horizon="1d",
                    engine_version="pytest",
                ),
                DecisionSignalOutcomeRecord(
                    signal_id=member_signal.id,
                    horizon="1d",
                    engine_version="pytest",
                ),
            ]
        )
        session.commit()
        owner_signal_id = int(owner_signal.id)
        member_signal_id = int(member_signal.id)

    repository = DecisionSignalOutcomeRepository(db)
    owner_tokens = set_actor_context(owner.user_id, "user")
    try:
        rows, total = repository.list_outcomes(engine_version="pytest")
        assert total == 1
        assert [row.signal_id for row in rows] == [owner_signal_id]
    finally:
        reset_actor_context(owner_tokens)

    member_tokens = set_actor_context(member["id"], "user")
    try:
        rows, total = repository.list_outcomes(engine_version="pytest")
        assert total == 1
        assert [row.signal_id for row in rows] == [member_signal_id]
        with pytest.raises(ValueError):
            repository.upsert_feedback(
                {
                    "signal_id": owner_signal_id,
                    "feedback_value": "useful",
                    "source": "api",
                }
            )
    finally:
        reset_actor_context(member_tokens)


def test_backtest_results_and_summaries_inherit_analysis_owner(identity_service) -> None:
    service, db = identity_service
    from src.repositories.backtest_repo import BacktestRepository
    from src.services.backtest_service import BacktestService
    from src.storage import AnalysisHistory, BacktestResult, BacktestSummary

    _admin_token, owner = _login(
        service, "owner", "owner-password-123", ADMIN_AUDIENCE
    )
    invitation = service.create_invitation(
        identifier="backtest-member",
        role_key="member",
        invited_by_user_id=owner.user_id,
    )
    member = service.accept_invitation(
        token=invitation["token"],
        password="backtest-password-123",
        display_name="Backtest member",
    )
    with db.get_session() as session:
        owner_history = AnalysisHistory(
            owner_user_id=owner.user_id,
            code="600519",
            name="Owner stock",
        )
        member_history = AnalysisHistory(
            owner_user_id=member["id"],
            code="600519",
            name="Member stock",
        )
        session.add_all([owner_history, member_history])
        session.flush()
        session.add_all(
            [
                BacktestResult(
                    analysis_history_id=owner_history.id,
                    code="600519",
                    eval_window_days=10,
                    engine_version="pytest",
                    eval_status="completed",
                ),
                BacktestResult(
                    analysis_history_id=member_history.id,
                    code="600519",
                    eval_window_days=10,
                    engine_version="pytest",
                    eval_status="completed",
                ),
            ]
        )
        session.commit()
        member_history_id = int(member_history.id)

    repository = BacktestRepository(db)
    owner_tokens = set_actor_context(owner.user_id, "user")
    try:
        assert repository.count_results(code="600519", engine_version="pytest") == 1
        BacktestService(db)._recompute_summaries(
            touched_codes=["600519"],
            eval_window_days=10,
            engine_version="pytest",
        )
        assert repository.get_summary(
            scope="stock",
            code="600519",
            eval_window_days=10,
            engine_version="pytest",
        ).total_evaluations == 1
        with pytest.raises(ValueError):
            repository.save_result(
                BacktestResult(
                    analysis_history_id=member_history_id,
                    code="600519",
                    eval_window_days=20,
                    engine_version="pytest",
                    eval_status="completed",
                )
            )
    finally:
        reset_actor_context(owner_tokens)

    member_tokens = set_actor_context(member["id"], "user")
    try:
        assert repository.count_results(code="600519", engine_version="pytest") == 1
        BacktestService(db)._recompute_summaries(
            touched_codes=["600519"],
            eval_window_days=10,
            engine_version="pytest",
        )
        assert repository.get_summary(
            scope="stock",
            code="600519",
            eval_window_days=10,
            engine_version="pytest",
        ).total_evaluations == 1
    finally:
        reset_actor_context(member_tokens)

    with db.get_session() as session:
        summaries = session.query(BacktestSummary).filter(
            BacktestSummary.scope == "stock",
            BacktestSummary.code == "600519",
            BacktestSummary.eval_window_days == 10,
            BacktestSummary.engine_version == "pytest",
        ).all()
        assert {row.owner_user_id for row in summaries} == {
            owner.user_id,
            member["id"],
        }
