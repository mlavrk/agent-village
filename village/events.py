"""Event bus: the engine publishes, the dashboard subscribes."""
from __future__ import annotations

import asyncio
import time
from typing import Any


class EventBus:
    """Fan-out that keeps history: a late subscriber still sees the whole game."""

    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._seq = 0

    def emit(self, kind: str, /, **payload: Any) -> dict[str, Any]:
        self._seq += 1
        event = {"seq": self._seq, "t": time.time(), "kind": kind, **payload}
        self.history.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        for event in self.history:
            queue.put_nowait(event)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)
