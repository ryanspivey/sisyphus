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

# 🔍 Shared logic for message validation
def is_message_allowed(message: discord.Message) -> bool:
    has_attachment = bool(message.attachments)
    has_link = any(word.startswith(("http://", "https://")) for word in message.content.split())
    return has_attachment or has_link

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

    if not is_message_allowed(message):
    print("🗑 Deleting text-only message (no media or link)")
    try:
        await message.delete()
        print("🗑 Message deleted")

        # Send a temporary help message
        warning = await message.channel.send(
            f"🚫 <@{message.author.id}>, text-only messages aren't allowed in this channel. Please include a link or attachment."
        )
        await warning.delete(delay=8)  # auto-delete after 8 seconds

    except discord.errors.NotFound:
        print("⚠️ Tried to delete a message that was already gone")
    except discord.errors.Forbidden:
        print("❌ Bot doesn't have permission to delete this message or post a warning")
    except Exception as e:
        print(f"❌ Unexpected error deleting message: {e}")

# Used for purge endpoint
async def purge_channel(channel_id: int):
    await client.wait_until_ready()

    channel = client.get_channel(channel_id)
    if not channel:
        print(f"❌ Channel {channel_id} not found")
        return

    print(f"🧹 Starting purge in channel {channel_id} ({channel.name})")

    deleted_count = 0
    skipped_count = 0

    try:
        async for message in channel.history(limit=1000):  # adjust as needed
            if message.author.bot:
                skipped_count += 1
                continue

            if not is_message_allowed(message):
                try:
                    await message.delete()
                    print(f"🧼 Deleted: [{message.author.display_name}] {message.content}")
                    deleted_count += 1
                except Exception as e:
                    print(f"❌ Error deleting message from {message.author.display_name}: {e}")
            else:
                skipped_count += 1

        print(f"✅ Purge complete: {deleted_count} messages deleted, {skipped_count} skipped.")
    except Exception as e:
        print(f"❌ Failed to purge channel {channel_id}: {e}")

keep_alive(client, purge_channel)
print("🚀 Starting bot...")
client.run(TOKEN)