# Telegram Random Media Bot

A highly efficient Telegram bot that distributes media (videos, anime clips, edits, images, etc.) directly from a Telegram channel using a simple `LAST_MESSAGE_ID` approach. 

The bot does **not** download files, does **not** index thousands of messages in a database, and avoids any heavy lifting. It randomly generates a message ID and uses Telegram's built-in `copyMessage` functionality to serve it from the storage channel.

## Features
- Storageless: Media files are stored natively inside your Telegram channel.
- Lightweight Database: The MongoDB instance literally only stores `{"key": "last_message_id", "value": 12345}` per channel.
- Smart Retries: Gracefully handles deleted messages and gaps by retrying up to 10 times.
- Auto-updating: Whenever you post new media to the storage channel, the bot automatically bumps its `LAST_MESSAGE_ID` silently.

## Deployment

1. Rename `.env.example` to `.env` and fill the variables:
   - `BOT_TOKEN`: From @BotFather
   - `MONGODB_URI`: Your MongoDB Atlas connection URL
   - `DATABASE_NAME`: Desired database name (e.g. `meme_bot_db`)

### How to use
Just add the bot as an administrator to ANY of your Telegram Channels and post a meme!
The bot automatically detects the channel, starts tracking its `last_message_id`, and adds it to the random rotation. It fully supports multiple channels out of the box!

The provided `Procfile` will automatically be detected:
```
worker: python run.py
```

### For Vercel (Webhooks)
Deploy directly to Vercel. After deployment, register the webhook:
`https://<your-vercel-app-url>.vercel.app/api/set_webhook?url=https://<your-vercel-app-url>.vercel.app`

### Local Setup
```bash
pip install -r requirements.txt
python run.py
```
