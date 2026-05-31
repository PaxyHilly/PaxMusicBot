import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
from datetime import datetime, timezone
import asyncio
import yt_dlp as youtube_dl
import time
import os
from flask import Flask
import threading

# ========= FLASK KEEP_ALIVE FOR RENDER =========
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

keep_alive()

# ========= DISCORD BOT SETUP =========
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN environment variable not set!")
    exit(1)

OWNER_ID = 1403449777978609674

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Music data
queues = {}
now_playing_messages = {}
sticky_tasks = {}
button_views = {}
current_provider = {}

# ========= PROVIDER CONFIGURATIONS =========
PROVIDERS = {
    'youtube': {
        'name': 'YouTube',
        'emoji': '▶️',
        'search_prefix': '',
        'extractor': 'youtube',
        'ytdl_options': {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0',
            'user_agent': 'Mozilla/5.0 (Android; Mobile; rv:109.0) Gecko/109.0 Firefox/109.0',
            'extractor_args': {'youtube': {'player_client': ['android', 'ios'], 'skip': ['hls']}},
        }
    },
    'soundcloud': {
        'name': 'SoundCloud',
        'emoji': '🎧',
        'search_prefix': 'scsearch:',
        'extractor': 'soundcloud',
        'ytdl_options': {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'scsearch',
            'source_address': '0.0.0.0',
        }
    },
    'bandcamp': {
        'name': 'Bandcamp',
        'emoji': '🏪',
        'search_prefix': 'bcsearch:',
        'extractor': 'bandcamp',
        'ytdl_options': {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'bcsearch',
            'source_address': '0.0.0.0',
        }
    },
    'deezer': {
        'name': 'Deezer',
        'emoji': '🎜',
        'search_prefix': 'dzsearch:',
        'extractor': 'deezer',
        'ytdl_options': {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'dzsearch',
            'source_address': '0.0.0.0',
        }
    },
    'tidal': {
        'name': 'Tidal',
        'emoji': '🌊',
        'search_prefix': 'tidalsearch:',
        'extractor': 'tidal',
        'ytdl_options': {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'tidalsearch',
            'source_address': '0.0.0.0',
        }
    },
    'audius': {
        'name': 'Audius',
        'emoji': '🎵',
        'search_prefix': 'audiussearch:',
        'extractor': 'audius',
        'ytdl_options': {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'audiussearch',
            'source_address': '0.0.0.0',
        }
    }
}

# Default ytdl options (YouTube)
default_ytdl_options = PROVIDERS['youtube']['ytdl_options'].copy()
ytdl = youtube_dl.YoutubeDL(default_ytdl_options)

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

class MusicQueue:
    def __init__(self):
        self.queue = []
        self.current = None
        self.start_time = None
        self.is_playing = False

def is_owner(interaction):
    return interaction.user.id == OWNER_ID

