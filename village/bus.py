"""Channels and mailboxes: an agent sees exactly what is addressed to it."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count


@dataclass
class Message:
    sender: str
    channel: str  # "village" (everyone) | "mafia" (private) | "system"
    text: str
    phase: str = ""
    day: int = 0
    seq: int = 0  # global ordering, assigned by the bus

    def render(self) -> str:
        return f"{self.sender}: {self.text}"


@dataclass
class MessageBus:
    """One feed per channel plus per-agent subscriptions."""

    channels: dict[str, list[Message]] = field(default_factory=dict)
    subscriptions: dict[str, set[str]] = field(default_factory=dict)  # agent -> channels
    _seq: count = field(default_factory=lambda: count(1))

    def subscribe(self, agent: str, channel: str) -> None:
        self.subscriptions.setdefault(agent, set()).add(channel)

    def post(self, message: Message) -> Message:
        message.seq = next(self._seq)
        self.channels.setdefault(message.channel, []).append(message)
        return message

    def inbox(self, agent: str, limit: int = 40) -> list[Message]:
        """Visible channels merged into a single chronological feed."""
        visible = self.subscriptions.get(agent, set())
        merged = [m for ch in visible for m in self.channels.get(ch, [])]
        merged.sort(key=lambda m: m.seq)
        return merged[-limit:]
