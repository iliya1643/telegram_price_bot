import asyncio
import json
import os
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import websockets
from threading import Thread
# ───── CONFIG ─────
BOT_TOKEN = "8343780728:AAHATAOgDochgcHuhLKDb5ZR6sXZ17cnioM"
CHAT_ID = "6961198983"
BITPIN_URL = "wss://ws.bitpin.ir"
RENDER_URL = "https://telegram-price-bot-knms.onrender.com"
WEBHOOK_PATH = f"/{BOT_TOKEN}"
FULL_WEBHOOK_URL = RENDER_URL.rstrip("/") + WEBHOOK_PATH
PORT = int(os.environ.get("PORT", 10000))

# ───── FLASK ─────
flask_app = Flask(__name__)

# ───── TELEGRAM ─────
application = ApplicationBuilder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name if update.effective_user else "there"
    await update.message.reply_text(f"Hello {user}! Async bot + WebSocket are running 🚀")

application.add_handler(CommandHandler("start", start))


# ───── BITPIN WEBSOCKET ─────
async def send_price(price):
    """Send price to Telegram chat."""
    message = f"💰 Current BTC/IRT price: {price}"
    await application.bot.send_message(chat_id=CHAT_ID, text=message)

async def bitpin_listener():
    """Connect to BitPin websocket and listen for updates."""
    while True:
        try:
            async with websockets.connect(BITPIN_URL, ping_interval=None) as ws:
                # Subscribe to tickers
                sub_msg = {"method": "sub_to_tickers"}
                await ws.send(json.dumps(sub_msg))
                print("✅ Subscribed to BitPin tickers")

                last_pong = asyncio.get_event_loop().time()

                async def ping_loop():
                    """Send PING every 20s and check PONG replies."""
                    nonlocal last_pong
                    while True:
                        await ws.send(json.dumps({"message": "PING"}))
                        print("📡 PING sent")
                        await asyncio.sleep(20)

                        # Check if PONG received recently
                        if asyncio.get_event_loop().time() - last_pong > 40:
                            print("⚠️ No PONG received, reconnecting...")
                            await ws.close()
                            break

                asyncio.create_task(ping_loop())

                async for msg in ws:
                    data = json.loads(msg)
                    # Track pong
                    if data.get("message") == "PONG":
                        last_pong = asyncio.get_event_loop().time()
                        continue
                    # Process ticker updates
                    if "BTC_IRT" in data:
                        price = data["BTC_IRT"]["price"]
                        print("BTC price:", price)
                        await send_price(price)

        except Exception as e:
            print("🔴 WebSocket error, reconnecting in 5s:", e)
            await asyncio.sleep(5)


# ───── TELEGRAM SETUP ─────
async def set_webhook():
    print(f"Setting webhook to: {FULL_WEBHOOK_URL}")
    result = await application.bot.set_webhook(url=FULL_WEBHOOK_URL)
    print("Webhook set result:", result)


# ───── FLASK ROUTES ─────
@flask_app.route("/", methods=["GET"])
def home():
    return "Bot and BitPin WebSocket running async 🚀", 200

@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), application.loop)
    except Exception as e:
        print("Webhook error:", e)
    return "ok", 200


# ───── MAIN ENTRY ─────
async def telegram_bitpin_starter():
    # Initialize Telegram bot
    await application.initialize()
    await application.start()

    # Set webhook on Telegram
    await set_webhook()

    # Run BitPin listener in parallel
    asyncio.create_task(bitpin_listener())

    while True:
        await asyncio.sleep(3600)
def sync_starter():
    asyncio.run(telegram_bitpin_starter())

if __name__ == "__main__":
    print("🚀 Starting Async Telegram + BitPin bot on Render...")
    Thread(target=sync_starter , daemon=True).start()
    flask_app.run(host="0.0.0.0", port=PORT)