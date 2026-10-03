import motor.motor_asyncio
import time
from bot.config import Config
import random
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, uri, database_name, bot_id=None):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self.client[database_name]
        prefix = f"{bot_id}_" if bot_id else ""
        self.channels = self.db[f"{prefix}channels"]
        self.users = self.db[f"{prefix}users"]
        self.settings = self.db[f"{prefix}settings"]
        self.early_access_media = self.db[f"{prefix}early_access_media"]
        self.subscribers = self.db[f"{prefix}subscribers"]
        self.pending_deletions = self.db[f"{prefix}pending_deletions"]
        self.media_groups = self.db[f"{prefix}media_groups"]
        self.user_progress = self.db[f"{prefix}user_progress"]
        self.bot_registry = self.db["bot_registry"]

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

    async def get_user_progress(self, chat_id, channel_id):
        user = await self.user_progress.find_one({"chat_id": chat_id, "channel_id": channel_id})
        if user:
            return user.get("progress", 1)
        return 1

    async def update_user_progress(self, chat_id, channel_id, progress):
        await self.user_progress.update_one(
            {"chat_id": chat_id, "channel_id": channel_id},
            {"$set": {"progress": progress}},
            upsert=True
        )
        
    async def check_cooldown(self, user_id, cooldown_seconds=5):
        user = await self.users.find_one({"_id": user_id})
        current_time = time.time()
        
        if user and "last_interaction" in user:
            time_since = current_time - user["last_interaction"]
            if time_since < cooldown_seconds:
                return False, int(cooldown_seconds - time_since)
                
        await self.users.update_one(
            {"_id": user_id},
            {"$set": {"last_interaction": current_time}},
            upsert=True
        )
        return True, 0

    async def get_setting(self, key, default_value=None):
        doc = await self.settings.find_one({"_id": key})
        if doc:
            return doc["value"]
        return default_value

    async def set_setting(self, key, value):
        await self.settings.update_one(
            {"_id": key},
            {"$set": {"value": value}},
            upsert=True
        )

    async def add_early_access_media(self, chat_id, message_id):
        await self.early_access_media.update_one(
            {"chat_id": chat_id, "message_id": message_id},
            {
                "$set": {"chat_id": chat_id, "message_id": message_id},
                "$setOnInsert": {"added_at": time.time()}
            },
            upsert=True
        )
        
    async def get_early_access_media_all(self):
        cursor = self.early_access_media.find({})
        return await cursor.to_list(length=None)
        
    async def remove_early_access_media(self, chat_id, message_id):
        await self.early_access_media.delete_one({"chat_id": chat_id, "message_id": message_id})

    async def get_expired_early_access_media(self, current_time, days=3):
        threshold = current_time - (days * 24 * 60 * 60)
        cursor = self.early_access_media.find({"added_at": {"$lt": threshold}})
        return await cursor.to_list(length=None)

    async def toggle_subscriber(self, chat_id, expires_at=None):
        existing = await self.subscribers.find_one({"chat_id": chat_id})
        if existing:
            await self.subscribers.delete_one({"chat_id": chat_id})
            return False
        else:
            await self.subscribers.insert_one({"chat_id": chat_id, "expires_at": expires_at})
            return True

    async def remove_subscriber(self, chat_id):
        await self.subscribers.delete_one({"chat_id": chat_id})

    async def get_subscribers(self):
        return await self.subscribers.find({}).to_list(length=None)

    async def schedule_deletion(self, chat_id, message_id, delete_at):
        await self.pending_deletions.insert_one({
            "chat_id": chat_id,
            "message_id": message_id,
            "delete_at": delete_at
        })

    async def get_pending_deletions(self, current_time):
        return await self.pending_deletions.find({"delete_at": {"$lte": current_time}}).to_list(length=None)

    async def remove_deletion(self, doc_id):
        await self.pending_deletions.delete_one({"_id": doc_id})

    async def add_to_media_group(self, chat_id, media_group_id, message_id):
        await self.media_groups.update_one(
            {"chat_id": chat_id, "media_group_id": media_group_id},
            {"$addToSet": {"message_ids": message_id}},
            upsert=True
        )

    async def get_media_group_by_message_id(self, chat_id, message_id):
        return await self.media_groups.find_one({
            "chat_id": chat_id,
            "message_ids": message_id
        })
        
    async def get_preferred_channel(self, chat_id):
        user = await self.users.find_one({"chat_id": chat_id})
        if user:
            return user.get("preferred_channel", "all")
        return "all"

    async def set_preferred_channel(self, chat_id, channel_id_str):
        await self.users.update_one(
            {"chat_id": chat_id},
            {"$set": {"preferred_channel": channel_id_str}},
            upsert=True
        )

_dbs = {}
def get_db(bot_id=None):
    if bot_id not in _dbs:
        _dbs[bot_id] = Database(Config.MONGODB_URI, Config.DATABASE_NAME, bot_id)
    return _dbs[bot_id]
