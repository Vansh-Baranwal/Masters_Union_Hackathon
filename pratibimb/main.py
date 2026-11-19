"""
Pratibimb — main entry point.

Starts either:
  - The FastAPI server  (default, or --mode api)
  - The Telegram bot    (--mode bot)
  - Both concurrently   (--mode all)

Usage:
    python main.py                 # API server on port 8000
    python main.py --mode bot      # Telegram bot only
    python main.py --mode all      # API + bot together

Environment: copy .env.example → .env and fill in secrets before running.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv
from core.database import init_db

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger("pratibimb")


def _build_uvicorn_config() -> uvicorn.Config:
    return uvicorn.Config(
        "api.app:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        reload=os.getenv("APP_ENV", "development") == "development",
    )


async def run_api() -> None:
    config = _build_uvicorn_config()
    server = uvicorn.Server(config)
    log.info("Starting API server on %s:%s", config.host, config.port)
    await server.serve()


async def run_bot() -> None:
    from intake.channel import run_bot_sync
    import asyncio as _asyncio
    log.info("Starting Telegram bot…")
    loop = _asyncio.get_event_loop()
    await loop.run_in_executor(None, run_bot_sync)


async def run_all() -> None:
    await asyncio.gather(run_api(), run_bot())


def main() -> None:
    parser = argparse.ArgumentParser(description="Pratibimb server")
    parser.add_argument(
        "--mode",
        choices=["api", "bot", "all"],
        default="api",
        help="Component to start (default: api)",
    )
    args = parser.parse_args()

    try:
        if args.mode == "api":
            asyncio.run(run_api())
        elif args.mode == "bot":
            # python-telegram-bot manages its own event loop — do NOT use asyncio.run()
            from intake.channel import run_bot_sync
            asyncio.run(init_db())
            run_bot_sync()
        elif args.mode == "all":
            asyncio.run(run_all())
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
