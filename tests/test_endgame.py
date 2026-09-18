"""check_end decides when the village stops. Every branch, and their order."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from village.events import EventBus
from village.game import GameConfig, MafiaGame
from village.mock import MockClient
from village.zen import Usage


def board(roles, *, day=1, max_days=6, budget=200_000, spent=0) -> MafiaGame:
    """A 6-player game forced onto an arbitrary surviving line-up."""
    usage = Usage()
    usage.prompt_tokens = spent
    game = MafiaGame(
        MockClient(usage),
        EventBus(),
        GameConfig(players=6, seed=1, max_days=max_days, token_budget=budget),
    )
    game.setup()
    for agent, role in zip(game.agents, roles):
        agent.role, agent.alive = role, True
    for agent in game.agents[len(roles):]:
        agent.alive = False
    game.day = day
    return game


CASES = [
    # (label, surviving roles, kwargs, expected winner)
    ("last mafia hanged", ["doctor", "villager", "villager"], {}, "town"),
    ("mafia wiped, one villager", ["villager"], {}, "town"),
    ("mafia outnumber town", ["mafia", "mafia", "villager"], {}, "mafia"),
    ("parity: 1 v 1", ["mafia", "villager"], {}, "mafia"),
    ("parity: 2 v 2", ["mafia", "mafia", "villager", "detective"], {}, "mafia"),
    ("town still ahead 2 v 1", ["mafia", "villager", "doctor"], {}, None),
    ("town far ahead", ["mafia", "villager", "doctor", "detective"], {}, None),
    ("day cap reached", ["mafia", "doctor", "villager"], {"day": 6, "max_days": 6}, "draw"),
    ("day cap exceeded", ["mafia", "doctor", "villager"], {"day": 9, "max_days": 6}, "draw"),
    ("day below cap", ["mafia", "doctor", "villager"], {"day": 5, "max_days": 6}, None),
    ("budget spent", ["mafia", "doctor", "villager"], {"budget": 1000, "spent": 1000}, "budget"),
    ("budget exceeded", ["mafia", "doctor", "villager"], {"budget": 1000, "spent": 5000}, "budget"),
    ("budget untouched", ["mafia", "doctor", "villager"], {"budget": 1000, "spent": 999}, None),
    # precedence: a decided game beats the two "ran out of X" stops
    ("win beats budget", ["doctor", "villager"], {"budget": 10, "spent": 999}, "town"),
    ("win beats day cap", ["mafia", "villager"], {"day": 9, "max_days": 6}, "mafia"),
    ("day cap beats budget", ["mafia", "doctor", "villager"],
     {"day": 9, "max_days": 6, "budget": 10, "spent": 999}, "draw"),
]


def main() -> None:
    for label, roles, kwargs, want in CASES:
        game = board(roles, **kwargs)
        got = game.check_end()
        assert got == want, f"{label}: check_end() -> {got!r}, wanted {want!r}"
        print(f"  {label:24} {'+'.join(roles):38} -> {got!r}")

    # completion counts both halves of the budget, not just the prompt side
    game = board(["mafia", "doctor", "villager"], budget=1000, spent=0)
    game.client.usage.add("Martha", 400, 400)
    assert game.check_end() is None, "800 of 1000 tokens already stopped the game"
    game.client.usage.add("Martha", 100, 100)
    assert game.check_end() == "budget", "completion tokens are not counted against the budget"
    print("  budget counts prompt + completion")
    print("OK")


main()
