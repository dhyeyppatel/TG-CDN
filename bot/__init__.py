import logging
from pyrogram import Client
from bot.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="cdn_bot",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            plugins=dict(root="bot/plugins"),
        )

    async def start(self):
        await super().start()
        me = await self.get_me()
        logger.info(f"Bot started as {me.username}")

    async def stop(self, *args):
        await super().stop()
        logger.info("Bot stopped.")
