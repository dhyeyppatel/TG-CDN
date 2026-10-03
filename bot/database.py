import motor.motor_asyncio
import time
import os
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
        self.premium_users = self.db[f"{prefix}premium_users"]
        self.plans = self.db[f"{prefix}plans"]
        self.shortener_links = self.db[f"{prefix}shortener_links"]
        self.referrals = self.db[f"{prefix}referrals"]
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

    async def toggle_premium_channel(self, chat_id):
        channel = await self.channels.find_one({"chat_id": chat_id})
        if not channel: return False
        
        is_premium = not channel.get("is_premium", False)
        await self.channels.update_one(
            {"chat_id": chat_id},
            {"$set": {"is_premium": is_premium}}
        )
        return is_premium

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
        
    async def add_premium_user(self, user_id, days):
        doc = await self.premium_users.find_one({"user_id": user_id})
        current_time = time.time()
        if doc and doc.get("expires_at", 0) > current_time:
            new_expires = doc["expires_at"] + (days * 86400)
        else:
            new_expires = current_time + (days * 86400)
            
        await self.premium_users.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "expires_at": new_expires}},
            upsert=True
        )

    async def remove_premium_user(self, user_id):
        await self.premium_users.delete_one({"user_id": user_id})

    async def is_premium_user(self, user_id):
        doc = await self.premium_users.find_one({"user_id": user_id})
        if doc:
            expires_at = doc.get("expires_at", 0)
            if expires_at > time.time():
                return True
        return False
        
    async def get_plans(self):
        return await self.plans.find({}).to_list(length=None)

    async def add_plan(self, price, days):
        plan_id = f"{price}_{days}"
        await self.plans.update_one(
            {"_id": plan_id},
            {"$set": {"price": price, "days": days}},
            upsert=True
        )
        
    async def remove_plan(self, plan_id):
        await self.plans.delete_one({"_id": plan_id})

    async def create_short_link(self, hash_str, user_id):
        await self.shortener_links.insert_one({
            "hash": hash_str,
            "user_id": user_id,
            "created_at": time.time(),
            "used": False
        })
        
    async def verify_short_link(self, hash_str, user_id):
        doc = await self.shortener_links.find_one({"hash": hash_str, "user_id": user_id, "used": False})
        if doc:
            await self.shortener_links.update_one({"_id": doc["_id"]}, {"$set": {"used": True}})
            return True
        return False
        
    async def add_referral(self, referrer_id, new_user_id):
        existing = await self.referrals.find_one({"new_user_id": new_user_id})
        if not existing:
            await self.referrals.insert_one({"referrer_id": referrer_id, "new_user_id": new_user_id, "date": time.time()})
            return True
        return False
        
    async def get_referral_count(self, user_id):
        return await self.referrals.count_documents({"referrer_id": user_id})

    async def add_user(self, user_id, first_name, username):
        user = await self.users.find_one({"_id": user_id})
        if not user:
            await self.users.insert_one({
                "_id": user_id,
                "first_name": first_name,
                "username": username,
                "joined_at": time.time(),
                "banned": False
            })
            return True
        return False
        
    async def set_user_banned(self, user_id, banned):
        await self.users.update_one(
            {"_id": user_id},
            {"$set": {"banned": banned}},
            upsert=True
        )
        
    async def is_user_banned(self, user_id):
        user = await self.users.find_one({"_id": user_id})
        if user and user.get("banned", False):
            return True
        return False

    async def get_admins(self):
        admins_doc = await self.settings.find_one({"_id": "admins"})
        return admins_doc.get("list", []) if admins_doc else []

    async def add_admin(self, user_id):
        await self.settings.update_one(
            {"_id": "admins"},
            {"$addToSet": {"list": user_id}},
            upsert=True
        )

    async def remove_admin(self, user_id):
        await self.settings.update_one(
            {"_id": "admins"},
            {"$pull": {"list": user_id}}
        )

    async def is_admin(self, user_id):
        owner_id = await self.get_setting("owner_id", Config.OWNER_ID)
        if user_id == owner_id:
            return True
        admins = await self.get_admins()
        return user_id in admins

_dbs = {}
def get_db(bot_id=None):
    if bot_id not in _dbs:
        # Get MONGODB_URI directly from env if Config.MONGODB_URI is not ready yet
        uri = Config.MONGODB_URI if hasattr(Config, 'MONGODB_URI') else os.environ.get("MONGODB_URI")
        _dbs[bot_id] = Database(uri, Config.DATABASE_NAME, bot_id)
    return _dbs[bot_id]
