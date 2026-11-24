from __future__ import annotations

import logging
import os

from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

from telegram_ui.bot_handlers import ZoneHunterTelegramBot
from zone_hunter.pipeline import ZoneHunterPipeline

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diatur di environment variable.")

    pipeline = ZoneHunterPipeline()
    bot_controller = ZoneHunterTelegramBot(analyzer_fn=pipeline.run_analysis)

    app = (
        ApplicationBuilder()
        .token(token)
        .connect_timeout(20.0)
        .read_timeout(30.0)
        .write_timeout(20.0)
        .pool_timeout(20.0)
        .get_updates_connect_timeout(20.0)
        .get_updates_read_timeout(30.0)
        .build()
    )
    app.add_handler(CommandHandler("start", bot_controller.start_command))
    app.add_handler(CommandHandler("menu", bot_controller.main_menu_command))
    app.add_handler(CallbackQueryHandler(bot_controller.on_callback_query))

    app.run_polling(drop_pending_updates=True, bootstrap_retries=-1)


if __name__ == "__main__":
    main()