def format_duration(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"

def format_duration_long(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"

def format_progress_bar(elapsed, total, width=15):
    if total <= 0:
        return "░" * width
    progress = int((elapsed / total) * width)
    progress = min(progress, width)
    return "█" * progress + "░" * (width - progress)

def format_number(num):
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}K"
    return str(num)

# ========= PROVIDER BUTTONS =========
class ProviderButtons(View):
    def __init__(self, guild_id):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        
        for key, provider in PROVIDERS.items():
            button = Button(
                label=provider['name'],
                emoji=provider['emoji'],
                style=discord.ButtonStyle.secondary,
                custom_id=key
            )
            button.callback = self.create_callback(key, provider)
            self.add_item(button)
    
    def create_callback(self, key, provider):
        async def callback(interaction: discord.Interaction):
            if not is_owner(interaction):
                await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
                return
            
            current_provider[interaction.guild.id] = key
            global ytdl
            ytdl = youtube_dl.YoutubeDL(provider['ytdl_options'])
            
            embed = discord.Embed(
                title=f"{provider['emoji']} Provider Changed",
                description=f"Now searching on **{provider['name']}**\n\nUse `/play <song>` to search!",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=None)
        return callback

# ========= MUSIC CONTROLS =========
class MusicControls(View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
    
    @discord.ui.button(label="⏸️ Pause", style=discord.ButtonStyle.primary)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        if not is_owner(interaction):
            await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
            return
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            button.label = "▶️ Resume"
            button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("❌ Nothing playing!", ephemeral=True)
    
    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        if not is_owner(interaction):
            await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
            return
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
            await interaction.response.send_message("⏭️ Skipped!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Nothing playing!", ephemeral=True)
    
    @discord.ui.button(label="🛑 Stop", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: Button):
        if not is_owner(interaction):
            await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
            return
        guild_id = self.guild_id
        if guild_id in queues:
            queues[guild_id].queue.clear()
            queues[guild_id].current = None
        if guild_id in sticky_tasks and sticky_tasks[guild_id]:
            sticky_tasks[guild_id] = False
        if guild_id in now_playing_messages:
            try:
                await now_playing_messages[guild_id].delete()
            except:
                pass
            del now_playing_messages[guild_id]
        if interaction.guild.voice_client:
            interaction.guild.voice_client.stop()
            await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("🛑 Stopped!", ephemeral=True)

def play_song(guild, song):
    def after_play(error):
        if error:
            print(f"Playback error: {error}")
        asyncio.run_coroutine_threadsafe(play_next_song(guild), bot.loop)
    
    try:
        with ytdl as ydl:
            info = ydl.extract_info(song['url'], download=False)
            if 'entries' in info:
                info = info['entries'][0]
            audio_url = info['url']
        
        player = discord.FFmpegPCMAudio(audio_url, **ffmpeg_options)
        player = discord.PCMVolumeTransformer(player, volume=0.5)
        
        guild.voice_client.play(player, after=after_play)
        return True
    except Exception as e:
        print(f"Play error: {e}")
        return False

async def update_now_playing(guild_id):
    while guild_id in sticky_tasks and sticky_tasks[guild_id]:
        try:
            if guild_id not in queues or not queues[guild_id].current:
                await asyncio.sleep(1)
                continue
            
            queue_obj = queues[guild_id]
            song = queue_obj.current
            
            if queue_obj.start_time:
                elapsed = time.time() - queue_obj.start_time
            else:
                elapsed = 0
            
            total = song.get('duration', 0)
            if elapsed > total and total > 0:
                elapsed = total
            
            progress_bar = format_progress_bar(elapsed, total, 15)
            elapsed_str = format_duration(elapsed)
            total_str = format_duration(total)
            
            provider_info = PROVIDERS.get(song.get('provider', 'youtube'), PROVIDERS['youtube'])
            
            content = (
                f"{provider_info['emoji']} **Now Playing:** {song['title']}\n"
                f"`{elapsed_str}` {progress_bar} `{total_str}`\n"
                f"📢 Requested by: {song['requester_name']}\n"
                f"🎵 Provider: {provider_info['name']}\n"
                f"─── ･ ｡ﾟ☆: *.☽ .* :☆ﾟ. ───"
            )
            
            if guild_id in now_playing_messages:
                try:
                    view = button_views.get(guild_id, MusicControls(guild_id))
                    await now_playing_messages[guild_id].edit(content=content, view=view)
                except:
                    pass
            
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Update error: {e}")
            await asyncio.sleep(1)
    
    if guild_id in now_playing_messages:
        try:
            await now_playing_messages[guild_id].delete()
        except:
            pass
        del now_playing_messages[guild_id]

async def keep_at_bottom(guild_id, channel_id):
    while guild_id in sticky_tasks and sticky_tasks[guild_id]:
        try:
            guild = bot.get_guild(guild_id)
            if not guild:
                break
            channel = guild.get_channel(channel_id)
            if not channel:
                break
            
            if guild_id not in now_playing_messages:
                await asyncio.sleep(1)
                continue
            
            np_msg = now_playing_messages[guild_id]
            
            async for msg in channel.history(limit=5):
                if msg.created_at > np_msg.created_at and msg.id != np_msg.id:
                    try:
                        await np_msg.delete()
                    except:
                        pass
                    
                    if guild_id in queues and queues[guild_id].current:
                        song = queues[guild_id].current
                        queue_obj = queues[guild_id]
                        
                        if queue_obj.start_time:
                            elapsed = time.time() - queue_obj.start_time
                        else:
                            elapsed = 0
                        
                        total = song.get('duration', 0)
                        if elapsed > total and total > 0:
                            elapsed = total
                        
                        progress_bar = format_progress_bar(elapsed, total, 15)
                        elapsed_str = format_duration(elapsed)
                        total_str = format_duration(total)
                        
                        provider_info = PROVIDERS.get(song.get('provider', 'youtube'), PROVIDERS['youtube'])
                        
                        content = (
                            f"{provider_info['emoji']} **Now Playing:** {song['title']}\n"
                            f"`{elapsed_str}` {progress_bar} `{total_str}`\n"
                            f"📢 Requested by: {song['requester_name']}\n"
                            f"🎵 Provider: {provider_info['name']}\n"
                            f"─── ･ ｡ﾟ☆: *.☽ .* :☆ﾟ. ───"
                        )
                        
                        view = MusicControls(guild_id)
                        button_views[guild_id] = view
                        new_msg = await channel.send(content, view=view)
                        now_playing_messages[guild_id] = new_msg
                    break
            
            await asyncio.sleep(2)
            
        except Exception as e:
            print(f"Sticky error: {e}")
            await asyncio.sleep(2)

async def play_next_song(guild):
    if guild.id not in queues or not queues[guild.id].queue:
        if guild.id in sticky_tasks:
            sticky_tasks[guild.id] = False
        return
    
    queue_obj = queues[guild.id]
    song = queue_obj.queue.pop(0)
    queue_obj.current = song
    queue_obj.start_time = time.time()
    
    if guild.id in now_playing_messages:
        try:
            await now_playing_messages[guild.id].delete()
        except:
            pass
        del now_playing_messages[guild.id]
    
    provider_info = PROVIDERS.get(song.get('provider', 'youtube'), PROVIDERS['youtube'])
    
    content = (
        f"{provider_info['emoji']} **Now Playing:** {song['title']}\n"
        f"`0:00` {'░' * 15} `{format_duration(song.get('duration', 0))}`\n"
        f"📢 Requested by: {song['requester_name']}\n"
        f"🎵 Provider: {provider_info['name']}\n"
        f"─── ･ ｡ﾟ☆: *.☽ .* :☆ﾟ. ───"
    )
    
    channel = bot.get_channel(song.get('channel_id'))
    if channel:
        view = MusicControls(guild.id)
        button_views[guild.id] = view
        msg = await channel.send(content, view=view)
        now_playing_messages[guild.id] = msg
        
        sticky_tasks[guild.id] = True
        asyncio.create_task(keep_at_bottom(guild.id, channel.id))
        asyncio.create_task(update_now_playing(guild.id))
    
    await asyncio.to_thread(play_song, guild, song)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    print(f"✅ Bot is in {len(bot.guilds)} servers")
    print("✅ 6 Music Providers Available: YouTube, SoundCloud, Bandcamp, Deezer, Tidal, Audius")
    print("✅ Use /provider to switch providers")

# ========= SLASH COMMANDS =========
@bot.tree.command(name="play", description="Play a song from current provider")
@app_commands.describe(query="Song name or URL")
async def play(interaction: discord.Interaction, query: str):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    if not interaction.user.voice:
        await interaction.followup.send("❌ Join a voice channel first!")
        return
    
    voice_channel = interaction.user.voice.channel
    
    if not interaction.guild.voice_client:
        await voice_channel.connect()
    elif interaction.guild.voice_client.channel != voice_channel:
        await interaction.guild.voice_client.move_to(voice_channel)
    
    provider_key = current_provider.get(interaction.guild.id, 'youtube')
    provider = PROVIDERS[provider_key]
    
    await interaction.followup.send(f"🔍 Searching {provider['emoji']} **{provider['name']}** for `{query}`...")
    
    try:
        def get_song_info():
            with ytdl as ydl:
                search_prefix = provider['search_prefix']
                search_query = f"{search_prefix}{query}" if search_prefix else query
                info = ydl.extract_info(search_query, download=False)
                if info and 'entries' in info and info['entries']:
                    return info['entries'][0]
                return None
        
        info = await asyncio.to_thread(get_song_info)
        
        if not info:
            await interaction.followup.send(f"❌ Could not find that song on {provider['name']}!")
            return
        
        song = {
            'title': info.get('title', 'Unknown')[:60],
            'url': info.get('webpage_url', info.get('url')),
            'duration': info.get('duration', 0),
            'requester_name': interaction.user.display_name,
            'requester_id': interaction.user.id,
            'channel_id': interaction.channel_id,
            'uploader': info.get('uploader', info.get('artist', 'Unknown')),
            'view_count': info.get('view_count', 0),
            'provider': provider_key,
        }
        
        if interaction.guild.id not in queues:
            queues[interaction.guild.id] = MusicQueue()
        
        queues[interaction.guild.id].queue.append(song)
        
        if not interaction.guild.voice_client.is_playing():
            await play_next_song(interaction.guild)
            await interaction.followup.send(f"{provider['emoji']} Now playing: **{song['title']}** from **{provider['name']}**")
        else:
            position = len(queues[interaction.guild.id].queue)
            await interaction.followup.send(f"{provider['emoji']} Added to queue: **{song['title']}** (Position {position}) on **{provider['name']}**")
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)[:100]}")

