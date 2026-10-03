import random
import logging
import time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from bot.database import db
from bot.config import Config

logger = logging.getLogger(__name__)

async def get_main_keyboard():
    delivery_mode = await db.get_setting("delivery_mode", "random")
    keyboard = []
    
    if delivery_mode == "serial":
        keyboard.append([KeyboardButton("Prev ⏪"), KeyboardButton("Next ⏩")])
    else:
        keyboard.append([KeyboardButton("Next ⏩")])
        
    keyboard.append([KeyboardButton("⏱ Auto-Send"), KeyboardButton("❓ Help")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def type_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = await db.get_all_channels()
    keyboard = []
    
    for c in channels:
        name = c.get('title', 'Unknown Channel')
        keyboard.append([InlineKeyboardButton(f"📁 {name}", callback_data=f"set_type_{c['chat_id']}")])
        
    keyboard.append([InlineKeyboardButton("🎲 All Channels (Mix)", callback_data="set_type_all")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("Select your preferred media type:", reply_markup=reply_markup)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = await get_main_keyboard()
    await update.message.reply_text(
        "Welcome!\n\nUse the buttons below to browse media, or use /type to select your preferred category.",
        reply_markup=reply_markup
    )
async def check_fsub(bot, user_id):
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

async def core_send_media(bot, chat_id, specific_channel_id=None, is_prev=False):
    channels = await db.get_all_channels()
    if not channels:
        return False, "No storage channels found yet! Forward a message from your channel to me to register it."
        
    if specific_channel_id:
        channels = [c for c in channels if c["chat_id"] == specific_channel_id]
        if not channels:
            return False, "This specific channel is no longer tracked."

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
                # User has exhausted this channel, loop back to start
                await db.update_user_progress(chat_id, c_id, 1)
                target_id = 1
        else:
            if is_prev:
                return False, "Previous button is only supported in Serial delivery mode."
            target_id = random.randint(1, last_message_id)
        
        try:
            media_group = await db.get_media_group_by_message_id(c_id, target_id)
            
            if media_group and len(media_group.get("message_ids", [])) > 1:
                # Copy the entire media group
                sent_messages = await bot.copy_messages(
                    chat_id=chat_id,
                    from_chat_id=c_id,
                    message_ids=media_group["message_ids"]
                )
                
                reply_markup = await get_main_keyboard()
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
                # Normal single message copy
                sent_message = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=c_id,
                    message_id=target_id,
                    reply_markup=None
                )
                
                reply_markup = await get_main_keyboard()
                warning_msg = await bot.send_message(
                    chat_id=chat_id, 
                    text=f"⏳ _This file will be automatically deleted in {autodelete_mins} minutes._",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
                
                # Schedule DB auto-delete
                delete_at = int(time.time()) + autodelete_secs
                await db.schedule_deletion(chat_id, sent_message.message_id, delete_at)
                await db.schedule_deletion(chat_id, warning_msg.message_id, delete_at)
                
                if delivery_mode == "serial":
                    await db.update_user_progress(chat_id, c_id, target_id + 1)
                    
                return True, None
        except BadRequest:
            if delivery_mode == "serial":
                # Message might be deleted in channel, skip it
                await db.update_user_progress(chat_id, c_id, target_id + 1)
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
            
            reply_markup = await get_main_keyboard()
            warning_msg = await bot.send_message(
                chat_id=chat_id, 
                text=f"⏳ _This file will be automatically deleted in {autodelete_mins} minutes._",
                parse_mode="Markdown",
                reply_markup=reply_markup
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

async def send_random_media(update: Update, context: ContextTypes.DEFAULT_TYPE, is_prev=False):
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
        # Fetch user's preferred channel
        pref = await db.get_preferred_channel(chat_id)
        specific = int(pref) if pref != "all" else None
        success, error_msg = await core_send_media(context.bot, chat_id, specific, is_prev)
        
    if not success and error_msg:
        await update.message.reply_text(error_msg)

async def toggle_autosend(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text(f"✅ Auto-send started! You will receive random media every 5 minutes for the next {expire_mins} minutes. (They will auto-delete {mins} mins after arriving).")
    else:
        await update.message.reply_text("🛑 Auto-send stopped.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *How to use this bot*\n\n"
        "Here are the available features and commands:\n\n"
        "🔹 *Core Features:*\n"
        "• *Next / Prev*: Request the next (or previous) media file. (Prev only works if the bot is in Serial Mode).\n"
        "• *Auto-Send*: Automatically receive a new media file every 5 minutes! (Toggle on/off).\n\n"
        "🔹 *Commands:*\n"
        "• /start - Restart the bot and show the main menu.\n"
        "• /type - Opens a menu allowing you to lock your requests to a specific category (e.g. only 'Memes').\n"
        "• /next - Request the next media.\n"
        "• /prev - Request the previous media.\n"
        "• /autosend - Toggle the Auto-Send feature.\n"
        "• /help - Show this help message.\n"
    )
    
    if Config.OWNER_ID and update.effective_user.id == Config.OWNER_ID:
        text += (
            "\n👑 *Admin Features:*\n"
            "• /settings - Open the Admin Control Panel to configure channels, timers, delivery modes, and more.\n"
            "   - *Storage Channels*: The bot randomly (or serially) pulls media from these channels for the default pool.\n"
            "   - *Early Access*: Posts sent to this chat are kept in an exclusive pool until they are automatically moved to Archive.\n"
            "   - *Force Sub*: Require users to join a specific channel before using the bot.\n"
        )
        
    await update.message.reply_text(text, parse_mode="Markdown")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 0. Handle Admin States
    if not Config.OWNER_ID:
        return
        
    if update.effective_user.id == Config.OWNER_ID:
        state = await db.get_setting("admin_state", None)
        if state and update.message and update.message.text:
            text = update.message.text
            if state == "wait_fsub_link":
                await db.set_setting("fsub_channel_link", text)
                await db.set_setting("admin_state", None)
                await update.message.reply_text(f"✅ FSUB Link updated to: {text}\nSend /settings to view changes.")
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
                # Check if it exists
                channels = await db.get_all_channels()
                exists = next((c for c in channels if c["chat_id"] == chat_id), None)
                if exists:
                    await db.update_channel(chat_id, text, exists["last_message_id"])
                else:
                    await db.update_channel(chat_id, text, msg_id)
                    
                await db.set_setting("admin_state", None)
                reply_markup = await get_main_keyboard()
                await update.message.reply_text(f"✅ Channel display name set to: **{text}**\n\nThe main menu has been updated.", parse_mode="Markdown", reply_markup=reply_markup)
                return

        # Handle wait_fw_ states
        if state and state.startswith("wait_fw_"):
            chat_id = None
            title = "Channel"
            msg_id = 1
            
            if update.message.forward_origin and hasattr(update.message.forward_origin, "chat"):
                chat_id = update.message.forward_origin.chat.id
                title = update.message.forward_origin.chat.title
                msg_id = update.message.forward_origin.message_id
            elif update.message.forward_from_chat:
                chat_id = update.message.forward_from_chat.id
                title = update.message.forward_from_chat.title
                msg_id = update.message.forward_from_message_id
            elif update.message.text:
                text = update.message.text.strip()
                if text.startswith("-100") and text.replace("-", "").isdigit():
                    chat_id = int(text)
                    title = "Manual Channel"
                    
            if chat_id:
                if state == "wait_fw_store":
                    keyboard = [
                        [InlineKeyboardButton("Add as Storage Channel", callback_data=f"fw_store_{chat_id}_{msg_id}")]
                    ]
                    await update.message.reply_text(
                        f"Target found: **{title}** (`{chat_id}`). Click below to confirm.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                elif state == "wait_fw_fsub":
                    await db.set_setting("fsub_channel_id", chat_id)
                    await update.message.reply_text(f"✅ FSUB Channel has been set to ID: {chat_id}")
                    await db.set_setting("admin_state", None)
                elif state == "wait_fw_early":
                    await db.set_setting("early_access_chat", chat_id)
                    await update.message.reply_text(f"✅ Early Access Chat has been set to ID: {chat_id}")
                    await db.set_setting("admin_state", None)
                elif state == "wait_fw_archive":
                    await db.set_setting("archive_channel_id", chat_id)
                    await update.message.reply_text(f"✅ Archive Channel has been set to ID: {chat_id}")
                    await db.set_setting("admin_state", None)
                return
            else:
                await update.message.reply_text("❌ Invalid format. Please forward a valid message from a channel, or type a raw channel ID (e.g., `-1001234567890`).", parse_mode="Markdown")
                return



    # 2. Handle standard text buttons
    if update.message and update.message.text:
        text = update.message.text
        if text in ["Next ⏩", "/next"]:
            await send_random_media(update, context, is_prev=False)
        elif text in ["Prev ⏪", "/prev"]:
            await send_random_media(update, context, is_prev=True)
        elif text == "⏱ Auto-Send":
            await toggle_autosend(update, context)
        elif text in ["❓ Help", "/help"]:
            await help_command(update, context)

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message:
        return
        
    # Ignore posts in the archive channel (do not add them to the Default Pool)
    archive_id = await db.get_setting("archive_channel_id", "")
    if archive_id and message.chat.id == int(archive_id):
        return
        
    # Any post in any channel dynamically registers/updates its last_message_id
    await db.update_channel(message.chat.id, message.chat.title, message.message_id)
    
    if message.media_group_id:
        await db.add_to_media_group(message.chat.id, message.media_group_id, message.message_id)
        
    logger.info(f"Updated LAST_MESSAGE_ID to {message.message_id} for channel {message.chat.id}")

async def reaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    # If the reaction happened in the Early Access chat
    if early_chat and chat_id == int(early_chat):
        if is_add:
            await db.add_early_access_media(chat_id, msg_id)
            logger.info(f"Added message {msg_id} to Early Access Media")
        else:
            await db.remove_early_access_media(chat_id, msg_id)
            logger.info(f"Removed message {msg_id} from Early Access Media due to unreact")

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
    keyboard = [
        [InlineKeyboardButton("⚙️ Channels Setup", callback_data="menu_channels")],
        [InlineKeyboardButton("⚙️ Timers & Limits", callback_data="menu_timers")],
        [InlineKeyboardButton("⚙️ Toggles", callback_data="menu_toggles")],
        [InlineKeyboardButton("🔄 Refresh DB Stats", callback_data="settings_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "⚙️ *Bot Settings & Admin Panel*\nSelect a category below:"
    
    if hasattr(query, 'edit_message_text'):
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def render_menu_channels(query):
    fsub_id = await db.get_setting("fsub_channel_id", "Not Set")
    early_id = await db.get_setting("early_access_chat", "Not Set")
    archive_id = await db.get_setting("archive_channel_id", "Not Set")
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Storage Channel", callback_data="prompt_fw_store")],
        [InlineKeyboardButton("📊 Storage Channels", callback_data="settings_channels")],
        [InlineKeyboardButton(f"FSUB Ch: {fsub_id}", callback_data="prompt_fw_fsub"), InlineKeyboardButton("❌", callback_data="rm_fsub_id")],
        [InlineKeyboardButton("Set FSUB Link", callback_data="prompt_fsub_link")],
        [InlineKeyboardButton(f"Early Access: {early_id}", callback_data="prompt_fw_early"), InlineKeyboardButton("❌", callback_data="rm_early")],
        [InlineKeyboardButton(f"Archive Ch: {archive_id}", callback_data="prompt_fw_archive"), InlineKeyboardButton("❌", callback_data="rm_archive")],
        [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
    ]
    await query.edit_message_text("⚙️ *Channels Setup*\n\n_To set a channel, forward a message from it to the bot, and select what type of channel it is. Or click buttons to remove them._", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def render_menu_timers(query):
    del_mins = await db.get_setting("autodelete_minutes", 5)
    exp_mins = await db.get_setting("autosend_expire_minutes", 60)
    archive_days = await db.get_setting("archive_days", 3)
    
    keyboard = [
        [InlineKeyboardButton(f"Auto-Delete: {del_mins}m", callback_data="settings_autodelete")],
        [InlineKeyboardButton(f"Auto-Send Expiry: {exp_mins}m", callback_data="settings_autoexpire")],
        [InlineKeyboardButton(f"Archive EA Time: {archive_days} Days", callback_data="prompt_archive_days")],
        [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
    ]
    await query.edit_message_text("⚙️ *Timers & Limits*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def render_menu_toggles(query):
    fsub = await db.get_setting("fsub_enabled", False)
    mode = await db.get_setting("bot_mode", "default")
    delivery = await db.get_setting("delivery_mode", "random")
    
    keyboard = [
        [InlineKeyboardButton(f"Delivery: {'🔀 Random' if delivery == 'random' else '🔢 Serial'}", callback_data="toggle_delivery")],
        [InlineKeyboardButton(f"Force Sub: {'🟢 ON' if fsub else '🔴 OFF'}", callback_data="toggle_fsub")],
        [InlineKeyboardButton(f"Mode: {'🟠 Early Access' if mode == 'early_access' else '🟢 Default'}", callback_data="toggle_mode")],
        [InlineKeyboardButton("🔙 Back", callback_data="settings_main")]
    ]
    await query.edit_message_text("⚙️ *Toggles*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not Config.OWNER_ID or update.effective_user.id != Config.OWNER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return
        
    await render_settings_main(update)

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not Config.OWNER_ID or query.from_user.id != Config.OWNER_ID:
        await query.answer("Unauthorized.", show_alert=True)
        return
        
    await query.answer()
    
    if query.data == "settings_main":
        await render_settings_main(query)
    elif query.data == "menu_channels":
        await render_menu_channels(query)
    elif query.data == "menu_timers":
        await render_menu_timers(query)
    elif query.data == "menu_toggles":
        await render_menu_toggles(query)
        
    elif query.data == "toggle_delivery":
        delivery = await db.get_setting("delivery_mode", "random")
        new_del = "serial" if delivery == "random" else "random"
        await db.set_setting("delivery_mode", new_del)
        await query.answer(f"Delivery mode changed to {new_del.title()}!", show_alert=False)
        await render_menu_toggles(query)
        
    elif query.data == "toggle_fsub":
        fsub = await db.get_setting("fsub_enabled", False)
        await db.set_setting("fsub_enabled", not fsub)
        await query.answer("Force sub toggled!", show_alert=False)
        await render_menu_toggles(query)
        
    elif query.data == "toggle_mode":
        mode = await db.get_setting("bot_mode", "default")
        new_mode = "early_access" if mode == "default" else "default"
        await db.set_setting("bot_mode", new_mode)
        await query.answer(f"Mode changed to {new_mode.replace('_', ' ').title()}!", show_alert=False)
        await render_menu_toggles(query)
        
    elif query.data.startswith("fw_store_"):
        parts = query.data.split("_")
        chat_id, msg_id = int(parts[2]), int(parts[3])
        
        # Prompt for channel name
        await db.set_setting("admin_state", f"wait_channel_name_{chat_id}_{msg_id}")
        await query.edit_message_text(f"✅ Preparing to add Storage Channel (ID: {chat_id}).\n\nPlease send the custom Display Name you want to use for this channel (e.g. 'Memes', 'Movie Edits'):")
        
    elif query.data.startswith("fw_early_"):
        chat_id = int(query.data.split("_")[2])
        await db.set_setting("early_access_chat", chat_id)
        await query.edit_message_text(f"✅ Early Access Chat has been set to ID: {chat_id}")

    elif query.data.startswith("set_type_"):
        chat_id_str = query.data.replace("set_type_", "")
        await db.set_preferred_channel(query.from_user.id, chat_id_str)
        if chat_id_str == "all":
            await query.edit_message_text("✅ Media type set to: **All Channels (Mix)**", parse_mode="Markdown")
        else:
            # Find name
            channels = await db.get_all_channels()
            target = next((c for c in channels if c["chat_id"] == int(chat_id_str)), None)
            name = target["title"] if target else "Specific Channel"
            await query.edit_message_text(f"✅ Media type set to: **{name}**", parse_mode="Markdown")

    elif query.data.startswith("fw_archive_"):
        chat_id = int(query.data.split("_")[2])
        await db.set_setting("archive_channel_id", chat_id)
        await query.edit_message_text(f"✅ Archive Channel has been set to ID: {chat_id}")

    elif query.data.startswith("fw_fsub_"):
        chat_id = int(query.data.split("_")[2])
        await db.set_setting("fsub_channel_id", chat_id)
        await query.edit_message_text(f"✅ FSUB Channel has been set to ID: {chat_id}")

    elif query.data.startswith("prompt_fw_"):
        mode = query.data.replace("prompt_fw_", "")
        await db.set_setting("admin_state", f"wait_fw_{mode}")
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_state")]]
        await query.edit_message_text(
            "Please **forward a message** from the target channel here.\n\n"
            "*(Or you can just send the chat ID manually, e.g. `-100123...`)*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif query.data == "cancel_state":
        await db.set_setting("admin_state", None)
        await query.answer("Cancelled.", show_alert=False)
        await render_menu_channels(query)
        
    elif query.data == "prompt_fsub_link":
        await db.set_setting("admin_state", "wait_fsub_link")
        await query.edit_message_text("🔗 Send me the new FSUB channel link (e.g., https://t.me/joinchat/...)")
        
    elif query.data == "prompt_archive_days":
        await db.set_setting("admin_state", "wait_archive_days")
        await query.edit_message_text("📅 Send me the new Archive Time in days (e.g., 3)")
        
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
        
    elif query.data == "settings_channels":
        channels = await db.get_all_channels()
        keyboard = []
        if not channels:
            text = "No active storage channels are currently tracked."
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
        
        # update main keyboard in case they deleted the only channel
        reply_markup_main = await get_main_keyboard()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🗑 Storage Channel (ID: {chat_id}) has been removed.\nMain menu updated.",
            reply_markup=reply_markup_main
        )
        
        await query.answer("Storage channel removed!", show_alert=False)
        # re-render list
        query.data = "settings_channels"
        await settings_callback(update, context)
        
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
            [InlineKeyboardButton("🔙 Back", callback_data="menu_timers")]
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
            [InlineKeyboardButton("🔙 Back", callback_data="menu_timers")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
