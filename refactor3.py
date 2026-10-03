import re

with open('bot/handlers.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Update render_menu_toggles to include Clone Mode
code = code.replace(
    '        [InlineKeyboardButton(f"Mode: {\'?? Early Access\' if mode == \'early_access\' else \'?? Default\'}", callback_data="toggle_mode")],',
    '        [InlineKeyboardButton(f"Mode: {\'?? Early Access\' if mode == \'early_access\' else \'?? Default\'}", callback_data="toggle_mode")],\n        [InlineKeyboardButton(f"Clone Mode: {\'?? ON\' if clone_mode else \'?? OFF\'}", callback_data="toggle_clone_mode")],'
)
code = code.replace(
    '    delivery = await db.get_setting("delivery_mode", "random")',
    '    delivery = await db.get_setting("delivery_mode", "random")\n    clone_mode = await db.get_setting("clone_mode", True)'
)

# Update settings_callback for toggle_clone_mode
code = code.replace(
    '    elif query.data == "toggle_mode":',
    '    elif query.data == "toggle_clone_mode":\n        current = await db.get_setting("clone_mode", True)\n        await db.set_setting("clone_mode", not current)\n        await render_menu_toggles(query)\n\n    elif query.data == "toggle_mode":'
)

# Update clone_command to enforce clone_mode
code = code.replace(
    '    text = update.message.text',
    '    clone_mode = await db.get_setting("clone_mode", True)\n    if not clone_mode and update.effective_user.id != (await db.get_setting("owner_id", Config.OWNER_ID)):\n        await update.message.reply_text("? Clone mode is currently disabled by the owner.")\n        return\n\n    text = update.message.text'
)

with open('bot/handlers.py', 'w', encoding='utf-8') as f:
    f.write(code)
