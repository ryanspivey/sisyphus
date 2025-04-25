# ──────────────────────────────────────────────────────────────────────────────
#  Sisyphus music-bot  –  ready to run
#    • Wavelink 3.4.x
# ──────────────────────────────────────────────────────────────────────────────
import os, time, random, asyncio, threading, functools
from dotenv import load_dotenv
from flask import Flask

import discord
from discord.ext import commands
from discord import app_commands
from discord.utils import get
import wavelink                       # 3.4.x

# ───────────────────────  helpers  ────────────────────────
print = functools.partial(print, flush=True)          # auto-flush logging


def log(*msg: object):
    print(f"[{os.getenv('RENDER_INSTANCE_ID','local')} {time.strftime('%H:%M:%S')}]",
          *msg)


# ───────────────────────  env / config  ───────────────────
load_dotenv()
TOKEN           = os.getenv("DISCORD_TOKEN")
CHANNEL_IDS_RAW = os.getenv("CHANNEL_IDS", "")
CHANNEL_IDS     = [int(c.strip()) for c in CHANNEL_IDS_RAW.split(",") if c.strip().isdigit()]

# ───────────────────────  discord  ────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.messages        = True
intents.guilds          = True
intents.voice_states    = True

bot = commands.Bot(command_prefix="/", intents=intents)

# ───────────────────────  lavalink connect  ───────────────
@bot.event
async def on_ready():
    log(f"Logged in as {bot.user} ({bot.user.id})")

    node = wavelink.Node(
        uri      = f"http://{os.getenv('LAVALINK_IP')}:2333",
        password = os.getenv("LAVALINK_PASS")
    )
    await wavelink.Pool.connect(client=bot, nodes=[node])
    log("Lavalink node connected")

    try:
        await bot.tree.sync()
        log("Slash commands synced")
    except Exception as exc:
        log("Failed to sync slash commands:", exc)


# ───────────────────────  music helpers  ──────────────────
class Music:
    """Utility wrappers around `wavelink.Player`."""

    # ── player lifetime ───────────────────────────────────
    @staticmethod
    async def ensure_player(inter: discord.Interaction) -> wavelink.Player:
        if not (inter.user.voice and inter.user.voice.channel):
            raise RuntimeError("You must be in a voice channel.")

        player = get(bot.voice_clients, guild=inter.guild)
        if not player:
            player = await inter.user.voice.channel.connect(cls=wavelink.Player)

            # custom state (queue object already exists!)
            player.history: list[wavelink.Playable] = []
            player.loop:    bool                     = False
            await player.set_volume(100)

        return player

    # ── queue / playback helpers ───────────────────────────
    @staticmethod
    async def play(player: wavelink.Player, track: wavelink.Playable):
        """Start playing a track immediately (does **not** touch the queue)."""
        await player.play(track)

    @staticmethod
    async def enqueue(player: wavelink.Player, track: wavelink.Playable):
        """Add a track to the end of the queue."""
        player.queue.put(track)

    @staticmethod
    async def bulk_enqueue(player: wavelink.Player, tracks: list[wavelink.Playable]):
        """Append many tracks to the queue (no await needed)."""
        for t in tracks:
            player.queue.put(t)

    @staticmethod
    async def next_track(player: wavelink.Player):
        """Skip to the next track in queue."""
        if player.queue.is_empty:
            return
        player.history.append(player.current)
        next_up: wavelink.Playable = player.queue.get()
        await player.play(next_up)

    @staticmethod
    async def previous_track(player: wavelink.Player):
        """Play the previous track, if any."""
        if not player.history:
            return
        previous = player.history.pop()
        # push the current song back to the front of the queue
        if player.current:
            await player.queue.put(player.current, index=0)
        await player.play(previous)


# ───────────────────────  interactive card  ───────────────
class PlayCard(discord.ui.View):
    def __init__(self, player: wavelink.Player):
        super().__init__(timeout=None)
        self.player = player

    # pause / resume
    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def _pause_resume(self, interaction: discord.Interaction, _):
        if self.player.paused:
            await self.player.pause(False)
        else:
            await self.player.pause(True)
        await interaction.response.defer()

    # skip
    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary, row=0)
    async def _skip(self, inter: discord.Interaction, _):
        await Music.next_track(self.player)
        await inter.response.defer()

    # previous
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.primary, row=0)
    async def _previous(self, inter: discord.Interaction, _):
        await Music.previous_track(self.player)
        await inter.response.defer()

    # shuffle
    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def _shuffle(self, inter: discord.Interaction, _):
        if self.player.queue.count > 1:
            self.player.queue.shuffle()
        await inter.response.defer()

    # loop toggle
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def _loop(self, inter: discord.Interaction, _):
        self.player.loop = not self.player.loop
        await inter.response.defer()

    # volume down
    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.success, row=0)
    async def _vol_down(self, inter: discord.Interaction, _):
        new_vol = max(10, self.player.volume - 10)
        await self.player.set_volume(new_vol)
        await inter.response.defer()

    # volume up
    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.success, row=0)
    async def _vol_up(self, inter: discord.Interaction, _):
        new_vol = min(150, self.player.volume + 10)
        await self.player.set_volume(new_vol)
        await inter.response.defer()

    # stop
    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=1)
    async def _stop(self, inter: discord.Interaction, _):
        await self.player.stop()
        await self.player.disconnect()
        await inter.response.defer()


