# -*- coding: utf-8 -*-
"""Deterministic tests for the bounded homepage market dashboard service."""

import time
from datetime import datetime
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.market_analyzer import MarketIndex
from src.services import market_light_service as service


class _FakeAnalyzer:
    def __init__(self, region: str, config=None):
        self.region = region

    def build_market_light_snapshot(self, overview):
        return {
            "region": self.region,
            "trade_date": overview.date,
            "status": "green",
            "score": 72,
            "label": "risk-on",
            "temperature_label": "偏热",
            "reasons": ["breadth positive"],
            "guidance": "follow breadth",
            "dimensions": {},
            "data_quality": "ok",
        }


def _config(*, budget=0.5, fresh_ttl=60, stale_ttl=1800):
    return SimpleNamespace(
        market_dashboard_fetch_budget_seconds=budget,
        market_dashboard_cache_ttl_seconds=fresh_ttl,
        market_dashboard_stale_ttl_seconds=stale_ttl,
    )


def _result(block: str, *, usable=True):
    values = {
        "indices": [
            MarketIndex(
                code="000001",
                name="上证指数",
                current=3600.0,
                change=18.0,
                change_pct=0.5,
                open=3580.0,
                high=3610.0,
                low=3575.0,
                prev_close=3582.0,
                volume=1.0,
                amount=5000.0,
                amplitude=0.98,
            )
        ],
        "breadth": {
            "up_count": 3200,
            "down_count": 1900,
            "flat_count": 100,
            "limit_up_count": 70,
            "limit_down_count": 5,
            "total_amount": 12345.0,
        },
        "sectors": (
            [{"name": "电子", "change_pct": 3.2, "source": "unit"}],
            [{"name": "煤炭", "change_pct": -1.1}],
        ),
        "concepts": ([{"name": "机器人", "change_pct": 2.8}], []),
    }
    return service._DashboardBlockResult(
        value=values.get(block),
        usable=usable,
        trade_date="2026-08-11",
        message=None if usable else "unit failure",
    )


@pytest.fixture(autouse=True)
def _clear_dashboard_state():
    service.clear_market_dashboard_cache_for_tests()
    with service._DASHBOARD_STATE_LOCK:
        service._DASHBOARD_PERSISTED_LOADED.update(service.MARKET_LIGHT_REGIONS)
    yield
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with service._DASHBOARD_STATE_LOCK:
            if not service._DASHBOARD_INFLIGHT:
                break
        time.sleep(0.01)
    service.clear_market_dashboard_cache_for_tests()


def test_build_market_dashboard_exposes_actual_block_coverage():
    with (
        patch.object(service, "get_config", return_value=_config()),
        patch.object(service, "MarketAnalyzer", _FakeAnalyzer),
        patch.object(service, "_fetch_market_dashboard_block", side_effect=lambda _region, block: _result(block)),
    ):
        result = service.build_market_dashboard("cn")

    assert result["data_status"] == "ok"
    assert result["indices"][0]["name"] == "上证指数"
    assert result["breadth"]["up_count"] == 3200
    assert result["rankings"]["top_sectors"][0] == {
        "name": "电子",
        "change_pct": 3.2,
        "source": "unit",
    }
    assert result["coverage"] == {
        "indices": True,
        "breadth": True,
        "sector_rankings": True,
        "concept_rankings": True,
    }
    assert all(block["status"] == "fresh" for block in result["blocks"].values())


def test_slow_dimension_does_not_blank_completed_dashboard_blocks():
    release_breadth = Event()

    def fetch(_region, block):
        if block == "breadth":
            release_breadth.wait(timeout=2)
        return _result(block)

    started_at = time.monotonic()
    try:
        with (
            patch.object(service, "get_config", return_value=_config(budget=0.5)),
            patch.object(service, "MarketAnalyzer", _FakeAnalyzer),
            patch.object(service, "_fetch_market_dashboard_block", side_effect=fetch),
        ):
            result = service.build_market_dashboard("cn")
    finally:
        release_breadth.set()

    elapsed = time.monotonic() - started_at
    assert elapsed < 1.2
    assert result["data_status"] == "partial"
    assert result["coverage"]["indices"] is True
    assert result["coverage"]["breadth"] is False
    assert result["blocks"]["breadth"]["status"] == "refreshing"
    assert result["refreshing"] is True


