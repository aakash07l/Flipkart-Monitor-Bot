"""
Flipkart PlayStation Store Gift Card Stock Monitor & Telegram Alert Bot.
Runs 24/7 on AWS EC2 / Railway / Replit with resource-efficient Playwright and instant Telegram notifications.
"""

import sys
import os
import re
import json
import time
import asyncio
import logging
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


async def send_startup_notification(engine_info: str = "Playwright Chromium Headless") -> bool:
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
        f"⏱️ <b>Check Interval:</b> Every {config.CHECK_INTERVAL_SECONDS} seconds (1.5 min)\n"
        f"🛡️ <b>Anti-Surge & Fast Scraping:</b> Active (Stealth + Warmup)\n\n"
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
        badge = "🟢 In Stock" if status == "IN_STOCK" else ("🔴 Out of Stock" if status == "OUT_OF_STOCK" else f"⚪ {status}")
        price_str = f" ({item.get('price')})" if item.get("price") else ""
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
        badge = "🟢 In Stock" if status == "IN_STOCK" else ("🔴 Out of Stock" if status == "OUT_OF_STOCK" else f"⚪ {status}")
        price_str = f" ({item.get('price')})" if item.get("price") else ""
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
        f"⚡ <b>Hurry! Gift cards sell out quickly!</b>\n"
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
                                f"🛡️ <b>Engine:</b> Playwright Chromium (Stealth + Warmup)\n"
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
# Playwright Scraping & Anti-Surge Filtering
# ==========================================
async def block_heavy_resources(route):
    """
    Blocks heavy third-party media and fonts, but ALLOWS Flipkart/Akamai verification scripts and cookies.
    """
    req = route.request
    r_type = req.resource_type
    url = req.url.lower()

    # Never block Flipkart or Akamai authentication/verification resources
    if "akam" in url or "flixcart" in url or "flipkart" in url:
        await route.continue_()
        return

    # Abort heavy external media and web fonts
    if r_type in ["media", "font"]:
        await route.abort()
    else:
        await route.continue_()


def parse_flipkart_jsonld(html: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parses Flipkart's Schema.org JSON-LD structured data.
    Returns (status, price). Zero CSS selector dependency.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.find_all("script", type="application/ld+json")
        for s in scripts:
            content = (s.string or s.text or "").strip()
            if not content:
                continue
            try:
                data = json.loads(content)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    offers = item.get("offers")
                    if isinstance(offers, list) and offers:
                        offers = offers[0]
                    if isinstance(offers, dict):
                        avail = str(offers.get("availability", ""))
                        price = str(offers.get("price", ""))
                        price_formatted = f"₹{price}" if price and not price.startswith("₹") else price

                        if "InStock" in avail:
                            return "IN_STOCK", price_formatted
                        elif "OutOfStock" in avail:
                            return "OUT_OF_STOCK", price_formatted
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"JSON-LD parsing exception: {e}")
    return None, None


