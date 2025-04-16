import discord
import os
from dotenv import load_dotenv
from keep_alive import keep_alive
import functools
print = functools.partial(print, flush=True)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Check that both env vars are loaded
if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN is missing.")
else:
    print("✅ DISCORD_TOKEN loaded.")

if not CHANNEL_ID:
    print("❌ ERROR: CHANNEL_ID is missing.")
else:
    print(f"✅ CHANNEL_ID loaded: {CHANNEL_ID}")

try:
    CHANNEL_ID = int(CHANNEL_ID)
except Exception as e:
    print(f"❌ ERROR converting CHANNEL_ID to int: {e}")

# Enable intents
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user} (ID: {client.user.id})")

@client.event
async def on_message(message):
    print(f"📨 Message received in #{message.channel.name} ({message.channel.id}): {message.content}")

    if message.author.bot:
        print("🔁 Skipping bot message")
        return

    if message.channel.id != CHANNEL_ID:
        print(f"❌ Message in untracked channel: {message.channel.id}")
        return

    has_attachment = bool(message.attachments)
    has_link = any(word.startswith(("http://", "https://")) for word in message.content.split())

    if not (has_attachment or has_link):
        print("🗑 Deleting non-link/non-attachment message")
        await message.delete()
    else:
        print("✅ Allowed message")

keep_alive()
print("🚀 Starting bot...")
client.run(TOKEN)
