from telegram.ext import Application, CommandHandler, MessageHandler, filters, ChatMemberHandler, CallbackQueryHandler, MessageReactionHandler, TypeHandler
from telegram import Update
from bot.config import Config
from bot.handlers import start_handler, channel_post_handler, message_handler, my_chat_member_handler, settings_handler, settings_callback, toggle_autosend, reaction_handler
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def create_app():
    app = Application.builder().token(Config.BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("autosend", toggle_autosend))
    
    # Settings command for admins
    app.add_handler(CommandHandler("settings", settings_handler))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^(settings_|set_del_|set_exp_|toggle_fsub|toggle_mode|fw_)"))
    
    # Listen for button presses in PM
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # Listen for new reactions in Early Access Chat (Works for both Private and Channels)
    app.add_handler(TypeHandler(Update, reaction_handler))
    
    # Listen for new memes in ALL channels to dynamically update LAST_MESSAGE_ID
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_post_handler))
    
    # Listen for when bot is kicked from a channel to clean up DB
    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    
    return app
