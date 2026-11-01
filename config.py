"""
Configuration for Flipkart PlayStation Store Gift Card Stock Monitor.
Monitors PSN vouchers (₹1000, ₹2000, ₹3000, ₹4000, ₹5000) with ultra-fast restock detection.
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
# 3. Monitored Flipkart PlayStation Gift Cards (1k, 2k, 3k, 4k, 5k)
# ==========================================
TARGET_SITES = [
    {
        "id": "flipkart_psn_1000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹1,000 Gift Card (Digital Voucher)",
        "url": "https://www.flipkart.com/playstation-rs-1000-inr-gift-card/p/itm22718b5b7e19d",
        "denomination": "₹1,000",
        "is_search": False,
        "enabled": True,
    },
    {
        "id": "flipkart_psn_2000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹2,000 Gift Card (Digital Voucher)",
        "url": "https://www.flipkart.com/ps-wallet-top-up-2000-new-for-ps4-ps5/p/itm5359a5de62acb",
        "denomination": "₹2,000",
        "is_search": False,
        "enabled": True,
    },
    {
        "id": "flipkart_psn_3000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹3,000 Gift Card (Digital Voucher)",
        "url": "https://www.flipkart.com/sony-interactive-entertainment-europe-rs-3000-playstation-store-gift-card-digital-voucher-delivery-email/p/itma3cec289dd512?pid=DGVHGEX6BGYDMJGZ",
        "denomination": "₹3,000",
        "is_search": False,
        "enabled": True,
    },
    {
        "id": "flipkart_psn_4000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹4,000 Gift Card (Digital Voucher)",
        "url": "https://www.flipkart.com/search?q=sony+interactive+entertainment+playstation+store+gift+card+4000",
        "denomination": "₹4,000",
        "is_search": True,
        "target_denomination_filter": 4000,
        "enabled": True,
    },
    {
        "id": "flipkart_psn_5000",
        "platform": "Flipkart",
        "item_name": "PlayStation Store ₹5,000 Gift Card (Digital Voucher)",
        "url": "https://www.flipkart.com/search?q=sony+interactive+entertainment+playstation+store+gift+card+5000",
        "denomination": "₹5,000",
        "is_search": True,
        "target_denomination_filter": 5000,
        "enabled": True,
    },
    {
        "id": "flipkart_psn_catchall",
        "platform": "Flipkart",
        "item_name": "PlayStation Store All Vouchers (Live Feed)",
        "url": "https://www.flipkart.com/search?q=playstation+store+gift+card+digital+voucher",
        "denomination": "All Denominations",
        "is_search": True,
        "target_denomination_filter": None,
        "enabled": True,
    },
]

