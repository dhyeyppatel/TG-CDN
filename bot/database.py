import motor.motor_asyncio
import time
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
        cursor = self.channels.find({"last_message_id": {"$gt": 0}})
        return await cursor.to_list(length=None)
        
    async def check_cooldown(self, user_id, cooldown_seconds=5):
        user = await self.db.users.find_one({"_id": user_id})
        current_time = time.time()
        
        if user and "last_interaction" in user:
            time_since = current_time - user["last_interaction"]
            if time_since < cooldown_seconds:
                return False, int(cooldown_seconds - time_since)
                
        await self.db.users.update_one(
            {"_id": user_id},
            {"$set": {"last_interaction": current_time}},
            upsert=True
        )
        return True, 0

    async def get_setting(self, key, default_value):
        doc = await self.db.settings.find_one({"_id": key})
        if doc:
            return doc["value"]
        return default_value

    async def set_setting(self, key, value):
        await self.db.settings.update_one(
            {"_id": key},
            {"$set": {"value": value}},
            upsert=True
        )

    async def add_early_access_media(self, chat_id, message_id):
        await self.db.early_access_media.update_one(
            {"chat_id": chat_id, "message_id": message_id},
            {"$set": {"chat_id": chat_id, "message_id": message_id}},
            upsert=True
        )
        
    async def get_early_access_media_all(self):
        cursor = self.db.early_access_media.find({})
        return await cursor.to_list(length=None)
        
    async def remove_early_access_media(self, chat_id, message_id):
        await self.db.early_access_media.delete_one({"chat_id": chat_id, "message_id": message_id})

    async def toggle_subscriber(self, chat_id, expires_at=None):
        existing = await self.db.subscribers.find_one({"chat_id": chat_id})
        if existing:
            await self.db.subscribers.delete_one({"chat_id": chat_id})
            return False
        else:
            await self.db.subscribers.insert_one({"chat_id": chat_id, "expires_at": expires_at})
            return True

    async def remove_subscriber(self, chat_id):
        await self.db.subscribers.delete_one({"chat_id": chat_id})

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
