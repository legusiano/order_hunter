"""Охотник за заказами: каждые 30 минут (GitHub Actions, .github/workflows/hunter.yml) смотрит открытые ленты заказов
и присылает владельцу в Telegram свежие заявки на Telegram-ботов и мини-аппы. Без входа в Telegram и без ИИ.

Откуда берёт:
- FL.ru — RSS всех проектов;
- Kwork — биржа проектов (список зашит в страницу как JSON);
- открытые ТГ-каналы с заказами — через веб-превью t.me/s/<канал>.
Что уже присылал — state.json (между запусками хранится в кэше GitHub Actions), чтобы не повторяться. Первый запуск присылает только несколько последних.
"""

import asyncio
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
STATE = Path(__file__).parent / "state.json"

OWNER_CHAT = int(os.getenv("OWNER_CHAT_ID", "2093180872"))
CHANNELS = ["freelancetaverna", "workk_on"]
KWORK_CATEGORIES = [11, 41]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
MAX_PER_RUN = 10
FIRST_RUN = 5

# только Telegram-боты: «бот» и «телеграм» рядом, в одной фразе («телеграм» сам по себе не годится — он в контактах
# почти везде, а «бот» без телеграма — это и боты для игр, и чат-боты на сайт)
TG = r"(телеграм|телеграмм|telegram|\bтг\b|\btg\b)"
KEYWORDS = re.compile(
    rf"{TG}[^.!?\n]{{0,30}}(\bбот|\bbot|mini ?app|мини.?апп|мини.?прилож|webapp)|"
    rf"(\bбот|\bbot|mini ?app|мини.?апп|мини.?прилож|webapp)[^.!?\n]{{0,30}}{TG}",
    re.I)
# а это не про нас: вакансии в штат и чужие боты, которые надо просто «продвинуть»
EXCLUDE = re.compile(r"в штат|полный рабочий день|full.?time|ботокс|робот.?пылесос|накрут", re.I)


def clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", text).strip()


def matches(title: str, body: str) -> bool:
    text = f"{title}\n{body}"
    return bool(KEYWORDS.search(text)) and not EXCLUDE.search(text)


async def fetch_fl(http: httpx.AsyncClient) -> list[dict]:
    r = await http.get("https://www.fl.ru/rss/all.xml")
    root = ET.fromstring(r.content)  # кодировка (windows-1251) берётся из заголовка XML
    leads = []
    for item in root.iter("item"):
        link = item.findtext("link", "")
        leads.append({"id": "fl:" + link, "source": "FL.ru", "title": clean(item.findtext("title")),
                      "body": clean(item.findtext("description")), "price": "", "url": link})
    return leads


async def fetch_kwork(http: httpx.AsyncClient, category: int) -> list[dict]:
    r = await http.get(f"https://kwork.ru/projects?c={category}")
    start = r.text.find('"wants":[')
    if start < 0:
        raise ValueError("не нашёл список проектов на странице")
    wants, _ = json.JSONDecoder().raw_decode(r.text, start + len('"wants":'))
    leads = []
    for w in wants:
        price = w.get("priceLimit") or ""
        leads.append({"id": f"kwork:{w['id']}", "source": "Kwork", "title": clean(w.get("name")),
                      "body": clean(w.get("description")), "price": f"до {float(price):.0f} ₽" if price else "",
                      "url": f"https://kwork.ru/projects/{w['id']}"})
    return leads


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
        jobs = [("FL.ru", fetch_fl(http))]
        jobs += [(f"Kwork c={c}", fetch_kwork(http, c)) for c in KWORK_CATEGORIES]
        jobs += [("@" + c, fetch_channel(http, c)) for c in CHANNELS]
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
