import discord
import os
from dotenv import load_dotenv
from keep_alive import keep_alive
import functools
print = functools.partial(print, flush=True)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_IDS_RAW = os.getenv("CHANNEL_IDS")

# Check that both env vars are loaded
if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN is missing.")
else:
    print("✅ DISCORD_TOKEN loaded.")

if not CHANNEL_IDS_RAW:
    print("❌ ERROR: CHANNEL_IDS is missing.")
    CHANNEL_IDS = []
else:
    try:
        CHANNEL_IDS = [int(cid.strip()) for cid in CHANNEL_IDS_RAW.split(',')]
        print(f"✅ CHANNEL_IDS loaded: {CHANNEL_IDS}")
    except Exception as e:
        print(f"❌ ERROR parsing CHANNEL_IDS: {e}")
        CHANNEL_IDS = []

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

    if message.channel.id not in CHANNEL_IDS:
        print(f"❌ Message in untracked channel: {message.channel.id}")
        return

    has_attachment = bool(message.attachments)
    has_link = any(word.startswith(("http://", "https://")) for word in message.content.split())

    if not (has_attachment or has_link):
        # Message is just text with no media or links — delete it
        print("🗑 Deleting text-only message (no media or link)")
        try:
            await message.delete()
            print("🗑 Message deleted")
        except discord.errors.NotFound:
            print("⚠️ Tried to delete a message that was already gone")
        except discord.errors.Forbidden:
            print("❌ Bot doesn't have permission to delete this message")
        except Exception as e:
            print(f"❌ Unexpected error deleting message: {e}")
    else:
        print("✅ Allowed: message has link or attachment (text is okay)")

async def purge_channel(channel_id: int):
    await client.wait_until_ready()

    channel = client.get_channel(channel_id)
    if not channel:
        print(f"❌ Channel {channel_id} not found")
        return

    print(f"🧹 Starting purge in channel {channel_id}")

    try:
        async for message in channel.history(limit=1000):  # adjust limit as needed
            if message.author.bot:
                continue

            has_attachment = bool(message.attachments)
            has_link = any(word.startswith(("http://", "https://")) for word in message.content.split())

            if not (has_attachment or has_link):
                try:
                    await message.delete()
                    print(f"🧼 Deleted message: {message.content}")
                except Exception as e:
                    print(f"❌ Error deleting message: {e}")
    except Exception as e:
        print(f"❌ Failed to purge channel {channel_id}: {e}")

keep_alive()
print("🚀 Starting bot...")
client.run(TOKEN)
