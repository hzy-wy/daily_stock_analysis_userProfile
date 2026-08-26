# -*- coding: utf-8 -*-
"""Deterministic checks for anonymous guest policy and transient quotas."""

from __future__ import annotations

from src.guest_access import (
    consume_guest_ai_quota,
    get_guest_ai_max_history_messages,
    get_guest_ai_requests_per_hour,
    is_guest_access_enabled,
    reset_guest_ai_quota,
)
from src.agent.factory import get_guest_tool_registry


def setup_function() -> None:
    reset_guest_ai_quota()


def teardown_function() -> None:
    reset_guest_ai_quota()


def test_guest_access_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("GUEST_ACCESS_ENABLED", raising=False)
    assert is_guest_access_enabled() is False

    monkeypatch.setenv("GUEST_ACCESS_ENABLED", "true")
    assert is_guest_access_enabled() is True


def test_guest_limits_are_bounded_when_environment_values_are_invalid(monkeypatch) -> None:
    monkeypatch.setenv("GUEST_AI_REQUESTS_PER_HOUR", "not-a-number")
    monkeypatch.setenv("GUEST_AI_MAX_HISTORY_MESSAGES", "999")

    assert get_guest_ai_requests_per_hour() == 20
    assert get_guest_ai_max_history_messages() == 30


def test_guest_ai_quota_is_per_client_and_expires_after_one_hour(monkeypatch) -> None:
    monkeypatch.setenv("GUEST_AI_REQUESTS_PER_HOUR", "2")

    assert consume_guest_ai_quota("friend-a", now=100.0) == (True, 1)
    assert consume_guest_ai_quota("friend-a", now=101.0) == (True, 0)
    assert consume_guest_ai_quota("friend-a", now=102.0) == (False, 0)
    assert consume_guest_ai_quota("friend-b", now=102.0) == (True, 1)
    assert consume_guest_ai_quota("friend-a", now=3701.0) == (True, 1)


def test_guest_agent_tools_exclude_all_user_owned_data_sources() -> None:
    names = {tool.name for tool in get_guest_tool_registry().list_tools()}

    assert names == {
        "get_realtime_quote",
        "get_daily_history",
        "get_chip_distribution",
        "get_stock_info",
        "get_capital_flow",
        "analyze_trend",
        "calculate_ma",
        "get_volume_analysis",
        "analyze_pattern",
        "search_stock_news",
        "search_comprehensive_intel",
        "get_market_indices",
        "get_sector_rankings",
    }
