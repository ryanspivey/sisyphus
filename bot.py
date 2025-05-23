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
            await player.queue.put(player.current, 0)
        await player.play(previous)

    @staticmethod
    async def announce_now_playing(
        player: wavelink.Player,
        interaction: discord.Interaction | None,
    ):
        """Post a fresh ‘Now playing…’ card, coping with expired tokens."""

        # which track is actually playing?
        track = player.current or (player.queue[0] if player.queue else None)
        if not track:
            return

        content = (
            f"▶️ **Now playing:** *{getattr(track, 'title', 'Unknown title')}*"
            f" — {getattr(track, 'author', 'Unknown artist')}"
        )
        view = PlayCard(player)

        # ── 1) we were invoked from a slash / button interaction ────────────
        if interaction is not None:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(content, view=view)
                else:
                    await interaction.response.send_message(content, view=view)
                return                              # posted successfully
            except discord.NotFound:
                # the token has expired – fall through to channel fallback
                pass

        # ── 2) fallback: first text-channel we can talk in ───────────────────
        text_ch = next(
            (
                ch
                for ch in player.guild.text_channels
                if ch.permissions_for(player.guild.me).send_messages
            ),
            None,
        )
        if text_ch:
            await text_ch.send(content, view=view)


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
        await Music.announce_now_playing(self.player, inter)
        await inter.response.defer()

    # previous
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.primary, row=0)
    async def _previous(self, inter: discord.Interaction, _):
        await Music.previous_track(self.player)
        await Music.announce_now_playing(self.player, inter)
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
    # acknowledge right away
    await inter.response.defer(thinking=True)

    # make sure we have a Player in the user’s VC
    try:
        player = await Music.ensure_player(inter)
    except RuntimeError as err:
        return await inter.followup.send(f"❌ {err}")

    # search via Lavalink / wavelink
    result = await wavelink.Playable.search(search)

    if not result:                         # nothing found at all
        return await inter.followup.send("❌ No results.")

    # ── PLAYLIST ───────────────────────────────────────────────
    if isinstance(result, wavelink.Playlist):
        playlist: wavelink.Playlist = result
        tracks = playlist.tracks

        if not player.playing:             # start playing immediately
            first, *rest = tracks
            await Music.play(player, first)
            if rest:
                await Music.bulk_enqueue(player, rest)
            await Music.announce_now_playing(player, inter)
        else:                              # just enqueue everything
            await Music.bulk_enqueue(player, tracks)
            await inter.followup.send(
                f"➕ Queued playlist **{playlist.name}** "
                f"(`{len(tracks)}` tracks)"
            )
        return                             # all done

    # ── SINGLE TRACK / SEARCH RESULT ──────────────────────────
    track: wavelink.Playable = result[0]

    if player.playing:                     # currently something on – queue it
        await player.queue.put(track)
        await inter.followup.send(f"➕ Queued **{track.title}**")
    else:                                  # nothing playing – start now
        await Music.play(player, track)
        await Music.announce_now_playing(player, inter)

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
    await Music.announce_now_playing(player, inter)


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
        await player.play(player.queue[0])
        await Music.announce_now_playing(player, None)
        return

    if len(player.queue) > 1:
        player.history.append(player.queue.pop(0))
        await player.play(player.queue[0])
        await Music.announce_now_playing(player, None)
    else:
        # queue empty – disconnect after 5 min idle
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
