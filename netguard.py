"""Сторож сети в кассе: на ноутбуке Кирилла иногда отваливается Wi-Fi (28.10 — на час ночью), и бот молчит.
Раз в минуту проверяем интернет; если его нет 2 минуты подряд — переподключаемся к последней сети через netsh.
Настройки Windows не меняются: это то же, что нажать на сеть в списке Wi-Fi.
"""

import asyncio
import logging
import re
import socket
import subprocess
import sys

log = logging.getLogger("netguard")
CHECK_EVERY = 60
OFFLINE_LIMIT = 2  # проверок подряд без сети, после которых переподключаемся


def online() -> bool:
    for host in (("api.telegram.org", 443), ("1.1.1.1", 53)):
        try:
            with socket.create_connection(host, timeout=5):
                return True
        except OSError:
            continue
    return False


def wifi_profile(output: str) -> str | None:
    """Имя профиля текущей сети из `netsh wlan show interfaces` (английская или русская Windows)."""
    match = re.search(r"^\s*(?:Profile|Профиль)\s*:\s*(.+?)\s*$", output, re.M)
    return match.group(1) if match else None


def netsh(*args: str) -> str:
    raw = subprocess.run(["netsh", "wlan", *args], capture_output=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    for encoding in ("utf-8", "cp866", "cp1251"):  # кодировка вывода зависит от настроек консоли
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


async def loop(notify=None):
    """notify(text) — сообщение владельцу, когда сеть вернулась после переподключения."""
    if sys.platform != "win32":
        return
    profile, offline = None, 0
    while True:
        if await asyncio.to_thread(online):
            if offline >= OFFLINE_LIMIT and notify:
                await notify(f"📶 Интернет на компьютере пропадал ~{offline} мин, переподключился — всё работает.")
            offline = 0
            profile = wifi_profile(await asyncio.to_thread(netsh, "show", "interfaces")) or profile
        else:
            offline += 1
            if offline >= OFFLINE_LIMIT and profile:
                log.warning("нет интернета %s мин — переподключаюсь к Wi-Fi", offline)
                await asyncio.to_thread(netsh, "connect", f"name={profile}")
        await asyncio.sleep(CHECK_EVERY)
