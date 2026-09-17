"""The doctor may save themselves at most once per game."""
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
    game = MafiaGame(MockClient(Usage()), EventBus(), GameConfig(players=6, seed=2))
    game.setup()
    doctor = next(a for a in game.agents if a.role == "doctor")

    async def always_self(agent, task, max_tokens=220):
        return Decision(say=None, target=doctor.name, thought="", raw="")

    game._ask = always_self
    picks = [await game._doctor_choice() for _ in range(4)]
    print("doctor:", doctor.name, "| nights:", picks, "| self-heals:", game.self_heals)
    assert picks.count(doctor.name) <= 1, "the doctor healed themselves more than once"
    assert all(picks[i] != picks[i + 1] for i in range(len(picks) - 1)), "healed the same person twice in a row"
    print("OK")


asyncio.run(main())
