"""Mafia rules and the phase loop. Every step is published to the EventBus."""
from __future__ import annotations

import asyncio
import random
from collections import Counter
from dataclasses import dataclass

from .agent import Agent, match_name
from .bus import Message, MessageBus
from .events import EventBus
from .models import assign

CAST = [
    ("Martha", "the village gossip, knows everyone's business and loves to hint"),
    ("Silas", "the blacksmith, blunt to the point of rudeness, trusts no words"),
    ("Edith", "the herbalist, speaks in riddles and watches people's hands"),
    ("Jonas", "the miller, sparing with words, but each one is weighed"),
    ("Clara", "the young schoolteacher, tries to keep everyone at peace"),
    ("Peter", "the shepherd, simple-hearted and easily led"),
    ("Agnes", "the mayor's widow, used to giving orders"),
    ("Thomas", "the village fool, talks nonsense that sometimes lands"),
]

ROLE_PLAN = {
    6: ["mafia", "mafia", "doctor", "detective", "villager", "villager"],
    7: ["mafia", "mafia", "doctor", "detective", "villager", "villager", "villager"],
    8: ["mafia", "mafia", "mafia", "doctor", "detective", "villager", "villager", "villager"],
}


@dataclass
class GameConfig:
    players: int = 6
    discussion_rounds: int = 2
    max_days: int = 6
    seed: int | None = None
    token_budget: int = 200_000  # hard cap for one game
    model_pool: list[str] | None = None  # None -> DEFAULT_POOL from models.py


