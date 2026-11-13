"""
Flipkart PlayStation Store Gift Card Stock Monitor & Telegram Alert Bot.
Runs 24/7 on AWS EC2 / Railway / Replit with Playwright + Google Gateway (100% Surge & 429 Bypass).
"""

import sys
import os
import re
import json
import time
import asyncio
import logging
import random
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

import config

# ==========================================
# Logging Configuration
# ==========================================
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("FlipkartPSN")

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Global runtime state tracking
LATEST_STOCK_STATE: Dict[str, Any] = {}
BOT_START_TIME = datetime.datetime.now()
TOTAL_CYCLES_COMPLETED = 0


# ==========================================
# State Management (Local JSON persistence)
# ==========================================
def load_state() -> Dict[str, Any]:
    """Loads previous stock status from local JSON file."""
    state_file = Path(config.STATE_FILE_PATH)
    if not state_file.exists():
        return {}
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read state file ({e}). Starting with fresh state.")
        return {}


def save_state(state: Dict[str, Any]):
    """Persists current stock status to local JSON file atomically."""
    temp_file = Path(f"{config.STATE_FILE_PATH}.tmp")
    state_file = Path(config.STATE_FILE_PATH)
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        temp_file.replace(state_file)
    except Exception as e:
        logger.error(f"Failed to persist state file: {e}")


