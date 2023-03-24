import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp as youtube_dl
from youtube_search import YoutubeSearch
import asyncio
from discord import FFmpegPCMAudio
import collections 

load_dotenv()
TOKEN = os.getenv("DISCORDBOT")

intents = discord.Intents.default()
intents.typing = False
intents.presences = False
intents.members = True
intents.message_content = True


ffmpeg_options = {
    "options": "-vn",
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
}

ytdl_format_options = {
    "format": "bestaudio/best",
    "outtmpl": "downloads/%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }
    ],
}


bot = commands.Bot(command_prefix="!", intents=intents)
Song = collections.namedtuple("Song", "source title requester")
song_queue = collections.deque()


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream)
        )

        if "entries" in data:
            data = data["entries"][0]

        filename = data["url"] if stream else ytdl.prepare_filename(data)
        return cls(FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


youtube_dl.utils.bug_reports_message = lambda: ""
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class VoiceConnectionError(commands.CommandError):
    pass


class InvalidVoiceChannel(VoiceConnectionError):
    pass


async def ensure_voice(ctx):
    if ctx.voice_client is None:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            raise InvalidVoiceChannel("You are not connected to a voice channel.")

async def play_next_song(ctx):
    if song_queue:
        song = song_queue.popleft()
        ctx.voice_client.play(song.source, after=lambda _: bot.loop.call_soon_threadsafe(play_next_song_if_not_playing, ctx))
        await ctx.send(f"Now playing: {song.title}, requested by {song.requester}")
    else:
        await ctx.voice_client.disconnect()


def play_next_song_if_not_playing(ctx):
    if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
        bot.loop.create_task(play_next_song(ctx))


@bot.command(name="play", help="Play a song from YouTube.")
async def play(ctx, *, search: str):
    try:
        await ensure_voice(ctx)

        async with ctx.typing():
            if not search.startswith("http"):
                results = YoutubeSearch(search, max_results=1).to_dict()
                url = f"https://www.youtube.com{results[0]['url_suffix']}"
            else:
                url = search

            player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
            song = Song(source=player, title=player.title, requester=ctx.author.name)
            song_queue.append(song)

            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                await play_next_song(ctx)
            else:
                await ctx.send(f"Added to queue: {song.title}, requested by {song.requester}")

    except Exception as e:
        await ctx.send(f"Error occurred: {str(e)}")


@bot.command(name="stop", help="Stop playing and disconnect from the voice channel.")
async def stop(ctx):
    if ctx.voice_client:
        song_queue.clear()
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.send("Stopped playing and cleared the queue.")
    else:
        await ctx.send("I am not currently connected to a voice channel.")


@bot.command(name="skip", help="Skip the current song and play the next one in the queue.")
async def skip(ctx):
    if ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Skipped the current song.")
    else:
        await ctx.send("There is no song currently playing.")

@bot.command(name="queue", help="Display the current queue of songs.")
async def display_queue(ctx):
    if song_queue:
        queue_text = "Current queue:\n"
        for i, song in enumerate(song_queue, start=1):
            queue_text += f"{i}. {song.title} (requested by {song.requester})\n"
        await ctx.send(queue_text)
    else:
        await ctx.send("The song queue is empty.")


@bot.event
async def on_ready():
    print(f"{bot.user.name} has connected to Discord!")

bot.run(TOKEN)
