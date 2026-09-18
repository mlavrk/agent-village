#!/usr/bin/env python
"""Run the village: engine plus a realtime dashboard on http://127.0.0.1:8300"""
from __future__ import annotations

import argparse
import asyncio
import traceback

import uvicorn

from village.events import EventBus
from village.game import GameConfig, MafiaGame
from village.models import DEFAULT_POOL
from village.web import build_app
from village.zen import Usage


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Village: mafia played by cheap models")
    parser.add_argument("--mock", action="store_true", help="no API: local stubs instead of models")
    parser.add_argument("--players", type=int, default=6, choices=[6, 7, 8])
    parser.add_argument("--rounds", type=int, default=2, help="discussion rounds per day")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--budget", type=int, default=200_000, help="token cap for one game")
    parser.add_argument("--port", type=int, default=8300)
    parser.add_argument(
        "--model",
        action="append",
        help="a Zen model; repeat the flag to define your own pool. "
        "Defaults to the pool in village/models.py",
    )
    parser.add_argument("--delay", type=float, default=3.0, help="pause before start, to open the dashboard")
    args = parser.parse_args()

    usage = Usage()
    if args.mock:
        from village.mock import MockClient

        client = MockClient(usage)
    else:
        from village.zen import ZenClient

        client = ZenClient(usage)

    config = GameConfig(
        players=args.players,
        discussion_rounds=args.rounds,
        seed=args.seed,
        token_budget=args.budget,
        model_pool=args.model,
    )

    async def preflight(events: EventBus) -> bool:
        """Check models before dealing roles, or the error surfaces mid-game."""
        working = []
        print("Checking models:")
        for model in dict.fromkeys(config.model_pool or DEFAULT_POOL):
            ok, detail = await client.probe(model)
            events.emit("preflight", model=model, ok=ok, detail=detail)
            print(f"  {'OK ' if ok else 'BAD'} {model}" + ("" if ok else f" — {detail}"))
            if ok:
                working.append(model)
        if not working:
            events.emit("error", agent="preflight", text="No model is reachable, game not started.")
            print("No model is reachable. Game not started.")
            return False
        config.model_pool = working
        return True

    async def runner(events: EventBus) -> None:
        await asyncio.sleep(args.delay)
        if not args.mock and not await preflight(events):
            return
        game = MafiaGame(client, events, config)
        try:
            winner = await game.run()
            print(
                f"\nWinner: {winner}. Tokens spent: {usage.total}\n"
                "Game over; the dashboard keeps showing the history. Ctrl+C to quit."
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            events.emit("error", agent="engine", text=traceback.format_exc()[-500:])
            traceback.print_exc()
        finally:
            await client.close()

    app = build_app(EventBus(), runner)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
            timeout_graceful_shutdown=5,
        )
    )
    # SSE streams close themselves as soon as uvicorn catches Ctrl+C
    app.state.should_stop = lambda: server.should_exit
    print(f"Dashboard: http://127.0.0.1:{args.port}  (game starts in {args.delay:g}s)")
    server.run()


if __name__ == "__main__":
    main()
