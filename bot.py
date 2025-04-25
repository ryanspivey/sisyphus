# ──────────────────────────────────────────────────────────────────────────────
#  Sisyphus music-bot – full code, ready to run
# ──────────────────────────────────────────────────────────────────────────────
import os, time, random, asyncio, threading, functools
from dotenv import load_dotenv
from flask import Flask, request

import discord
from discord.ext import commands
from discord import app_commands
from discord.utils import get
import wavelink                   # 3.4.x

# always-flushed print
print = functools.partial(print, flush=True)

# ╭─────────────────────  ENV & CONFIG  ─────────────────────╮
load_dotenv()
TOKEN           = os.getenv("DISCORD_TOKEN")
CHANNEL_IDS_RAW = os.getenv("CHANNEL_IDS", "")

CHANNEL_IDS = [int(cid.strip()) for cid in CHANNEL_IDS_RAW.split(",") if cid.strip().isdigit()]

# ╭─────────────────────  DISCORD  ──────────────────────────╮
intents               = discord.Intents.default()
intents.message_content = True
intents.messages        = True
intents.guilds          = True
intents.voice_states    = True

bot  = commands.Bot(command_prefix="/", intents=intents)

def log(*msg):
    print(f"[{os.getenv('RENDER_INSTANCE_ID', 'local')} {time.strftime('%H:%M:%S')}]",
          *msg)

# ╭─────────────────────  LAVALINK CONNECT  ─────────────────╮
@bot.event
async def on_ready():
    log(f"Logged in as {bot.user} ({bot.user.id})")
    # connect lavalink
    node = wavelink.Node(
        uri      = f"http://{os.getenv('LAVALINK_IP')}:2333",
        password = os.getenv("LAVALINK_PASS")
    )
    await wavelink.Pool.connect(client=bot, nodes=[node])
    log("Lavalink node connected")

    try:
        await bot.tree.sync()
        log("Slash commands synced")
    except Exception as e:
        log("Failed to sync commands:", e)


# ╭─────────────────────  MUSIC HELPERS  ────────────────────╮
class Music:
    """Utility helpers – works on `wavelink.Player` instances."""

    @staticmethod
    async def ensure_player(inter: discord.Interaction) -> wavelink.Player:
        """Get or create a voice-player bound to this guild."""
        if not (inter.user.voice and inter.user.voice.channel):
            raise RuntimeError("You must be in a voice channel.")

        # connection / reuse
        player = get(bot.voice_clients, guild=inter.guild)
        if not player:
            player = await inter.user.voice.channel.connect(cls=wavelink.Player)

            # attach a queue & state
            player.queue   = []
            player.history = []
            player.loop    = False
            await player.set_volume(100)
        return player

    # simple wrappers ---------------------------------------------------------
    @staticmethod
    async def play(player: wavelink.Player, track: wavelink.Playable):
        await player.play(track)
        player.queue.insert(0, track)  # currently playing at index 0

    @staticmethod
    async def enqueue(player: wavelink.Player, track: wavelink.Playable):
        player.queue.append(track)

    @staticmethod
    async def next_track(player: wavelink.Player):
        if player.queue:
            player.history.append(player.queue.pop(0))
        if player.queue:
            await player.play(player.queue[0])

    @staticmethod
    async def previous_track(player: wavelink.Player):
        if player.history:
            previous = player.history.pop()
            player.queue.insert(0, previous)
            await player.play(previous)

# ╭─────────────────────  INTERACTIVE UI  ───────────────────╮
class PlayCard(discord.ui.View):
    def __init__(self, player: wavelink.Player):
        super().__init__(timeout=None)
        self.player = player

    # ► / ❚❚
    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, _):
        if self.player.paused:
            await self.player.resume()
        else:
            await self.player.pause()
        await interaction.response.defer()

    # ⏭
    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary, row=0)
    async def skip(self, interaction: discord.Interaction, _):
        await Music.next_track(self.player)
        await interaction.response.defer()

    # ⏮
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.primary, row=0)
    async def previous(self, interaction: discord.Interaction, _):
        await Music.previous_track(self.player)
        await interaction.response.defer()

    # 🔀 shuffle
    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle(self, interaction: discord.Interaction, _):
        if len(self.player.queue) > 2:
            head = self.player.queue[0]
            rest = self.player.queue[1:]
            random.shuffle(rest)
            self.player.queue = [head] + rest
        await interaction.response.defer()

    # 🔁 loop
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def loop(self, interaction: discord.Interaction, _):
        self.player.loop = not getattr(self.player, "loop", False)
        await interaction.response.defer()

    # 🔉
    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.success, row=0)
    async def vol_down(self, interaction: discord.Interaction, _):
        self.player.volume = max(10, self.player.volume - 10)
        await self.player.set_volume(self.player.volume)
        await interaction.response.defer()

    # 🔊
    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.success, row=0)
    async def vol_up(self, interaction: discord.Interaction, _):
        self.player.volume = min(150, self.player.volume + 10)
        await self.player.set_volume(self.player.volume)
        await interaction.response.defer()

    # ⏹ stop / disconnect
    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=1)
    async def stop(self, interaction: discord.Interaction, _):
        await self.player.stop()
        await self.player.disconnect()
        await interaction.response.defer()