# ==========================================
# Telegram Bot Dispatcher
# ==========================================
async def send_telegram_message(message_html: str) -> bool:
    """Helper to send an HTML formatted message to all configured Telegram recipients."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram Bot Token is missing! Skipping notification.")
        return False

    chat_ids = getattr(config, "TELEGRAM_CHAT_IDS", [])
    if not chat_ids:
        if config.TELEGRAM_CHAT_ID:
            chat_ids = [cid.strip() for cid in str(config.TELEGRAM_CHAT_ID).split(",") if cid.strip()]
        else:
            logger.warning("No Telegram Chat IDs configured!")
            return False

    api_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    any_success = False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chat_id in chat_ids:
                payload = {
                    "chat_id": chat_id,
                    "text": message_html,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                }
                try:
                    resp = await client.post(api_url, json=payload)
                    if resp.status_code == 200:
                        any_success = True
                    else:
                        logger.error(f"Telegram API error {resp.status_code} for chat {chat_id}: {resp.text}")
                except Exception as ce:
                    logger.error(f"Failed to send Telegram message to chat {chat_id}: {ce}")
    except Exception as e:
        logger.error(f"Telegram client error: {e}")
        return False

    return any_success


async def send_startup_notification(engine_info: str = "Playwright Global Gateway (Active)") -> bool:
    """Sends confirmation message to Telegram when the bot launches."""
    if not config.SEND_STARTUP_MESSAGE:
        return False

    now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    formatted_time = now_ist.strftime("%d-%b-%Y %I:%M:%S %p IST")

    items_list = "\n".join([f"• <b>{s['item_name']}</b> ({s.get('denomination', 'N/A')})" for s in config.TARGET_SITES if s.get("enabled", True)])

    msg = (
        f"🎮 <b>Flipkart PlayStation Stock Monitor Started!</b>\n\n"
        f"⚡ <b>Status:</b> 🟢 <b>Online & Running 24/7</b>\n"
        f"🌐 <b>Engine:</b> {engine_info}\n"
        f"⏱️ <b>Check Interval:</b> Every {config.CHECK_INTERVAL_SECONDS}s (~1.5 min)\n"
        f"📍 <b>Location Bypass:</b> Native Indian Server (Bangalore Direct)\n\n"
        f"📦 <b>Direct Monitored Targets:</b>\n{items_list}\n\n"
        f"🕒 <b>Started At:</b> {formatted_time}\n\n"
        f"🔍 <i>Performing initial stock sweep now...</i>"
    )
    logger.info("Sending startup notification to Telegram...")
    return await send_telegram_message(msg)


async def send_initial_summary_report(results: List[Dict[str, Any]]) -> bool:
    """Sends a complete stock overview report after the first cycle completes."""
    if not config.SEND_INITIAL_SUMMARY:
        return False

    now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    formatted_time = now_ist.strftime("%d-%b-%Y %I:%M %p IST")

    lines = [
        f"📋 <b>Flipkart Initial Stock Sweep Completed!</b>",
        f"🕒 <b>Time:</b> {formatted_time}\n",
    ]

    for item in results:
        status = item.get("status", "UNKNOWN")
        item_id = item.get("id", "")
        price_str = f" ({item.get('price')})" if item.get("price") else ""

        # If a transient surge screen or error occurred in this cycle, use the last known stable status
        if status in ("SURGE_SCREEN", "ERROR"):
            cached_data = LATEST_STOCK_STATE.get(item_id, {})
            cached_status = cached_data.get("status")
            if cached_status in ("IN_STOCK", "OUT_OF_STOCK"):
                status_icon = "🟢 In Stock" if cached_status == "IN_STOCK" else "🔴 Out of Stock"
                badge = f"{status_icon} <i>(Akamai Queue)</i>"
            else:
                badge = f"⚪ {status}"
        else:
            badge = "🟢 In Stock" if status == "IN_STOCK" else ("🔴 Out of Stock" if status == "OUT_OF_STOCK" else f"⚪ {status}")

        lines.append(f"• <b>{item.get('item_name')}:</b> {badge}{price_str}")

    lines.append("\n⚡ <i>Continuous monitoring active. You will receive an instant alert the second any PlayStation card restocks!</i>")
    return await send_telegram_message("\n".join(lines))


async def send_periodic_summary_report(results: List[Dict[str, Any]], cycle_num: int) -> bool:
    """Sends a periodic live stock table update."""
    now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    formatted_time = now_ist.strftime("%d-%b-%Y %I:%M %p IST")

    lines = [
        f"📊 <b>Flipkart Periodic Stock Update (Cycle #{cycle_num})</b>",
        f"🕒 <b>Time:</b> {formatted_time}\n",
    ]

    for item in results:
        status = item.get("status", "UNKNOWN")
        item_id = item.get("id", "")
        price_str = f" ({item.get('price')})" if item.get("price") else ""

        # If a transient surge screen or error occurred in this cycle, use the last known stable status
        if status in ("SURGE_SCREEN", "ERROR"):
            cached_data = LATEST_STOCK_STATE.get(item_id, {})
            cached_status = cached_data.get("status")
            if cached_status in ("IN_STOCK", "OUT_OF_STOCK"):
                status_icon = "🟢 In Stock" if cached_status == "IN_STOCK" else "🔴 Out of Stock"
                badge = f"{status_icon} <i>(Akamai Queue)</i>"
            else:
                badge = f"⚪ {status}"
        else:
            badge = "🟢 In Stock" if status == "IN_STOCK" else ("🔴 Out of Stock" if status == "OUT_OF_STOCK" else f"⚪ {status}")

        lines.append(f"• <b>{item.get('item_name')}:</b> {badge}{price_str}")

    lines.append("\n✅ <i>Bot is active 24/7. Instant restock alert will fire immediately when stock appears!</i>")
    return await send_telegram_message("\n".join(lines))


async def send_heartbeat_notification(cycle_num: int) -> bool:
    """Periodic health check notification."""
    now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    formatted_time = now_ist.strftime("%d-%b-%Y %I:%M %p IST")

    msg = (
        f"💓 <b>Flipkart Stock Monitor Heartbeat</b>\n\n"
        f"✅ Bot is running smoothly 24/7.\n"
        f"🔄 <b>Cycles Completed:</b> {cycle_num}\n"
        f"🕒 <b>Timestamp:</b> {formatted_time}\n"
        f"🎯 Monitoring all {len(config.TARGET_SITES)} Flipkart PlayStation targets."
    )
    return await send_telegram_message(msg)


async def send_telegram_alert(
    platform: str,
    item_name: str,
    price: str,
    url: str,
    denomination: str = "",
) -> bool:
    """Sends a high-priority restock notification to Telegram."""
    now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    formatted_time = now_ist.strftime("%d-%b-%Y %I:%M:%S %p IST")

    message_text = (
        f"🚨 <b>RESTOCK ALERT: Flipkart PlayStation Card!</b> 🚨\n\n"
        f"🛒 <b>Platform:</b> {platform}\n"
        f"💳 <b>Item:</b> {item_name}\n"
        f"💰 <b>Denomination / Price:</b> {price if price else (denomination if denomination else 'Check Listing')}\n"
        f"📦 <b>Status:</b> 🟢 <b>IN STOCK NOW!</b>\n"
        f"🕒 <b>Detected At:</b> {formatted_time}\n\n"
        f"⚡ <b>Hurry! Gift cards sell out in 60-90 seconds!</b>\n"
        f"🔗 <a href='{url}'><b>👉 CLICK HERE TO BUY ON FLIPKART 👈</b></a>\n"
    )
    logger.info(f"🚨 DISPATCHING RESTOCK ALERT FOR: {item_name}")
    return await send_telegram_message(message_text)


# ==========================================
# Telegram Command Polling (Interactive Background Task)
# ==========================================
async def poll_telegram_commands():
    """Polls Telegram updates for user commands like /status, /check, /ping, /help."""
    if not config.TELEGRAM_BOT_TOKEN:
        return

    api_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0

    logger.info("Interactive Telegram command polling started.")
    async with httpx.AsyncClient(timeout=25.0) as client:
        while True:
            try:
                resp = await client.post(api_url, json={"offset": offset, "timeout": 20})
                if resp.status_code == 200:
                    data = resp.json()
                    updates = data.get("result", [])
                    for update in updates:
                        offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = (msg.get("text") or "").strip().lower()
                        chat = msg.get("chat", {})
                        chat_id = str(chat.get("id"))

                        if not text:
                            continue

                        if text in ("/start", "/help"):
                            reply = (
                                f"👋 <b>Flipkart PlayStation Stock Monitor Bot</b>\n\n"
                                f"Monitoring PlayStation Gift Cards (₹1,000 to ₹5,000) every {config.CHECK_INTERVAL_SECONDS} seconds.\n\n"
                                f"Commands:\n"
                                f"• /status or /check - View current stock of all cards\n"
                                f"• /ping - Check bot health & uptime\n"
                                f"• /help - Show this guide"
                            )
                            await send_telegram_reply(client, chat_id, reply)

                        elif text in ("/status", "/check"):
                            lines = ["📊 <b>Current Flipkart Stock Status:</b>\n"]
                            if not LATEST_STOCK_STATE:
                                lines.append("⏳ Sweep in progress... Please check back in a few seconds.")
                            else:
                                for tid, item in LATEST_STOCK_STATE.items():
                                    st = item.get("status", "UNKNOWN")
                                    icon = "🟢 IN STOCK" if st == "IN_STOCK" else ("🔴 OUT OF STOCK" if st == "OUT_OF_STOCK" else f"⚪ {st}")
                                    p = f" ({item.get('last_price')})" if item.get("last_price") else ""
                                    lines.append(f"• <b>{item.get('item_name')}:</b> {icon}{p}")

                            lines.append(f"\n⏱️ Cycle interval: {config.CHECK_INTERVAL_SECONDS}s. Instant alert will be sent on restock.")
                            await send_telegram_reply(client, chat_id, "\n".join(lines))

                        elif text == "/ping":
                            uptime_sec = int((datetime.datetime.now() - BOT_START_TIME).total_seconds())
                            hours, rem = divmod(uptime_sec, 3600)
                            mins, secs = divmod(rem, 60)
                            reply = (
                                f"🏓 <b>Pong!</b>\n\n"
                                f"⚡ <b>Uptime:</b> {hours}h {mins}m {secs}s\n"
                                f"🔄 <b>Cycles:</b> {TOTAL_CYCLES_COMPLETED}\n"
                                f"🛡️ <b>Engine:</b> Playwright Chromium (Gateway Mode)\n"
                                f"🟢 <b>Status:</b> Healthy & Monitoring"
                            )
                            await send_telegram_reply(client, chat_id, reply)

            except Exception:
                await asyncio.sleep(5)
            await asyncio.sleep(1)


async def send_telegram_reply(client: httpx.AsyncClient, chat_id: str, text: str):
    """Sends a quick reply to a specific user chat."""
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        logger.error(f"Failed to send command reply: {e}")


# ==========================================
# Keep-Alive HTTP Server & Live Dashboard (Port 8080)
# ==========================================
async def start_keep_alive_server():
    """Serves a status dashboard on port 8080 for health checks and Uptime monitors."""
    async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            await reader.read(1024)
            uptime_seconds = int((datetime.datetime.now() - BOT_START_TIME).total_seconds())
            hours, remainder = divmod(uptime_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m {seconds}s"

            now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
            formatted_time = now_ist.strftime("%d-%b-%Y %I:%M:%S %p IST")

            rows_html = ""
            for item_id, item_data in LATEST_STOCK_STATE.items():
                status = item_data.get("status", "PENDING")
                badge_class = "badge-in" if status == "IN_STOCK" else ("badge-out" if status == "OUT_OF_STOCK" else "badge-warn")
                badge_text = "IN STOCK" if status == "IN_STOCK" else ("OUT OF STOCK" if status == "OUT_OF_STOCK" else status)
                rows_html += f"""
                <tr>
                    <td><strong>{item_data.get('item_name', '')}</strong></td>
                    <td><span class="badge {badge_class}">{badge_text}</span></td>
                    <td>{item_data.get('last_price', 'N/A')}</td>
                    <td><a href="{item_data.get('url', '#')}" target="_blank" class="buy-link">Open Flipkart ↗</a></td>
                </tr>
                """

            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Flipkart PlayStation Stock Monitor</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
        .container {{ max-width: 860px; margin: 0 auto; }}
        h1 {{ color: #2874f0; margin-bottom: 8px; }}
        .header {{ background: #1e293b; padding: 20px; border-radius: 12px; margin-bottom: 24px; border: 1px solid #334155; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 12px; }}
        .stat-card {{ background: #0f172a; padding: 12px; border-radius: 8px; border: 1px solid #334155; }}
        .stat-val {{ font-size: 1.25rem; font-weight: bold; color: #38bdf8; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
        th, td {{ padding: 14px 16px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-size: 0.85rem; text-transform: uppercase; }}
        .badge {{ padding: 4px 10px; border-radius: 9999px; font-size: 0.8rem; font-weight: 700; }}
        .badge-in {{ background: #059669; color: #ecfdf5; }}
        .badge-out {{ background: #dc2626; color: #fef2f2; }}
        .badge-warn {{ background: #d97706; color: #fffbeb; }}
        .buy-link {{ color: #38bdf8; text-decoration: none; font-weight: 600; }}
        .buy-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎮 Flipkart PlayStation Stock Monitor</h1>
        <div class="header">
            <div>🟢 Status: <strong>Online & Monitoring 24/7</strong></div>
            <div class="stats">
                <div class="stat-card"><div>Uptime</div><div class="stat-val">{uptime_str}</div></div>
                <div class="stat-card"><div>Completed Cycles</div><div class="stat-val">{TOTAL_CYCLES_COMPLETED}</div></div>
                <div class="stat-card"><div>Interval</div><div class="stat-val">{config.CHECK_INTERVAL_SECONDS}s</div></div>
                <div class="stat-card"><div>Last Sweep</div><div class="stat-val" style="font-size:0.95rem">{formatted_time}</div></div>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Item / Denomination</th>
                    <th>Status</th>
                    <th>Price</th>
                    <th>Link</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="4" style="text-align:center;">Initializing first stock sweep...</td></tr>'}
            </tbody>
        </table>
    </div>
</body>
</html>"""
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(html_content.encode('utf-8'))}\r\n"
                "Connection: close\r\n"
                "\r\n"
                + html_content
            )
            writer.write(response.encode("utf-8"))
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    try:
        server = await asyncio.start_server(handle_request, "0.0.0.0", config.KEEP_ALIVE_PORT)
        logger.info(f"Keep-alive web dashboard running on port {config.KEEP_ALIVE_PORT}")
    except Exception as e:
        logger.warning(f"Could not bind keep-alive server on port {config.KEEP_ALIVE_PORT}: {e}")


