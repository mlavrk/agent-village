"""Thin async client for OpenCode Zen (OpenAI-compatible chat/completions)."""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .models import token_floor

BASE_URL = "https://opencode.ai/zen/v1"


class FatalAPIError(RuntimeError):
    """Not worth retrying: bad key, no access, wrong model or malformed body."""


class EmptyResponse(RuntimeError):
    """The model returned no text — usually the whole budget went into reasoning."""


def load_api_key() -> str:
    key = os.environ.get("OPENCODE_API_KEY")
    if key:
        return key
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError(
        "No OpenCode Zen key. Put it in agent-village/.env as "
        "OPENCODE_API_KEY=sk-... or export it in the environment."
    )


@dataclass
class Usage:
    """Shared counter that doubles as the in-game budget."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    per_agent: dict[str, int] = field(default_factory=dict)

    def add(self, agent: str, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1
        self.per_agent[agent] = self.per_agent.get(agent, 0) + prompt + completion

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ZenClient:
    def __init__(self, usage: Usage, concurrency: int = 4) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {load_api_key()}",
                "Content-Type": "application/json",
                # the default python-httpx/* agent is easily filtered at the edge
                "User-Agent": "agent-village/0.1",
            },
            timeout=httpx.Timeout(120.0),
            follow_redirects=False,  # a 302 must never carry the key to another host
        )
        self._gate = asyncio.Semaphore(concurrency)
        self.usage = usage

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        agent: str = "?",
        max_tokens: int = 400,
        temperature: float = 0.9,
        attempts: int = 4,
    ) -> str:
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max(max_tokens, token_floor(model)),
            "temperature": temperature,
        }
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self._gate:
                    response = await self._client.post("/chat/completions", json=body)
                if response.status_code in (429, 500, 502, 503, 529):
                    raise httpx.HTTPError(f"{response.status_code}: {response.text[:300]}")
                if response.status_code >= 400:
                    # 401/403/404/422 — nothing to retry: key, model or body is wrong
                    raise FatalAPIError(
                        f"{response.status_code} from model {model}: {response.text[:400]}"
                    )
                data = response.json()
                usage = data.get("usage") or {}
                self.usage.add(
                    agent,
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
                choice = data["choices"][0]
                message = choice.get("message") or {}
                content = (message.get("content") or "").strip()
                if not content:
                    # A reasoning model burned the budget thinking and never
                    # answered. Use its reasoning ONLY if it contains JSON,
                    # otherwise raw chain-of-thought would land in the dialogue.
                    thinking = (message.get("reasoning_content") or message.get("reasoning") or "").strip()
                    if '"say"' in thinking:
                        content = thinking
                    else:
                        raise EmptyResponse(
                            f"{model}: empty content "
                            f"(finish_reason={choice.get('finish_reason')!r}, "
                            f"{len(thinking)} chars of reasoning)"
                        )
                return content
            except FatalAPIError:
                raise
            except Exception as exc:  # network, rate limits, malformed reply — retry
                last_error = exc
                if isinstance(exc, EmptyResponse):
                    body["max_tokens"] = min(int(body["max_tokens"] * 2), 2000)
                await asyncio.sleep(1.5 * 2**attempt + random.random())
        raise RuntimeError(f"Zen did not answer after {attempts} attempts: {last_error}")

    async def probe(self, model: str) -> tuple[bool, str]:
        """Cheap availability check before the game starts."""
        try:
            await self.chat(
                model,
                [{"role": "user", "content": "Answer with one word: hello"}],
                agent="preflight",
                # too small a budget and a reasoning model never answers,
                # which would mark a healthy model as broken
                max_tokens=200,
                attempts=1,
            )
            return True, "ok"
        except Exception as exc:
            return False, str(exc)[:200]


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)
_STRING = r'"((?:[^"\\]|\\.)*)'


def _field(text: str, name: str) -> str | None:
    """Pull a field even out of truncated JSON (closing quote missing)."""
    match = re.search(rf'"{name}"\s*:\s*{_STRING}', text, re.S)
    if not match:
        return None
    value = match.group(1)
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.replace('\\"', '"').strip()


def parse_json(raw: str) -> dict:
    """Cheap models love wrapping JSON in chatter, fences — or cutting it short."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    # cut off by the token limit — salvage whatever arrived
    salvaged = {name: _field(text, name) for name in ("thought", "say", "target")}
    if any(salvaged.values()):
        return {**{k: v for k, v in salvaged.items() if v}, "_partial": True}
    return {"say": text[:400], "_partial": True}
