"""An ellipsis is silence, not a line of dialogue."""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from village.agent import Agent
from village.bus import MessageBus

SILENT = ["...", "…", "  ", "null", "None", "--", "—", "***", "pass", "(silence)"]
SPOKEN = ["...and that is why I say Peter.", "No.", "Well?", "I saw him."]


class FakeClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def chat(self, *_args, **_kw) -> str:
        return self.reply


async def decide_with(say: str):
    agent = Agent(name="Silas", role="villager", persona="the blacksmith", model="test")
    import json

    client = FakeClient(json.dumps({"thought": "t", "say": say, "target": "Jonas"}))
    return await agent.decide(
        client, day=1, phase="day", alive=["Silas", "Jonas"], bus=MessageBus(), task="speak"
    )


async def main() -> None:
    for say in SILENT:
        decision = await decide_with(say)
        assert decision.say is None, f"{say!r} should count as silence, got {decision.say!r}"
        print(f"  silence  {say!r:14} ok")
    for say in SPOKEN:
        decision = await decide_with(say)
        assert decision.say == say, f"{say!r} was swallowed"
        print(f"  speech   {say!r:14} ok")
    print("OK")


asyncio.run(main())
