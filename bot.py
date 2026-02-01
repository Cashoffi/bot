import glob
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, UTC

# === Настройки ===
ALLOWED_ROLES_FOR_RESTART = {1463540497535602833, 1463502977355743381}
GUILD_ID = 1463456630833287304

intents = discord.Intents.default()
intents.message_content = True
intents.presences = True
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)

# === Настройки для отслеживания активности ===
GAME_ROLE_MAP = {
    "Dota 2": 1463643348345819381,
    "Counter-Strike 2": 1463646558493868042,
}
ALLOWED_GAMES = set(GAME_ROLE_MAP.keys())
HISTORY_DAYS = 7
USERS_DATA_PATH = Path("users_data.json")

def load_users_data():
    if USERS_DATA_PATH.exists():
        try:
            return json.loads(USERS_DATA_PATH.read_text())
        except Exception:
            return {}
    return {}

def save_users_data(data):
    try:
        USERS_DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[users_data] Ошибка записи: {e}")

def prune_old_games(games):
    now = datetime.now(UTC).timestamp()
    return [entry for entry in games if now - entry[1] <= HISTORY_DAYS * 86400]

async def user_has_allowed_role(user: discord.abc.Snowflake, guild: discord.Guild | None = None) -> bool:
    member = user
    if not hasattr(member, 'roles'):
        if guild is None:
            return False
        try:
            member = await guild.fetch_member(user.id)
        except Exception:
            return False
    user_role_ids = {role.id for role in member.roles}
    return bool(user_role_ids & ALLOWED_ROLES_FOR_RESTART)

# === События ===
@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!')
    try:
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync()
        await bot.tree.sync(guild=guild)
        print(f'Слэш-команды синхронизированы для сервера {GUILD_ID}')
    except Exception as e:
        print(f'Ошибка синхронизации команд: {e}')
    try:
        restart_file = Path(__file__).parent / 'restart_info.json'
        if restart_file.exists():
            data = json.loads(restart_file.read_text())
            channel_id = int(data.get('channel_id')) if data.get('channel_id') else None
            text = data.get('text', 'Бот перезапустился.')
            if channel_id:
                channel = bot.get_channel(channel_id)
                if channel is None:
                    channel = await bot.fetch_channel(channel_id)
                await channel.send(text)
            try:
                restart_file.unlink()
            except Exception:
                pass
    except Exception:
        pass

@bot.event
async def on_message(message: discord.Message):
    if message.guild is None or message.author.bot:
        return
    data = load_users_data()
    uid = str(message.author.id)
    if uid not in data:
        data[uid] = {"messages": 0, "voice_seconds": 0, "games": [], "_voice_join_time": None}
    data[uid]["messages"] = data[uid].get("messages", 0) + 1
    save_users_data(data)
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if not member.guild or member.bot:
        return
    data = load_users_data()
    uid = str(member.id)
    if uid not in data:
        data[uid] = {"messages": 0, "voice_seconds": 0, "games": [], "_voice_join_time": None}
    if before.channel is None and after.channel is not None:
        data[uid]["_voice_join_time"] = int(discord.utils.utcnow().timestamp())
    elif before.channel is not None and after.channel is None:
        join_time = data[uid].pop("_voice_join_time", None)
        if join_time:
            now = int(discord.utils.utcnow().timestamp())
            data[uid]["voice_seconds"] = data[uid].get("voice_seconds", 0) + (now - join_time)
    save_users_data(data)

@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    uid = str(after.id)
    now_ts = datetime.now(UTC).timestamp()
    data = load_users_data()
    if uid not in data:
        data[uid] = {"messages": 0, "voice_seconds": 0, "games": [], "_voice_join_time": None}
    data[uid]["games"] = prune_old_games(data[uid].get("games", []))
    if after.activities:
        for activity in after.activities:
            if isinstance(activity, discord.Game):
                data[uid]["games"].append([activity.name, now_ts])
    save_users_data(data)

# === Команды ===
@bot.tree.command(name="sync", description="Принудительная синхронизация команд (только для админов)")
async def sync_command(interaction: discord.Interaction):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для этой команды!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync()
        await bot.tree.sync(guild=guild)
        await interaction.followup.send("Команды успешно синхронизированы!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Ошибка синхронизации: {e}", ephemeral=True)

