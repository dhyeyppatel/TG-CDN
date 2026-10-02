from pyrogram import Client, filters
from pyrogram.types import Message
from bot.config import Config
from bot.database import db
import logging

logger = logging.getLogger(__name__)

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    # Check if there is a payload (e.g., /start uuid)
    if len(message.command) > 1:
        payload = message.command[1]
        
        # Fetch file info from DB using the payload (uuid)
        file_doc = await db.get_file(payload)
        
        if file_doc:
            message_id = file_doc["message_id"]
            
            try:
                # Copy the message from the channel to the user
                # We remove the reply_markup so the inline button doesn't appear in the PM
                await client.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=Config.CHANNEL_ID,
                    message_id=message_id,
                    reply_markup=None 
                )
                logger.info(f"File {message_id} sent to user {message.from_user.id}")
            except Exception as e:
                logger.error(f"Error sending file to user: {e}")
                await message.reply_text("An error occurred while fetching the file. Ensure the bot is still an admin in the channel.")
        else:
            await message.reply_text("File not found! The link might be invalid or expired.")
        return

    # Default start message
    await message.reply_text(
        "Hello! I am a CDN File Bot.\n\n"
        "I provide files directly when you click on links generated in my channel."
    )