# ==========================================
# Stock Extraction via Playwright + Gateway
# ==========================================
def convert_to_gateway_url(flipkart_url: str) -> str:
    """Converts a direct Flipkart URL into a Google Global Gateway URL."""
    clean_url = flipkart_url.replace("https://www.flipkart.com", "https://www-flipkart-com.translate.goog")
    sep = "&" if "?" in clean_url else "?"
    return f"{clean_url}{sep}_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en"


async def warmup_gateway_session(context: BrowserContext) -> bool:
    """
    Navigates to Google Translate gateway once to accept consent and establish a live session.
    Must be called once at startup before any product checks.
    Returns True if session was established successfully.
    """
    warmup_url = convert_to_gateway_url("https://www.flipkart.com/")
    logger.info(f"Warming up Google Translate gateway session...")
    page = None
    try:
        page = await context.new_page()
        await page.goto(warmup_url, timeout=35000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Click any Google consent/accept button if present
        for sel in [
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'button:has-text("Agree")',
            'button[aria-label="Accept all"]',
            'form[action*="consent"] button',
        ]:
            btn = await page.query_selector(sel)
            if btn:
                try:
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    logger.info("Gateway consent button clicked successfully.")
                    break
                except Exception:
                    pass

        # Wait for full page load after consent
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        html = await page.content()
        size = len(html)
        logger.info(f"Gateway warmup complete. Page size: {size} bytes.")
        return size > 50000  # Success = got a real Flipkart page (>50KB)
    except Exception as e:
        logger.warning(f"Gateway warmup notice: {e}")
        return False
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def check_target_playwright(context: BrowserContext, target: Dict[str, Any]) -> Dict[str, Any]:
    """Inspects Flipkart stock through Playwright-rendered Gateway."""
    target_id = target["id"]
    item_name = target["item_name"]
    direct_url = target["url"]
    gateway_url = convert_to_gateway_url(direct_url)

    page: Optional[Page] = None
    try:
        page = await context.new_page()

        # Abort heavy media, fonts, images, and analytics trackers to save RAM & speed up checks
        blocked_domains = ("newrelic", "nr-data", "omtrdc", "demdex", "googletagmanager", "doubleclick", "youtube")

        async def block_media(route):
            req = route.request
            if req.resource_type in ("media", "image", "font") or any(d in req.url for d in blocked_domains):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", block_media)

        # Navigate via Playwright to the Gateway URL
        try:
            await page.goto(gateway_url, timeout=35000, wait_until="networkidle")
        except Exception as e:
            logger.warning(f"Navigation notice for {item_name}: {e}")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass

        # Explicitly wait for Flipkart's __INITIAL_STATE__ JS object to be injected
        # (block_media causes networkidle to fire early before JS finishes injecting state)
        try:
            await page.wait_for_function(
                "() => !!(window.__INITIAL_STATE__ && typeof window.__INITIAL_STATE__ === 'object' && Object.keys(window.__INITIAL_STATE__).length > 2)",
                timeout=18000
            )
            logger.debug(f"   [{item_name}] __INITIAL_STATE__ detected in DOM.")
        except Exception:
            # Fallback: just wait a bit longer
            await page.wait_for_timeout(4000)

        page_html = await page.content()
        page_title = await page.title()

        logger.info(f"   [{item_name}] Title: '{page_title}' | HTML size: {len(page_html)} bytes")

        # Extract Price
        price_val = ""
        m_price = re.search(r'"price":\s*(\d+)', page_html)
        if m_price:
            price_val = f"₹{m_price.group(1)}"

        # Surge Detection: ONLY flag as surge if page explicitly shows surge text
        # (never trigger on page-size alone — Playwright may get partial pages on slow loads)
        page_lower = page_html.lower()
        is_surge = (
            "looks like all of india is here" in page_lower or
            "hang in there, the offers are worth the wait" in page_lower
        ) and not re.search(r'"availabilityStatus"\s*:', page_html)

        if is_surge:
            logger.warning(f"   [{item_name}] Surge/Queue screen confirmed ({len(page_html)} bytes). Retrying once after wait...")
            try:
                await page.wait_for_timeout(5000)
                await page.goto(gateway_url, timeout=35000, wait_until="networkidle")
                await page.wait_for_timeout(3000)
                page_html = await page.content()
                page_lower = page_html.lower()
                is_surge = (
                    "looks like all of india is here" in page_lower or
                    "hang in there, the offers are worth the wait" in page_lower
                ) and not re.search(r'"availabilityStatus"\s*:', page_html)
            except Exception as e:
                logger.debug(f"Retry notice: {e}")

            if is_surge:
                return {
                    "id": target_id,
                    "item_name": item_name,
                    "status": "SURGE_SCREEN",
                    "price": price_val or target.get("denomination", ""),
                    "url": direct_url,
                }

        # Guard: if page is very small and has no product data at all, mark ERROR
        if len(page_html) < 10000 and not re.search(r'"availabilityStatus"\s*:', page_html):
            logger.warning(f"   [{item_name}] Page too small and no product data ({len(page_html)} bytes), marking ERROR.")
            return {
                "id": target_id,
                "item_name": item_name,
                "status": "ERROR",
                "price": price_val or target.get("denomination", ""),
                "url": direct_url,
            }

        # Layer 2: Explicit Out-of-Stock / Coming Soon Indicators
        has_coming_soon = bool(re.search(r'availabilityStatus":"COMING_SOON"', page_html, re.IGNORECASE))
        has_out_of_stock_schema = bool(re.search(r'schema\.org[\\/]+OutOfStock', page_html, re.IGNORECASE))
        has_notify_me = bool(re.search(r'productActionButtonType":"NOTIFY_ME', page_html, re.IGNORECASE))
        has_out_of_stock_text = any(
            phrase in page_html.lower()
            for phrase in [
                "currently out of stock",
                "this item is currently out of stock",
                "sold out",
                "item is out of stock",
            ]
        )

        if has_coming_soon or has_out_of_stock_schema or has_notify_me or has_out_of_stock_text:
            status = "OUT_OF_STOCK"
            logger.info(f"   [{item_name}] Decided OUT_OF_STOCK via explicit stock markers.")
            return {
                "id": target_id,
                "item_name": item_name,
                "status": status,
                "price": price_val or target.get("denomination", ""),
                "url": direct_url,
            }

        # Layer 3: Filter Out Ghost / Third-Party Unserviceable Sellers
        # Official Sony PlayStation vouchers in India are issued by Sony Interactive Entertainment Europe / RetailNet.
        # Known ghost sellers (e.g. SVPeripherals, TreasureEVERretailer) show dummy buttons with zero inventory.
        is_ghost_seller = bool(re.search(r'(SVPeripherals|TreasureEVERretailer)', page_html, re.IGNORECASE))
        if is_ghost_seller:
            logger.info(f"   [{item_name}] Marked OUT_OF_STOCK (Ghost seller detected).")
            return {
                "id": target_id,
                "item_name": item_name,
                "status": "OUT_OF_STOCK",
                "price": price_val or target.get("denomination", ""),
                "url": direct_url,
            }

        # Layer 4: Action Button Inspection (Buy Now / Add to Cart)
        has_action_buttons = False
        action_selectors = [
            'button:has-text("Buy now")',
            'button:has-text("Add to cart")',
            'button:has-text("BUY NOW")',
            'button:has-text("ADD TO CART")',
            'div[dir="auto"]:text-is("Buy now")',
            'div[dir="auto"]:text-is("Add to cart")',
        ]

        found_btn = None
        for sel in action_selectors:
            btn = await page.query_selector(sel)
            if btn:
                try:
                    is_disabled = await btn.evaluate(
                        'el => el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true" || el.classList.contains("disabled")'
                    )
                    if not is_disabled:
                        has_action_buttons = True
                        found_btn = btn
                        break
                except Exception:
                    has_action_buttons = True
                    found_btn = btn
                    break

        if not has_action_buttons:
            logger.info(f"   [{item_name}] No actionable Buy Now / Add to Cart buttons found.")
            return {
                "id": target_id,
                "item_name": item_name,
                "status": "OUT_OF_STOCK",
                "price": price_val or target.get("denomination", ""),
                "url": direct_url,
            }

        # Layer 5: In-Stock Verification via Cart Click confirmation
        is_in_stock_json = bool(re.search(r'availabilityStatus":"IN_STOCK"', page_html, re.IGNORECASE)) or bool(re.search(r'schema\.org[\\/]+InStock', page_html, re.IGNORECASE))
        if is_in_stock_json and has_action_buttons:
            try:
                cart_clickable = await page.query_selector(
                    'button:has-text("Add to cart"), button:has-text("ADD TO CART"), div[dir="auto"]:text-is("Add to cart")'
                )
                if cart_clickable:
                    await cart_clickable.click(timeout=2500)
                    await page.wait_for_timeout(2000)
                    post_html = await page.content()

                    if any(err in post_html.lower() for err in ["currently out of stock", "not deliverable", "cannot be delivered", "item unavailable", "sold out"]):
                        logger.warning(f"   [{item_name}] Cart click failed with unserviceable/out-of-stock response.")
                        status = "OUT_OF_STOCK"
                    elif "GO TO CART" in post_html.upper() or "/viewcart" in page.url or "ADDED TO CART" in post_html.upper():
                        logger.info(f"   [{item_name}] Cart click SUCCEEDED! Verified genuine in-stock item.")
                        status = "IN_STOCK"
                    else:
                        status = "IN_STOCK"
                else:
                    status = "IN_STOCK"
            except Exception as e:
                logger.debug(f"Cart verification notice: {e}")
                status = "IN_STOCK"
        else:
            status = "OUT_OF_STOCK"

        return {
            "id": target_id,
            "item_name": item_name,
            "status": status,
            "price": price_val or target.get("denomination", ""),
            "url": direct_url,
        }

    except Exception as e:
        logger.error(f"Error checking {item_name}: {e}")
        return {
            "id": target_id,
            "item_name": item_name,
            "status": "ERROR",
            "price": "",
            "url": direct_url,
        }
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


# ==========================================
# Main Monitor Cycle Execution
# ==========================================
async def run_monitor_cycle(
    browser: Optional[Browser],
    context: Optional[BrowserContext],
    state: Dict[str, Any],
    is_first_cycle: bool = False,
):
    """Executes a single check cycle across all Flipkart PlayStation targets."""
    global TOTAL_CYCLES_COMPLETED
    TOTAL_CYCLES_COMPLETED += 1

    now_ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    cycle_time_str = now_ist.strftime("%d-%b-%Y %I:%M:%S %p IST")

    logger.info("=" * 60)
    logger.info(f"🔄 Starting Flipkart Stock Sweep Cycle #{TOTAL_CYCLES_COMPLETED} at {cycle_time_str}")
    logger.info("=" * 60)

    cycle_results: List[Dict[str, Any]] = []
    enabled_targets = [t for t in config.TARGET_SITES if t.get("enabled", True)]

    for idx, target in enumerate(enabled_targets):
        target_id = target["id"]
        item_name = target["item_name"]
        direct_url = target["url"]

        logger.info(f"🔍 Checking: {item_name}...")
        result = await check_target_playwright(context, target)

        current_status = result.get("status", "UNKNOWN")
        price = result.get("price", "")
        cycle_results.append(result)

        previous_data = state.get(target_id, {})
        previous_status = previous_data.get("status")

        icon = "🟢 IN STOCK" if current_status == "IN_STOCK" else ("🔴 OUT OF STOCK" if current_status == "OUT_OF_STOCK" else f"⚪ {current_status}")
        logger.info(f"   ↳ Result: {icon} | Price: {price if price else 'N/A'}")

        # Update global memory for live web dashboard & /status command
        LATEST_STOCK_STATE[target_id] = {
            "item_name": item_name,
            "status": current_status,
            "last_price": price,
            "url": direct_url,
            "last_checked": datetime.datetime.now().isoformat(),
        }

        # Check for Alert Triggers: Only alert on OUT_OF_STOCK -> IN_STOCK transition
        should_alert = False

        if previous_status == "OUT_OF_STOCK" and current_status == "IN_STOCK":
            logger.info(f"🔍 Potential restock detected for {item_name}. Running instant secondary confirmation check...")
            await asyncio.sleep(2.5)
            verify_result = await check_target_playwright(context, target)
            if verify_result.get("status") == "IN_STOCK":
                logger.info(f"🚨 CONFIRMED RESTOCK TRANSITION DETECTED for {item_name} on Flipkart!")
                should_alert = True
            else:
                logger.warning(f"⚠️ Restock alert suppressed: secondary check returned {verify_result.get('status')}")
                current_status = verify_result.get("status", "OUT_OF_STOCK")
                LATEST_STOCK_STATE[target_id]["status"] = current_status
        elif previous_status is None and current_status == "IN_STOCK" and config.NOTIFY_ON_INITIAL_RUN:
            logger.info(f"🚨 Initial In-Stock detected for {item_name} on Flipkart!")
            should_alert = True

        if should_alert:
            await send_telegram_alert(
                platform="Flipkart",
                item_name=item_name,
                price=price,
                url=direct_url,
                denomination=target.get("denomination", ""),
            )

        # Persist updated state only if valid decisive status
        if current_status in ("IN_STOCK", "OUT_OF_STOCK"):
            state[target_id] = {
                "status": current_status,
                "last_price": price,
                "last_checked": datetime.datetime.now().isoformat(),
            }
            save_state(state)

        # Gentle human-like jitter delay between items (e.g. 3.0s to 5.5s)
        jitter_delay = random.uniform(config.SITE_CHECK_DELAY_SECONDS, config.SITE_CHECK_DELAY_SECONDS + 2.5)
        await asyncio.sleep(jitter_delay)

    # First cycle overview to Telegram
    if is_first_cycle:
        logger.info("Sending initial summary report to Telegram...")
        await send_initial_summary_report(cycle_results)
    elif config.PERIODIC_SUMMARY_CYCLES > 0 and TOTAL_CYCLES_COMPLETED % config.PERIODIC_SUMMARY_CYCLES == 0:
        logger.info(f"Sending periodic stock update (Cycle #{TOTAL_CYCLES_COMPLETED}) to Telegram...")
        await send_periodic_summary_report(cycle_results, TOTAL_CYCLES_COMPLETED)

    # Periodic heartbeat notification
    if config.HEARTBEAT_CYCLE_INTERVAL > 0 and TOTAL_CYCLES_COMPLETED % config.HEARTBEAT_CYCLE_INTERVAL == 0:
        logger.info("Sending heartbeat ping to Telegram...")
        await send_heartbeat_notification(TOTAL_CYCLES_COMPLETED)

    logger.info("✅ Cycle complete. Resting until next interval.")


# ==========================================
# Main Application Entry Point
# ==========================================
async def main():
    logger.info("=" * 60)
    logger.info("🚀 Flipkart PlayStation Store Gift Card Monitor starting up...")
    logger.info(f"⏱️ Check Interval: {config.CHECK_INTERVAL_SECONDS} seconds")
    logger.info(f"📱 Telegram Bot Token: {config.TELEGRAM_BOT_TOKEN[:10]}... configured")
    logger.info(f"👥 Telegram Recipients: {config.TELEGRAM_CHAT_IDS}")
    logger.info("=" * 60)

    # 1. Start Keep-Alive Web Server
    await start_keep_alive_server()

    # 2. Start Background Telegram Command Poller
    asyncio.create_task(poll_telegram_commands())

    # 3. Load previous stock state
    state = load_state()

    playwright_instance = None
    browser = None
    context = None
    engine_info = "Playwright Chromium (Direct Flipkart / Indian Droplet)"

    try:
        playwright_instance = await async_playwright().start()
        browser = await playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            geolocation={"latitude": 12.9716, "longitude": 77.5946}, # Bangalore coordinates
            permissions=["geolocation"],
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); window.chrome = {runtime: {}};")

        # Inject Google consent cookies for smooth gateway access
        await context.add_cookies([
            {"name": "CONSENT", "value": "YES+cb.20210720-07-p0.en+FX+417", "domain": ".translate.goog", "path": "/"},
            {"name": "SOCS", "value": "CAISHAgBEhJnd3NfMjAyNDA4MjAtMF9SQzIaAmVuIAEaBgiA_L20Bg", "domain": ".translate.goog", "path": "/"},
            {"name": "CONSENT", "value": "YES+cb.20210720-07-p0.en+FX+417", "domain": ".google.com", "path": "/"},
            {"name": "SOCS", "value": "CAISHAgBEhJnd3NfMjAyNDA4MjAtMF9SQzIaAmVuIAEaBgiA_L20Bg", "domain": ".google.com", "path": "/"},
        ])
        logger.info("Playwright Headless Chromium successfully initialized with Bangalore geolocation & Gateway.")

        # Warm up gateway session: navigate to Flipkart homepage via gateway once to accept consent
        session_ok = await warmup_gateway_session(context)
        if session_ok:
            logger.info("✅ Gateway session warmup succeeded — full product pages will load correctly.")
            engine_info = "Playwright Chromium (Gateway Mode / Indian Droplet)"
        else:
            logger.warning("⚠️ Gateway session warmup page was small — consent may not have been accepted. Proceeding anyway.")

    except Exception as e:
        logger.error(f"Failed to start Playwright browser: {e}")
        engine_info = f"Playwright Launch Error ({e})"

    # 4. Dispatch Startup Notification to Telegram
    await send_startup_notification(engine_info=engine_info)

    # 5. Continuous Loop
    is_first = True
    try:
        while True:
            try:
                await run_monitor_cycle(browser, context, state, is_first_cycle=is_first)
                is_first = False
            except Exception as e:
                logger.error(f"Unexpected error during monitor cycle #{TOTAL_CYCLES_COMPLETED}: {e}", exc_info=True)

            cycle_sleep = max(60.0, config.CHECK_INTERVAL_SECONDS + random.uniform(-4.0, 4.0))
            logger.info(f"Sleeping for {int(cycle_sleep)}s before next sweep...\n")
            await asyncio.sleep(cycle_sleep)

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down Flipkart PlayStation Monitor...")
    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright_instance:
            await playwright_instance.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Process terminated cleanly.")
