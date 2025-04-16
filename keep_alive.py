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

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
