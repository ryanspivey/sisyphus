from flask import Flask, request
import asyncio, threading, typing
import discord

app = Flask(__name__)

# will be filled in from bot.py at startup
client_ref: typing.Optional[discord.Client] = None
purge_fn:   typing.Optional[typing.Callable[[int], asyncio.Future]] = None

@app.route('/')
def home():
    return "Bot is alive!"

@app.route('/purge/<int:channel_id>')
def purge_text_channel(channel_id: int):
    print(f"📥 Received purge request for channel {channel_id}")

    if client_ref is None or purge_fn is None:
        return "❌ Bot not ready", 503

    fut = asyncio.run_coroutine_threadsafe(
        purge_fn(channel_id), client_ref.loop
    )
    print(f"🧹 Scheduled purge task: {fut}")
    return f"Purge started for {channel_id}", 200


def start_flask() -> None:
    print("🌐 Starting Flask keep‑alive server …")
    app.run(host="0.0.0.0", port=8080)


def keep_alive(bot_client: discord.Client, purge_coroutine):
    """Call this once from bot.py"""
    global client_ref, purge_fn
    client_ref = bot_client
    purge_fn   = purge_coroutine

    thread = threading.Thread(target=start_flask, daemon=True)
    thread.start()
