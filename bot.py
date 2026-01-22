import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, UTC

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='/', intents=intents)

GUILD_ID = 1463456630833287304
# Разрешённые каналы для команд
ALLOWED_CHANNELS = {1463798624612909097, 1463798810047152178}
# ID ролей, которым разрешён рестарт
ALLOWED_ROLES_FOR_RESTART = {1463540497535602833, 1463502977355743381}  # замените на реальные ID ролей

async def user_has_allowed_role(user: discord.abc.Snowflake, guild: discord.Guild | None = None) -> bool:
    """Проверяет, есть ли у пользователя хотя бы одна из разрешённых ролей.
    Принимает `interaction.user` (User или Member). Если нужно, подгружает Member из guild.
    """
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

@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!')
    # Если перед перезапуском был записан файл с информацией — отправим уведомление
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


# Слэш-команда /clear
@bot.tree.command(name="clear", description="Очистить сообщения в чате", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(amount="Сколько сообщений удалить (по умолчанию 5)")
async def clear(interaction: discord.Interaction, amount: int = 5):
    # Команда теперь работает во всех чатах
    # Проверяем роль у пользователя
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав на использование этой команды!", ephemeral=True)
        return
    await interaction.response.send_message(f"Удаляю {amount} сообщений...", ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Удалено сообщений: {len(deleted)}", ephemeral=True)

# Слэш-команда /restart
@bot.tree.command(name="restart", description="Перезапустить бота (только для определённых ролей)", guild=discord.Object(id=GUILD_ID))
async def restart(interaction: discord.Interaction):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для перезапуска бота!", ephemeral=True)
        return
    await interaction.response.send_message("Бот перезапускается...", ephemeral=True)
    # Запишем информацию о перезапуске, чтобы новый процесс отправил уведомление
    try:
        restart_file = Path(__file__).parent / 'restart_info.json'
        restart_info = {'channel_id': interaction.channel_id, 'text': f'Бот был перезапущен пользователем {interaction.user}.'}
        restart_file.write_text(json.dumps(restart_info))
    except Exception:
        pass
    import subprocess, sys
    # Запускаем новый экземпляр процесса Python с теми же аргументами
    subprocess.Popen([sys.executable] + sys.argv)
    # Корректно закрываем бота и выходим
    await bot.close()


# Дополнительные команды
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
    # Заглушка: подсчет сообщений (реализуйте хранение и подсчет в on_message)
    try:
        stats_path = Path(f"userstats_{member.id}.json")
        if stats_path.exists():
            stats = json.loads(stats_path.read_text())
            msg_count = stats.get("messages", 0)
            voice_seconds = stats.get("voice_seconds", 0)
        else:
            msg_count = 0
            voice_seconds = 0
    except Exception:
        msg_count = 0
        voice_seconds = 0
    hours = round(voice_seconds / 3600, 2)
    await interaction.response.send_message(
        f"Пользователь: {member}\nПрисоединился: {joined}\nСообщений: {msg_count}\nЧасов в голосе: {hours}",
        ephemeral=False
    )
@bot.event
async def on_message(message: discord.Message):
    if message.guild is None or message.author.bot:
        return
    stats_path = Path(f"userstats_{message.author.id}.json")
    stats = {"messages": 0, "voice_seconds": 0}
    if stats_path.exists():
        try:
            stats = json.loads(stats_path.read_text())
        except Exception:
            pass
    stats["messages"] = stats.get("messages", 0) + 1
    stats_path.write_text(json.dumps(stats))
    await bot.process_commands(message)

# Для учета времени в голосе требуется отдельная логика (on_voice_state_update)
@bot.event
async def on_voice_state_update(member, before, after):
    if not member.guild or member.bot:
        return
    stats_path = Path(f"userstats_{member.id}.json")
    stats = {"messages": 0, "voice_seconds": 0}
    if stats_path.exists():
        try:
            stats = json.loads(stats_path.read_text())
        except Exception:
            pass
    # Вход в голосовой канал
    if before.channel is None and after.channel is not None:
        stats["_voice_join_time"] = int(discord.utils.utcnow().timestamp())
    # Выход из голосового канала
    elif before.channel is not None and after.channel is None:
        join_time = stats.pop("_voice_join_time", None)
        if join_time:
            now = int(discord.utils.utcnow().timestamp())
            stats["voice_seconds"] = stats.get("voice_seconds", 0) + (now - join_time)
    stats_path.write_text(json.dumps(stats))


@bot.tree.command(name="say", description="Бот отправит сообщение от своего имени", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(text="Текст для отправки")
async def say(interaction: discord.Interaction, text: str):
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        await interaction.response.send_message("У вас нет прав для использования этой команды.", ephemeral=True)
        return
    await interaction.response.send_message("Сообщение отправлено.", ephemeral=True)
    await interaction.channel.send(f"```\n{text}\n```")

# Словари для хранения времени последнего вызова команд
last_top_call = {}
last_voice_top_call = {}

# Топ пользователей по сообщениям
@bot.tree.command(name="top", description="Топ пользователей по количеству сообщений", guild=discord.Object(id=GUILD_ID))
async def top(interaction: discord.Interaction):
    now = datetime.now(UTC)
    user_id = interaction.user.id
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        if user_id in last_top_call and now - last_top_call[user_id] < timedelta(minutes=5):
            await interaction.response.send_message("Эту команду можно использовать раз в 5 минут.", ephemeral=True)
            return
        last_top_call[user_id] = now
    from glob import glob
    stats_files = glob("userstats_*.json")
    stats = []
    for file in stats_files:
        try:
            data = json.loads(Path(file).read_text())
            user_id_stat = int(file.split("_")[1].split(".")[0])
            stats.append((user_id_stat, data.get("messages", 0)))
        except Exception:
            pass
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

# Топ пользователей по времени в голосовых каналах
@bot.tree.command(name="voice_top", description="Топ пользователей по времени в голосовых каналах", guild=discord.Object(id=GUILD_ID))
async def voice_top(interaction: discord.Interaction):
    now = datetime.now(UTC)
    user_id = interaction.user.id
    if not await user_has_allowed_role(interaction.user, interaction.guild):
        if user_id in last_voice_top_call and now - last_voice_top_call[user_id] < timedelta(minutes=5):
            await interaction.response.send_message("Эту команду можно использовать раз в 5 минут.", ephemeral=True)
            return
        last_voice_top_call[user_id] = now
    from glob import glob
    stats_files = glob("userstats_*.json")
    stats = []
    for file in stats_files:
        try:
            data = json.loads(Path(file).read_text())
            user_id_stat = int(file.split("_")[1].split(".")[0])
            stats.append((user_id_stat, data.get("voice_seconds", 0)))
        except Exception:
            pass
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

# Узнать своё место в топе по сообщениям
@bot.tree.command(name="myrank", description="Ваше место в топе по сообщениям", guild=discord.Object(id=GUILD_ID))
async def myrank(interaction: discord.Interaction):
    from glob import glob
    stats_files = glob("userstats_*.json")
    stats = []
    for file in stats_files:
        try:
            data = json.loads(Path(file).read_text())
            user_id = int(file.split("_")[1].split(".")[0])
            stats.append((user_id, data.get("messages", 0)))
        except Exception:
            pass
    stats.sort(key=lambda x: x[1], reverse=True)
    user_id = interaction.user.id
    rank = next((i+1 for i, (uid, _) in enumerate(stats) if uid == user_id), None)
    msg_count = next((count for uid, count in stats if uid == user_id), 0)
    if rank:
        await interaction.response.send_message(f"Ваше место в топе: {rank}\nСообщений: {msg_count}", ephemeral=True)
    else:
        await interaction.response.send_message("Вы пока не в топе по сообщениям.", ephemeral=True)

# Предупреждение пользователю (можно в любом канале)
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

    # Если 3 и более предупреждений — мут на 1 час
    if len(warns) == 3:
        # Создаём/находим роль "Muted"
        mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not mute_role:
            mute_role = await interaction.guild.create_role(name="Muted", reason="Автоматический мут за 3 предупреждения")
            # Запретить писать во всех каналах, кроме разрешённого
            for channel in interaction.guild.text_channels:
                if channel.id != 1463825318249889889:
                    await channel.set_permissions(mute_role, send_messages=False)
                else:
                    await channel.set_permissions(mute_role, send_messages=True)
        # Выдать роль
        await member.add_roles(mute_role, reason="3 предупреждения — мут на 1 час")
        await interaction.followup.send(f"{member.mention} получил мут на 1 час и может писать только в <#1463825318249889889>", ephemeral=False)
        # Снять мут через 1 час
        async def unmute_later():
            await discord.utils.sleep_until(discord.utils.utcnow() + discord.timedelta(hours=1))
            await member.remove_roles(mute_role, reason="Автоматическое снятие мута после 1 часа")
            try:
                await member.send("Ваш мут снят. Пожалуйста, соблюдайте правила.")
            except Exception:
                pass
        import asyncio
        asyncio.create_task(unmute_later())


# Команда для просмотра своих предупреждений
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

# Справка по командам
@bot.tree.command(name="help", description="Показать список команд", guild=discord.Object(id=GUILD_ID))
async def help_command(interaction: discord.Interaction):
    commands = [
        "/clear — Очистить сообщения в чате",
        "/restart — Перезапустить бота (только для определённых ролей)",
        "/ping — Проверить задержку бота",
        "/userinfo — Информация о пользователе (сообщения и часы в голосе)",
        "/say — Бот отправит сообщение от своего имени",
        "/top — Топ пользователей по сообщениям",
        "/voice_top — Топ пользователей по времени в голосе",
        "/myrank — Ваше место в топе по сообщениям",
        "/warn — Выдать предупреждение пользователю (только для определённых ролей)",
        "/mywarns — Посмотреть свои предупреждения",
        "/clearwarns — Очистить все предупреждения пользователя (только для определённых ролей)",
        "/help — Показать список команд"
    ]
    await interaction.response.send_message("Доступные команды:\n" + "\n".join(commands), ephemeral=True)

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
