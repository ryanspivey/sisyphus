import discord
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id != CHANNEL_ID:
        return

    has_attachment = bool(message.attachments)
    has_link = any(word.startswith(("http://", "https://")) for word in message.content.split())

    if not (has_attachment or has_link):
        await message.delete()

keep_alive()
client.run(TOKEN)
