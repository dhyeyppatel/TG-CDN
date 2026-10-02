import motor.motor_asyncio
from bot.config import Config
import random
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, uri, database_name):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self.client[database_name]
        self.channels = self.db.channels

    async def update_channel(self, chat_id, title, message_id):
        # Uses $max so we only update last_message_id if the new message_id is higher
        await self.channels.update_one(
            {"chat_id": chat_id},
            {
                "$set": {"title": title},
                "$max": {"last_message_id": message_id}
            },
            upsert=True
        )

    async def remove_channel(self, chat_id):
        await self.channels.delete_one({"chat_id": chat_id})

    async def get_all_channels(self):
        # Return all channels that have at least one tracked message
        cursor = self.channels.find({"last_message_id": {"$gt": 0}})
        return await cursor.to_list(length=None)

    async def toggle_subscriber(self, chat_id):
        existing = await self.db.subscribers.find_one({"chat_id": chat_id})
        if existing:
            await self.db.subscribers.delete_one({"chat_id": chat_id})
            return False
        else:
            await self.db.subscribers.insert_one({"chat_id": chat_id})
            return True

    async def get_subscribers(self):
        return await self.db.subscribers.find({}).to_list(length=None)

    async def schedule_deletion(self, chat_id, message_id, delete_at):
        await self.db.pending_deletions.insert_one({
            "chat_id": chat_id,
            "message_id": message_id,
            "delete_at": delete_at
        })

    async def get_pending_deletions(self, current_time):
        return await self.db.pending_deletions.find({"delete_at": {"$lte": current_time}}).to_list(length=None)

    async def remove_deletion(self, doc_id):
        await self.db.pending_deletions.delete_one({"_id": doc_id})

db = Database(Config.MONGODB_URI, Config.DATABASE_NAME)
