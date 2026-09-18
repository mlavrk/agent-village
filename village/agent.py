"""A villager: role, memory, prompt assembly, decision as strict JSON."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .bus import Message, MessageBus
from .zen import parse_json

ROLE_BRIEF = {
    "mafia": (
        "You are MAFIA. At night you and your partners pick a victim in a private "
        "channel. By day you play innocent: hesitate, agree with others, gently "
        "steer suspicion onto townsfolk. Never confess."
    ),
    "doctor": (
        "You are the DOCTOR. Each night you save one villager. Yourself — at most "
        "once in the whole game, and never the same person two nights running. "
        "The mafia strikes whoever threatens them: loudmouths, accusers, anyone "
        "who smells like the detective. Cover those. By day you are an ordinary "
        "villager: reveal yourself and you are the next to die."
    ),
    "detective": (
        "You are the DETECTIVE. Each night you investigate one villager and learn "
        "whether they are mafia. By day you may hint at what you found, but an "
        "open reveal makes you target number one."
    ),
    "villager": (
        "You are an ordinary VILLAGER. No special power — only ears, logic and a "
        "voice. Your job is to catch the mafia in their contradictions."
    ),
}

STYLE = (
    "Speak sharp and short: one or two sentences, like a village argument. "
    "No bullet-point analysis, no preambles. "
    "Silence is a last resort: if you have nothing to say, ask a question or "
    "back someone else's suspicion, but do not go quiet."
)

PROTOCOL = (
    "Reply with ONE JSON object and nothing else — no prose, no markdown:\n"
    '{"thought": "<one private sentence>", "say": "<spoken line or null>", '
    '"target": "<name or null>"}'
)

PHASE_TITLE = {
    "setup": lambda d: "Beginning",
    "night": lambda d: f"Night {d + 1}",
    "dawn": lambda d: f"Morning of day {d}",
    "day": lambda d: f"Day {d}, discussion",
    "vote": lambda d: f"Day {d}, vote",
    "over": lambda d: "Finale",
}


def transcript(messages) -> str:
    """Feed with day and phase headers: without them agents confuse then and now."""
    lines: list[str] = []
    current = None
    for message in messages:
        key = (message.day, message.phase)
        if key != current:
            current = key
            title = PHASE_TITLE.get(message.phase, lambda d: message.phase)(message.day)
            lines.append(f"── {title} ──")
        lines.append(message.render())
    return "\n".join(lines)


@dataclass
class Decision:
    say: str | None
    target: str | None
    thought: str
    raw: str
    partial: bool = False  # reply arrived truncated, fields salvaged piecemeal


@dataclass
class Agent:
    name: str
    role: str
    persona: str
    model: str
    alive: bool = True
    notes: list[str] = field(default_factory=list)  # private knowledge: checks, heals

    @property
    def team(self) -> str:
        return "mafia" if self.role == "mafia" else "town"

    def remember(self, note: str) -> None:
        self.notes.append(note)

    def system_prompt(self, allies: list[str]) -> str:
        parts = [
            f"Your name is {self.name}. {self.persona}",
            ROLE_BRIEF[self.role],
            STYLE,
            PROTOCOL,
        ]
        if self.role == "mafia" and allies:
            parts.insert(2, f"Your partners: {', '.join(allies)}. Never touch them.")
        return "\n\n".join(parts)

    def user_prompt(self, *, day: int, phase: str, alive: list[str], bus: MessageBus, task: str) -> str:
        history = transcript(bus.inbox(self.name)) or "(silence so far)"
        blocks = [
            f"Day {day}, phase: {phase}.",
            "Alive: " + ", ".join(alive),
        ]
        if self.notes:
            blocks.append("What you know privately:\n" + "\n".join(f"- {n}" for n in self.notes))
        blocks.append("What you heard:\n" + history)
        blocks.append(f"TASK: {task}")
        return "\n\n".join(blocks)

    async def decide(self, client, *, day, phase, alive, bus, task, allies=(), max_tokens=320) -> Decision:
        messages = [
            {"role": "system", "content": self.system_prompt(list(allies))},
            {"role": "user", "content": self.user_prompt(day=day, phase=phase, alive=alive, bus=bus, task=task)},
        ]
        raw = await client.chat(self.model, messages, agent=self.name, max_tokens=max_tokens)
        data = parse_json(raw)
        say = data.get("say")
        target = data.get("target")
        if isinstance(say, str) and _is_silence(say):
            say = None
        if isinstance(target, str):
            target = target.strip().strip(".,!?\"'")
            if target.lower() in {"", "null", "none", "nobody", "no one"}:
                target = None
        return Decision(
            say=say if isinstance(say, str) else None,
            target=target if isinstance(target, str) else None,
            thought=str(data.get("thought") or ""),
            raw=raw,
            partial=bool(data.get("_partial")),
        )


def _is_silence(say: str) -> bool:
    """Models sometimes "speak" a bare ellipsis or a dash — that is silence."""
    stripped = say.strip().lower()
    if stripped in {"", "null", "none", "pass", "(silence)", "silence"}:
        return True
    return bool(re.fullmatch(r"[.\-—–_*\s…]+", stripped))


_MIN_FRAGMENT = 3  # shorter than this, a "name fragment" is just noise


def match_name(candidate: str | None, alive: list[str]) -> str | None:
    """Models fumble case, add punctuation or bury the name in a sentence."""
    if not candidate:
        return None
    lowered = candidate.strip().lower()
    if not lowered:
        return None
    for name in alive:
        if name.lower() == lowered:
            return name
    # a name spoken inside a sentence: the FIRST one named wins, not whoever
    # happens to sit earliest in the seating order
    best: tuple[int, str] | None = None
    for name in alive:
        found = re.search(rf"\b{re.escape(name.lower())}\b", lowered)
        if found and (best is None or found.start() < best[0]):
            best = (found.start(), name)
    if best:
        return best[1]
    # a name cut short ("Marth") — but only when it is long enough to be a
    # fragment of a name rather than a stray letter
    if len(lowered) >= _MIN_FRAGMENT:
        for name in alive:
            if name.lower().startswith(lowered):
                return name
    return None
