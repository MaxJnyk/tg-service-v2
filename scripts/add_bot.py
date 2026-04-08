"""
Add a bot token to tg-service-v2.

Usage:
  python scripts/add_bot.py --name tadvert_test_bot --token 8169557246:AAG... --platform-id <uuid>
"""

import asyncio
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def add(name: str, token: str, platform_id: str | None) -> None:
    from src.modules.accounts.service import AccountService
    from src.infrastructure.database import close_engine

    bot_id = await AccountService.add_bot(name=name, token=token, platform_id=platform_id)
    logger.info("Bot added: @%s id=%s platform_id=%s", name, bot_id, platform_id)
    await close_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Add bot to tg-service-v2")
    parser.add_argument("--name", required=True, help="Bot username")
    parser.add_argument("--token", required=True, help="Bot token")
    parser.add_argument("--platform-id", default=None, help="Platform UUID to link to")
    args = parser.parse_args()

    asyncio.run(add(args.name, args.token, args.platform_id))


if __name__ == "__main__":
    main()
