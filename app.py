from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio
import threading
import os

BOT_TOKEN = "8343780728:AAHATAOgDochgcHuhLKDb5ZR6sXZ17cnioM"
RENDER_URL = "https://telegram-price-bot-knms.onrender.com"  # your Render app URL
WEBHOOK_PATH = f"/{BOT_TOKEN}"
FULL_WEBHOOK_URL = RENDER_URL.rstrip("/") + WEBHOOK_PATH
PORT = int(os.environ.get("PORT", 10000))

flask_app = Flask(__name__)

application = ApplicationBuilder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name if update.effective_user else "there"
    await update.message.reply_text(f"Hello {user}, webhook is working on Render with PTB v21+!")

application.add_handler(CommandHandler("start", start))

ptb_loop = asyncio.new_event_loop()

def _run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(application.initialize())
    loop.run_until_complete(application.start())
    loop.run_forever()

threading.Thread(target=_run_loop, args=(ptb_loop,), daemon=True).start()

async def set_webhook():
    print(f"Setting webhook to: {FULL_WEBHOOK_URL}")
    result = await application.bot.set_webhook(url=FULL_WEBHOOK_URL)
    print("Webhook set result:", result)

asyncio.run_coroutine_threadsafe(set_webhook(), ptb_loop)

@flask_app.route("/", methods=["GET"])
def home():
    return "Bot is running on Render 🚀", 200

@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    """Handle incoming updates from Telegram."""
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), ptb_loop)
    except Exception as e:
        print("Webhook error:", e)
    return "ok", 200

if __name__ == "__main__":
    print(f"Starting Flask server on port {PORT}")
    flask_app.run(host="0.0.0.0", port=PORT)
