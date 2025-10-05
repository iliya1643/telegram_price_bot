import asyncio
import threading
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = "YOUR_REAL_BOT_TOKEN"
WEBHOOK_PATH = f"/{BOT_TOKEN}"
PORT = 8000  

flask_app = Flask(__name__)
application = ApplicationBuilder().token(BOT_TOKEN).build()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name if update.effective_user else "there"
    await update.message.reply_text(f"Hello, {user_name}! Webhook is working on Koyeb!")

application.add_handler(CommandHandler("start", start_command))

ptb_loop = asyncio.new_event_loop()
def _ptb_loop_thread(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=_ptb_loop_thread, args=(ptb_loop,), daemon=True).start()

asyncio.run_coroutine_threadsafe(application.initialize(), ptb_loop).result(timeout=20)
asyncio.run_coroutine_threadsafe(application.start(), ptb_loop).result(timeout=20)

@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    try:
        payload = request.get_json(force=True)
        update = Update.de_json(payload, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), ptb_loop)
    except Exception as e:
        print("Webhook error:", e)
    return "ok", 200

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=PORT)
