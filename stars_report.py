"""Сводка по звёздам раз в неделю (GitHub Actions, .github/workflows/stars.yml, вс 19:00 МСК): баланс бота,
сколько пришло и сколько вернули за неделю. Данные берёт прямо у Telegram, база заказов не нужна.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
OWNER_CHAT = int(os.getenv("OWNER_CHAT_ID", "2093180872"))
WEEK = 7 * 86400


def summarize(balance: int, transactions: list[dict], now: int) -> str:
    week = [t for t in transactions if t["date"] >= now - WEEK]
    # входящие — от пользователя (source), исходящие — возвраты и выводы (receiver)
    income = [t for t in week if "source" in t]
    outgoing = [t for t in week if "receiver" in t]
    refunds = [t for t in outgoing if t["receiver"].get("type") == "user"]
    lines = ["⭐ Звёзды за неделю",
             f"Пришло: {sum(t['amount'] for t in income)} ⭐ ({len(income)} оплат)"]
    if refunds:
        lines.append(f"Вернули: {sum(t['amount'] for t in refunds)} ⭐ ({len(refunds)})")
    if withdrawn := sum(t["amount"] for t in outgoing if t not in refunds):
        lines.append(f"Выведено: {withdrawn} ⭐")
    lines.append(f"Баланс бота: {balance} ⭐")
    if not week:
        lines.append("Оплат пока не было — охотник ищет заказы 🙂")
    return "\n".join(lines)


async def fetch(http: httpx.AsyncClient, token: str) -> tuple[int, list[dict]]:
    api = f"https://api.telegram.org/bot{token}"
    balance = (await http.get(f"{api}/getMyStarBalance")).json()["result"]["amount"]
    transactions, offset = [], 0
    while True:  # Telegram отдаёт по 100, новые первыми не гарантированы — забираем все
        page = (await http.get(f"{api}/getStarTransactions", params={"offset": offset, "limit": 100})).json()
        items = page["result"]["transactions"]
        transactions += items
        if len(items) < 100:
            return balance, transactions
        offset += 100


async def main(dry: bool = False) -> int:
    token = os.environ["TELEGRAM_TOKEN"]
    async with httpx.AsyncClient(timeout=30) as http:
        balance, transactions = await fetch(http, token)
        text = summarize(balance, transactions, int(time.time()))
        if dry:
            print(text)
            return 0
        await http.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": OWNER_CHAT, "text": text})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--dry-run" in sys.argv)))