@bot.tree.command(name="migrate", description="Миграция старых файлов статистики в users_data.json (только для админов)")
async def migrate_command(interaction: discord.Interaction):
    allowed = False
    if hasattr(interaction.user, 'roles'):
        allowed = any(role.id in ALLOWED_ROLES_FOR_RESTART for role in interaction.user.roles)
    if not allowed:
        await interaction.response.send_message("У вас нет прав для этой команды!", ephemeral=True)
        return
    users_data = {}
    for path in glob.glob("userstats_*.json"):
        try:
            uid = path.split("_")[1].split(".")[0]
            with open(path, "r", encoding="utf-8") as f:
                stats = json.load(f)
            users_data.setdefault(uid, {"messages": 0, "voice_seconds": 0, "games": [], "_voice_join_time": None})
            users_data[uid]["messages"] = stats.get("messages", 0)
            users_data[uid]["voice_seconds"] = stats.get("voice_seconds", 0)
        except Exception as e:
            print(f"Ошибка миграции {path}: {e}")
    for path in glob.glob("gamehistory_*.json"):
        try:
            uid = path.split("_")[1].split(".")[0]
            with open(path, "r", encoding="utf-8") as f:
                games = json.load(f)
            users_data.setdefault(uid, {"messages": 0, "voice_seconds": 0, "games": [], "_voice_join_time": None})
            users_data[uid]["games"] = games
        except Exception as e:
            print(f"Ошибка миграции {path}: {e}")
    try:
        with open("users_data.json", "w", encoding="utf-8") as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
        await interaction.response.send_message("Миграция завершена успешно! users_data.json создан.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Ошибка сохранения users_data.json: {e}", ephemeral=True)

@bot.tree.command(name="activity", description="Активность пользователей за неделю (только для админов)")
async def activity(interaction: discord.Interaction):
    allowed = False
    if hasattr(interaction.user, 'roles'):
        allowed = any(role.id in ALLOWED_ROLES_FOR_RESTART for role in interaction.user.roles)
    if not allowed:
        await interaction.response.send_message("У вас нет прав для этой команды!", ephemeral=True)
        return
    data = load_users_data()
    lines = []
    for uid, info in data.items():
        if not info:
            continue
        games = prune_old_games(info.get("games", []))
        game_counter = {}
        for game, ts in games:
            game_counter[game] = game_counter.get(game, 0) + 1
        user = None
        try:
            user = await interaction.guild.fetch_member(int(uid))
        except Exception:
            pass
        uname = user.display_name if user else f"ID {uid}"
        msg_count = info.get("messages", 0)
        voice_sec = info.get("voice_seconds", 0)
        hours = round(voice_sec / 3600, 2)
        games_str = ", ".join(f"{g}: {c}" for g, c in game_counter.items()) if game_counter else "-"
        lines.append(f"{uname}: сообщений: {msg_count}, часов в войсе: {hours}, игры: {games_str}")
    if not lines:
        lines = ["Нет данных за неделю."]
    await interaction.response.send_message("Активность за неделю:\n" + "\n".join(lines), ephemeral=True)

