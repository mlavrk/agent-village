"""Stub provider: the engine and dashboard can be debugged with no key and no tokens."""
from __future__ import annotations

import asyncio
import json
import random

from .zen import Usage

_CHATTER = [
    "I slept through the whole night, I swear it.",
    "{target} has been far too quiet, and I do not like it.",
    "Yesterday {target} agreed with the majority a little too fast.",
    "Let us not rush, or we will hang one of our own.",
    "I have no proof, but my gut points at {target}.",
    "I will vouch for {target}, they are no mafia.",
]


class MockClient:
    """Same interface as ZenClient, but answers are generated locally."""

    def __init__(self, usage: Usage, concurrency: int = 8) -> None:
        self.usage = usage
        self._gate = asyncio.Semaphore(concurrency)

    async def close(self) -> None:
        return None

    async def chat(self, model, messages, *, agent="?", max_tokens=400, **_kw) -> str:
        async with self._gate:
            await asyncio.sleep(random.uniform(0.2, 0.8))
        prompt = messages[-1]["content"]
        others = _candidates(prompt, agent)
        target = random.choice(others) if others else "nobody"
        reply = {
            "thought": f"({model}) weighing who looks suspicious",
            "say": random.choice(_CHATTER).format(target=target),
            "target": target,
        }
        self.usage.add(agent, len(prompt) // 4, 60)
        return json.dumps(reply, ensure_ascii=False)


def _candidates(prompt: str, me: str) -> list[str]:
    """Read the living from the "Alive: A, B, C" line of the prompt."""
    for line in prompt.splitlines():
        if line.startswith("Alive:"):
            names = [n.strip() for n in line.split(":", 1)[1].split(",")]
            return [n for n in names if n and n != me]
    return []


async def probe(self, model: str) -> tuple[bool, str]:  # pragma: no cover - parity helper
    return True, "ok"


MockClient.probe = probe
