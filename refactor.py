import re

with open('bot/handlers.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace db import
code = code.replace('from bot.database import db', 'from bot.database import get_db')

# Insert db = get_db(context.bot.id) in all main handlers
code = re.sub(
    r'(async def [a-zA-Z0-9_]+\(update: Update, context: ContextTypes\.DEFAULT_TYPE\):\s+)',
    r'\1db = get_db(context.bot.id)\n    ',
    code
)

# Fix get_main_keyboard
code = code.replace('async def get_main_keyboard():', 'async def get_main_keyboard(bot_id):')
code = code.replace('db.get_setting(\"delivery_mode\"', 'get_db(bot_id).get_setting(\"delivery_mode\"')
code = code.replace('await get_main_keyboard()', 'await get_main_keyboard(context.bot.id)')

# Fix check_fsub
code = code.replace('async def check_fsub(bot, user_id):', 'async def check_fsub(bot, user_id):\n    db = get_db(bot.id)')

# Fix core_send_media
code = code.replace('async def core_send_media(bot, chat_id, specific_channel_id=None, is_prev=False):', 'async def core_send_media(bot, chat_id, specific_channel_id=None, is_prev=False):\n    db = get_db(bot.id)')

# Fix core_send_early_access_media
code = code.replace('async def core_send_early_access_media(bot, chat_id):', 'async def core_send_early_access_media(bot, chat_id):\n    db = get_db(bot.id)')

# Fix render methods
code = re.sub(
    r'(async def render_[a-zA-Z0-9_]+\(update\):\s+)',
    r'\1db = get_db(update.get_bot().id)\n    ',
    code
)
code = re.sub(
    r'(async def render_[a-zA-Z0-9_]+\(query\):\s+)',
    r'\1db = get_db(query.message.get_bot().id)\n    ',
    code
)

# Handle owner checks dynamically
code = code.replace('if not Config.OWNER_ID:', 'owner_id = await db.get_setting(\"owner_id\", Config.OWNER_ID)\n    if not owner_id:')
code = code.replace('Config.OWNER_ID', 'owner_id')

with open('bot/handlers.py', 'w', encoding='utf-8') as f:
    f.write(code)
