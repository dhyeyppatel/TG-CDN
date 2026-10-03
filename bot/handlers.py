import random
import logging
import time
import uuid
import urllib.parse
import aiohttp
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from bot.database import get_db
from bot.config import Config

logger = logging.getLogger(__name__)

# ─── Helpers ───────────────────────────────────────────────

async def get_main_keyboard(bot_id):
    db = get_db(bot_id)
    delivery_mode = await db.get_setting("delivery_mode", "random")
    keyboard = []
    
    if delivery_mode == "serial":
        keyboard.append([KeyboardButton("Prev ⏪"), KeyboardButton("Next ⏩")])
    else:
        keyboard.append([KeyboardButton("Next ⏩")])
        
    keyboard.append([KeyboardButton("⏱ Auto-Send"), KeyboardButton("❓ Help")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def check_fsub(bot, user_id):
    db = get_db(bot.id)
    fsub_enabled = await db.get_setting("fsub_enabled", False)
    fsub_channel_id = await db.get_setting("fsub_channel_id", "")
    if not fsub_enabled or not fsub_channel_id:
        return True
        
    try:
        member = await bot.get_chat_member(chat_id=fsub_channel_id, user_id=user_id)
        if member.status in ["left", "kicked"]:
            return False
        return True
    except BadRequest:
        return False

async def send_log(bot, db, text):
    log_channel = await db.get_setting("log_channel_id", None)
    if log_channel:
        try:
            await bot.send_message(chat_id=log_channel, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send log to {log_channel}: {e}")

# ─── Core Media Logic ─────────────────────────────────────

async def core_send_media(bot, chat_id, specific_channel_id=None, is_prev=False):
    db = get_db(bot.id)
    channels = await db.get_all_channels()
    if not channels:
        return False, "📭 No storage channels found yet! Use /settings to add one."
        
    is_premium = await db.is_premium_user(chat_id)

    if specific_channel_id:
        channels = [c for c in channels if c["chat_id"] == specific_channel_id]
        if not channels:
            return False, "This specific channel is no longer tracked."
            
        if channels[0].get("is_premium") and not is_premium:
            return False, "💎 *Premium Content*\nYou need a premium subscription to access this specific channel."
    else:
        # Filter channels based on premium status
        if not is_premium:
            channels = [c for c in channels if not c.get("is_premium")]
        if not channels:
            return False, "📭 No free channels available. All content is premium-only."

    autodelete_mins = await db.get_setting("autodelete_minutes", 5)
    autodelete_secs = autodelete_mins * 60
    
    delivery_mode = await db.get_setting("delivery_mode", "random")

    for attempt in range(20):
        chosen_channel = random.choice(channels)
        c_id = chosen_channel["chat_id"]
        last_message_id = chosen_channel["last_message_id"]
        
        if delivery_mode == "serial":
            target_id = await db.get_user_progress(chat_id, c_id)
            if is_prev:
                target_id = max(1, target_id - 2)
                
            if target_id > last_message_id:
                await db.update_user_progress(chat_id, c_id, 1)
                target_id = 1
        else:
            if is_prev:
                return False, "⚠️ Previous button is only supported in Serial delivery mode."
            target_id = random.randint(1, last_message_id)
        
        try:
            media_group = await db.get_media_group_by_message_id(c_id, target_id)
            
            if media_group and len(media_group.get("message_ids", [])) > 1:
                sent_messages = await bot.copy_messages(
                    chat_id=chat_id,
                    from_chat_id=c_id,
                    message_ids=media_group["message_ids"]
                )
                
                reply_markup = await get_main_keyboard(bot.id)
                warning_msg = await bot.send_message(
                    chat_id=chat_id, 
                    text=f"⏳ _This media group will be automatically deleted in {autodelete_mins} minutes._",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
                
                delete_at = int(time.time()) + autodelete_secs
                for sm in sent_messages:
                    await db.schedule_deletion(chat_id, sm.message_id, delete_at)
                await db.schedule_deletion(chat_id, warning_msg.message_id, delete_at)
                
                if delivery_mode == "serial":
                    await db.update_user_progress(chat_id, c_id, max(media_group["message_ids"]) + 1)
                    
                return True, None
            else:
                sent_message = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=c_id,
                    message_id=target_id,
                    reply_markup=None
                )
                
                reply_markup = await get_main_keyboard(bot.id)
                warning_msg = await bot.send_message(
                    chat_id=chat_id, 
                    text=f"⏳ _This file will be automatically deleted in {autodelete_mins} minutes._",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
                
                delete_at = int(time.time()) + autodelete_secs
                await db.schedule_deletion(chat_id, sent_message.message_id, delete_at)
                await db.schedule_deletion(chat_id, warning_msg.message_id, delete_at)
                
                if delivery_mode == "serial":
                    await db.update_user_progress(chat_id, c_id, target_id + 1)
                    
                return True, None
        except BadRequest:
            if delivery_mode == "serial":
                await db.update_user_progress(chat_id, c_id, target_id + 1)
            continue
        except Exception:
            continue
            
    return False, "😕 Couldn't find a valid post after several attempts. Please try again later!"

async def core_send_early_access_media(bot, chat_id):
    db = get_db(bot.id)
    media_list = await db.get_early_access_media_all()
    if not media_list:
        return False, "📭 No early access media found yet! React to a message in your Early Access chat to add it."

    autodelete_mins = await db.get_setting("autodelete_minutes", 5)
    autodelete_secs = autodelete_mins * 60

    for attempt in range(10):
        chosen = random.choice(media_list)
        c_id = chosen["chat_id"]
        m_id = chosen["message_id"]
        
        try:
            sent_message = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=c_id,
                message_id=m_id,
                reply_markup=None
            )
            
            reply_markup = await get_main_keyboard(bot.id)
            warning_msg = await bot.send_message(
                chat_id=chat_id, 
                text=f"⏳ _This file will be automatically deleted in {autodelete_mins} minutes._",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            
            delete_at = int(time.time()) + autodelete_secs
            await db.schedule_deletion(chat_id, sent_message.message_id, delete_at)
            await db.schedule_deletion(chat_id, warning_msg.message_id, delete_at)
            return True, None
        except BadRequest:
            await db.remove_early_access_media(c_id, m_id)
            continue
            
    return False, "😕 Failed to fetch early access media after multiple attempts."

# ─── User Commands ─────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    
    if await db.is_user_banned(update.effective_user.id):
        await update.message.reply_text("❌ You have been banned from using this bot.")
        return
    
    # Handle deep links
    if context.args:
        arg = context.args[0]
        if arg == "cdn":
            clone_mode = await db.get_setting("clone_mode", True)
            is_admin = await db.is_admin(update.effective_user.id)
            if not clone_mode and not is_admin:
                await update.message.reply_text("❌ Clone mode is currently disabled by the owner.")
                return
                
            await update.message.reply_text(
                "🚀 *Welcome to the Bot Cloner!*\n\n"
                "To clone this bot for your own use:\n\n"
                "1️⃣ Go to @BotFather and create a new bot\n"
                "2️⃣ Copy the HTTP API Token\n"
                "3️⃣ Send it here in this format:\n\n"
                "`/clone YOUR_BOT_TOKEN_HERE`\n\n"
                "✨ Once cloned, your bot will run autonomously!",
                parse_mode="Markdown"
            )
            return
        elif arg.startswith("prem_"):
            if await db.verify_short_link(arg, update.effective_user.id):
                days = await db.get_setting("shortener_duration_days", 1)
                await db.add_premium_user(update.effective_user.id, days)
                await update.message.reply_text(f"🎉 **Congratulations!** You've claimed {days} days of Premium access by watching the ad!", parse_mode="Markdown")
                await send_log(context.bot, db, f"🔗 <b>Shortener Unlocked</b>\n<a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a> completed an ad and got {days} days premium.")
            else:
                await update.message.reply_text("❌ This link is invalid, already used, or does not belong to you.")
        elif arg.startswith("ref_"):
            referrer_id = int(arg.split("_")[1])
            if referrer_id != update.effective_user.id:
                if await db.add_referral(referrer_id, update.effective_user.id):
                    days = await db.get_setting("referral_duration_days", 1)
                    await db.add_premium_user(referrer_id, days)
                    try:
                        await context.bot.send_message(chat_id=referrer_id, text=f"🎉 **New Referral!** Someone used your invite link. You've earned {days} days of Premium access!")
                        await send_log(context.bot, db, f"👥 <b>Referral</b>\n<a href='tg://user?id={referrer_id}'>{referrer_id}</a> referred <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a> and earned {days} days premium.")
                    except Exception:
                        pass
        
    reply_markup = await get_main_keyboard(context.bot.id)
    bot_info = await context.bot.get_me()
    
    welcome_text = (
        f"✨ *Welcome to {bot_info.first_name}!* ✨\n\n"
        "🎬 Your premium media delivery bot.\n"
        "Browse, discover, and enjoy content seamlessly.\n\n"
        "📌 Use the buttons below or send /type to filter by category."
    )
    
    clone_mode = await db.get_setting("clone_mode", True)
    if clone_mode:
        clone_url = f"https://t.me/{bot_info.username}?start=cdn"
    else:
        clone_url = "https://t.me/CThreadpaybot?start=cdn"
        
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Create your own Clone", url=clone_url)]
    ])
    
    is_new = await db.add_user(update.effective_user.id, update.effective_user.first_name, update.effective_user.username)
    if is_new:
        await send_log(context.bot, db, f"🆕 <b>New User</b>\n<a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a> (<code>{update.effective_user.id}</code>) started the bot.")
        
    
    await update.message.reply_text(welcome_text, reply_markup=inline_kb, parse_mode="Markdown")
    await update.message.reply_text("👇 Choose an option below:", reply_markup=reply_markup)

async def type_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    channels = await db.get_all_channels()
    keyboard = []
    
    for c in channels:
        name = c.get('title', 'Unknown Channel')
        if c.get("is_premium"):
            name = f"💎 {name}"
        else:
            name = f"📁 {name}"
        keyboard.append([InlineKeyboardButton(name, callback_data=f"set_type_{c['chat_id']}")])
        
    keyboard.append([InlineKeyboardButton("🎲 All Channels (Mix)", callback_data="set_type_all")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("📂 *Select your preferred media type:*", reply_markup=reply_markup, parse_mode="Markdown")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    if not await db.is_admin(update.effective_user.id):
        return
        
    if not context.args:
        await update.message.reply_text("Usage: `/ban <user_id>`", parse_mode="Markdown")
        return
        
    user_id_str = context.args[0]
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ Please provide a valid numeric user ID.")
        return
        
    user_id = int(user_id_str)
    await db.set_user_banned(user_id, True)
    await update.message.reply_text(f"✅ User `{user_id}` has been banned.", parse_mode="Markdown")
    await send_log(context.bot, db, f"⛔ <b>User Banned</b>\nAdmin banned user <code>{user_id}</code>.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    if not await db.is_admin(update.effective_user.id):
        return
        
    if not context.args:
        await update.message.reply_text("Usage: `/unban <user_id>`", parse_mode="Markdown")
        return
        
    user_id_str = context.args[0]
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ Please provide a valid numeric user ID.")
        return
        
    user_id = int(user_id_str)
    await db.set_user_banned(user_id, False)
    await update.message.reply_text(f"✅ User `{user_id}` has been unbanned.", parse_mode="Markdown")
    await send_log(context.bot, db, f"✅ <b>User Unbanned</b>\nAdmin unbanned user <code>{user_id}</code>.")

async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    owner_id = await db.get_setting("owner_id", Config.OWNER_ID)
    if update.effective_user.id != owner_id:
        return
        
    if not context.args:
        await update.message.reply_text("Usage: `/addadmin <user_id>`", parse_mode="Markdown")
        return
        
    user_id_str = context.args[0]
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ Please provide a valid numeric user ID.")
        return
        
    user_id = int(user_id_str)
    await db.add_admin(user_id)
    await update.message.reply_text(f"✅ User `{user_id}` has been added as an admin.", parse_mode="Markdown")
    await send_log(context.bot, db, f"👮 <b>Admin Added</b>\nUser <code>{user_id}</code> is now an admin.")

async def rmadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    owner_id = await db.get_setting("owner_id", Config.OWNER_ID)
    if update.effective_user.id != owner_id:
        return
        
    if not context.args:
        await update.message.reply_text("Usage: `/rmadmin <user_id>`", parse_mode="Markdown")
        return
        
    user_id_str = context.args[0]
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ Please provide a valid numeric user ID.")
        return
        
    user_id = int(user_id_str)
    await db.remove_admin(user_id)
    await update.message.reply_text(f"✅ User `{user_id}` has been removed from admins.", parse_mode="Markdown")
    await send_log(context.bot, db, f"👮 <b>Admin Removed</b>\nUser <code>{user_id}</code> is no longer an admin.")


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    bot_info = await context.bot.get_me()
    
    is_prem = await db.is_premium_user(update.effective_user.id)
    status = "✅ ACTIVE" if is_prem else "❌ INACTIVE"
    
    plans = await db.get_plans()
    payment_info = await db.get_setting("payment_info", "Contact admin to purchase.")
    
    text = f"💎 **Premium Subscription**\n\nYour Status: {status}\n\n"
    text += "👑 **Buy Premium**\n"
    for p in plans:
        text += f"- {p['price']}/- for {p['days']} days\n"
    if plans:
        text += f"\n*Payment Info:*\n{payment_info}\n\n"
        
    text += "🎁 **Get Premium for FREE!**\n"
    text += "1. **Watch an Ad:** Click the button below to generate a short link. After viewing, you'll earn Premium time!\n\n"
    
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{update.effective_user.id}"
    ref_count = await db.get_referral_count(update.effective_user.id)
    text += f"2. **Refer Friends:** Share your invite link to earn Premium time per referral.\nYour link: `{ref_link}`\nYour Referrals: {ref_count}"
    
    keyboard = [
        [InlineKeyboardButton("💰 Buy Premium", callback_data="buy_premium")],
        [InlineKeyboardButton("📺 Watch Ad for Premium", callback_data="gen_short_link")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", disable_web_page_preview=True)

async def send_random_media(update: Update, context: ContextTypes.DEFAULT_TYPE, is_prev=False):
    db = get_db(context.bot.id)
    # Check Force Sub
    if not await check_fsub(context.bot, update.effective_user.id):
        fsub_link = await db.get_setting("fsub_channel_link", "")
        keyboard = [[InlineKeyboardButton("Join Channel 📢", url=fsub_link)]] if fsub_link else []
        await update.message.reply_text("⚠️ You must join our channel to use this bot!", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
        return
        
    # Check Cooldown
    allowed, wait_time = await db.check_cooldown(update.effective_user.id, 5)
    if not allowed:
        await update.message.reply_text(f"⏳ Please wait {wait_time}s before requesting again.")
        return

    chat_id = update.effective_chat.id
    mode = await db.get_setting("bot_mode", "default")
    
    if update.message and update.message.text:
        if update.message.text.startswith("/prev"):
            is_prev = True
        
    if mode == "early_access":
        success, error_msg = await core_send_early_access_media(context.bot, chat_id)
    else:
        pref = await db.get_preferred_channel(chat_id)
        specific = int(pref) if pref != "all" else None
        success, error_msg = await core_send_media(context.bot, chat_id, specific, is_prev)
        
    if not success and error_msg:
        await update.message.reply_text(error_msg)

async def toggle_autosend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    # Check Force Sub
    if not await check_fsub(context.bot, update.effective_user.id):
        fsub_link = await db.get_setting("fsub_channel_link", "")
        keyboard = [[InlineKeyboardButton("Join Channel 📢", url=fsub_link)]] if fsub_link else []
        await update.message.reply_text("⚠️ You must join our channel to use this bot!", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
        return
        
    chat_id = update.effective_chat.id
    
    expire_mins = await db.get_setting("autosend_expire_minutes", 60)
    expires_at = int(time.time()) + (expire_mins * 60)
    
    is_subscribed = await db.toggle_subscriber(chat_id, expires_at)
    
    if is_subscribed:
        mins = await db.get_setting("autodelete_minutes", 5)
        await update.message.reply_text(
            f"✅ *Auto-send started!*\n\n"
            f"📬 You'll receive media every 5 minutes for the next {expire_mins} minutes.\n"
            f"🗑 Each file auto-deletes after {mins} minutes.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("🛑 Auto-send stopped.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    owner_id = await db.get_setting("owner_id", Config.OWNER_ID)
    
    text = (
        "🤖 *How to use this bot*\n\n"
        "Here are the available features and commands:\n\n"
        "🔹 *Core Features:*\n"
        "• *Next / Prev* — Request the next (or previous) media file. Prev only works in Serial mode.\n"
        "• *Auto-Send* — Automatically receive a new media file every 5 minutes! Toggle on/off.\n\n"
        "🔹 *Commands:*\n"
        "• /start — Restart the bot and show the main menu\n"
        "• /type — Filter by a specific media category\n"
        "• /next — Request the next media\n"
        "• /prev — Request the previous media\n"
        "• /autosend — Toggle the Auto-Send feature\n"
        "• /help — Show this help message\n"
    )
    
    if await db.is_admin(update.effective_user.id):
        text += (
            "\n👑 *Admin Features:*\n"
            "• /settings — Open the Admin Control Panel\n"
            "   ◦ *Storage Channels* — Bot pulls media from these\n"
            "   ◦ *Early Access* — Exclusive pool before archival\n"
            "   ◦ *Force Sub* — Require users to join a channel\n"
            "   ◦ *Clone Mode* — Allow/disallow users to clone\n"
        )
        
    await update.message.reply_text(text, parse_mode="Markdown")

async def clone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    clone_mode = await db.get_setting("clone_mode", True)
    
    if not clone_mode and not await db.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Clone mode is currently disabled by the owner.")
        return

    text = update.message.text
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("📋 *Usage:* `/clone YOUR_BOT_TOKEN`", parse_mode="Markdown")
        return
        
    token = parts[1].strip()
    try:
        new_bot = Bot(token)
        bot_info = await new_bot.get_me()
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid token: `{str(e)}`", parse_mode="Markdown")
        return
        
    global_db = get_db()
    app_domain = await global_db.get_setting("app_domain")
    if not app_domain:
        await update.message.reply_text("❌ App domain not configured. The admin needs to set the webhook first.")
        return
        
    # Save to bot registry
    await global_db.bot_registry.update_one(
        {"bot_id": bot_info.id},
        {"$set": {"token": token, "owner_id": update.effective_user.id, "username": bot_info.username}},
        upsert=True
    )
    
    # Configure initial settings for cloned bot
    cloned_db = get_db(bot_info.id)
    await cloned_db.set_setting("owner_id", update.effective_user.id)
    
    webhook_url = f"{app_domain}/api/webhook/{token}"
    try:
        await new_bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query", "channel_post", "my_chat_member", "message_reaction", "message_reaction_count"]
        )
        await update.message.reply_text(
            f"✅ *Bot successfully cloned!*\n\n"
            f"🤖 Your new bot: @{bot_info.username}\n\n"
            f"Send `/start` to your new bot to get started!",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to set webhook: `{str(e)}`", parse_mode="Markdown")

# ─── Channel & Reaction Handlers ──────────────────────────

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    message = update.channel_post
    if not message:
        return
        
    # Ignore posts in the archive channel
    archive_id = await db.get_setting("archive_channel_id", "")
    if archive_id and message.chat.id == int(archive_id):
        return
        
    # Dynamically register/update channel
    await db.update_channel(message.chat.id, message.chat.title, message.message_id)
    
    if message.media_group_id:
        await db.add_to_media_group(message.chat.id, message.media_group_id, message.message_id)
        
    logger.info(f"Updated LAST_MESSAGE_ID to {message.message_id} for channel {message.chat.id}")

async def reaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    if update.message_reaction:
        chat_id = update.message_reaction.chat.id
        msg_id = update.message_reaction.message_id
        is_add = bool(update.message_reaction.new_reaction)
    elif update.message_reaction_count:
        chat_id = update.message_reaction_count.chat.id
        msg_id = update.message_reaction_count.message_id
        is_add = bool(update.message_reaction_count.reactions)
    else:
        return
        
    early_chat = await db.get_setting("early_access_chat", None)
    
    if early_chat and chat_id == int(early_chat):
        if is_add:
            await db.add_early_access_media(chat_id, msg_id)
            logger.info(f"Added message {msg_id} to Early Access Media")
        else:
            await db.remove_early_access_media(chat_id, msg_id)
            logger.info(f"Removed message {msg_id} from Early Access Media due to unreact")

async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    result = update.my_chat_member
    
    if result.chat.type == "channel":
        new_status = result.new_chat_member.status
        if new_status in ["left", "kicked"]:
            await db.remove_channel(result.chat.id)
            logger.info(f"Bot removed from channel: {result.chat.id}, deleted from database.")

# ─── Message Handler (Admin States + Buttons) ─────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    
    # Handle Admin States
    if await db.is_admin(update.effective_user.id):
        state = await db.get_setting("admin_state", None)
        
        # Text-based admin states
        if state and update.message and update.message.text:
            text = update.message.text
            if state == "wait_fsub_link":
                await db.set_setting("fsub_channel_link", text)
                await db.set_setting("admin_state", None)
                await update.message.reply_text(f"✅ FSUB Link updated to: {text}\nSend /settings to view changes.")
                return
            elif state == "wait_add_prem":
                parts = text.split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    user_id = int(parts[0])
                    days = int(parts[1])
                    await db.add_premium_user(user_id, days)
                    await db.set_setting("admin_state", None)
                    await update.message.reply_text(f"✅ User `{user_id}` has been granted premium access for {days} days!", parse_mode="Markdown")
                    await send_log(context.bot, db, f"👑 <b>Premium Added</b>\nAdmin granted <b>{days} days</b> to <a href='tg://user?id={user_id}'>{user_id}</a>.")
                else:
                    await update.message.reply_text("❌ Invalid format. Please send ID and days (e.g. `123456789 3`).")
                return
            elif state == "wait_rm_prem":
                if text.isdigit():
                    user_id = int(text)
                    await db.remove_premium_user(user_id)
                    await db.set_setting("admin_state", None)
                    await update.message.reply_text(f"❌ User `{user_id}`'s premium access has been revoked.", parse_mode="Markdown")
                    await send_log(context.bot, db, f"🚫 <b>Premium Revoked</b>\nAdmin revoked premium for <a href='tg://user?id={user_id}'>{user_id}</a>.")
                else:
                    await update.message.reply_text("❌ Please send a valid user ID (numbers only).")
                return
            elif state == "wait_pay_info":
                await db.set_setting("payment_info", text)
                await db.set_setting("admin_state", None)
                await update.message.reply_text("✅ Payment Instructions updated.")
                return
            elif state == "wait_add_plan":
                lines = text.strip().split('\n')
                added = []
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        await db.add_plan(int(parts[0]), int(parts[1]))
                        added.append(f"{parts[0]}/- for {parts[1]} days")
                
                await db.set_setting("admin_state", None)
                if added:
                    await update.message.reply_text("✅ Added plans:\n" + "\n".join(added))
                else:
                    await update.message.reply_text("❌ Invalid format. Please send price and days (e.g. `29 3`).")
                return
            elif state == "wait_shortener_domain":
                await db.set_setting("shortener_domain", text.strip())
                await db.set_setting("admin_state", None)
                await update.message.reply_text("✅ Shortener Domain saved.")
                return
            elif state == "wait_shortener_api":
                await db.set_setting("shortener_api", text.strip())
                await db.set_setting("admin_state", None)
                await update.message.reply_text("✅ Shortener API Key saved.")
                return
            elif state == "wait_shortener_days":
                if text.isdigit():
                    await db.set_setting("shortener_duration_days", int(text))
                    await db.set_setting("admin_state", None)
                    await update.message.reply_text(f"✅ Reward set to {text} days.")
                else:
                    await update.message.reply_text("❌ Send a valid number.")
                return
            elif state == "wait_ref_days":
                if text.isdigit():
                    await db.set_setting("referral_duration_days", int(text))
                    await db.set_setting("admin_state", None)
                    await update.message.reply_text(f"✅ Referral reward set to {text} days.")
                else:
                    await update.message.reply_text("❌ Send a valid number.")
                return
            elif state == "wait_archive_days":
                if text.isdigit():
                    await db.set_setting("archive_days", int(text))
                    await db.set_setting("admin_state", None)
                    await update.message.reply_text(f"✅ Archive time updated to {text} days.\nSend /settings to view changes.")
                else:
                    await update.message.reply_text("❌ Please send a valid number.")
                return
            elif state.startswith("wait_channel_name_"):
                parts = state.split("_")
                chat_id = int(parts[3])
                msg_id = int(parts[4])
                channels = await db.get_all_channels()
                exists = next((c for c in channels if c["chat_id"] == chat_id), None)
                if exists:
                    await db.update_channel(chat_id, text, exists["last_message_id"])
                else:
                    await db.update_channel(chat_id, text, msg_id)
                    
                await db.set_setting("admin_state", None)
                reply_markup = await get_main_keyboard(context.bot.id)
                await update.message.reply_text(f"✅ Channel display name set to: **{text}**\n\nThe main menu has been updated.", parse_mode="Markdown", reply_markup=reply_markup)
                return

        # Forward/ID-based admin states (wait_fw_*)
        if state and state.startswith("wait_fw_"):
            chat_id = None
            title = "Channel"
            msg_id = 1
            
            if update.message.forward_origin and hasattr(update.message.forward_origin, "chat"):
                chat_id = getattr(update.message.forward_origin.chat, "id", None)
                title = getattr(update.message.forward_origin.chat, "title", "Channel")
                msg_id = getattr(update.message.forward_origin, "message_id", 1)
            elif update.message.forward_from_chat:
                chat_id = update.message.forward_from_chat.id
                title = getattr(update.message.forward_from_chat, "title", "Channel")
                msg_id = getattr(update.message, "forward_from_message_id", 1)
            elif update.message.text:
                text = update.message.text.strip()
                if text.startswith("-100") and text.replace("-", "").isdigit():
                    chat_id = int(text)
                    title = "Manual Channel"
                    
            if chat_id:
                if state == "wait_fw_store":
                    keyboard = [
                        [InlineKeyboardButton("✅ Add as Storage Channel", callback_data=f"fw_store_{chat_id}_{msg_id}")]
                    ]
                    await update.message.reply_text(
                        f"📡 Target found: **{title}** (`{chat_id}`). Click below to confirm.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                elif state == "wait_fw_fsub":
                    await db.set_setting("fsub_channel_id", chat_id)
                    await update.message.reply_text(f"✅ FSUB Channel has been set to ID: `{chat_id}`", parse_mode="Markdown")
                    await db.set_setting("admin_state", None)
                elif state == "wait_fw_early":
                    await db.set_setting("early_access_chat", chat_id)
                    await update.message.reply_text(f"✅ Early Access Chat has been set to ID: `{chat_id}`", parse_mode="Markdown")
                    await db.set_setting("admin_state", None)
                elif state == "wait_fw_archive":
                    await db.set_setting("archive_channel_id", chat_id)
                    await update.message.reply_text(f"✅ Archive Channel has been set to ID: `{chat_id}`", parse_mode="Markdown")
                    await db.set_setting("admin_state", None)
                elif state == "wait_fw_log":
                    await db.set_setting("log_channel_id", chat_id)
                    await update.message.reply_text(f"✅ Log Channel has been set to ID: `{chat_id}`", parse_mode="Markdown")
                    await db.set_setting("admin_state", None)
                return
            else:
                await update.message.reply_text("❌ Invalid format. Please forward a valid message from a channel, or type a raw channel ID (e.g., `-1001234567890`).", parse_mode="Markdown")
                return

    # Handle standard text buttons (all users)
    if update.message and update.message.text:
        if await db.is_user_banned(update.effective_user.id):
            return
            
        text = update.message.text
        if text in ["Next ⏩", "/next"]:
            await send_random_media(update, context, is_prev=False)
        elif text in ["Prev ⏪", "/prev"]:
            await send_random_media(update, context, is_prev=True)
        elif text == "⏱ Auto-Send":
            await toggle_autosend(update, context)
        elif text in ["❓ Help", "/help"]:
            await help_command(update, context)

# ─── Settings UI ───────────────────────────────────────────

async def render_settings_main(target):
    bot = target.get_bot() if hasattr(target, 'get_bot') else target.message.get_bot()
    db = get_db(bot.id)
    keyboard = [
        [InlineKeyboardButton("📡 Channels Setup", callback_data="menu_channels")],
        [InlineKeyboardButton("⏱ Timers & Limits", callback_data="menu_timers")],
        [InlineKeyboardButton("🔀 Toggles", callback_data="menu_toggles")],
        [InlineKeyboardButton("💸 Monetization & Premium", callback_data="menu_premium")],
        [InlineKeyboardButton("📈 DB Stats", callback_data="settings_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "⚙️ *Bot Settings & Admin Panel*\n\nSelect a category below:"
    
    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await target.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def render_menu_premium(query):
    db = get_db(query.message.get_bot().id)
    keyboard = [
        [InlineKeyboardButton("➕ Add Premium User", callback_data="prompt_add_prem"), InlineKeyboardButton("➖ Rm User", callback_data="prompt_rm_prem")],
        [InlineKeyboardButton("👑 Premium Channels", callback_data="settings_prem_channels")],
        [InlineKeyboardButton("💰 Premium Plans", callback_data="settings_prem_plans")],
        [InlineKeyboardButton("🔗 Shortener Settings", callback_data="settings_shortener")],
        [InlineKeyboardButton("👥 Referral Settings", callback_data="settings_referrals")],
        [InlineKeyboardButton("💳 Payment Info", callback_data="prompt_pay_info")],
        [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
    ]
    plans = await db.get_plans()
    pay_info = await db.get_setting("payment_info", "Not Set")
    s_domain = await db.get_setting("shortener_domain", "earn4link.in")
    s_api = await db.get_setting("shortener_api", "Not Set")
    s_days = await db.get_setting("shortener_duration_days", 1)
    r_days = await db.get_setting("referral_duration_days", 1)
    
    text = f"💸 *Monetization & Premium*\n\n"
    text += f"**💰 Active Plans:** `{len(plans)}`\n"
    text += f"**💳 Payment Info:** `{pay_info[:20]}...`\n"
    text += f"**🔗 Shortener API:** `{s_api[:8]}...` (`{s_domain}`)\n"
    text += f"**🎁 Shortener Reward:** `{s_days} Days`\n"
    text += f"**👥 Referral Reward:** `{r_days} Days`\n\n"
    text += "Manage users, plans, and reward settings below:"
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def render_menu_channels(query):
    db = get_db(query.message.get_bot().id)
    fsub_id = await db.get_setting("fsub_channel_id", "Not Set")
    early_id = await db.get_setting("early_access_chat", "Not Set")
    archive_id = await db.get_setting("archive_channel_id", "Not Set")
    
    log_id = await db.get_setting("log_channel_id", "Not Set")
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Storage Channel", callback_data="prompt_fw_store")],
        [InlineKeyboardButton("📊 Storage Channels", callback_data="settings_channels")],
        [InlineKeyboardButton(f"FSUB Ch: {fsub_id}", callback_data="prompt_fw_fsub"), InlineKeyboardButton("❌", callback_data="rm_fsub_id")],
        [InlineKeyboardButton("🔗 Set FSUB Link", callback_data="prompt_fsub_link")],
        [InlineKeyboardButton(f"Early Access: {early_id}", callback_data="prompt_fw_early"), InlineKeyboardButton("❌", callback_data="rm_early")],
        [InlineKeyboardButton(f"Archive Ch: {archive_id}", callback_data="prompt_fw_archive"), InlineKeyboardButton("❌", callback_data="rm_archive")],
        [InlineKeyboardButton(f"Log Ch: {log_id}", callback_data="prompt_fw_log"), InlineKeyboardButton("❌", callback_data="rm_log")],
        [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
    ]
    await query.edit_message_text("⚙️ *Channels Setup*\n\n_Click a button to set a channel, or forward a message after clicking._", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def render_menu_timers(query):
    db = get_db(query.message.get_bot().id)
    del_mins = await db.get_setting("autodelete_minutes", 5)
    exp_mins = await db.get_setting("autosend_expire_minutes", 60)
    archive_days = await db.get_setting("archive_days", 3)
    
    keyboard = [
        [InlineKeyboardButton(f"🗑 Auto-Delete: {del_mins}m", callback_data="settings_autodelete")],
        [InlineKeyboardButton(f"📬 Auto-Send Expiry: {exp_mins}m", callback_data="settings_autoexpire")],
        [InlineKeyboardButton(f"📦 Archive EA Time: {archive_days} Days", callback_data="prompt_archive_days")],
        [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
    ]
    await query.edit_message_text("⚙️ *Timers & Limits*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def render_menu_toggles(query):
    db = get_db(query.message.get_bot().id)
    fsub = await db.get_setting("fsub_enabled", False)
    mode = await db.get_setting("bot_mode", "default")
    delivery = await db.get_setting("delivery_mode", "random")
    clone_mode = await db.get_setting("clone_mode", True)
    
    keyboard = [
        [InlineKeyboardButton(f"Delivery: {'🔀 Random' if delivery == 'random' else '🔢 Serial'}", callback_data="toggle_delivery")],
        [InlineKeyboardButton(f"Force Sub: {'🟢 ON' if fsub else '🔴 OFF'}", callback_data="toggle_fsub")],
        [InlineKeyboardButton(f"Mode: {'🟠 Early Access' if mode == 'early_access' else '🟢 Default'}", callback_data="toggle_mode")],
        [InlineKeyboardButton(f"Clone Mode: {'🟢 ON' if clone_mode else '🔴 OFF'}", callback_data="toggle_clone_mode")],
        [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
    ]
    await query.edit_message_text("⚙️ *Toggles*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    if not await db.is_admin(update.effective_user.id):
        await update.message.reply_text("🔒 You are not authorized to use this command.")
        return
        
    await render_settings_main(update)

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db(context.bot.id)
    query = update.callback_query
    
    if not await db.is_admin(query.from_user.id) and await db.is_user_banned(query.from_user.id):
        await query.answer("❌ You are banned.", show_alert=True)
        return
        
    # Allow set_type_, buy_premium, gen_short_link callbacks for all users
    if query.data.startswith("set_type_"):
        await query.answer()
        chat_id_str = query.data.replace("set_type_", "")
        await db.set_preferred_channel(query.from_user.id, chat_id_str)
        if chat_id_str == "all":
            await query.edit_message_text("✅ Media type set to: **All Channels (Mix)**", parse_mode="Markdown")
        else:
            channels = await db.get_all_channels()
            target = next((c for c in channels if c["chat_id"] == int(chat_id_str)), None)
            name = target["title"] if target else "Specific Channel"
            await query.edit_message_text(f"✅ Media type set to: **{name}**", parse_mode="Markdown")
        return
        
    if query.data == "buy_premium":
        await query.answer()
        plans = await db.get_plans()
        payment_info = await db.get_setting("payment_info", "Contact admin to purchase.")
        text = "👑 **Buy Premium**\n\n"
        for p in plans:
            text += f"- {p['price']}/- for {p['days']} days\n"
        text += f"\n*Payment Info:*\n{payment_info}\n"
        await query.edit_message_text(text, parse_mode="Markdown")
        return
        
    if query.data == "gen_short_link":
        await query.answer()
        api_token = await db.get_setting("shortener_api", None)
        domain = await db.get_setting("shortener_domain", "earn4link.in")
        if not api_token:
            await query.answer("❌ Shortener API not configured.", show_alert=True)
            return
            
        hash_str = f"prem_{uuid.uuid4().hex[:8]}"
        bot_info = await context.bot.get_me()
        destination_link = f"https://t.me/{bot_info.username}?start={hash_str}"
        
        api_url = f"https://{domain}/api?api={api_token}&url={urllib.parse.quote(destination_link)}&format=text"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as resp:
                    short_url = await resp.text()
                    
            if "http" not in short_url:
                raise Exception(f"Failed to shorten: {short_url}")
                
            await db.create_short_link(hash_str, query.from_user.id)
            keyboard = [[InlineKeyboardButton("🔗 Open Link", url=short_url)]]
            await query.edit_message_text(f"📺 Click the link below, watch the ad, and follow the instructions to claim your premium!", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"Shortener API Error: {e}")
            await query.edit_message_text("❌ Error generating link.")
        return
    
    # All other callbacks require owner
    if not await db.is_admin(query.from_user.id):
        await query.answer("🔒 Unauthorized.", show_alert=True)
        return
        
    await query.answer()
    
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_admin_state")]])
    
    if query.data == "settings_main":
        await render_settings_main(query)
    elif query.data == "cancel_admin_state":
        await db.set_setting("admin_state", None)
        await query.answer("Canceled.", show_alert=False)
        query.data = "settings_main"
        await render_settings_main(query)
    elif query.data == "menu_channels":
        await render_menu_channels(query)
    elif query.data == "menu_timers":
        await render_menu_timers(query)
    elif query.data == "menu_toggles":
        await render_menu_toggles(query)
    elif query.data == "menu_premium":
        await render_menu_premium(query)
    elif query.data == "prompt_add_prem":
        await db.set_setting("admin_state", "wait_add_prem")
        await query.edit_message_text("➕ Send me the User ID and duration in days (e.g. `123456789 3` for 3 days):", reply_markup=cancel_kb)
    elif query.data == "prompt_rm_prem":
        await db.set_setting("admin_state", "wait_rm_prem")
        await query.edit_message_text("➖ Send me the User ID of the user you want to revoke Premium access from:", reply_markup=cancel_kb)
    elif query.data == "settings_prem_channels":
        channels = await db.get_all_channels()
        keyboard = []
        if not channels:
            text = "📭 No active storage channels are currently tracked."
        else:
            text = "👑 *Premium Channels Setup:*\n\n_Click on a channel to toggle its premium status. Premium channels are ONLY accessible by Premium Users._\n\n"
            for c in channels:
                title = c.get('title', 'Unknown')
                status = "💎 (Premium)" if c.get("is_premium") else "🆓 (Free)"
                keyboard.append([InlineKeyboardButton(f"{status} {title}", callback_data=f"toggle_prem_{c['chat_id']}")])
                
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_premium")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif query.data.startswith("toggle_prem_"):
        chat_id = int(query.data.split("_")[2])
        await db.toggle_premium_channel(chat_id)
        query.data = "settings_prem_channels"
        await settings_callback(update, context)
    elif query.data == "settings_prem_plans":
        plans = await db.get_plans()
        text = "💰 *Premium Plans*\n\n"
        keyboard = [[InlineKeyboardButton("➕ Add New Plan", callback_data="prompt_add_plan")]]
        for p in plans:
            text += f"- {p['price']}/- for {p['days']} days\n"
            keyboard.append([InlineKeyboardButton(f"❌ Remove {p['price']}/-", callback_data=f"rm_plan_{p['_id']}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_premium")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif query.data == "settings_shortener":
        domain = await db.get_setting("shortener_domain", "earn4link.in")
        api = await db.get_setting("shortener_api", "Not Set")
        days = await db.get_setting("shortener_duration_days", 1)
        text = f"🔗 *Shortener API Settings*\n\n**Domain:** `{domain}`\n**Current API Key:** `{api}`\n**Reward:** `{days}` days\n\nUsers can watch ads on your shortener to get premium."
        keyboard = [
            [InlineKeyboardButton("Set Domain", callback_data="prompt_shortener_domain"), InlineKeyboardButton("Set API Key", callback_data="prompt_shortener_api")],
            [InlineKeyboardButton("Set Reward Days", callback_data="prompt_shortener_days")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_premium")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "settings_referrals":
        days = await db.get_setting("referral_duration_days", 1)
        text = f"👥 *Referral Settings*\n\n**Reward:** `{days}` days per referral."
        keyboard = [
            [InlineKeyboardButton("Set Reward Days", callback_data="prompt_ref_days")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_premium")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif query.data == "prompt_pay_info":
        await db.set_setting("admin_state", "wait_pay_info")
        current = await db.get_setting("payment_info", "Not Set")
        await query.edit_message_text(f"💳 *Payment Instructions*\n\n**Current:**\n`{current}`\n\nSend the Payment Instructions text to display to users:", parse_mode="Markdown", reply_markup=cancel_kb)
    elif query.data == "prompt_add_plan":
        await db.set_setting("admin_state", "wait_add_plan")
        await query.edit_message_text("💰 Send the plan details in this format: `PRICE DAYS`\nExample (29/- for 3 days): `29 3`\n\n_You can send multiple plans on separate lines._", parse_mode="Markdown", reply_markup=cancel_kb)
    elif query.data.startswith("rm_plan_"):
        plan_id = query.data.replace("rm_plan_", "")
        await db.remove_plan(plan_id)
        query.data = "settings_prem_plans"
        await settings_callback(update, context)
    elif query.data == "prompt_shortener_api":
        await db.set_setting("admin_state", "wait_shortener_api")
        current = await db.get_setting("shortener_api", "Not Set")
        await query.edit_message_text(f"🔗 *Shortener API Token*\n\n**Current:** `{current}`\n\nSend your Earn4link (or compatible) API Token:", parse_mode="Markdown", reply_markup=cancel_kb)
    elif query.data == "prompt_shortener_days":
        await db.set_setting("admin_state", "wait_shortener_days")
        current = await db.get_setting("shortener_duration_days", 1)
        await query.edit_message_text(f"🔗 *Shortener Reward Days*\n\n**Current:** `{current}`\n\nSend the reward duration in days (e.g. `1`):", parse_mode="Markdown", reply_markup=cancel_kb)
    elif query.data == "prompt_ref_days":
        await db.set_setting("admin_state", "wait_ref_days")
        current = await db.get_setting("referral_duration_days", 1)
        await query.edit_message_text(f"👥 *Referral Reward Days*\n\n**Current:** `{current}`\n\nSend the referral reward duration in days (e.g. `1`):", parse_mode="Markdown", reply_markup=cancel_kb)
        
    elif query.data == "prompt_shortener_domain":
        await db.set_setting("admin_state", "wait_shortener_domain")
        current = await db.get_setting("shortener_domain", "earn4link.in")
        await query.edit_message_text(f"🔗 *Shortener API Domain*\n\n**Current:** `{current}`\n\nSend your Shortener API Domain (e.g. `earn4link.in`):", parse_mode="Markdown", reply_markup=cancel_kb)
        
    elif query.data == "toggle_delivery":
        delivery = await db.get_setting("delivery_mode", "random")
        new_del = "serial" if delivery == "random" else "random"
        await db.set_setting("delivery_mode", new_del)
        await render_menu_toggles(query)
        
    elif query.data == "toggle_fsub":
        fsub = await db.get_setting("fsub_enabled", False)
        await db.set_setting("fsub_enabled", not fsub)
        await render_menu_toggles(query)
        
    elif query.data == "toggle_clone_mode":
        current = await db.get_setting("clone_mode", True)
        await db.set_setting("clone_mode", not current)
        await render_menu_toggles(query)

    elif query.data == "toggle_mode":
        mode = await db.get_setting("bot_mode", "default")
        new_mode = "early_access" if mode == "default" else "default"
        await db.set_setting("bot_mode", new_mode)
        await render_menu_toggles(query)
        
    elif query.data.startswith("fw_store_"):
        parts = query.data.split("_")
        chat_id, msg_id = int(parts[2]), int(parts[3])
        await db.set_setting("admin_state", f"wait_channel_name_{chat_id}_{msg_id}")
        await query.edit_message_text(f"✅ Preparing to add Storage Channel (ID: `{chat_id}`).\n\nPlease send the custom Display Name (e.g. 'Memes', 'Movie Edits'):", parse_mode="Markdown")
        
    elif query.data.startswith("fw_early_"):
        chat_id = int(query.data.split("_")[2])
        await db.set_setting("early_access_chat", chat_id)
        await query.edit_message_text(f"✅ Early Access Chat has been set to ID: `{chat_id}`", parse_mode="Markdown")

    elif query.data.startswith("fw_archive_"):
        chat_id = int(query.data.split("_")[2])
        await db.set_setting("archive_channel_id", chat_id)
        await query.edit_message_text(f"✅ Archive Channel has been set to ID: `{chat_id}`", parse_mode="Markdown")

    elif query.data.startswith("fw_fsub_"):
        chat_id = int(query.data.split("_")[2])
        await db.set_setting("fsub_channel_id", chat_id)
        await query.edit_message_text(f"✅ FSUB Channel has been set to ID: `{chat_id}`", parse_mode="Markdown")

    elif query.data.startswith("prompt_fw_"):
        mode = query.data.replace("prompt_fw_", "")
        await db.set_setting("admin_state", f"wait_fw_{mode}")
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_state")]]
        await query.edit_message_text(
            "📨 Please **forward a message** from the target channel here.\n\n"
            "_(Or type the chat ID manually, e.g. `-100123...`)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif query.data == "cancel_state":
        await db.set_setting("admin_state", None)
        await render_menu_channels(query)
        
    elif query.data == "prompt_fsub_link":
        await db.set_setting("admin_state", "wait_fsub_link")
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_state")]]
        await query.edit_message_text("🔗 Send me the new FSUB channel link (e.g., https://t.me/joinchat/...)", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif query.data == "prompt_archive_days":
        await db.set_setting("admin_state", "wait_archive_days")
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_state")]]
        await query.edit_message_text("📅 Send me the new Archive Time in days (e.g., 3)", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif query.data == "rm_fsub_id":
        await db.set_setting("fsub_channel_id", "")
        await query.answer("FSUB Channel cleared!", show_alert=False)
        await render_menu_channels(query)
        
    elif query.data == "rm_early":
        await db.set_setting("early_access_chat", "")
        await query.answer("Early Access Chat cleared!", show_alert=False)
        await render_menu_channels(query)
        
    elif query.data == "rm_archive":
        await db.set_setting("archive_channel_id", "")
        await query.answer("Archive Channel cleared!", show_alert=False)
        await render_menu_channels(query)
        
    elif query.data == "rm_log":
        await db.set_setting("log_channel_id", "")
        await query.answer("Log Channel cleared!", show_alert=False)
        await render_menu_channels(query)
        
    elif query.data == "settings_channels":
        channels = await db.get_all_channels()
        keyboard = []
        if not channels:
            text = "📭 No active storage channels are currently tracked."
        else:
            text = "📡 *Tracked Storage Channels:*\n\n"
            for c in channels:
                title = c.get('title', 'Unknown')
                text += f"▪️ *{title}*\n"
                text += f"   ID: `{c['chat_id']}`\n"
                text += f"   Last Message ID: {c['last_message_id']}\n\n"
                keyboard.append([InlineKeyboardButton(f"❌ Remove {title}", callback_data=f"rm_store_{c['chat_id']}")])
                
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_channels")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        
    elif query.data.startswith("rm_store_"):
        chat_id = int(query.data.split("_")[2])
        await db.remove_channel(chat_id)
        
        reply_markup_main = await get_main_keyboard(context.bot.id)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🗑 Storage Channel (ID: `{chat_id}`) has been removed.",
            reply_markup=reply_markup_main,
            parse_mode="Markdown"
        )
        
        await query.answer("Storage channel removed!", show_alert=False)
        query.data = "settings_channels"
        await settings_callback(update, context)
        
    elif query.data == "settings_stats":
        channels = await db.get_all_channels()
        total_channels = len(channels)
        total_posts_approx = sum(c['last_message_id'] for c in channels)
        
        text = (
            "📈 *Database Statistics*\n\n"
            f"📡 Total Tracked Channels: {total_channels}\n"
            f"📝 Approximate Total Posts: ~{total_posts_approx}\n"
            "_(Note: Includes deleted messages and gaps)_"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="settings_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    elif query.data == "settings_autodelete" or query.data.startswith("set_del_"):
        if query.data.startswith("set_del_"):
            mins = int(query.data.split("_")[2])
            await db.set_setting("autodelete_minutes", mins)
            
        current_time = await db.get_setting("autodelete_minutes", 5)
        text = f"⏱ *Auto-Delete Configuration*\n\nCurrent time: **{current_time} minutes**\n\nSelect a new duration:"
        
        keyboard = [
            [InlineKeyboardButton("1 Min", callback_data="set_del_1"),
             InlineKeyboardButton("5 Mins", callback_data="set_del_5"),
             InlineKeyboardButton("15 Mins", callback_data="set_del_15")],
            [InlineKeyboardButton("30 Mins", callback_data="set_del_30"),
             InlineKeyboardButton("60 Mins", callback_data="set_del_60")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_timers")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    elif query.data == "settings_autoexpire" or query.data.startswith("set_exp_"):
        if query.data.startswith("set_exp_"):
            mins = int(query.data.split("_")[2])
            await db.set_setting("autosend_expire_minutes", mins)
            
        current_time = await db.get_setting("autosend_expire_minutes", 60)
        text = f"⏳ *Auto-Send Expiry Configuration*\n\nCurrent duration: **{current_time} minutes**\n\nSelect a new duration:"
        
        keyboard = [
            [InlineKeyboardButton("5 Mins", callback_data="set_exp_5"),
             InlineKeyboardButton("15 Mins", callback_data="set_exp_15"),
             InlineKeyboardButton("30 Mins", callback_data="set_exp_30")],
            [InlineKeyboardButton("1 Hour", callback_data="set_exp_60"),
             InlineKeyboardButton("3 Hours", callback_data="set_exp_180"),
             InlineKeyboardButton("12 Hours", callback_data="set_exp_720")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_timers")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