class MafiaGame:
    def __init__(self, client, events: EventBus, config: GameConfig | None = None) -> None:
        self.client = client
        self.events = events
        self.config = config or GameConfig()
        self.bus = MessageBus()
        self.rng = random.Random(self.config.seed)
        self.agents: list[Agent] = []
        self.day = 0
        self.phase = "setup"
        self.last_healed: str | None = None
        self.self_heals = 0
        self.winner: str | None = None

    # --- state -----------------------------------------------------
    @property
    def alive(self) -> list[Agent]:
        return [a for a in self.agents if a.alive]

    @property
    def alive_names(self) -> list[str]:
        return [a.name for a in self.alive]

    def by_name(self, name: str) -> Agent | None:
        return next((a for a in self.agents if a.name == name), None)

    def mafia(self, only_alive: bool = True) -> list[Agent]:
        return [a for a in (self.alive if only_alive else self.agents) if a.role == "mafia"]

    # --- plumbing --------------------------------------------------
    def _emit_state(self) -> None:
        self.events.emit(
            "state",
            day=self.day,
            phase=self.phase,
            agents=[
                {
                    "name": a.name,
                    "role": a.role,
                    "model": a.model,
                    "alive": a.alive,
                    "persona": a.persona,
                    "tokens": self.client.usage.per_agent.get(a.name, 0),
                }
                for a in self.agents
            ],
            usage={"total": self.client.usage.total, "calls": self.client.usage.calls},
        )

    def _post(self, agent: Agent, channel: str, text: str, thought: str = "") -> None:
        message = self.bus.post(
            Message(sender=agent.name, channel=channel, text=text, phase=self.phase, day=self.day)
        )
        self.events.emit(
            "speech",
            agent=agent.name,
            channel=channel,
            text=text,
            thought=thought,
            role=agent.role,
            day=self.day,
            phase=self.phase,
            seq=message.seq,
        )

    def _narrate(self, text: str) -> None:
        self.bus.post(Message(sender="Narrator", channel="village", text=text, phase=self.phase, day=self.day))
        self.events.emit("narration", text=text, day=self.day, phase=self.phase)

    def _set_phase(self, phase: str) -> None:
        self.phase = phase
        self.events.emit("phase", day=self.day, phase=phase)
        self._emit_state()

    async def _ask(self, agent: Agent, task: str, *, max_tokens: int = 220):
        self.events.emit("thinking", agent=agent.name, phase=self.phase)
        allies = [m.name for m in self.mafia() if m.name != agent.name] if agent.role == "mafia" else []
        try:
            decision = await agent.decide(
                self.client,
                day=self.day,
                phase=self.phase,
                alive=self.alive_names,
                bus=self.bus,
                task=task,
                allies=allies,
            )
        except Exception as exc:
            self.events.emit("error", agent=agent.name, text=str(exc)[:300])
            return None
        finally:
            self.events.emit("idle", agent=agent.name)
        if decision and decision.partial:
            self.events.emit("truncated", agent=agent.name, model=agent.model)
        return decision

    # --- phases ----------------------------------------------------
    def setup(self) -> None:
        cast = CAST[: self.config.players]
        roles = ROLE_PLAN[self.config.players][:]
        self.rng.shuffle(roles)
        self.agents = [
            Agent(name=name, role=role, persona=persona, model=assign(i, self.config.model_pool))
            for i, ((name, persona), role) in enumerate(zip(cast, roles))
        ]
        for agent in self.agents:
            self.bus.subscribe(agent.name, "village")
            if agent.role == "mafia":
                self.bus.subscribe(agent.name, "mafia")
        self.events.emit("game_start", players=self.config.players)
        self._set_phase("setup")
        self._narrate("The village is uneasy: one of our own turned out to be a stranger.")

    async def night(self) -> None:
        self._set_phase("night")
        self._narrate("Night falls. The village goes to sleep.")
        victim = await self._mafia_choice()
        healed, checked = await asyncio.gather(self._doctor_choice(), self._detective_choice())

        self.day += 1
        self._set_phase("dawn")
        if victim and victim == healed:
            self._narrate(f"They came for {victim} in the night, but the doctor was quicker. Everyone lives.")
            self.events.emit("saved", agent=victim)
        elif victim:
            target = self.by_name(victim)
            if target:
                target.alive = False
                self._narrate(f"Morning. {victim} was found dead.")
                self.events.emit("death", agent=victim, cause="mafia", role=target.role)
        else:
            self._narrate("Morning. The mafia could not agree — this night everyone survived.")
        if checked:
            actor = self.by_name(checked["actor"])
            # the detective may have been killed the same night: the check
            # happened, but the knowledge died with them
            self.events.emit("investigation", lost=not (actor and actor.alive), **checked)
        self._emit_state()

    async def _mafia_choice(self) -> str | None:
        killers = self.mafia()
        if not killers:
            return None
        targets = [n for n in self.alive_names if n not in {m.name for m in killers}]
        if not targets:
            return None
        votes: list[str] = []
        for index, killer in enumerate(killers):  # sequential: partners hear each other
            if index == 0:
                task = (
                    "Propose to your partners who to remove tonight and justify it. "
                    f"Put the victim's name in 'target', chosen from: {', '.join(targets)}."
                )
            else:
                # without this the second mafioso just parrots the first one
                task = (
                    "A partner already named a victim. Plain agreement is forbidden: either "
                    "object and propose someone else, or give a NEW argument they did not make. "
                    f"Put your choice in 'target', from: {', '.join(targets)}."
                )
            decision = await self._ask(killer, task)
            if not decision:
                continue
            if decision.say:
                self._post(killer, "mafia", decision.say, decision.thought)
            picked = match_name(decision.target, targets)
            if picked:
                votes.append(picked)
                self.events.emit("night_action", action="kill_vote", actor=killer.name, target=picked)
        if not votes:
            return None
        top = Counter(votes).most_common()
        if len(top) > 1 and top[0][1] == top[1][1]:
            return self.rng.choice([name for name, count in top if count == top[0][1]])
        return top[0][0]

    async def _doctor_choice(self) -> str | None:
        doctor = next((a for a in self.alive if a.role == "doctor"), None)
        if not doctor:
            return None
        options = [n for n in self.alive_names if n != self.last_healed]
        if self.self_heals >= 1:  # yourself: only once per game
            options = [n for n in options if n != doctor.name]
        decision = await self._ask(
            doctor,
            f"Who do you save tonight? Name in 'target', chosen from: {', '.join(options)}. "
            "Think about who is most dangerous to the mafia and cover them. "
            "Leave 'say' as null — at night you stay silent.",
        )
        healed = match_name(decision.target if decision else None, options)
        if not healed:
            # pick among others: models name themselves far too often
            healed = self.rng.choice([n for n in options if n != doctor.name] or options)
        if healed == doctor.name:
            self.self_heals += 1
        self.last_healed = healed
        doctor.remember(f"Night {self.day + 1}: I healed {healed}.")
        self.events.emit("night_action", action="heal", actor=doctor.name, target=healed)
        return healed

    async def _detective_choice(self) -> dict | None:
        detective = next((a for a in self.alive if a.role == "detective"), None)
        if not detective:
            return None
        options = [n for n in self.alive_names if n != detective.name]
        decision = await self._ask(
            detective,
            f"Who do you investigate tonight? Name in 'target', chosen from: {', '.join(options)}. "
            "Leave 'say' as null — at night you stay silent.",
        )
        checked = match_name(decision.target if decision else None, options) or self.rng.choice(options)
        suspect = self.by_name(checked)
        is_mafia = bool(suspect and suspect.role == "mafia")
        verdict = "MAFIA" if is_mafia else "innocent"
        detective.remember(f"Night {self.day + 1}: I investigated {checked} — {verdict}.")
        return {"actor": detective.name, "target": checked, "is_mafia": is_mafia}

    async def discussion(self) -> None:
        self._set_phase("day")
        self._narrate(f"Day {self.day}. The village gathers in the square.")
        for round_index in range(self.config.discussion_rounds):
            order = self.alive[:]
            self.rng.shuffle(order)  # speaking order changes every round
            for agent in order:
                decision = await self._ask(
                    agent,
                    "Say something that matters: accuse, defend yourself, ask a question or back "
                    "someone else's suspicion. Staying silent (say: null) is allowed only if there "
                    "is truly nothing to add. Put your strongest suspect in 'target' (or null).",
                )
                if not decision:
                    continue
                if decision.say:
                    self._post(agent, "village", decision.say, decision.thought)
                else:
                    self.events.emit("pass", agent=agent.name, thought=decision.thought)
            self.events.emit("round_end", day=self.day, round=round_index + 1)

    async def vote(self) -> None:
        self._set_phase("vote")
        self._narrate("Time to vote. Each of you names one person.")
        tally = await self._collect_votes()
        if not tally:
            self._narrate("Nobody dared to name a name. The village breaks up with nothing.")
            self.events.emit("vote_result", tally={}, lynched=None)
            return

        leaders = self._leaders(tally)
        if len(leaders) > 1:
            self._narrate("The vote is tied between " + ", ".join(leaders) + ". Run-off!")
            self.events.emit("vote_result", tally=dict(tally), lynched=None, runoff=True)
            tally = await self._collect_votes(runoff=leaders)
            leaders = self._leaders(tally) if tally else []
            if len(leaders) != 1:
                self._narrate("Tied again — today the village hangs no one.")
                self.events.emit("vote_result", tally=dict(tally or {}), lynched=None)
                return

        lynched = self.by_name(leaders[0])
        if lynched:
            lynched.alive = False
            self._narrate(f"The village has decided: {lynched.name}. The sentence is carried out.")
            self.events.emit("vote_result", tally=dict(tally), lynched=lynched.name, role=lynched.role)
            self.events.emit("death", agent=lynched.name, cause="lynch", role=lynched.role)
        self._emit_state()

    @staticmethod
    def _leaders(tally: Counter[str]) -> list[str]:
        if not tally:
            return []
        top = tally.most_common(1)[0][1]
        return [name for name, count in tally.items() if count == top]

    async def _collect_votes(self, runoff: list[str] | None = None) -> Counter[str]:
        """Ballots are cast simultaneously, then published — the tally is evidence."""
        voters = self.alive[:]
        if runoff:
            task = (
                f"Run-off between: {', '.join(runoff)}. Put ONE OF THEM in 'target', "
                "and a short justification in 'say'."
            )
        else:
            task = (
                "Put the name of whoever hangs in 'target', and one sentence of reasoning "
                "in 'say'. You cannot vote for yourself."
            )
        results = await asyncio.gather(*(self._ask(agent, task, max_tokens=200) for agent in voters))

        tally: Counter[str] = Counter()
        ballots: list[str] = []
        for agent, decision in zip(voters, results):
            if not decision:
                continue
            pool = runoff or self.alive_names
            options = [n for n in pool if n != agent.name]
            target = match_name(decision.target, options)
            if decision.say:
                self._post(agent, "village", decision.say, decision.thought)
            if not target:
                # silence in a vote changes the outcome — ask again, bluntly
                retry = await self._ask(
                    agent,
                    "You named no one, and abstaining is not allowed. Reply with EXACTLY this: "
                    '{"say": null, "target": "<name>"} — one name from: '
                    + ", ".join(options),
                    max_tokens=80,
                )
                target = match_name(retry.target, options) if retry else None
                self.events.emit("vote_retry", agent=agent.name, ok=bool(target))
            if target:
                tally[target] += 1
                ballots.append(f"{agent.name} -> {target}")
                self.events.emit("vote", voter=agent.name, target=target, runoff=bool(runoff))
        if ballots:
            # into the bus, not just the dashboard: tomorrow this is the only
            # record of who pushed whom
            label = "Run-off" if runoff else f"Vote tally, day {self.day}"
            self._narrate(f"{label}: " + "; ".join(ballots) + ".")
        return tally

    # --- end conditions --------------------------------------------
    def check_end(self) -> str | None:
        mafia = len(self.mafia())
        town = len(self.alive) - mafia
        if mafia == 0:
            return "town"
        if mafia >= town:
            return "mafia"
        if self.day >= self.config.max_days:
            return "draw"
        if self.client.usage.total >= self.config.token_budget:
            return "budget"
        return None

    async def run(self) -> str:
        self.setup()
        while True:
            await self.night()
            self.winner = self.check_end()
            if self.winner:
                break
            await self.discussion()
            await self.vote()
            self.winner = self.check_end()
            if self.winner:
                break
        self._set_phase("over")
        self.events.emit(
            "game_over",
            winner=self.winner,
            roles={a.name: a.role for a in self.agents},
            usage={"total": self.client.usage.total, "per_agent": self.client.usage.per_agent},
        )
        return self.winner