def parse_flipkart_initial_state(html: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parses Flipkart's window.__INITIAL_STATE__ script block.
    """
    try:
        if "__INITIAL_STATE__" not in html:
            return None, None

        # Look for schema availability inside initial state
        if '"availability":"https://schema.org/InStock"' in html:
            if '"availabilityStatus":"COMING_SOON"' not in html:
                m_price = re.search(r'"price":\s*(\d+)', html)
                price_str = f"₹{m_price.group(1)}" if m_price else ""
                return "IN_STOCK", price_str

        if '"availability":"https://schema.org/OutOfStock"' in html or '"availabilityStatus":"COMING_SOON"' in html:
            m_price = re.search(r'"price":\s*(\d+)', html)
            price_str = f"₹{m_price.group(1)}" if m_price else ""
            return "OUT_OF_STOCK", price_str
    except Exception as e:
        logger.debug(f"Initial state parsing exception: {e}")
    return None, None


async def check_target_playwright(context: BrowserContext, target: Dict[str, Any]) -> Dict[str, Any]:
    """Inspects Flipkart direct product page using Playwright with anti-surge challenge waiting."""
    target_id = target["id"]
    item_name = target["item_name"]
    url = target["url"]

    page: Optional[Page] = None
    try:
        page = await context.new_page()

        if config.BLOCK_MEDIA_RESOURCES:
            await page.route("**/*", block_heavy_resources)

        # Navigate to direct product page
        try:
            await page.goto(url, timeout=config.PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(3500)
        except Exception as e:
            logger.warning(f"Navigation warning for {item_name}: {e}")

        # Extract page text and HTML
        page_html = await page.content()
        page_text = (await page.inner_text("body") if await page.query_selector("body") else "").lower()

        # Check for Flipkart Surge Screen ("All of India is here")
        if "all of india is here" in page_text or "experiencing higher traffic than normal" in page_text:
            logger.info(f"Surge screen seen for {item_name}. Waiting 4 seconds for Akamai challenge solve...")
            await page.wait_for_timeout(4000)
            page_html = await page.content()
            page_text = (await page.inner_text("body") if await page.query_selector("body") else "").lower()

        # If STILL on surge screen after waiting, return SURGE_SCREEN so no false restock triggers
        if "all of india is here" in page_text or "experiencing higher traffic than normal" in page_text:
            logger.warning(f"Flipkart Surge Screen persisting for {item_name}. Retrying next cycle.")
            return {
                "id": target_id,
                "item_name": item_name,
                "status": "SURGE_SCREEN",
                "price": "",
                "url": url,
            }

        # 1. Primary: JSON-LD Structured Data
        status, price = parse_flipkart_jsonld(page_html)

        # 2. Secondary: __INITIAL_STATE__
        if not status:
            status, price = parse_flipkart_initial_state(page_html)

        # 3. Tertiary: Button and text inspection
        if not status:
            has_buy_button = False
            has_oos_button = False

            buttons = await page.query_selector_all("button, a")
            for btn in buttons:
                try:
                    btn_txt = (await btn.inner_text()).strip().upper()
                    if "BUY NOW" in btn_txt or "ADD TO CART" in btn_txt:
                        has_buy_button = True
                        break
                    if "NOTIFY ME" in btn_txt or "COMING SOON" in btn_txt or "OUT OF STOCK" in btn_txt:
                        has_oos_button = True
                except Exception:
                    pass

            if has_buy_button:
                status = "IN_STOCK"
            elif has_oos_button or "currently out of stock" in page_text or "coming soon" in page_text:
                status = "OUT_OF_STOCK"
            else:
                status = "OUT_OF_STOCK"

        return {
            "id": target_id,
            "item_name": item_name,
            "status": status or "OUT_OF_STOCK",
            "price": price or target.get("denomination", ""),
            "url": url,
        }

    except Exception as e:
        logger.error(f"Error checking {item_name}: {e}")
        return {
            "id": target_id,
            "item_name": item_name,
            "status": "ERROR",
            "price": "",
            "url": url,
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

    for target in config.TARGET_SITES:
        if not target.get("enabled", True):
            continue

        target_id = target["id"]
        item_name = target["item_name"]
        url = target["url"]

        logger.info(f"🔍 Checking: {item_name}...")
        result = await check_target_playwright(context, target)

        current_status = result.get("status", "UNKNOWN")
        price = result.get("price", "")
        item_url = result.get("url", url)
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
            "url": item_url,
            "last_checked": datetime.datetime.now().isoformat(),
        }

        # Check for Alert Triggers: Only alert on OUT_OF_STOCK -> IN_STOCK transition
        should_alert = False

        if previous_status == "OUT_OF_STOCK" and current_status == "IN_STOCK":
            logger.info(f"🚨 RESTOCK TRANSITION DETECTED for {item_name} on Flipkart!")
            should_alert = True
        elif previous_status is None and current_status == "IN_STOCK" and config.NOTIFY_ON_INITIAL_RUN:
            logger.info(f"🚨 Initial In-Stock detected for {item_name} on Flipkart!")
            should_alert = True

        if should_alert:
            await send_telegram_alert(
                platform="Flipkart",
                item_name=item_name,
                price=price,
                url=item_url,
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

        # Gentle delay between items to avoid rate limiting
        await asyncio.sleep(config.SITE_CHECK_DELAY_SECONDS)

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
    engine_info = "Playwright Chromium (Stealth + Anti-Surge)"

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
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            geolocation={"latitude": 19.0760, "longitude": 72.8777},
            permissions=["geolocation"],
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        # Advanced stealth: bypass navigator.webdriver and fake browser environment
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['en-IN', 'en-GB', 'en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """)
        logger.info("Playwright Headless Chromium successfully initialized with stealth headers.")

        # Session warmup with Flipkart homepage to establish initial Akamai session cookies
        logger.info("Initiating Flipkart session warmup...")
        try:
            warmup_page = await context.new_page()
            await warmup_page.goto("https://www.flipkart.com", timeout=35000, wait_until="domcontentloaded")
            await warmup_page.wait_for_timeout(3000)
            await warmup_page.close()
            logger.info("Flipkart session warmup complete. Akamai cookies established.")
        except Exception as e:
            logger.warning(f"Session warmup notice: {e}")

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

            logger.info(f"Sleeping for {config.CHECK_INTERVAL_SECONDS}s before next sweep...\n")
            await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)

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
