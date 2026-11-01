"""
Configuration for Flipkart PlayStation Store Gift Card Stock Monitor.
Monitors exact PSN vouchers (₹1000, ₹2000, ₹3000, ₹4000, ₹5000) with zero false alarms.
"""

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==========================================
# 1. Telegram Credentials
# ==========================================
# Bot Token for @Flipkart_Stock_Monitor_Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9094805444:AAElcttCMQYvLcny-tttmveiK3CTyydyqfY").strip()

# Both required recipient Chat IDs (Aakash: 5701727023, Ajay: 1988639571)
DEFAULT_RECIPIENT_IDS = ["5701727023", "1988639571"]

# Read from env if provided and merge so both recipients ALWAYS receive alerts
_env_cids = [cid.strip() for cid in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if cid.strip()]
TELEGRAM_CHAT_IDS = list(dict.fromkeys(_env_cids + DEFAULT_RECIPIENT_IDS))
TELEGRAM_CHAT_ID = ",".join(TELEGRAM_CHAT_IDS)

# ==========================================
# 2. Monitoring & Bot Behavior Settings
# ==========================================
# Check interval in seconds (90s = 1.5 minutes to prevent Flipkart rate-limiting/blocking)
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "90"))

# Delay between checking each individual item (seconds)
SITE_CHECK_DELAY_SECONDS = int(os.getenv("SITE_CHECK_DELAY_SECONDS", "3"))

# If True, sends an alert on startup for any items currently In Stock
NOTIFY_ON_INITIAL_RUN = os.getenv("NOTIFY_ON_INITIAL_RUN", "False").lower() in ("true", "1", "yes")

# Send startup confirmation message to Telegram when bot launches
SEND_STARTUP_MESSAGE = os.getenv("SEND_STARTUP_MESSAGE", "True").lower() in ("true", "1", "yes")

# Send full summary report after the very first check cycle
SEND_INITIAL_SUMMARY = os.getenv("SEND_INITIAL_SUMMARY", "True").lower() in ("true", "1", "yes")

# Send regular periodic summary update report (every 40 cycles ~ 1 hour)
PERIODIC_SUMMARY_CYCLES = int(os.getenv("PERIODIC_SUMMARY_CYCLES", "40"))

# Periodic heartbeat ping to Telegram (every 160 cycles ~ 4 hours). 0 to disable
HEARTBEAT_CYCLE_INTERVAL = int(os.getenv("HEARTBEAT_CYCLE_INTERVAL", "160"))

# Browser page navigation timeout in milliseconds
PAGE_TIMEOUT_MS = int(os.getenv("PAGE_TIMEOUT_MS", "35000"))

# State persistence file
STATE_FILE_PATH = os.getenv("STATE_FILE_PATH", "stock_state.json")

# Built-in Keep-Alive Web Server port (for EC2 / Railway / Replit)
KEEP_ALIVE_PORT = int(os.getenv("PORT", "8080"))

# Block heavy media resources in Playwright (images, fonts, media) to keep RAM ~120MB and checks at 2-3s
BLOCK_MEDIA_RESOURCES = True

# ==========================================
# 3. Direct Monitored Flipkart PlayStation Gift Cards (1k, 2k, 3k, 4k, 5k)
# Direct product URLs only - avoids search feed false positives (games, accessories)
# ==========================================
TARGET_SITES = [
    {
        "id": "flipkart_psn_1000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹1,000 Gift Card",
        "url": "https://www.flipkart.com/playstation-rs-1000-inr-gift-card/p/itm3d59225ae5e13",
        "denomination": "₹1,000",
        "enabled": True,
    },
    {
        "id": "flipkart_psn_2000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹2,000 Gift Card",
        "url": "https://www.flipkart.com/playstation-rs-2000-inr-gift-card/p/itmd41e56cc4ca04",
        "denomination": "₹2,000",
        "enabled": True,
    },
    {
        "id": "flipkart_psn_3000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹3,000 Gift Card",
        "url": "https://www.flipkart.com/sony-interactive-entertainment-europe-rs-3000-playstation-store-gift-card-digital-voucher-delivery-email/p/itma3cec289dd512?pid=DGVHGEX6BGYDMJGZ",
        "denomination": "₹3,000",
        "enabled": True,
    },
    {
        "id": "flipkart_psn_4000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹4,000 Gift Card",
        "url": "https://www.flipkart.com/playstation-rs-4000-store-gift-card/p/itm0ceacc74a0363",
        "denomination": "₹4,000",
        "enabled": True,
    },
    {
        "id": "flipkart_psn_5000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹5,000 Gift Card",
        "url": "https://www.flipkart.com/sony-interactive-entertainment-europe-rs-5000-playstation-store-gift-card-digital-voucher-delivery-email/p/itmcf54504b6dee2",
        "denomination": "₹5,000",
        "enabled": True,
    },
]
