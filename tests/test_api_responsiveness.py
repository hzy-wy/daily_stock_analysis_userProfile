"""Regression coverage for blocking work dispatched by asynchronous endpoints."""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.requests import Request

from api.v1.endpoints import agent, stocks
from api.v1.endpoints import analysis


@pytest.mark.parametrize("operation", ["list", "messages", "delete", "import"])
def test_blocking_endpoint_work_runs_outside_event_loop(operation):
    async def run():
        loop_thread = threading.get_ident()
        worker_threads = []

        def work(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            return 0 if operation == "delete" else []

        db = SimpleNamespace(
            get_chat_sessions=work,
            get_conversation_messages=work,
            delete_conversation_session=work,
        )
        with patch("src.storage.get_db", return_value=db), patch.object(
            stocks, "parse_import_from_text", side_effect=work
        ):
            if operation == "list":
                await agent.list_chat_sessions()
            elif operation == "messages":
                await agent.get_chat_session_messages("session")
            elif operation == "delete":
                await agent.delete_chat_session("session")
            else:
                async def receive():
                    return {"type": "http.request", "body": b'{"text":"600519"}'}

                request = Request({
                    "type": "http", "method": "POST", "path": "/parse-import",
                    "headers": [(b"content-type", b"application/json")],
                }, receive)
                await stocks.parse_import(request)
        assert worker_threads
        assert all(worker != loop_thread for worker in worker_threads)

    asyncio.run(run())


@pytest.mark.parametrize("concurrency", [1, 5, 20])
def test_auth_requests_leave_event_loop_responsive(concurrency, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from api.v1.endpoints import auth

    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_status(request):
        calls.append(threading.get_ident())
        started.set()
        assert release.wait(3), "Health request could not run while authentication was blocked"
        return {"loggedIn": False}

    monkeypatch.setattr(auth, "is_multi_user_mode", lambda: False)
    monkeypatch.setattr(auth, "_get_auth_status_dict", slow_status)

    @app.get("/health")
    async def health():
        return {"ok": True}

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending = [asyncio.create_task(client.get("/auth/status")) for _ in range(concurrency)]
            try:
                deadline = time.monotonic() + 2
                while not started.is_set() and time.monotonic() < deadline:
                    await asyncio.sleep(0.001)
                assert started.is_set()
                assert len(calls) == 1
                response = await asyncio.wait_for(client.get("/health"), timeout=1)
                assert response.status_code == 200
                assert all(thread != threading.get_ident() for thread in calls)
            finally:
                release.set()
                responses = await asyncio.gather(*pending)
            assert all(response.status_code == 200 for response in responses)
    asyncio.run(run())


def test_task_stream_subscribes_before_first_yield_and_cleans_up():
    async def run():
        subscribers = []
        queue = SimpleNamespace(
            subscribe=subscribers.append,
            unsubscribe=subscribers.remove,
            list_pending_tasks=lambda: [],
        )
        with patch.object(analysis, "get_task_queue", return_value=queue):
            response = await analysis.task_stream()
            stream = response.body_iterator
            assert "connected" in await anext(stream)
            assert len(subscribers) == 1
            subscribers[0].put_nowait({"type": "task_completed", "data": {"task_id": "done"}})
            assert "task_completed" in await anext(stream)
            await stream.aclose()
            assert subscribers == []

    asyncio.run(run())


def test_agent_stream_buffer_is_bounded_and_terminal_event_wins():
    queue = asyncio.Queue(maxsize=3)
    for index in range(1000):
        agent._enqueue_stream_event(
            queue,
            {"type": "thinking", "step": index},
        )
        assert queue.qsize() <= 3

    agent._enqueue_stream_event(queue, {"type": "done", "success": True})
    assert queue.qsize() == 1
    assert queue.get_nowait() == {"type": "done", "success": True}
