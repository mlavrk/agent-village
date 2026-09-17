"""A tied vote must trigger a run-off between the leaders."""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from village.agent import Decision
from village.events import EventBus
from village.game import GameConfig, MafiaGame
from village.mock import MockClient
from village.zen import Usage


async def main() -> None:
    events = EventBus()
    game = MafiaGame(MockClient(Usage()), events, GameConfig(players=6, seed=1))
    game.setup()
    names = game.alive_names

    # round one: 2-2-2, three leaders; run-off: almost everyone for names[1]
    first = {names[0]: names[1], names[1]: names[0], names[2]: names[1],
             names[3]: names[0], names[4]: names[2], names[5]: names[2]}

    async def fake_ask(agent, task, max_tokens=220):
        if "Run-off" in task:
            target = names[1] if agent.name != names[1] else names[0]
        else:
            target = first[agent.name]
        return Decision(say=f"I vote {target}", target=target, thought="", raw="")

    game._ask = fake_ask
    await game.vote()

    narration = [e["text"] for e in events.history if e["kind"] == "narration"]
    results = [e for e in events.history if e["kind"] == "vote_result"]
    for line in narration:
        print("  ", line)
    assert any("Run-off" in t or "tied" in t for t in narration), "no run-off happened"
    assert results[-1]["lynched"] == names[1], "the wrong villager was hanged"
    print("OK")


asyncio.run(main())
