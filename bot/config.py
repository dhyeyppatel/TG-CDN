import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    MONGODB_URI = os.environ.get("MONGODB_URI", "")
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "media_bot_db")
    OWNER_ID = int(os.environ.get("OWNER_ID", os.environ.get("ADMIN_ID", 0)))
