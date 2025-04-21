import os
import asyncio
import threading
import typing
from dotenv import load_dotenv
from flask import Flask, request

import discord
from discord.ext import commands
from discord import app_commands
import wavelink
import functools
print = functools.partial(print, flush=True)

# === Load environment variables ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_IDS_RAW = os.getenv("CHANNEL_IDS")

if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN is missing.")

if not CHANNEL_IDS_RAW:
    print("❌ ERROR: CHANNEL_IDS is missing.")
    CHANNEL_IDS = []
else:
    try:
        CHANNEL_IDS = [int(cid.strip()) for cid in CHANNEL_IDS_RAW.split(',')]
    except Exception as e:
        print(f"❌ ERROR parsing CHANNEL_IDS: {e}")
        CHANNEL_IDS = []

# === Intents and Bot Setup ===
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="/", intents=intents)

# === Lavalink Setup ===
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        await bot.tree.sync()
        print("✅ Slash commands synced")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

    print(f"LAVALINK_PASS: {os.getenv('LAVALINK_PASS')}")
    print(f"LAVALINK_IP: {os.getenv('LAVALINK_IP')}")

    node = wavelink.Node(uri=f'http://{os.getenv("LAVALINK_IP")}:2333', password=os.getenv("LAVALINK_PASS"))
    await wavelink.Pool.connect(client=bot, nodes=[node])
    print("🎶 Lavalink node connected")

# === Slash Command: /play ===
@bot.tree.command(name="play", description="Play a song in your voice channel")
@app_commands.describe(search="The song name or URL to play")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()

    # Step 1: Make sure the user is in a voice channel
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("❌ You must be in a voice channel to use this command.")
        return

    # Step 2: Get or connect Lavalink node
    node: wavelink.Node = wavelink.Pool.get_node()

    # Step 3: Get or create player for this guild
    player: wavelink.Player = node.get_player(interaction.guild.id)
    if not player:
        player = await node.connect(interaction.guild.id)

    # Step 4: Connect bot to the user's voice channel if not already connected
    if not player.is_connected():
        await player.connect(interaction.user.voice.channel.id)

    # Step 5: Search and play track
    tracks = await wavelink.YouTubeTrack.search(search, return_first=True)
    if not tracks:
        await interaction.followup.send("❌ No results found.")
        return

    await player.play(tracks)
    await interaction.followup.send(f"▶️ Now playing: **{tracks.title}**")

# === Message Filter ===
def is_message_allowed(message: discord.Message) -> bool:
    has_attachment = bool(message.attachments)
    has_link = any(word.startswith(("http://", "https://")) for word in message.content.split())
    return has_attachment or has_link

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id not in CHANNEL_IDS:
        return

    if not is_message_allowed(message):
        try:
            await message.delete()
            warning = await message.channel.send(
                f"🚫 <@{message.author.id}>, text-only messages aren't allowed. Include a link or file."
            )
            await warning.delete(delay=8)
        except Exception as e:
            print(f"❌ Failed to delete message or send warning: {e}")

# === Purge Channel ===
async def purge_channel(channel_id: int):
    await bot.wait_until_ready()
    channel = bot.get_channel(channel_id)
    if not channel:
        print(f"❌ Channel {channel_id} not found")
        return

    deleted_count = 0
    skipped_count = 0

    try:
        async for message in channel.history(limit=1000):
            if message.author.bot:
                skipped_count += 1
                continue
            if not is_message_allowed(message):
                try:
                    await message.delete()
                    deleted_count += 1
                except Exception as e:
                    print(f"❌ Error deleting message: {e}")
            else:
                skipped_count += 1
        print(f"✅ Purge complete: {deleted_count} deleted, {skipped_count} skipped.")
    except Exception as e:
        print(f"❌ Error purging channel: {e}")

# === Keep-alive Server ===
app = Flask(__name__)
client_ref = None
purge_fn = None

@app.route('/')
def home():
    return "Bot is alive!"

@app.route('/purge/<int:channel_id>')
def purge_text_channel(channel_id: int):
    fut = asyncio.run_coroutine_threadsafe(
        purge_fn(channel_id), client_ref.loop
    )
    return f"Purge started for {channel_id}", 200

def start_flask():
    app.run(host="0.0.0.0", port=8080)

def keep_alive(bot_client, purge_coroutine):
    global client_ref, purge_fn
    client_ref = bot_client
    purge_fn = purge_coroutine
    threading.Thread(target=start_flask, daemon=True).start()

# === Start Bot ===
keep_alive(bot, purge_channel)
print("🚀 Starting bot...")
bot.run(TOKEN)
