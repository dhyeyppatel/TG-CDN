import random
import logging
import time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from bot.database import db
from bot.config import Config

logger = logging.getLogger(__name__)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎲 Random Media")],
            [KeyboardButton("⏱ Toggle Auto-Send")]
        ],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "Welcome!\n\nClick a button below to get a random media post or start auto-sending.",
        reply_markup=reply_markup
    )
async def check_fsub(bot, user_id):
    fsub_enabled = await db.get_setting("fsub_enabled", False)
    if not fsub_enabled or not Config.FSUB_CHANNEL_ID:
        return True
        
    try:
        member = await bot.get_chat_member(chat_id=Config.FSUB_CHANNEL_ID, user_id=user_id)
        if member.status in ["left", "kicked"]:
            return False
        return True
    except BadRequest:
        return False

async def core_send_media(bot, chat_id):
    channels = await db.get_all_channels()
    if not channels:
        return False, "No storage channels found yet! Forward a message from your channel to me to register it."

    autodelete_mins = await db.get_setting("autodelete_minutes", 5)
    autodelete_secs = autodelete_mins * 60

    for attempt in range(10):
        chosen_channel = random.choice(channels)
        c_id = chosen_channel["chat_id"]
        last_message_id = chosen_channel["last_message_id"]
        random_id = random.randint(1, last_message_id)
        
        try:
            sent_message = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=c_id,
                message_id=random_id,
                reply_markup=None
            )
            
            warning_msg = await bot.send_message(
                chat_id=chat_id, 
                text=f"⏳ _This file will be automatically deleted in {autodelete_mins} minutes._",
                parse_mode="Markdown"
            )
            
            # Schedule DB auto-delete
            delete_at = int(time.time()) + autodelete_secs
            await db.schedule_deletion(chat_id, sent_message.message_id, delete_at)
            await db.schedule_deletion(chat_id, warning_msg.message_id, delete_at)
            return True, None
        except BadRequest:
            continue
        except Exception:
            continue
            
    return False, "Couldn't find a valid post after several attempts. Please try again later!"

async def core_send_early_access_media(bot, chat_id):
    media_list = await db.get_early_access_media_all()
    if not media_list:
        return False, "No early access media found yet! React to a message in your Early Access chat to add it."

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
            
            warning_msg = await bot.send_message(
                chat_id=chat_id, 
                text=f"⏳ _This file will be automatically deleted in {autodelete_mins} minutes._",
                parse_mode="Markdown"
            )
            
            # Schedule DB auto-delete
            delete_at = int(time.time()) + autodelete_secs
            await db.schedule_deletion(chat_id, sent_message.message_id, delete_at)
            await db.schedule_deletion(chat_id, warning_msg.message_id, delete_at)
            return True, None
        except BadRequest:
            await db.remove_early_access_media(c_id, m_id)
            continue
            
    return False, "Failed to fetch early access media after multiple attempts."

async def send_random_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    mode = await db.get_setting("bot_mode", "default")
    
    if mode == "early_access":
        success, error_msg = await core_send_early_access_media(context.bot, chat_id)
    else:
        success, error_msg = await core_send_media(context.bot, chat_id)
        
    if not success and error_msg:
        await update.message.reply_text(error_msg)

