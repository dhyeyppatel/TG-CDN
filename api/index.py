from fastapi import FastAPI, Request
from telegram import Update
from bot.main import create_app
from bot.database import get_db
import asyncio
import time

app = FastAPI()
_bots = {}

async def get_tg_app(token: str):
    if token not in _bots:
        tg_app = create_app(token)
        await tg_app.initialize()
        _bots[token] = tg_app
    return _bots[token]

@app.post("/api/webhook/{token}")
async def webhook_clone(token: str, request: Request):
    tg_app = await get_tg_app(token)
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"status": "ok"}

@app.post("/api/webhook")
async def webhook_main(request: Request):
    from bot.config import Config
    return await webhook_clone(Config.BOT_TOKEN, request)

@app.get("/api/set_webhook")
async def set_webhook(url: str):
    from bot.config import Config
    tg_app = await get_tg_app(Config.BOT_TOKEN)
    
    webhook_url = f"{url.rstrip('/')}/api/webhook"
    
    global_db = get_db()
    await global_db.set_setting("app_domain", url.rstrip('/'))
    
    await tg_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=["message", "callback_query", "channel_post", "my_chat_member", "message_reaction", "message_reaction_count"]
    )
    return {"status": "Webhook set successfully", "url": webhook_url}

@app.get("/api/cron")
async def vercel_cron():
    from bot.config import Config
    global_db = get_db()
    
    # Get all registered bots
    bots = await global_db.bot_registry.find({}).to_list(length=None)
    
    # Include main bot if not in registry
    tokens = [Config.BOT_TOKEN] + [b["token"] for b in bots if b.get("token")]
    tokens = list(set(tokens)) # deduplicate
    
    current_time = int(time.time())
    total_deletions = 0
    total_sent = 0
    
    from bot.handlers import core_send_media, core_send_early_access_media
    
    for token in tokens:
        try:
            tg_app = await get_tg_app(token)
            bot = tg_app.bot
            db = get_db(bot.id)
            
            # 1. Process deletions
            deletions = await db.get_pending_deletions(current_time)
            for doc in deletions:
                try:
                    await bot.delete_message(chat_id=doc["chat_id"], message_id=doc["message_id"])
                except Exception:
                    pass
                await db.remove_deletion(doc["_id"])
                total_deletions += 1
                
            # 2. Process Early Access Archiving
            archive_days = await db.get_setting("archive_days", 3)
            expired_media = await db.get_expired_early_access_media(current_time, archive_days)
            target_channel = await db.get_setting("archive_channel_id", "")
            
            if target_channel:
                target_channel = int(target_channel)
                for media in expired_media:
                    try:
                        await bot.copy_message(
                            chat_id=target_channel,
                            from_chat_id=media["chat_id"],
                            message_id=media["message_id"]
                        )
                    except Exception:
                        pass
                    finally:
                        await db.remove_early_access_media(media["chat_id"], media["message_id"])

            # 3. Process autosend
            subscribers = await db.get_subscribers()
            mode = await db.get_setting("bot_mode", "default")
            
            for sub in subscribers:
                expires_at = sub.get("expires_at", 0)
                if expires_at and current_time > expires_at:
                    await db.remove_subscriber(sub["chat_id"])
                    try:
                        await bot.send_message(
                            chat_id=sub["chat_id"], 
                            text="? *Your auto-send session has expired!*\nAuto-send is now turned off.",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                else:
                    if mode == "early_access":
                        await core_send_early_access_media(bot, sub["chat_id"])
                    else:
                        await core_send_media(bot, sub["chat_id"])
                    total_sent += 1
        except Exception as e:
            print(f"Cron error for bot {token[-5:]}: {e}")
            
    return {"status": "Cron executed successfully", "deleted": total_deletions, "sent": total_sent}

@app.get("/")
def index():
    return {"status": "Bot Cloner is running on Vercel!"}
