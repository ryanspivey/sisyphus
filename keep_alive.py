from flask import Flask, request
from threading import Thread
import asyncio
import functools
print = functools.partial(print, flush=True)

app = Flask('')

@app.route('/')
def home():
    print(f"Ping from {request.remote_addr}")
    print(f"User-Agent: {request.headers.get('User-Agent')}")
    return "Bot is alive!"

@app.route('/purge/<int:channel_id>', methods=['GET'])
def purge_text_channel(channel_id):
    from bot import client, purge_channel  # import both
    try:
        future = asyncio.run_coroutine_threadsafe(purge_channel(channel_id), client.loop)
        print(f"🧹 Scheduled purge task for {channel_id}: {future}")
        return f"Purge started for channel {channel_id}", 200
    except Exception as e:
        print(f"❌ Exception during purge scheduling: {e}")
        return f"❌ Internal error: {e}", 500

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
