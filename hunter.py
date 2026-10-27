"""Охотник за заказами: каждые 30 минут (GitHub Actions, .github/workflows/hunter.yml) смотрит открытые ленты заказов
и присылает владельцу в Telegram свежие заявки на Telegram-ботов и мини-аппы. Без входа в Telegram и без ИИ.

Откуда берёт: только открытые ТГ-каналы с заказами — через веб-превью t.me/s/<канал> (биржи Кириллу неудобны).
Что уже присылал — state.json (между запусками хранится в кэше GitHub Actions), чтобы не повторяться. Первый запуск присылает только несколько последних.
"""

import asyncio
import html
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
STATE = Path(__file__).parent / "state.json"

OWNER_CHAT = int(os.getenv("OWNER_CHAT_ID", "2093180872"))
# открытые каналы с заказами, где есть свежие посты (проверено 27.10.2026)
CHANNELS = ["freelancetaverna", "workk_on", "FrWork3", "FreeWorkFeed", "allgigs", "devjobs", "frilancekomfort",
            "job_python", "vakansii_it", "work_finde", "normrabota", "remote_w0rk", "dddwork", "digitaltender"]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
MAX_PER_RUN = 10
FIRST_RUN = 5

# только Telegram-боты: «бот» и «телеграм» рядом, в одной фразе («телеграм» сам по себе не годится — он в контактах
# почти везде, а «бот» без телеграма — это и боты для игр, и чат-боты на сайт)
TG = r"(телеграм|телеграмм|telegram|\bтг\b|\btg\b)"
# что делаем: ботов, ИИ-ассистентов на их основе и мини-аппы
WHAT = r"(\bбот|\bbot|mini ?app|мини.?апп|мини.?прилож|webapp|ассистент|assistant|ии.?агент|ai.?agent)"
KEYWORDS = re.compile(rf"{TG}[^.!?\n]{{0,30}}{WHAT}|{WHAT}[^.!?\n]{{0,30}}{TG}", re.I)
# а здесь «ассистент» — это человек, а не бот
HUMAN = re.compile(r"(личн|бизнес|виртуальн|онлайн|удал[её]нн)\S*.?ассистент|ассистент.?(руководител|директор)", re.I)
# а это не про нас: вакансии в штат и чужие боты, которые надо просто «продвинуть»
EXCLUDE = re.compile(r"в штат|полный рабочий день|full.?time|ботокс|робот.?пылесос|накрут|"
                     r"обязанност|будет плюсом|оклад|зарплат|\bз/п\b|#вакансия|#(junior|middle|senior)\b", re.I)
# заказ не на разработку: в заголовке другая профессия
ROLE = re.compile(r"копирайтер|сценарист|дизайнер|маркетолог|\bsmm|менеджер|монтаж|рилс|таргет|ассистент руковод", re.I)


def clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", text).strip()


def matches(title: str, body: str) -> bool:
    text = f"{title}\n{body}"
    if not KEYWORDS.search(text) or EXCLUDE.search(text) or ROLE.search(title):
        return False
    # вакансия «личный ассистент, связь в телеграм» — не наше, если про бота там ни слова
    return not HUMAN.search(text) or bool(re.search(r"\bбот|\bbot|mini ?app|мини.?апп", text, re.I))


async def fetch_channel(http: httpx.AsyncClient, channel: str) -> list[dict]:
    r = await http.get(f"https://t.me/s/{channel}")
    leads = []
    for post, body in re.findall(r'data-post="([^"]+)".*?tgme_widget_message_text[^>]*>(.*?)</div>', r.text, re.S):
        text = clean(body)
        leads.append({"id": "tg:" + post, "source": "@" + channel, "title": text.split("\n")[0][:120],
                      "body": text, "price": "", "url": "https://t.me/" + post})
    return leads


async def collect() -> tuple[list[dict], list[str]]:
    leads, errors = [], []
    async with httpx.AsyncClient(timeout=30, headers=UA, follow_redirects=True) as http:
        jobs = [("@" + c, fetch_channel(http, c)) for c in CHANNELS]
        for (name, _), res in zip(jobs, await asyncio.gather(*(j for _, j in jobs), return_exceptions=True)):
            if isinstance(res, Exception):
                errors.append(f"{name}: {res!r}"[:200])
            else:
                leads += res
    unique = {lead["id"]: lead for lead in leads}
    return [lead for lead in unique.values() if matches(lead["title"], lead["body"])], errors


def format_lead(lead: dict) -> str:
    body = lead["body"]
    if body.startswith(lead["title"]):
        body = body[len(lead["title"]):].strip()
    head = f"🎯 {lead['source']}: {lead['title']}"
    if lead["price"]:
        head += f" ({lead['price']})"
    return f"{head}\n{body[:600]}{'…' if len(body) > 600 else ''}\n{lead['url']}"


async def send(text: str):
    token = os.environ["TELEGRAM_TOKEN"]
    async with httpx.AsyncClient(timeout=30) as http:
        await http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": OWNER_CHAT, "text": text[:4000], "disable_web_page_preview": True})


async def main(dry: bool = False) -> int:
    leads, errors = await collect()
    if dry:
        for lead in leads:
            print(format_lead(lead), end="\n\n")
        print(f"подходящих: {len(leads)}; ошибки: {errors}")
        return 0
    first_run = not STATE.exists()
    state = {"seen": []} if first_run else json.loads(STATE.read_text(encoding="utf-8"))
    seen = set(state["seen"])
    fresh = [lead for lead in leads if lead["id"] not in seen]
    limit = FIRST_RUN if first_run else MAX_PER_RUN
    for lead in fresh[:limit]:
        await send(format_lead(lead))
    if len(fresh) > limit:
        await send(f"…и ещё {len(fresh) - limit} похожих заказов, показал самые первые.")
    # помним последние ~2000, чтобы состояние не росло бесконечно
    state["seen"] = (state["seen"] + [lead["id"] for lead in fresh])[-2000:]
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    if errors:
        print("ошибки источников:", errors)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--dry-run" in sys.argv)))
