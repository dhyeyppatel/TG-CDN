from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import Config
from bot.database import db
import logging

logger = logging.getLogger(__name__)

# Listen for documents, videos, and audio in the specified channel
@Client.on_message(filters.chat(Config.CHANNEL_ID) & (filters.document | filters.video | filters.audio))
async def on_channel_post(client: Client, message: Message):
    try:
        # Determine the file_id based on media type
        file_id = None
        if message.document:
            file_id = message.document.file_id
        elif message.video:
            file_id = message.video.file_id
        elif message.audio:
            file_id = message.audio.file_id

        if not file_id:
            return

        message_id = message.id
        
        # Save to MongoDB and get a unique short id for the deep link
        file_uuid = await db.save_file(file_id, message_id)
        
        # Get Bot info to generate the link
        me = await client.get_me()
        bot_username = me.username
        
        # Generate the deep link payload
        link = f"https://t.me/{bot_username}?start={file_uuid}"
        
        # Append inline keyboard with the link to the original channel post
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Get File 📥", url=link)]]
        )
        
        await message.edit_reply_markup(reply_markup=reply_markup)
        logger.info(f"Processed file from channel: {message_id}, link generated.")
        
    except Exception as e:
        logger.error(f"Error processing channel post: {e}")
