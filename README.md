# 🎮 Flipkart PlayStation Store Gift Card Stock Monitor Bot

24/7 Autonomous stock monitor for **Sony PlayStation Store Gift Cards** (₹1,000, ₹2,000, ₹3,000, ₹4,000, ₹5,000 digital vouchers) on Flipkart with instant Telegram restock alerts.

Built on resource-efficient **Playwright Chromium**, zero CSS selector dependency (using Schema.org JSON-LD & `__INITIAL_STATE__`), and heavy media blocking for ~120MB RAM usage and 2-3 second page checks.

---

## ⚡ Features
- **Zero CSS Selector Breakage:** Parses Flipkart's internal `application/ld+json` Schema & `__INITIAL_STATE__`. Even if Flipkart alters its frontend classes (`_75nlfW`, `Nx9bqj`), the bot never breaks.
- **Resource Optimization:** Blocks images, media, and fonts via Playwright request routing. Cuts RAM consumption to ~120MB and speeds up page checks to ~2 seconds.
- **90-Second Check Interval:** Safe interval preventing Flipkart/Akamai rate limiting while catching brief restock windows.
- **Instant Dual Alerts:** Sends instant Telegram alerts to both configured Chat IDs with direct one-click purchase links.
- **Anti-Surge Protection:** Gracefully handles Flipkart's high-traffic surge screen without crashing or triggering false alarms.
- **Interactive Commands:** Send `/status`, `/check`, or `/ping` to `@Flipkart_Stock_Monitor_Bot` at any time to view live stock across all cards.
- **Keep-Alive Dashboard:** Built-in web dashboard on port `8080`.

---

## 🚀 AWS EC2 Deployment Guide

Run these commands in your EC2 terminal (`ubuntu@ip-172-31-33-58`):

```bash
# 1. Navigate to bot directory and pull latest code
cd ~/flipkart-bot
git fetch origin
git reset --hard origin/main

# 2. Run automated setup script
bash setup_aws.sh
```

### Manual Service Controls
```bash
# Restart bot service
sudo systemctl restart flipkart-bot

# View live logs
sudo journalctl -u flipkart-bot -f

# Check service status
sudo systemctl status flipkart-bot
```

---

## ⚙️ Configuration (`config.py`)
| Parameter | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `9094805444:...` | Bot token from @BotFather |
| `DEFAULT_RECIPIENT_IDS` | `["5701727023", "1988639571"]` | Chat IDs receiving alerts |
| `CHECK_INTERVAL_SECONDS` | `90` | Check interval in seconds |
| `BLOCK_MEDIA_RESOURCES` | `True` | Aborts images/fonts for low RAM |

---

## 🤖 Telegram Bot Commands
- `/status` or `/check` — View live stock status of ₹1k, ₹2k, ₹3k, ₹4k, ₹5k cards
- `/ping` — View bot uptime, cycles completed, and health
- `/help` — Overview of bot features
