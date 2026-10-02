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

async def send_random_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    success, error_msg = await core_send_media(context.bot, update.effective_chat.id)
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
            
            await db.update_channel(chat_id, title, msg_id)
            await update.message.reply_text(f"✅ Successfully registered channel:\n**{title}**\nLast Message ID: {msg_id}")
            return

    # 2. Handle standard text buttons
    if update.message and update.message.text:
        text = update.message.text
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

async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This fires when the bot is added or removed from a chat
    result = update.my_chat_member
    
    if result.chat.type == "channel":
        new_status = result.new_chat_member.status
        if new_status in ["left", "kicked"]:
            # Removed from channel, stop tracking it
            await db.remove_channel(result.chat.id)
            logger.info(f"Bot removed from channel: {result.chat.id}, deleted from database.")

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if Config.ADMIN_ID and update.effective_user.id != Config.ADMIN_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return
        
    keyboard = [
        [InlineKeyboardButton("📊 View Tracked Channels", callback_data="settings_channels")],
        [InlineKeyboardButton("🔄 Refresh DB Stats", callback_data="settings_stats")],
        [InlineKeyboardButton("⏱ Config Auto-Delete Time", callback_data="settings_autodelete")],
        [InlineKeyboardButton("⏳ Config Auto-Send Expiry", callback_data="settings_autoexpire")]
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
        keyboard = [
            [InlineKeyboardButton("📊 View Tracked Channels", callback_data="settings_channels")],
            [InlineKeyboardButton("🔄 Refresh DB Stats", callback_data="settings_stats")],
            [InlineKeyboardButton("⏱ Config Auto-Delete Time", callback_data="settings_autodelete")],
            [InlineKeyboardButton("⏳ Config Auto-Send Expiry", callback_data="settings_autoexpire")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "⚙️ *Bot Settings & Admin Panel*\nSelect an option below:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
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
