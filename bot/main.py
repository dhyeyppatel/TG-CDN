from telegram.ext import Application, CommandHandler, MessageHandler, filters, ChatMemberHandler, CallbackQueryHandler, MessageReactionHandler, TypeHandler
from telegram import Update
from bot.config import Config
from bot.handlers import start_handler, channel_post_handler, message_handler, my_chat_member_handler, settings_handler, settings_callback, toggle_autosend, reaction_handler, type_command, send_random_media, help_command, clone_command, premium_command, ban_command, unban_command, addadmin_command, rmadmin_command
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def create_app(token=None):
    if token is None:
        token = Config.BOT_TOKEN
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("autosend", toggle_autosend))
    app.add_handler(CommandHandler("type", type_command))
    app.add_handler(CommandHandler("next", send_random_media))
    app.add_handler(CommandHandler("prev", send_random_media))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clone", clone_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("addadmin", addadmin_command))
    app.add_handler(CommandHandler("rmadmin", rmadmin_command))
    
    # Settings command for admins
    app.add_handler(CommandHandler("settings", settings_handler))
    app.add_handler(CallbackQueryHandler(settings_callback))
    
    # Listen for button presses and forwards in PM
    app.add_handler(MessageHandler(~filters.COMMAND, message_handler))
    
    # Listen for new reactions in Early Access Chat (Works for both Private and Channels)
    app.add_handler(TypeHandler(Update, reaction_handler))
    
    # Listen for new memes in ALL channels to dynamically update LAST_MESSAGE_ID
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_post_handler))
    
    # Listen for when bot is kicked from a channel to clean up DB
    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    
    return app
