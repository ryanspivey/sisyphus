from flask import Flask, request
import asyncio

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

@app.route('/purge/<int:channel_id>', methods=['GET'])
def purge_text_channel(channel_id):
    print(f"📥 Received purge request for channel {channel_id}")
    try:
        from bot import client, purge_channel
        future = asyncio.run_coroutine_threadsafe(purge_channel(channel_id), client.loop)
        print(f"🧹 Scheduled purge task for {channel_id}: {future}")
        return f"Purge started for channel {channel_id}", 200
    except Exception as e:
        print(f"❌ Exception during purge scheduling: {e}")
        return f"❌ Internal error: {e}", 500

def keep_alive():
    from threading import Thread

    def run():
        try:
            print("🌐 Starting Flask keep-alive server...")
            app.run(host="0.0.0.0", port=8080)
        except Exception as e:
            print(f"❌ Flask server failed to start: {e}")

    thread = Thread(target=run)
    thread.daemon = True  # let it die with the main process
    thread.start()