# ───────────────────────  slash commands  ─────────────────
@bot.tree.command(name="play", description="Play a track or playlist")
@app_commands.describe(search="song / playlist link or search term")
async def slash_play(inter: discord.Interaction, search: str):
    await inter.response.defer(thinking=True)

    try:
        player = await Music.ensure_player(inter)
    except RuntimeError as err:
        return await inter.followup.send(f"❌ {err}")

    result = await wavelink.Playable.search(search)

    # ── Nothing found
    if not result:
        return await inter.followup.send("❌ No results.")

    # ── Result is a Playlist object
    if isinstance(result, wavelink.Playlist):
        playlist: wavelink.Playlist = result
        tracks = playlist.tracks

        # If nothing is playing, start with the first track
        if not player.playing:
            first, *rest = tracks
            await Music.play(player, first)
            if rest:
                await Music.bulk_enqueue(player, rest)
            msg = f"▶️ Playing **{first.title}** from playlist **{playlist.name}** " \
                  f"(`{len(tracks)}` tracks)"
        else:
            await Music.bulk_enqueue(player, tracks)
            msg = f"➕ Queued playlist **{playlist.name}** (`{len(tracks)}` tracks)"

        card = PlayCard(player)
        return await inter.followup.send(msg, view=card)

    # ── Result is a normal search list (tracks[0] is first playable)
    track: wavelink.Playable = result[0]
    if player.playing:
        player.queue.put(track)
        await inter.followup.send(f"➕ Queued **{track.title}**")
    else:
        await Music.play(player, track)
        card = PlayCard(player)
        await inter.followup.send(f"▶️ Now playing **{track.title}**", view=card)


# quick wrappers (optional – they map to the card buttons)
@bot.tree.command(name="pause", description="Pause / resume")
async def slash_pause(inter: discord.Interaction):
    player = await Music.ensure_player(inter)
    await inter.response.defer()
    if player.paused:
        await player.pause(False)
    else:
        await player.pause(True)


@bot.tree.command(name="skip", description="Skip track")
async def slash_skip(inter: discord.Interaction):
    player = await Music.ensure_player(inter)
    await inter.response.defer()
    await Music.next_track(player)


@bot.tree.command(name="stop", description="Stop & disconnect")
async def slash_stop(inter: discord.Interaction):
    player = await Music.ensure_player(inter)
    await inter.response.defer()
    await player.stop()
    await player.disconnect()


# ───────────────────────  autoplay / loop  ────────────────
@bot.listen("wavelink_track_end")
async def _on_track_end(player: wavelink.Player, *_):
    # loop?
    if getattr(player, "loop", False):
        await player.play(player.current)
        return

    # next in queue
    if not player.queue.is_empty:
        next_up = player.queue.get()
        player.history.append(player.current)
        await player.play(next_up)
    else:
        # nothing left – disconnect after 5 min idle
        await asyncio.sleep(300)
        if not player.playing:
            await player.disconnect()


# ───────────────────────  message filter  ─────────────────
def is_allowed(msg: discord.Message) -> bool:
    return msg.attachments or any(w.startswith(("http://", "https://"))
                                  for w in msg.content.split())


@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot or msg.channel.id not in CHANNEL_IDS:
        return
    if not is_allowed(msg):
        await msg.delete()
        warn = await msg.channel.send(
            f"🚫 <@{msg.author.id}>, text-only messages aren’t allowed. "
            "Include a link or file."
        )
        await warn.delete(delay=8)


# ───────────────────────  keep-alive flask  ───────────────
app = Flask(__name__)
client_ref = purge_fn = None


@app.route("/")
def home():
    return "Bot is alive!"


@app.route("/purge/<int:cid>")
def purge_ep(cid: int):
    fut = asyncio.run_coroutine_threadsafe(purge_fn(cid), client_ref.loop)
    return f"Purge started for {cid}", 200


def _flask():
    app.run(host="0.0.0.0", port=8080)


def keep_alive(client, purge_coroutine):
    global client_ref, purge_fn
    client_ref, purge_fn = client, purge_coroutine
    threading.Thread(target=_flask, daemon=True).start()


# ───────────────────────  start  ──────────────────────────
keep_alive(bot, lambda *_: None)  # purge endpoint kept for parity
log("Starting bot…")
bot.run(TOKEN)
