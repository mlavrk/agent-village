"""Bad table sizes are rejected, and the doctor always has a legal move."""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from village.agent import Decision
from village.events import EventBus
from village.game import ROLE_PLAN, GameConfig, MafiaGame
from village.mock import MockClient
from village.zen import Usage


def new_game(**kw) -> MafiaGame:
    return MafiaGame(MockClient(Usage()), EventBus(), GameConfig(**kw))


def check_player_counts() -> None:
    for players in sorted(ROLE_PLAN):
        game = new_game(players=players, seed=1)
        game.setup()
        assert len(game.agents) == players, f"{players}: built {len(game.agents)} agents"
        assert len({a.name for a in game.agents}) == players, f"{players}: duplicate names"
        assert game.mafia(), f"{players}: no mafia dealt"
        assert len(game.mafia()) < players - len(game.mafia()), f"{players}: mafia already win"
        print(f"  {players} players  ok ({len(game.mafia())} mafia)")

    for players in (0, 1, 5, 9, 12, -1):
        try:
            new_game(players=players).setup()
        except ValueError as exc:            # used to be a bare KeyError
            assert str(players) in str(exc), f"{players}: unhelpful message {exc}"
            print(f"  {players:>3} players  rejected: {exc}")
        else:
            raise AssertionError(f"{players} players was accepted")


async def check_doctor_has_a_move() -> None:
    """Both heal bans at once used to leave rng.choice() an empty list."""
    game = new_game(players=6, seed=3)
    game.setup()
    doctor = next(a for a in game.agents if a.role == "doctor")
    survivor = next(a for a in game.agents if a is not doctor)
    for agent in game.agents:
        agent.alive = agent in (doctor, survivor)

    # every living player is banned: the survivor by last_healed, the doctor
    # by the one-self-heal rule
    game.last_healed = survivor.name
    game.self_heals = 1

    async def names_nobody(agent, task, max_tokens=220):
        return Decision(say=None, target=None, thought="", raw="")

    game._ask = names_nobody
    healed = await game._doctor_choice()          # used to raise IndexError
    assert healed in game.alive_names, f"healed {healed!r}, not among {game.alive_names}"
    print(f"  exhausted options   healed {healed} instead of crashing")

    # and the ordinary case still respects the ban
    game2 = new_game(players=6, seed=3)
    game2.setup()
    game2.last_healed = game2.alive_names[0]
    game2._ask = names_nobody
    healed2 = await game2._doctor_choice()
    assert healed2 != game2.alive_names[0], "healed the same person two nights running"
    print(f"  normal night        avoided {game2.alive_names[0]}, healed {healed2}")


def main() -> None:
    check_player_counts()
    asyncio.run(check_doctor_has_a_move())
    print("OK")


main()
