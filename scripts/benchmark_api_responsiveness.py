"""Compare ASGI loop delay with simulated blocking auth work, without external I/O.

Run from the repository root. This measures scheduling isolation, not production
throughput, password hashing cost, or real data-provider latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from api.auth_dispatch import auth_worker  # noqa: E402


async def measure(concurrency: int, delay: float, offloaded: bool) -> dict:
    app = FastAPI()

    def work():
        time.sleep(delay)
        return {"ok": True}

    async def blocking():
        return work()

    app.add_api_route("/auth", auth_worker(work) if offloaded else blocking)
    loop_delays = []
    request_times = []
    done = asyncio.Event()

    async def monitor():
        while not done.is_set():
            expected = time.perf_counter() + 0.005
            await asyncio.sleep(0.005)
            loop_delays.append(max(0.0, time.perf_counter() - expected) * 1000)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://benchmark") as client:
        async def request():
            started = time.perf_counter()
            response = await client.get("/auth")
            response.raise_for_status()
            request_times.append((time.perf_counter() - started) * 1000)

        observer = asyncio.create_task(monitor())
        await asyncio.sleep(0)
        started = time.perf_counter()
        try:
            await asyncio.gather(*(request() for _ in range(concurrency)))
        finally:
            total_ms = (time.perf_counter() - started) * 1000
            done.set()
            await observer
    return {
        "mode": "worker" if offloaded else "blocking_baseline",
        "concurrency": concurrency,
        "batch_ms": round(total_ms, 2),
        "request_median_ms": round(statistics.median(request_times), 2),
        "max_event_loop_delay_ms": round(max(loop_delays, default=0), 2),
    }


async def main(delay: float):
    return [await measure(count, delay, offloaded)
            for count in (1, 5, 20) for offloaded in (False, True)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay-ms", type=float, default=25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0 < args.delay_ms <= 1000:
        parser.error("--delay-ms must be in (0, 1000]")
    result = {"simulated_work_ms": args.delay_ms, "results": asyncio.run(main(args.delay_ms / 1000))}
    content = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)
