"""The night channel is private. If it ever leaks, every game is ruined."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from village.bus import Message, MessageBus
from village.events import EventBus
from village.game import GameConfig, MafiaGame
from village.mock import MockClient
from village.zen import Usage


def check_isolation() -> None:
    bus = MessageBus()
    for name in ("Boss", "Thug", "Clara"):
        bus.subscribe(name, "village")
    for name in ("Boss", "Thug"):
        bus.subscribe(name, "mafia")

    bus.post(Message(sender="Clara", channel="village", text="good morning"))
    bus.post(Message(sender="Boss", channel="mafia", text="we take Clara tonight"))
    bus.post(Message(sender="Thug", channel="mafia", text="agreed"))
    bus.post(Message(sender="Boss", channel="village", text="I slept like a stone"))

    clara = [m.text for m in bus.inbox("Clara")]
    assert "we take Clara tonight" not in clara, "the plot leaked to the town"
    assert not any(m.channel == "mafia" for m in bus.inbox("Clara")), "town sees a mafia message"
    assert clara == ["good morning", "I slept like a stone"], f"town feed wrong: {clara}"
    print("  town     sees only the square")

    boss = [m.text for m in bus.inbox("Boss")]
    assert "we take Clara tonight" in boss and "good morning" in boss, f"mafia feed wrong: {boss}"
    assert boss == ["good morning", "we take Clara tonight", "agreed", "I slept like a stone"], \
        f"channels interleaved out of order: {boss}"
    print("  mafia    sees both, in one chronological feed")

    # an unknown agent is subscribed to nothing, not to everything
    assert bus.inbox("Nobody") == [], "an unsubscribed name got a feed"
    print("  stranger sees nothing")


def check_inbox_cap() -> None:
    """A loud night must not push the whole day out of a mafioso's memory."""
    bus = MessageBus()
    bus.subscribe("Boss", "village")
    bus.subscribe("Boss", "mafia")
    for i in range(50):
        bus.post(Message(sender="Boss", channel="mafia", text=f"night-{i}"))
    for i in range(3):
        bus.post(Message(sender="Clara", channel="village", text=f"day-{i}"))

    feed = bus.inbox("Boss")
    assert len(feed) == 40, f"cap not applied: {len(feed)} messages"
    village = [m.text for m in feed if m.channel == "village"]
    assert village == ["day-0", "day-1", "day-2"], f"the day was evicted: {village}"
    assert [m.seq for m in feed] == sorted(m.seq for m in feed), "cap broke the ordering"
    print(f"  40-cap   keeps the newest, day survives ({len(village)} village lines)")

    short = bus.inbox("Boss", limit=2)
    assert [m.text for m in short] == ["day-1", "day-2"], f"limit ignored: {short}"
    print("  limit    honoured")


def check_game_wiring() -> None:
    """setup() must subscribe mafia to 'mafia' and nobody else."""
    game = MafiaGame(MockClient(Usage()), EventBus(), GameConfig(players=8, seed=7))
    game.setup()
    for agent in game.agents:
        channels = game.bus.subscriptions[agent.name]
        assert "village" in channels, f"{agent.name} cannot hear the square"
        if agent.role == "mafia":
            assert "mafia" in channels, f"mafia {agent.name} is cut off from partners"
        else:
            assert "mafia" not in channels, f"{agent.role} {agent.name} is wired into the mafia channel"
    print(f"  setup    {len(game.mafia())} mafia wired in, {len(game.agents) - len(game.mafia())} townsfolk out")


def main() -> None:
    check_isolation()
    check_inbox_cap()
    check_game_wiring()
    print("OK")


main()
