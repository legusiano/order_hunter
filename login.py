"""Вход в аккаунт Telegram для охотника (один раз, руками владельца): спрашивает номер и код из Telegram,
сохраняет сессию в .env как TG_SESSION. Сессию никому не показывать — с ней можно писать от имени аккаунта.

Запуск: python login.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv, set_key
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

ENV = Path(__file__).parent / ".env"
load_dotenv(ENV)

with TelegramClient(StringSession(), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"]) as client:
    me = client.get_me()
    set_key(str(ENV), "TG_SESSION", client.session.save())
    print(f"Готово: вошёл как {me.first_name} (@{me.username}). Сессия сохранена в .env")
