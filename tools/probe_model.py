#!/usr/bin/env python
"""Show a model's raw reply: where exactly it puts the text.

    .venv/bin/python tools/probe_model.py glm-5.3-flash
"""
import asyncio
import json
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from village.zen import BASE_URL, load_api_key  # noqa: E402


async def main(model: str) -> None:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": 'Reply with JSON ONLY: {"say": "<line>", "target": null}'},
            {"role": "user", "content": "Say one line about the weather in the village."},
        ],
        "max_tokens": 320,
    }
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {load_api_key()}", "User-Agent": "agent-village/0.1"},
        timeout=120.0,
    ) as client:
        response = await client.post("/chat/completions", json=body)
    print("HTTP", response.status_code)
    data = response.json()
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    print("finish_reason:", choice.get("finish_reason"))
    print("message fields:", sorted(message))
    for key, value in message.items():
        preview = json.dumps(value, ensure_ascii=False)[:300] if value else repr(value)
        print(f"  {key}: {preview}")
    print("usage:", data.get("usage"))


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "deepseek-v4-flash"))
