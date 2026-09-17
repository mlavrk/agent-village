"""Model pools for OpenCode Zen — every agent gets its own brain.

Only models served by /chat/completions belong here: that is the single
endpoint ZenClient talks to. All gpt-* models in Zen use /responses and
union-alpha uses /messages; sending them here returns a bare 500.

The free tier is unusable from this project: Zen rejects direct API calls
with FreeTierError ("can only be used from within OpenCode").
"""
from __future__ import annotations

# Cheapest paid models on /chat/completions, $/1M tokens (input/output):
#   deepseek-v4-flash  0.14 / 0.28
#   glm-5.3-flash      0.15 / 0.50
PAID_POOL = [
    "deepseek-v4-flash",
    "glm-5.3-flash",
]

# Kept for reference; these return 403 over the HTTP API.
FREE_POOL = [
    "mimo-v2.5-free",
    "nemotron-3-ultra-free",
    "ling-3.0-flash-fin-free",
]

DEFAULT_POOL = PAID_POOL

# Reasoning models spend part of the budget thinking and may never reach the
# answer. This is the floor for max_tokens below which asking them is pointless.
TOKEN_FLOOR = {
    "glm-5.3-flash": 700,
}


def token_floor(model: str) -> int:
    return TOKEN_FLOOR.get(model, 0)


def assign(index: int, pool: list[str] | None = None) -> str:
    pool = pool or DEFAULT_POOL
    return pool[index % len(pool)]
