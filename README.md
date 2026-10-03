# Telegram Media CDN Bot

A highly efficient, multi-tenant Telegram bot that acts as a Content Delivery Network (CDN) for media. It serves videos, images, and clips directly from Telegram channels without downloading or storing files on your server.

This bot supports **Clone Mode**, allowing users to deploy their own clones via @BotFather. Each clone operates independently with its own database scope.

## 🚀 Features

- **Storageless Architecture:** Media files are served natively from Telegram channels using `copyMessage`.
- **Multi-Tenant (Clone Mode):** Users can send `/clone <BOT_TOKEN>` to create their own autonomous instance of the bot.
- **Advanced Admin Dashboard:** A powerful inline menu (`/settings`) to manage Channels, Timers, Toggles, and Monetization.
- **Monetization & Premium System:**
  - Sell Premium plans with direct payment instructions.
  - Shortener API integration (e.g. Earn4link) for users to earn Premium time by watching ads.
  - Referral system to incentivize growth.
- **User Management & Moderation:** `/ban`, `/unban`, `/addadmin`, `/rmadmin` controls.
- **Force Subscribe & Auto-Delete:** Force users to join your main channel and automatically delete served files to prevent scraping.
- **Early Access Mode:** A dedicated queue where VIPs/Premium users can access media before it hits public storage channels.
- **Logging Channel:** Centralized tracking of all admin actions, new users, referrals, and premium upgrades.

## 🛠 Admin Commands

* `/settings` — Open the Admin Control Panel
* `/ban <user_id>` — Ban a user from the bot
* `/unban <user_id>` — Unban a user
* `/addadmin <user_id>` — Grant another user full admin access (Owner only)
* `/rmadmin <user_id>` — Revoke admin access (Owner only)

## 👤 User Commands

* `/start` — Start the bot and show the main menu
* `/type` — Filter by a specific media category
* `/next` & `/prev` — Request media files
* `/autosend` — Toggle the Auto-Send feature
* `/premium` — Manage Premium subscription, watch ads, or get a referral link
* `/clone <TOKEN>` — Clone the bot instance
* `/help` — Show help message

## ⚙️ Deployment

1. Rename `.env.example` to `.env` and fill the variables:
   - `BOT_TOKEN`: From @BotFather
   - `MONGODB_URI`: Your MongoDB connection URL
   - `DATABASE_NAME`: Desired database name
   - `OWNER_ID`: Your Telegram User ID (used for root permissions)
   - `APP_DOMAIN`: The domain where this bot is hosted (required for cloning webhooks)

### For Vercel (Webhooks)
Deploy directly to Vercel. After deployment, register the webhook:
`https://<your-vercel-app-url>/api/set_webhook?url=https://<your-vercel-app-url>`

### Local Setup (Polling)
```bash
pip install -r requirements.txt
python run.py
```
