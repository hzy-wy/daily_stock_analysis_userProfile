"""Async backtest API contract tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.v1.endpoints import backtest
from api.v1.schemas.backtest import BacktestRunRequest
from src.services.task_queue import DuplicateTaskError, TaskStatus


def test_submit_backtest_returns_before_worker_execution():
    queue = MagicMock()
    queue.submit_background_task.return_value = SimpleNamespace(
        task_id="backtest-1", status=TaskStatus.PENDING, message="回测任务已提交"
    )
    request = BacktestRunRequest(code="600519", eval_window_days=10)
    with patch.object(backtest, "get_task_queue", return_value=queue):
        response = backtest.submit_backtest(request, MagicMock())
    assert response.task_id == "backtest-1"
    submitted = queue.submit_background_task.call_args
    assert submitted.kwargs["report_type"] == "backtest"
    assert submitted.kwargs["dedupe"] is True
    assert "600519" in submitted.kwargs["dedupe_key"]
    assert callable(submitted.args[0])


def test_submit_backtest_reports_existing_equivalent_task():
    queue = MagicMock()
    queue.submit_background_task.side_effect = DuplicateTaskError(
        "backtest:600519",
        "existing-1",
    )
    with patch.object(backtest, "get_task_queue", return_value=queue):
        with pytest.raises(HTTPException) as error:
            backtest.submit_backtest(BacktestRunRequest(code="600519"), MagicMock())
    assert error.value.status_code == 409
    assert error.value.detail["task_id"] == "existing-1"


def test_backtest_task_returns_typed_completed_result():
    result = {
        "processed": 1, "saved": 1, "completed": 1, "insufficient": 0,
        "errors": 0, "applied_eval_window_days": 10,
    }
    task = SimpleNamespace(
        task_id="backtest-1", report_type="backtest", status=TaskStatus.COMPLETED,
        progress=100, message="done", result=result, error=None,
    )
    with patch.object(backtest, "get_task_queue", return_value=SimpleNamespace(get_task=lambda _: task)):
        response = backtest.get_backtest_task("backtest-1")
    assert response.status == "completed"
    assert response.result and response.result.saved == 1


def test_backtest_task_rejects_unrelated_task():
    task = SimpleNamespace(report_type="detailed")
    with patch.object(backtest, "get_task_queue", return_value=SimpleNamespace(get_task=lambda _: task)):
        with pytest.raises(HTTPException) as error:
            backtest.get_backtest_task("other")
    assert error.value.status_code == 404
