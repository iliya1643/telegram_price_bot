import asyncio
import json
import os
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import websockets
from threading import Thread

# ───── CONFIG ─────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8343780728:AAHATAOgDochgcHuhLKDb5ZR6sXZ17cnioM")
CHAT_ID = int(os.environ.get("CHAT_ID", "6961198983"))
BITPIN_URL = "wss://ws.bitpin.ir"
RENDER_URL = os.environ.get("RENDER_URL", "https://telegram-price-bot-knms.onrender.com")
WEBHOOK_PATH = f"/{BOT_TOKEN}"
FULL_WEBHOOK_URL = RENDER_URL.rstrip("/") + WEBHOOK_PATH
PORT = int(os.environ.get("PORT", "10000"))
stop_requested = False
ws_lock = asyncio.Lock()
# ───── FLASK ─────
flask_app = Flask(__name__)

# ───── TELEGRAM ─────
application = ApplicationBuilder().token(BOT_TOKEN).build()

# global handles (must exist before usage)
bitpin_task: asyncio.Task | None = None
ping_task: asyncio.Task | None = None
_ws: websockets.WebSocketClientProtocol | None = None


# ---------- Telegram handlers ----------
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Safely stop ping task, close websocket connection and cancel listener task.
    Runs inside application.loop so 'await' is allowed.
    """
    await application.bot.send_message(chat_id=CHAT_ID, text="stoping")
    global ping_task, bitpin_task, _ws,stop_requested
    stop_requested = True
    replies = []

    # 1) send unsubscribe on existing connection (if supported)
    async with ws_lock:
        if _ws is not None:
            try:
                try:
                    await _ws.send(json.dumps({"method": "unsub_tickers"}))
                    replies.append("Unsubscribe message sent.")
                except Exception as e:
                    replies.append(f"Couldn't send unsubscribe: {e}")
    
                if not _ws.closed:
                    await _ws.close()
                    replies.append("WebSocket closed.")
            except Exception as e:
                replies.append(f"Error while closing WebSocket: {e}")
            finally:
                _ws = None
        else:
            replies.append("No active WebSocket connection found.")

    # 2) cancel ping_task
    if ping_task:
        if not ping_task.done():
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                replies.append("Ping task cancelled.")
        else:
            replies.append("Ping task already finished.")
        ping_task = None
    else:
        replies.append("No ping task.")

    # 3) cancel bitpin listener
    if bitpin_task:
        if not bitpin_task.done():
            bitpin_task.cancel()
            try:
                await bitpin_task
            except asyncio.CancelledError:
                replies.append("BitPin listener cancelled.")
        else:
            replies.append("BitPin listener already finished.")
        bitpin_task = None
    else:
        replies.append("No BitPin listener task.")
    await application.bot.send_message(chat_id=CHAT_ID, text="stoped")
    await update.message.reply_text("\n".join(replies))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bitpin_task, stop_requested
    stop_requested = False
    if not (bitpin_task and not bitpin_task.done()):
        bitpin_task = asyncio.create_task(bitpin_listener())
        await update.message.reply_text("BitPin listener started.")
    else:
        await update.message.reply_text("Already running.")

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("stop", stop))


# ───── BITPIN WEBSOCKET ─────
async def send_price(price):
    """Send price to Telegram chat."""
    try:
        await application.bot.send_message(chat_id=CHAT_ID, text=f"💰 Current price of ETH : {price}")
    except Exception as e:
        print("Failed to send telegram message:", e)


async def bitpin_listener():
    """Connect to BitPin websocket and listen for updates."""
    global ping_task, bitpin_task, _ws
    loop = asyncio.get_running_loop()
    while True:
        if stop_requested :
            break
        try:
            async with websockets.connect(BITPIN_URL, ping_interval=None) as ws:
                print("✅ Connected to BitPin")
                async with ws_lock:
                    _ws = ws
    
                    # Subscribe
                    sub_msg = {"method": "sub_to_tickers"}
                    await ws.send(json.dumps(sub_msg))
                    print("✅ Subscribed to BitPin tickers")
    
                    last_pong = loop.time()
    
                    async def ping_loop():
                        nonlocal last_pong
                        try:
                            while True:
                                await ws.send(json.dumps({"message": "PING"}))
                                # print("📡 PING sent")
                                await asyncio.sleep(20)
                                if loop.time() - last_pong > 40:
                                    print("⚠️ No PONG received, reconnecting...")
                                    try:
                                        await ws.close()
                                    except Exception:
                                        pass
                                    break
                        except asyncio.CancelledError:
                            # ping task cancelled
                            raise
    
                # create and keep global handle
                ping_task = asyncio.create_task(ping_loop())

                # read messages
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue

                    # handle pong
                    if data.get("message") == "PONG":
                        last_pong = loop.time()
                        continue

                    # defensive price access: try BTC_IRT then USDT_IRT
                    ticker = data.get("ETH_IRT") or {}
                    price = ticker.get("price")
                    if price:
                        print("ETC Price:", price)
                        await send_price(price)

                # if loop exits, ws closed — ensure ping_task cancelled
                if ping_task and not ping_task.done():
                    ping_task.cancel()
                    try:
                        await ping_task
                    except asyncio.CancelledError:
                        pass
                ping_task = None
                print("ping_pong has been ended")

                async with ws_lock:
                    _ws = None

        except asyncio.CancelledError:
            print("bitpin_listener cancelled")
            break
        except Exception as e:
            print(" WebSocket error, reconnecting in 5s:", e)
            if stop_requested:
                break
            # cleanup ping_task if any
            if ping_task and not ping_task.done():
                ping_task.cancel()
                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass
                ping_task = None
            _ws = None
            await asyncio.sleep(5)

    # final cleanup
    if ping_task and not ping_task.done():
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass
    if _ws:
        try:
            await _ws.close()
        except Exception:
            pass
        _ws = None


# ───── TELEGRAM SETUP ─────
async def set_webhook():
    print(f"Setting webhook to: {FULL_WEBHOOK_URL}")
    try:
        result = await application.bot.set_webhook(url=FULL_WEBHOOK_URL)
        print("Webhook set result:", result)
    except Exception as e:
        print("Failed to set webhook:", e)


# ───── FLASK ROUTES ─────
@flask_app.route("/", methods=["GET"])
def home():
    return "Bot and BitPin WebSocket running async 🚀", 200


@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        loop = application.loop
        if loop is None:
            print("Warning: application.loop is None (bot not started yet)")
            return "service not ready", 503
        asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    except Exception as e:
        print("Webhook error:", e)
    return "ok", 200


# ───── MAIN ENTRY ─────
async def telegram_bitpin_starter():
    global bitpin_task
    await application.initialize()
    await application.start()
    await set_webhook()
    if not (bitpin_task and not bitpin_task.done()):
        bitpin_task = asyncio.create_task(bitpin_listener())
    while True:
        await asyncio.sleep(3600)


def sync_starter():
    asyncio.run(telegram_bitpin_starter())

if __name__ == "__main__":
    print("🚀 Starting Async Telegram + BitPin bot on Render...")
    Thread(target=sync_starter, daemon=True).start()
    flask_app.run(host="0.0.0.0", port=PORT)
    