def test_failed_refresh_keeps_last_successful_value_and_marks_it_stale():
    with (
        patch.object(service, "get_config", return_value=_config(fresh_ttl=60)),
        patch.object(service, "MarketAnalyzer", _FakeAnalyzer),
        patch.object(service, "_fetch_market_dashboard_block", side_effect=lambda _region, block: _result(block)),
    ):
        first = service.build_market_dashboard("cn")

    assert first["data_status"] == "ok"

    with (
        patch.object(service, "get_config", return_value=_config(fresh_ttl=0, stale_ttl=1800)),
        patch.object(service, "MarketAnalyzer", _FakeAnalyzer),
        patch.object(
            service,
            "_fetch_market_dashboard_block",
            side_effect=lambda _region, block: _result(block, usable=False),
        ),
    ):
        second = service.build_market_dashboard("cn")

    assert second["data_status"] == "stale"
    assert second["is_stale"] is True
    assert second["indices"][0]["name"] == "上证指数"
    assert second["breadth"]["up_count"] == 3200
    assert all(block["status"] == "stale" for block in second["blocks"].values())


def test_stale_cache_returns_quickly_while_refresh_continues_in_background():
    with (
        patch.object(service, "get_config", return_value=_config(fresh_ttl=60)),
        patch.object(service, "MarketAnalyzer", _FakeAnalyzer),
        patch.object(service, "_fetch_market_dashboard_block", side_effect=lambda _region, block: _result(block)),
    ):
        service.build_market_dashboard("cn")

    release_refresh = Event()

    def slow_refresh(_region, block):
        release_refresh.wait(timeout=2)
        return _result(block)

    started_at = time.monotonic()
    try:
        with (
            patch.object(service, "get_config", return_value=_config(budget=0.5, fresh_ttl=0)),
            patch.object(service, "MarketAnalyzer", _FakeAnalyzer),
            patch.object(service, "_fetch_market_dashboard_block", side_effect=slow_refresh),
        ):
            result = service.build_market_dashboard("cn")
    finally:
        release_refresh.set()

    assert time.monotonic() - started_at < 0.8
    assert result["data_status"] == "stale"
    assert result["refreshing"] is True
    assert result["indices"][0]["name"] == "上证指数"


def test_build_market_dashboard_does_not_fake_non_cn_dimensions():
    with (
        patch.object(service, "get_config", return_value=_config()),
        patch.object(service, "MarketAnalyzer", _FakeAnalyzer),
        patch.object(service, "_fetch_market_dashboard_block", return_value=_result("indices")),
    ):
        result = service.build_market_dashboard("us")

    assert result["data_status"] == "ok"
    assert result["breadth"]["available"] is False
    assert result["rankings"]["available"] is False
    assert result["blocks"]["breadth"]["status"] == "unsupported"


def test_persisted_market_review_warms_last_known_dashboard_blocks():
    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def all(self):
            return [row]

    generated_at = datetime.now().astimezone().isoformat()
    row = SimpleNamespace(
        id=1,
        created_at=datetime.now().astimezone(),
        context_snapshot={
            "market_review_payload": {
                "region": "cn",
                "date": "2026-08-11",
                "generated_at": generated_at,
                "indices": [{
                    "code": "000001",
                    "name": "上证指数",
                    "current": 3600,
                    "change": 18,
                    "change_pct": 0.5,
                }],
                "breadth": {"up_count": 3200, "down_count": 1900},
                "sectors": {"top": [{"name": "电子", "change_pct": 3.2}], "bottom": []},
                "concepts": {"top": [], "bottom": []},
            },
        },
    )
    fake_db = SimpleNamespace(get_session=lambda: _FakeSession())
    with service._DASHBOARD_STATE_LOCK:
        service._DASHBOARD_PERSISTED_LOADED.discard("cn")

    with patch.object(service.DatabaseManager, "get_instance", return_value=fake_db):
        service._load_persisted_market_dashboard_cache("cn")

    index_cache = service._read_market_dashboard_cache("cn", "indices")
    breadth_cache = service._read_market_dashboard_cache("cn", "breadth")
    assert index_cache is not None
    assert index_cache.value[0].name == "上证指数"
    assert breadth_cache is not None
    assert breadth_cache.value["up_count"] == 3200
    assert service._read_market_dashboard_cache("cn", "concepts") is None


def test_build_market_dashboard_rejects_unknown_region():
    with pytest.raises(ValueError, match="market target"):
        service.build_market_dashboard("moon")
