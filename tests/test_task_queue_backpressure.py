"""Real worker admission and slow-subscriber regressions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event

import pytest

from src.services import task_queue as module
from src.services.task_queue import (
    AnalysisTaskQueue,
    DuplicateTaskError,
    TaskInfo,
    TaskQueueFullError,
    TaskStatus,
)


@pytest.fixture
def queue(monkeypatch):
    monkeypatch.setattr(AnalysisTaskQueue, "_instance", None)
    monkeypatch.setattr(AnalysisTaskQueue, "_current_owner_user_id", staticmethod(lambda: None))
    instance = AnalysisTaskQueue(max_workers=1)
    yield instance
    instance.shutdown()


def test_concurrent_admission_is_bounded_and_recovers(queue, monkeypatch):
    monkeypatch.setattr(module, "MAX_ACTIVE_TASKS", 3)
    release = Event()

    def work():
        assert release.wait(5)
        return {"ok": True}

    def submit(index):
        try:
            return queue.submit_background_task(work, stock_code=str(index))
        except TaskQueueFullError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(submit, range(20)))
        accepted = [task for task in results if task is not None]
        assert len(accepted) == 3
        assert len(queue._tasks) == 3
        assert len(queue._futures) == 3
    finally:
        release.set()
    for future in list(queue._futures.values()):
        future.result(timeout=5)
    recovered = queue.submit_background_task(lambda: {"ok": True}, stock_code="new")
    assert queue._futures[recovered.task_id].result(timeout=5) == {"ok": True}


def test_generic_task_dedupe_is_atomic_and_released_after_completion(queue):
    release = Event()

    def work():
        assert release.wait(5)
        return {"ok": True}

    first = queue.submit_background_task(
        work,
        stock_code="backtest:600519",
        dedupe=True,
    )
    with pytest.raises(DuplicateTaskError) as error:
        queue.submit_background_task(
            work,
            stock_code="backtest:600519",
            dedupe=True,
        )
    assert error.value.existing_task_id == first.task_id

    release.set()
    queue._futures[first.task_id].result(timeout=5)
    second = queue.submit_background_task(
        lambda: {"ok": True},
        stock_code="backtest:600519",
        dedupe=True,
    )
    assert queue._futures[second.task_id].result(timeout=5) == {"ok": True}


def test_batch_rejection_is_atomic_and_duplicates_use_no_capacity(queue, monkeypatch):
    monkeypatch.setattr(module, "MAX_ACTIVE_TASKS", 1)
    task = TaskInfo(task_id="existing", stock_code="600519")
    queue._tasks[task.task_id] = task
    queue._analyzing_stocks["600519"] = task.task_id
    accepted, duplicates = queue.submit_tasks_batch(["600519"])
    assert not accepted and len(duplicates) == 1
    with pytest.raises(TaskQueueFullError):
        queue.submit_tasks_batch(["600519", "000001", "000002"])
    assert list(queue._tasks) == ["existing"]
    assert not queue._futures


def test_status_filter_precedes_limit_and_keeps_owner_scope(queue, monkeypatch):
    now = datetime.now()
    queue._tasks = {
        "active": TaskInfo(task_id="active", stock_code="1", owner_user_id="a", created_at=now),
        "other": TaskInfo(task_id="other", stock_code="2", owner_user_id="b", created_at=now),
        "done": TaskInfo(task_id="done", stock_code="3", owner_user_id="a",
                         status=TaskStatus.COMPLETED, created_at=now + timedelta(seconds=1)),
    }
    monkeypatch.setattr(queue, "_current_owner_user_id", lambda: "a")
    assert [t.task_id for t in queue.list_all_tasks(limit=1, statuses=["pending"])] == ["active"]


def test_overflow_is_bounded_and_requests_resynchronization():
    async def run():
        events = asyncio.Queue(maxsize=3)
        for index in range(1000):
            AnalysisTaskQueue._enqueue_event(events, {"type": "task_progress", "data": {"n": index}})
            assert events.qsize() <= 3
        buffered = []
        while not events.empty():
            buffered.append(events.get_nowait())
        assert any(event["type"] == "resync_required" for event in buffered)
    asyncio.run(run())


def test_queue_full_http_contract():
    import httpx
    from fastapi import FastAPI
    from api.middlewares.error_handler import add_error_handlers

    app = FastAPI()
    add_error_handlers(app)

    @app.post("/submit")
    def submit():
        raise TaskQueueFullError()

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/submit")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "30"
        assert response.json()["error"] == "task_queue_full"
    asyncio.run(run())
