from flask import Flask, request
from threading import Thread
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
    loop = asyncio.get_event_loop()
    loop.create_task(purge_channel(channel_id))
    return f"🧹 Purge started for channel {channel_id}", 200

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