@bot.tree.command(name="clear", description="Очистить сообщения в чате", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(amount="Сколько сообщений удалить (по умолчанию 5)")
async def clear(interaction: discord.Interaction, amount: int = 5):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав на использование этой команды!", ephemeral=True)
        return
    await interaction.response.send_message(f"Удаляю {amount} сообщений...", ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Удалено сообщений: {len(deleted)}", ephemeral=True)

@bot.tree.command(name="restart", description="Перезапустить бота (только для определённых ролей)", guild=discord.Object(id=GUILD_ID))
async def restart(interaction: discord.Interaction):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для перезапуска бота!", ephemeral=True)
        return
    await interaction.response.send_message("Бот перезапускается...", ephemeral=True)
    try:
        restart_file = Path(__file__).parent / 'restart_info.json'
        restart_info = {'channel_id': interaction.channel_id, 'text': f'Бот был перезапущен пользователем {interaction.user}.'}
        restart_file.write_text(json.dumps(restart_info))
    except Exception:
        pass
    import subprocess, sys
    subprocess.Popen([sys.executable] + sys.argv)
    await bot.close()

@bot.tree.command(name="ping", description="Пинг бота", guild=discord.Object(id=GUILD_ID))
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong!", ephemeral=False)

@bot.tree.command(name="userinfo", description="Информация о пользователе", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Пользователь (по умолчанию вы)")
async def userinfo(interaction: discord.Interaction, member: discord.Member | None = None):
    if member is None:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None and interaction.guild:
            member = await interaction.guild.fetch_member(interaction.user.id)
    if member is None:
        await interaction.response.send_message("Не удалось получить информацию о пользователе.", ephemeral=True)
        return
    joined = member.joined_at.strftime('%Y-%m-%d %H:%M:%S') if member.joined_at else 'N/A'
    data = load_users_data()
    uid = str(member.id)
    if uid in data:
        msg_count = data[uid].get("messages", 0)
        voice_seconds = data[uid].get("voice_seconds", 0)
    else:
        msg_count = 0
        voice_seconds = 0
    hours = round(voice_seconds / 3600, 2)
    await interaction.response.send_message(
        f"Пользователь: {member}\nПрисоединился: {joined}\nСообщений: {msg_count}\nЧасов в голосе: {hours}",
        ephemeral=False
    )

@bot.tree.command(name="say", description="Бот отправит сообщение от своего имени", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(text="Текст для отправки")
async def say(interaction: discord.Interaction, text: str):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для использования этой команды.", ephemeral=True)
        return
    await interaction.response.send_message("Сообщение отправлено.", ephemeral=True)
    await interaction.channel.send(f"```\n{text}\n```")

last_top_call = {}
last_voice_top_call = {}

@bot.tree.command(name="top", description="Топ пользователей по количеству сообщений", guild=discord.Object(id=GUILD_ID))
async def top(interaction: discord.Interaction):
    now = datetime.now(UTC)
    user_id = interaction.user.id
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        if user_id in last_top_call and now - last_top_call[user_id] < timedelta(minutes=5):
            await interaction.response.send_message("Эту команду можно использовать раз в 5 минут.", ephemeral=True)
            return
        last_top_call[user_id] = now
    data = load_users_data()
    stats = []
    for uid, info in data.items():
        stats.append((int(uid), info.get("messages", 0)))
    stats.sort(key=lambda x: x[1], reverse=True)
    lines = []
    for i, (user_id_stat, count) in enumerate(stats[:10], 1):
        user = interaction.guild.get_member(user_id_stat)
        if not user:
            try:
                user = await interaction.guild.fetch_member(user_id_stat)
            except Exception:
                user = None
        if user:
            name = user.display_name
        else:
            name = f"ID {user_id_stat}"
        lines.append(f"{i}. {name}: {count} сообщений")
    if not lines:
        lines = ["Нет данных."]
    await interaction.response.send_message("Топ по сообщениям:\n" + "\n".join(lines), ephemeral=False)

@bot.tree.command(name="voice_top", description="Топ пользователей по времени в голосовых каналах", guild=discord.Object(id=GUILD_ID))
async def voice_top(interaction: discord.Interaction):
    now = datetime.now(UTC)
    user_id = interaction.user.id
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        if user_id in last_voice_top_call and now - last_voice_top_call[user_id] < timedelta(minutes=5):
            await interaction.response.send_message("Эту команду можно использовать раз в 5 минут.", ephemeral=True)
            return
        last_voice_top_call[user_id] = now
    data = load_users_data()
    stats = []
    for uid, info in data.items():
        stats.append((int(uid), info.get("voice_seconds", 0)))
    stats.sort(key=lambda x: x[1], reverse=True)
    lines = []
    for i, (user_id_stat, seconds) in enumerate(stats[:10], 1):
        user = interaction.guild.get_member(user_id_stat)
        if not user:
            try:
                user = await interaction.guild.fetch_member(user_id_stat)
            except Exception:
                user = None
        if user:
            name = user.display_name
        else:
            name = f"ID {user_id_stat}"
        hours = round(seconds / 3600, 2)
        lines.append(f"{i}. {name}: {hours} ч.")
    if not lines:
        lines = ["Нет данных."]
    await interaction.response.send_message("Топ по времени в голосе:\n" + "\n".join(lines), ephemeral=False)

@bot.tree.command(name="myrank", description="Ваше место в топе по сообщениям", guild=discord.Object(id=GUILD_ID))
async def myrank(interaction: discord.Interaction):
    data = load_users_data()
    stats = []
    for uid, info in data.items():
        stats.append((int(uid), info.get("messages", 0)))
    stats.sort(key=lambda x: x[1], reverse=True)
    user_id = interaction.user.id
    rank = next((i+1 for i, (uid, _) in enumerate(stats) if uid == user_id), None)
    msg_count = next((count for uid, count in stats if uid == user_id), 0)
    if rank:
        await interaction.response.send_message(f"Ваше место в топе: {rank}\nСообщений: {msg_count}", ephemeral=True)
    else:
        await interaction.response.send_message("Вы пока не в топе по сообщениям.", ephemeral=True)

@bot.tree.command(name="warn", description="Выдать предупреждение пользователю", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Пользователь для предупреждения", reason="Причина предупреждения")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для выдачи предупреждений!", ephemeral=True)
        return
    warns_path = Path(f"warns_{member.id}.json")
    warns = []
    if warns_path.exists():
        try:
            warns = json.loads(warns_path.read_text())
        except Exception:
            pass
    warns.append({"by": interaction.user.id, "reason": reason})
    warns_path.write_text(json.dumps(warns, ensure_ascii=False))
    await interaction.response.send_message(f"Пользователь {member.mention} получил предупреждение. Причина: {reason}", ephemeral=False)
    if len(warns) == 3:
        mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not mute_role:
            mute_role = await interaction.guild.create_role(name="Muted", reason="Автоматический мут за 3 предупреждения")
            for channel in interaction.guild.text_channels:
                if channel.id != 1463825318249889889:
                    await channel.set_permissions(mute_role, send_messages=False)
                else:
                    await channel.set_permissions(mute_role, send_messages=True)
        await member.add_roles(mute_role, reason="3 предупреждения — мут на 1 час")
        await interaction.followup.send(f"{member.mention} получил мут на 1 час и может писать только в <#1463825318249889889>", ephemeral=False)
        import asyncio
        async def unmute_later():
            await asyncio.sleep(3600)
            await member.remove_roles(mute_role, reason="Автоматическое снятие мута после 1 часа")
            try:
                await member.send("Ваш мут снят. Пожалуйста, соблюдайте правила.")
            except Exception:
                pass
        asyncio.create_task(unmute_later())

@bot.tree.command(name="mywarns", description="Посмотреть свои предупреждения", guild=discord.Object(id=GUILD_ID))
async def mywarns(interaction: discord.Interaction):
    warns_path = Path(f"warns_{interaction.user.id}.json")
    if not warns_path.exists():
        await interaction.response.send_message("У вас нет предупреждений!", ephemeral=True)
        return
    try:
        warns = json.loads(warns_path.read_text())
    except Exception:
        await interaction.response.send_message("Ошибка при чтении предупреждений.", ephemeral=True)
        return
    if not warns:
        await interaction.response.send_message("У вас нет предупреждений!", ephemeral=True)
        return
    lines = [f"{i+1}. Причина: {w['reason']}" for i, w in enumerate(warns)]
    await interaction.response.send_message("Ваши предупреждения:\n" + "\n".join(lines), ephemeral=True)

@bot.tree.command(name="clearwarns", description="Очистить все предупреждения пользователя", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Пользователь для очистки предупреждений")
async def clearwarns(interaction: discord.Interaction, member: discord.Member):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для этой команды!", ephemeral=True)
        return
    warns_path = Path(f"warns_{member.id}.json")
    if warns_path.exists():
        try:
            warns_path.unlink()
            await interaction.response.send_message(f"Все предупреждения для {member.mention} были удалены.", ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f"Ошибка при удалении файла предупреждений: {e}", ephemeral=True)
    else:
        await interaction.response.send_message(f"У пользователя {member.mention} нет предупреждений.", ephemeral=True)

@bot.tree.command(name="help", description="Показать список команд", guild=discord.Object(id=GUILD_ID))
async def help_command(interaction: discord.Interaction):
    commands_list = [
        "/clear - Очистить сообщения в чате",
        "/restart - Перезапустить бота",
        "/ping - Пинг бота",
        "/userinfo - Информация о пользователе",
        "/say - Отправить сообщение от имени бота",
        "/top - Топ по сообщениям",
        "/voice_top - Топ по времени в голосе",
        "/myrank - Ваше место в топе",
        "/warn - Выдать предупреждение",
        "/mywarns - Посмотреть свои предупреждения",
        "/clearwarns - Очистить предупреждения пользователя",
        "/migrate - Миграция статистики",
        "/activity - Активность пользователей",
        "/sync - Синхронизация команд",
        "/help - Показать это сообщение"
    ]
    await interaction.response.send_message("Доступные команды:\n" + "\n".join(commands_list), ephemeral=True)

# Запуск бота
bot_token = os.environ.get('DISCORD_BOT_TOKEN')
if not bot_token:
    raise ValueError("Не найден токен бота в переменных окружения. Установите DISCORD_BOT_TOKEN.")
bot.run(bot_token)

@bot.event
async def on_connect():
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync()
    await bot.tree.sync(guild=guild)
    print(f'Слэш-команды синхронизированы для сервера {GUILD_ID}')

@bot.tree.command(name="clearwarns", description="Очистить все предупреждения пользователя", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Пользователь для очистки предупреждений")
async def clearwarns(interaction: discord.Interaction, member: discord.Member):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для очистки предупреждений!", ephemeral=True)
        return
    warns_path = Path(f"warns_{member.id}.json")
    if warns_path.exists():
        warns_path.unlink()
        await interaction.response.send_message(f"Все предупреждения пользователя {member.mention} были удалены.", ephemeral=False)
    else:
        await interaction.response.send_message(f"У пользователя {member.mention} нет предупреждений.", ephemeral=True)

@bot.tree.command(name="mute", description="Выдать мут пользователю на X минут", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Пользователь для мута", minutes="На сколько минут (по умолчанию 60)", reason="Причина мута")
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int = 60, reason: str = "Не указана"):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для выдачи мута!", ephemeral=True)
        return
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await interaction.guild.create_role(name="Muted", reason="Мут пользователя через команду")
        for channel in interaction.guild.text_channels:
            await channel.set_permissions(mute_role, send_messages=False)
    await member.add_roles(mute_role, reason=f"Мут на {minutes} минут. Причина: {reason}")
    await interaction.response.send_message(f"Пользователь {member.mention} получил мут на {minutes} минут. Причина: {reason}", ephemeral=False)
    # Снять мут через minutes
    async def unmute_later():
        await discord.utils.sleep_until(discord.utils.utcnow() + discord.timedelta(minutes=minutes))
        await member.remove_roles(mute_role, reason="Автоматическое снятие мута")
        try:
            await member.send("Ваш мут снят. Пожалуйста, соблюдайте правила.")
        except Exception:
            pass
    import asyncio
    asyncio.create_task(unmute_later())

@bot.tree.command(name="unmute", description="Снять мут с пользователя", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(member="Пользователь для снятия мута")
async def unmute(interaction: discord.Interaction, member: discord.Member):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для снятия мута!", ephemeral=True)
        return
    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if mute_role and mute_role in member.roles:
        await member.remove_roles(mute_role, reason="Снятие мута через команду")
        await interaction.response.send_message(f"Мут с пользователя {member.mention} снят.", ephemeral=False)
    else:
        await interaction.response.send_message(f"У пользователя {member.mention} нет мута.", ephemeral=True)

@bot.tree.command(name="stop", description="Выключить бота (только для определённых ролей)")
async def stop(interaction: discord.Interaction):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для выключения бота!", ephemeral=True)
        return
    await interaction.response.send_message("Бот выключается...", ephemeral=True)
    await bot.close()

@bot.command(name="say", help="Отправить сообщение от имени бота (только для определённых ролей)")
async def owner_say(ctx, *, message: str):
    if not await user_has_allowed_role(ctx.author, ctx.guild):
        await ctx.send("У вас нет прав для использования этой команды.", delete_after=5)
        return
    await ctx.message.delete()
    await ctx.send(message)

token = os.getenv('API_TOKEN')
if not token:
    print('ERROR: DISCORD_TOKEN environment variable is not set. Do not commit your token to git.')
else:
    bot.run(token)
