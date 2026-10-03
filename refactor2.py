import re

with open('bot/handlers.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix owner_id undefined variables
code = code.replace('owner_id = await db.get_setting("owner_id", owner_id)', 'owner_id = await db.get_setting("owner_id", Config.OWNER_ID)')

code = code.replace(
    'if owner_id and update.effective_user.id == owner_id:',
    'owner_id = await db.get_setting("owner_id", Config.OWNER_ID)\n    if owner_id and update.effective_user.id == owner_id:'
)

# In channel_post_handler, replace db = get_db(context.bot.id) with db = get_db(context.bot.id)
# Check for any other owner_id errors
with open('bot/handlers.py', 'w', encoding='utf-8') as f:
    f.write(code)