# ╭─────────────────────  SLASH COMMANDS  ───────────────────╮
@bot.tree.command(name="play", description="Play a song (search term or URL)")
@app_commands.describe(search="song name / link")
async def slash_play(inter: discord.Interaction, search: str):
    # acknowledge
    await inter.response.defer(thinking=True)

    # create / get player
    try:
        player = await Music.ensure_player(inter)
    except RuntimeError as err:
        return await inter.followup.send(f"❌ {err}")

    # search
    tracks = await wavelink.Playable.search(search)
    if not tracks:
        return await inter.followup.send("❌ No results.")

    track = tracks[0]

    if player.is_playing():
        await Music.enqueue(player, track)
        await inter.followup.send(f"➕ Queued **{track.title}**")
    else:
        await Music.play(player, track)
        card = PlayCard(player)
        await inter.followup.send(f"▶️ Now playing **{track.title}**", view=card)


# simple slash wrappers mapping to the buttons -------------------------------
@bot.tree.command(name="pause", description="Pause / resume playback")
async def slash_pause(inter: discord.Interaction):
    player = await Music.ensure_player(inter)
    await inter.response.defer()
    if player.paused:
        await player.resume()
    else:
        await player.pause()


@bot.tree.command(name="skip", description="Skip to next track")
async def slash_skip(inter: discord.Interaction):
    player = await Music.ensure_player(inter)
    await inter.response.defer()
    await Music.next_track(player)


@bot.tree.command(name="stop", description="Stop and disconnect")
async def slash_stop(inter: discord.Interaction):
    player = await Music.ensure_player(inter)
    await inter.response.defer()
    await player.stop()
    await player.disconnect()


# ╭─────────────────────  AUTOPLAY / LOOP  ──────────────────╮
@bot.listen("wavelink_track_end")
async def _on_track_end(player: wavelink.Player, *_):
    # if looping, replay
    if getattr(player, "loop", False):
        await player.play(player.queue[0])
        return

    # otherwise next in queue
    if len(player.queue) > 1:
        player.history.append(player.queue.pop(0))
        await player.play(player.queue[0])
    else:
        # queue empty -> disconnect after a grace period
        await asyncio.sleep(300)
        if not player.is_playing():
            await player.disconnect()

# ╭─────────────────────  MESSAGE FILTER / PURGE / FLASK  ──╮
def is_message_allowed(msg: discord.Message) -> bool:
    return msg.attachments or any(word.startswith(("http://", "https://"))
                                  for word in msg.content.split())

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot or msg.channel.id not in CHANNEL_IDS:
        return
    if not is_message_allowed(msg):
        await msg.delete()
        warn = await msg.channel.send(
            f"🚫 <@{msg.author.id}>, text-only messages aren’t allowed. Include a link or file."
        )
        await warn.delete(delay=8)

async def purge_channel(ch_id: int):
    await bot.wait_until_ready()
    ch = bot.get_channel(ch_id)
    if not ch:
        return
    async for m in ch.history(limit=1000):
        if not (m.author.bot or is_message_allowed(m)):
            await m.delete()

# small keep-alive server (unchanged) ----------------------------------------
app = Flask(__name__)
client_ref = None; purge_fn = None

@app.route("/")
def home(): return "Bot is alive!"

@app.route("/purge/<int:cid>")
def purge_ep(cid: int):
    fut = asyncio.run_coroutine_threadsafe(purge_fn(cid), client_ref.loop)
    return f"Purge started for {cid}", 200

def _flask(): app.run(host="0.0.0.0", port=8080)

def keep_alive(client, purge_coroutine):
    global client_ref, purge_fn
    client_ref, purge_fn = client, purge_coroutine
    threading.Thread(target=_flask, daemon=True).start()

# ╭─────────────────────  START  ────────────────────────────╮
keep_alive(bot, purge_channel)
log("Starting bot…")
bot.run(TOKEN)
