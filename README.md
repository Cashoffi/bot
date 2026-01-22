# Discord Bot

Инструкции по подготовке и загрузке репозитория для хостинга через Git URL.

Установка зависимостей:

```bash
python -m pip install -r requirements.txt
```

Настройка токена (не коммитьте токен в репозиторий):

- Скопируйте `.env.example` в `.env` и подставьте свой токен,
  или установите переменную окружения `DISCORD_TOKEN`.

Запуск локально:

```bash
# В PowerShell
$env:DISCORD_TOKEN='ваш_токен'
python "bot.py"
```

Создание Git-репозитория и загрузка на GitHub (пример):

```bash
git init
git add .
git commit -m "Initial commit"
# Создайте репозиторий на GitHub и затем:
git remote add origin https://github.com/USERNAME/REPO.git
git branch -M main
git push -u origin main
```

Если установлен GitHub CLI, можно создать репозиторий и запушить в одну команду:

```bash
gh repo create REPO --public --source=. --remote=origin --push
```

После этого скопируйте Git URL (`https://github.com/USERNAME/REPO.git` или `git@github.com:USERNAME/REPO.git`) и вставьте его в форму хостинга.