@bot.tree.command(name="provider", description="Change the music provider")
async def provider(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    
    current = current_provider.get(interaction.guild.id, 'youtube')
    current_name = PROVIDERS[current]['name']
    current_emoji = PROVIDERS[current]['emoji']
    
    embed = discord.Embed(
        title="🎵 Music Provider Selector",
        description=f"**Current:** {current_emoji} {current_name}\n\nClick a button below to change the music source:",
        color=discord.Color.blue()
    )
    
    provider_list = "\n".join([f"{p['emoji']} **{p['name']}**" for p in PROVIDERS.values()])
    embed.add_field(name="📋 Available Providers", value=provider_list, inline=False)
    embed.set_footer(text="YouTube works best | Some providers have limited catalogs")
    
    await interaction.response.send_message(embed=embed, view=ProviderButtons(interaction.guild.id))

@bot.tree.command(name="skip", description="Skip current song")
async def skip(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ Skipped!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Nothing playing!", ephemeral=True)

@bot.tree.command(name="stop", description="Stop music and clear queue")
async def stop(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    guild_id = interaction.guild.id
    if guild_id in queues:
        queues[guild_id].queue.clear()
        queues[guild_id].current = None
    if guild_id in sticky_tasks:
        sticky_tasks[guild_id] = False
    if guild_id in now_playing_messages:
        try:
            await now_playing_messages[guild_id].delete()
        except:
            pass
        del now_playing_messages[guild_id]
    if interaction.guild.voice_client:
        interaction.guild.voice_client.stop()
        await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("🛑 Stopped and cleared queue!")

@bot.tree.command(name="pause", description="Pause current song")
async def pause(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.pause()
        await interaction.response.send_message("⏸️ Paused!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Nothing playing!", ephemeral=True)

@bot.tree.command(name="resume", description="Resume paused song")
async def resume(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
        interaction.guild.voice_client.resume()
        await interaction.response.send_message("▶️ Resumed!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Nothing paused!", ephemeral=True)

@bot.tree.command(name="servers", description="Show which servers the bot is in")
async def list_servers(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    
    embed = discord.Embed(title="🌐 Bot Server Status", color=discord.Color.green())
    
    for guild in bot.guilds:
        is_playing = "🎵 Playing" if guild.voice_client and guild.voice_client.is_playing() else "⏹️ Idle"
        queue_size = len(queues.get(guild.id, MusicQueue()).queue) if guild.id in queues else 0
        provider = current_provider.get(guild.id, 'youtube')
        provider_name = PROVIDERS[provider]['name']
        embed.add_field(
            name=guild.name,
            value=f"ID: `{guild.id}`\nStatus: {is_playing}\nQueue: {queue_size} songs\nProvider: {provider_name}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="songinfo", description="Get info about current or searched song")
@app_commands.describe(query="Song name (leave empty for current song)")
async def songinfo(interaction: discord.Interaction, query: str = None):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    if not query:
        if interaction.guild.id not in queues or not queues[interaction.guild.id].current:
            await interaction.followup.send("❌ No song playing! Use `/songinfo <song name>` to search.")
            return
        song = queues[interaction.guild.id].current
        provider_info = PROVIDERS.get(song.get('provider', 'youtube'), PROVIDERS['youtube'])
        embed = discord.Embed(title=f"{provider_info['emoji']} Currently Playing", color=discord.Color.purple())
        embed.add_field(name="Title", value=song['title'], inline=False)
        embed.add_field(name="Provider", value=provider_info['name'], inline=True)
        embed.add_field(name="Uploader", value=song.get('uploader', 'Unknown'), inline=True)
        embed.add_field(name="Duration", value=format_duration_long(song.get('duration', 0)), inline=True)
        embed.add_field(name="Requested by", value=song['requester_name'], inline=True)
        await interaction.followup.send(embed=embed)
    else:
        provider_key = current_provider.get(interaction.guild.id, 'youtube')
        provider = PROVIDERS[provider_key]
        await interaction.followup.send(f"🔍 Searching {provider['emoji']} **{provider['name']}** for `{query}`...")
        
        def fetch_info():
            try:
                with ytdl as ydl:
                    search_prefix = provider['search_prefix']
                    search_query = f"{search_prefix}{query}" if search_prefix else query
                    data = ydl.extract_info(search_query, download=False)
                    if data and 'entries' in data and data['entries']:
                        return data['entries'][0]
                    return None
            except:
                return None
        
        info = await asyncio.to_thread(fetch_info)
        if not info:
            await interaction.followup.send(f"❌ Could not find that song on {provider['name']}!")
            return
        embed = discord.Embed(title=f"{provider['emoji']} {info.get('title', 'Unknown')}", url=info.get('webpage_url'), color=discord.Color.purple())
        embed.add_field(name="Provider", value=provider['name'], inline=True)
        embed.add_field(name="Uploader/Artist", value=info.get('uploader', info.get('artist', 'Unknown')), inline=True)
        embed.add_field(name="Duration", value=format_duration_long(info.get('duration', 0)), inline=True)
        embed.add_field(name="Views/Plays", value=format_number(info.get('view_count', 0)), inline=True)
        thumbnail = info.get('thumbnail')
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        await interaction.followup.send(embed=embed)

# ========= OTHER COMMANDS =========
@bot.tree.command(name="dm", description="Send a DM")
@app_commands.describe(message="What to say", user="User mention", user_id="User ID")
async def dm(interaction, message: str, user: discord.User = None, user_id: str = None):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    target = user
    if not target and user_id:
        try:
            target = await bot.fetch_user(int(user_id))
        except:
            await interaction.followup.send("❌ Invalid user ID", ephemeral=True)
            return
    if not target:
        await interaction.followup.send("❌ Provide a user mention or ID", ephemeral=True)
        return
    try:
        await target.send(message)
        await interaction.followup.send(f"✅ Sent to {target.name}", ephemeral=True)
    except:
        await interaction.followup.send(f"❌ Can't DM {target.name}", ephemeral=True)

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms")

@bot.tree.command(name="echo", description="Repeat your message")
@app_commands.describe(text="Text to echo")
async def echo(interaction, text: str):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    await interaction.response.send_message(f"📢 {text}")

@bot.tree.command(name="userinfo", description="Get user info")
@app_commands.describe(user="User to lookup")
async def userinfo(interaction, user: discord.User):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    embed = discord.Embed(title=f"📋 {user.name}", color=0x00ff00)
    embed.add_field(name="ID", value=user.id)
    embed.add_field(name="Created", value=user.created_at.strftime("%Y-%m-%d"))
    embed.set_thumbnail(url=user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="slap", description="Slap someone")
@app_commands.describe(target="Who to slap")
async def slap(interaction, target: discord.User):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    await interaction.response.send_message(f"🎣 {interaction.user.display_name} slaps {target.display_name} with a giant fish!")

@bot.tree.command(name="osint", description="Basic OSINT on a Discord user")
@app_commands.describe(user="User to investigate")
async def osint(interaction, user: discord.User):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    await interaction.response.defer()
    now = datetime.now(timezone.utc)
    age = now - user.created_at
    years = age.days // 365
    days = age.days % 365
    embed = discord.Embed(title=f"🕵️ OSINT: {user.name}", color=discord.Color.blue())
    embed.add_field(name="ID", value=f"`{user.id}`")
    embed.add_field(name="Created", value=user.created_at.strftime("%Y-%m-%d"))
    embed.add_field(name="Age", value=f"~{years}y {days}d")
    embed.set_thumbnail(url=user.display_avatar.url)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="deeposint", description="Advanced OSINT - username/email generation")
@app_commands.describe(user="User to investigate")
async def deeposint(interaction, user: discord.User):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
        return
    await interaction.response.defer()
    base = user.name.lower().replace(" ", "")
    usernames = list(set([base, base + "123", base + "_", base + str(user.discriminator) if user.discriminator != "0" else base]))
    emails = []
    for u in usernames[:3]:
        for domain in ["gmail.com", "yahoo.com", "outlook.com"]:
            emails.append(f"{u}@{domain}")
    embed = discord.Embed(title=f"🔍 Deep OSINT: {user.name}", color=discord.Color.dark_red())
    embed.add_field(name="Potential Usernames", value="\n".join([f"• `{u}`" for u in usernames[:5]]), inline=False)
    embed.add_field(name="Possible Emails", value="\n".join([f"• `{e}`" for e in emails[:5]]), inline=False)
    embed.add_field(name="Tools", value="• https://whatsmyname.app\n• Sherlock: `sherlock {base}`", inline=False)
    await interaction.followup.send(embed=embed)

bot.run(TOKEN)
