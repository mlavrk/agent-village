"""Dashboard: serve the page and stream game events over SSE."""
from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, StreamingResponse
from starlette.routing import Route

STATIC = Path(__file__).resolve().parent / "static"
TICK = 1.0           # how often we check whether it is time to close
KEEPALIVE_TICKS = 5  # ": keepalive" every 5s so the connection is not dropped


def build_app(events, runner) -> Starlette:
    """runner(events) -> the game coroutine, started with the server.

    After Ctrl+C uvicorn first waits for connections to close and only then
    shuts down the lifespan, so an endless SSE stream must watch for the stop
    itself: it polls app.state.should_stop, which run.py sets.
    """
    shutdown = asyncio.Event()

    async def index(_request):
        return FileResponse(STATIC / "dashboard.html")

    async def stream(request):
        queue = events.subscribe()
        should_stop = getattr(request.app.state, "should_stop", lambda: False)

        def stopping() -> bool:
            return shutdown.is_set() or should_stop()

        async def generator():
            idle_ticks = 0
            try:
                while not stopping():
                    getter = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait({getter}, timeout=TICK)
                    if getter not in done:
                        getter.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await getter
                        if stopping() or await request.is_disconnected():
                            break
                        idle_ticks += 1
                        if idle_ticks >= KEEPALIVE_TICKS:
                            idle_ticks = 0
                            yield ": keepalive\n\n"
                        continue
                    idle_ticks = 0
                    yield f"data: {json.dumps(getter.result(), ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                pass  # client left or the server is going down — not an error
            finally:
                events.unsubscribe(queue)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(runner(events))
        try:
            yield
        finally:
            shutdown.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return Starlette(routes=[Route("/", index), Route("/events", stream)], lifespan=lifespan)
