from fastapi import FastAPI, Request
from telegram import Update
from bot.main import create_app
from bot.database import db
import asyncio
import time

app = FastAPI()
tg_app = create_app()

@app.post("/api/webhook")
async def webhook(request: Request):
    # Initialize the app on first run
    if not tg_app._initialized:
        await tg_app.initialize()
        
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    
    # Process the update without blocking
    await tg_app.process_update(update)
    return {"status": "ok"}

@app.get("/api/set_webhook")
async def set_webhook(url: str):
    if not tg_app._initialized:
        await tg_app.initialize()
    
    webhook_url = f"{url.rstrip('/')}/api/webhook"
    await tg_app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=["message", "callback_query", "channel_post", "my_chat_member", "message_reaction", "message_reaction_count"]
    )
    return {"status": "Webhook set successfully", "url": webhook_url}

@app.get("/api/cron")
async def vercel_cron():
    if not tg_app._initialized:
        await tg_app.initialize()

    bot = tg_app.bot
    current_time = int(time.time())
    
    # 1. Process deletions
    deletions = await db.get_pending_deletions(current_time)
    for doc in deletions:
        try:
            await bot.delete_message(chat_id=doc["chat_id"], message_id=doc["message_id"])
        except Exception:
            pass # ignore if already deleted
        await db.remove_deletion(doc["_id"])

    # 2. Process Early Access Graduations (After 3 Days)
    expired_media = await db.get_expired_early_access_media(current_time, 3)
    target_channel = -1002684551966
    for media in expired_media:
        try:
            await bot.copy_message(
                chat_id=target_channel,
                from_chat_id=media["chat_id"],
                message_id=media["message_id"]
            )
        except Exception:
            pass  # Ignore errors (e.g., deleted message or missing bot permissions)
        finally:
            await db.remove_early_access_media(media["chat_id"], media["message_id"])

    # 3. Process autosend
    subscribers = await db.get_subscribers()
    mode = await db.get_setting("bot_mode", "default")
    from bot.handlers import core_send_media, core_send_early_access_media
    for sub in subscribers:
        expires_at = sub.get("expires_at", 0)
        # If there is an expiration time and it has passed
        if expires_at and current_time > expires_at:
            await db.remove_subscriber(sub["chat_id"])
            try:
                await bot.send_message(
                    chat_id=sub["chat_id"], 
                    text="⏳ *Your auto-send session has expired!*\nAuto-send is now turned off.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            if mode == "early_access":
                await core_send_early_access_media(bot, sub["chat_id"])
            else:
                await core_send_media(bot, sub["chat_id"])
        
    return {"status": "Cron executed successfully", "deleted": len(deletions), "sent": len(subscribers)}

@app.get("/")
def index():
    return {"status": "Bot is running on Vercel!"}