async def toggle_autosend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    expire_mins = await db.get_setting("autosend_expire_minutes", 60)
    expires_at = int(time.time()) + (expire_mins * 60)
    
    is_subscribed = await db.toggle_subscriber(chat_id, expires_at)
    
    if is_subscribed:
        mins = await db.get_setting("autodelete_minutes", 5)
        await update.message.reply_text(f"✅ Auto-send started! You will receive random media every 5 minutes for the next {expire_mins} minutes. (They will auto-delete {mins} mins after arriving).")
    else:
        await update.message.reply_text("🛑 Auto-send stopped.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Handle Channel Forwarding initialization (Admin Only)
    if update.message and update.message.forward_origin and update.message.forward_origin.type == "channel":
        if Config.ADMIN_ID and update.effective_user.id == Config.ADMIN_ID:
            chat_id = update.message.forward_origin.chat.id
            title = update.message.forward_origin.chat.title
            msg_id = update.message.forward_origin.message_id
            
            keyboard = [
                [InlineKeyboardButton("Add as Storage Channel", callback_data=f"fw_store_{chat_id}_{msg_id}")],
                [InlineKeyboardButton("Set as Early Access Chat", callback_data=f"fw_early_{chat_id}")]
            ]
            await update.message.reply_text(
                f"You forwarded a message from **{title}**.\nWhat do you want to do with this chat?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

    # 2. Handle standard text buttons
    if update.message and update.message.text:
        text = update.message.text
        if text in ["🎲 Random Media", "⏱ Toggle Auto-Send"]:
            # Check Force Sub
            if not await check_fsub(context.bot, update.effective_user.id):
                keyboard = [[InlineKeyboardButton("Join Channel 📢", url=Config.FSUB_CHANNEL_LINK)]]
                await update.message.reply_text("⚠️ You must join our channel to use this bot!", reply_markup=InlineKeyboardMarkup(keyboard))
                return
                
            # Check Cooldown
            allowed, wait_time = await db.check_cooldown(update.effective_user.id, 5)
            if not allowed:
                await update.message.reply_text(f"⏳ Please wait {wait_time}s before requesting again.")
                return
                
        if text == "🎲 Random Media":
            await send_random_media(update, context)
        elif text == "⏱ Toggle Auto-Send":
            await toggle_autosend(update, context)

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message:
        return
        
    # Any post in any channel dynamically registers/updates its last_message_id
    await db.update_channel(message.chat.id, message.chat.title, message.message_id)
    logger.info(f"Updated LAST_MESSAGE_ID to {message.message_id} for channel {message.chat.id}")

async def reaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reaction = update.message_reaction
    if not reaction:
        return
        
    chat_id = reaction.chat.id
    early_chat = await db.get_setting("early_access_chat", None)
    
    # If the reaction happened in the Early Access chat
    if early_chat and chat_id == int(early_chat):
        # Check if the reaction has new additions
        if reaction.new_reaction:
            await db.add_early_access_media(chat_id, reaction.message_id)
            logger.info(f"Added message {reaction.message_id} to Early Access Media")

async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This fires when the bot is added or removed from a chat
    result = update.my_chat_member
    
    if result.chat.type == "channel":
        new_status = result.new_chat_member.status
        if new_status in ["left", "kicked"]:
            # Removed from channel, stop tracking it
            await db.remove_channel(result.chat.id)
            logger.info(f"Bot removed from channel: {result.chat.id}, deleted from database.")

async def render_settings_main(query):
    fsub = await db.get_setting("fsub_enabled", False)
    fsub_text = "🟢 ON" if fsub else "🔴 OFF"
    
    mode = await db.get_setting("bot_mode", "default")
    mode_text = "🟠 Early Access Mode" if mode == "early_access" else "🟢 Default Mode"
    
    keyboard = [
        [InlineKeyboardButton("📊 View Tracked Channels", callback_data="settings_channels")],
        [InlineKeyboardButton("🔄 Refresh DB Stats", callback_data="settings_stats")],
        [InlineKeyboardButton("⏱ Config Auto-Delete Time", callback_data="settings_autodelete")],
        [InlineKeyboardButton("⏳ Config Auto-Send Expiry", callback_data="settings_autoexpire")],
        [InlineKeyboardButton(f"📢 Force Sub: {fsub_text}", callback_data="toggle_fsub")],
        [InlineKeyboardButton(f"Mode: {mode_text}", callback_data="toggle_mode")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "⚙️ *Bot Settings & Admin Panel*\nSelect an option below:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if Config.ADMIN_ID and update.effective_user.id != Config.ADMIN_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return
        
    fsub = await db.get_setting("fsub_enabled", False)
    fsub_text = "🟢 ON" if fsub else "🔴 OFF"
    
    mode = await db.get_setting("bot_mode", "default")
    mode_text = "🟠 Early Access Mode" if mode == "early_access" else "🟢 Default Mode"
    
    keyboard = [
        [InlineKeyboardButton("📊 View Tracked Channels", callback_data="settings_channels")],
        [InlineKeyboardButton("🔄 Refresh DB Stats", callback_data="settings_stats")],
        [InlineKeyboardButton("⏱ Config Auto-Delete Time", callback_data="settings_autodelete")],
        [InlineKeyboardButton("⏳ Config Auto-Send Expiry", callback_data="settings_autoexpire")],
        [InlineKeyboardButton(f"📢 Force Sub: {fsub_text}", callback_data="toggle_fsub")],
        [InlineKeyboardButton(f"Mode: {mode_text}", callback_data="toggle_mode")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚙️ *Bot Settings & Admin Panel*\nSelect an option below:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if Config.ADMIN_ID and query.from_user.id != Config.ADMIN_ID:
        await query.answer("Unauthorized.", show_alert=True)
        return
        
    await query.answer()
    
    if query.data == "settings_main":
        await render_settings_main(query)
        
    elif query.data == "toggle_fsub":
        fsub = await db.get_setting("fsub_enabled", False)
        await db.set_setting("fsub_enabled", not fsub)
        await query.answer("Force sub toggled!", show_alert=False)
        await render_settings_main(query)
        
    elif query.data == "toggle_mode":
        mode = await db.get_setting("bot_mode", "default")
        new_mode = "early_access" if mode == "default" else "default"
        await db.set_setting("bot_mode", new_mode)
        await query.answer(f"Mode changed to {new_mode.replace('_', ' ').title()}!", show_alert=False)
        await render_settings_main(query)
        
    elif query.data.startswith("fw_store_"):
        parts = query.data.split("_")
        chat_id, msg_id = int(parts[2]), int(parts[3])
        await db.update_channel(chat_id, "Tracked Storage Channel", msg_id)
        await query.edit_message_text(f"✅ Added as a Storage Channel! ID: {chat_id}, Last Msg: {msg_id}")
        
    elif query.data.startswith("fw_early_"):
        chat_id = int(query.data.split("_")[2])
        await db.set_setting("early_access_chat", chat_id)
        await query.edit_message_text(f"✅ Early Access Chat has been set to ID: {chat_id}")
        
    elif query.data == "settings_channels":
        channels = await db.get_all_channels()
        if not channels:
            text = "No active storage channels are currently tracked."
        else:
            text = "📡 *Tracked Storage Channels:*\n\n"
            for c in channels:
                title = c.get('title', 'Unknown')
                text += f"▪️ *{title}*\n"
                text += f"   ID: `{c['chat_id']}`\n"
                text += f"   Last Message ID: {c['last_message_id']}\n\n"
                
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="settings_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        
    elif query.data == "settings_stats":
        channels = await db.get_all_channels()
        total_channels = len(channels)
        total_posts_approx = sum(c['last_message_id'] for c in channels)
        
        text = (
            "📈 *Database Statistics*\n\n"
            f"Total Tracked Channels: {total_channels}\n"
            f"Approximate Total Posts: ~{total_posts_approx}\n"
            "_(Note: This includes deleted messages and gaps)_"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="settings_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    elif query.data == "settings_autodelete" or query.data.startswith("set_del_"):
        if query.data.startswith("set_del_"):
            mins = int(query.data.split("_")[2])
            await db.set_setting("autodelete_minutes", mins)
            await query.answer(f"Auto-delete time set to {mins} minutes!", show_alert=False)
            
        current_time = await db.get_setting("autodelete_minutes", 5)
        text = f"⏱ *Auto-Delete Configuration*\n\nCurrent time: **{current_time} minutes**\n\nSelect a new duration:"
        
        keyboard = [
            [InlineKeyboardButton("1 Min", callback_data="set_del_1"),
             InlineKeyboardButton("5 Mins", callback_data="set_del_5"),
             InlineKeyboardButton("15 Mins", callback_data="set_del_15")],
            [InlineKeyboardButton("30 Mins", callback_data="set_del_30"),
             InlineKeyboardButton("60 Mins", callback_data="set_del_60")],
            [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    elif query.data == "settings_autoexpire" or query.data.startswith("set_exp_"):
        if query.data.startswith("set_exp_"):
            mins = int(query.data.split("_")[2])
            await db.set_setting("autosend_expire_minutes", mins)
            await query.answer(f"Auto-Send expiry set to {mins} minutes!", show_alert=False)
            
        current_time = await db.get_setting("autosend_expire_minutes", 60)
        text = f"⏳ *Auto-Send Expiry Configuration*\n\nCurrent duration: **{current_time} minutes**\n\nSelect a new duration for auto-send subscriptions:"
        
        keyboard = [
            [InlineKeyboardButton("5 Mins", callback_data="set_exp_5"),
             InlineKeyboardButton("15 Mins", callback_data="set_exp_15"),
             InlineKeyboardButton("30 Mins", callback_data="set_exp_30")],
            [InlineKeyboardButton("1 Hour", callback_data="set_exp_60"),
             InlineKeyboardButton("3 Hours", callback_data="set_exp_180"),
             InlineKeyboardButton("12 Hours", callback_data="set_exp_720")],
            [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
