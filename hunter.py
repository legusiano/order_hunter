"""Охотник за заказами: каждые 10 минут внутри кассы на компьютере (cashier.py → loop(); вручную — hunter.yml) смотрит открытые ленты заказов
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
from urllib.parse import quote
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
STATE = Path(__file__).parent / "state.json"

OWNER_CHAT = int(os.getenv("OWNER_CHAT_ID", "2093180872"))
# открытые каналы с заказами, где есть свежие посты (проверено 27–28.10.2026)
CHANNELS = ["freelancetaverna", "workk_on", "FrWork3", "FreeWorkFeed", "allgigs", "devjobs", "frilancekomfort",
            "job_python", "vakansii_it", "work_finde", "normrabota", "remote_w0rk", "dddwork", "digitaltender",
            "Getitrussia", "dnative_job", "evacuatejobs", "jobforjunior", "morejobs", "onlinevakansii", "rabotka_zdes",
            "yuniorapp", "javascript_jobs_feed", "zakazy_it", "freelance_zakazy", "jobbyrussia", "chooseajob", "FreelanceBay",
            # рубрика «скрипты, боты, мини-аппы» — самый плотный источник заказов на ботов
            "freelance_zakazy#скрипты_боты_miniapp"]
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
                     r"обязанност|будет плюсом|оклад|зарплат|\bз/п\b|#вакансия|#(junior|middle|senior)\b|"
                     r"резюме|дайджест|подборк|лучшие вакансии|вакансия|в команду|занятость|график работы|"
                     r"опыт работы от|опыт от \d|трудоустр|оформление по|соцпакет|\bДМС\b|разработчик в компанию|"
                     r"на правах рекламы|подписывайтесь|наш курс|вебинар|диджитализация|"
                     # реклама студий и исполнителей — это конкуренты, а не заказчики
                     r"мы (делаем|разрабатываем|создаём|создаем)|наша команда|наши услуги|оставьте заявку|"
                     r"разработка .{0,30}под ключ", re.I)
# берём только разовые заказы: в посте должно быть видно, что человеку нужно что-то сделать под ключ
ORDER = re.compile(r"нуж(ен|на|но|ны)|требуется|ищу (исполнител|разработчик|программист|кто)|ищем исполнител|"
                   r"(сделать|создать|разработать|написать|доработать|настроить|разработк\w*) (бот|телеграм|tg|тг|мини|ии)|"
                   r"бюджет|оплата за проект|\bтз\b|техническ\w* задани|срок|кто (может|сделает|возьм)|#заказ|"
                   r"задача:|за сколько", re.I)
# заказ не на разработку: в заголовке другая профессия
ROLE = re.compile(r"копирайтер|сценарист|дизайнер|маркетолог|\bsmm|менеджер|монтаж|рилс|таргет|ассистент руковод|"
                  r"engineer|инженер|designer", re.I)


def clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", text).strip()


# «нужен бот на пайтон» без слова «телеграм» — тоже наше; а вот боты для других площадок и железа — нет
ANY_BOT = re.compile(r"чат.?бот|\bбот(а|у|ом|ов|ы)?\b|\bbot\b|mini ?app|мини.?апп|мини.?прилож|ии.?ассистент|"
                     r"ai.?ассистент|ии.?агент|ai.?agent|ии.?менеджер", re.I)
# берём любых ботов (Telegram, VK, WhatsApp, Discord, для сайта); не берём игровых ботов, железо и «накрутку»
OTHER_PLATFORM = re.compile(r"raspberry|роблокс|roblox|майнкрафт|minecraft|black russia|\bsamp\b|\bgta\b|android|"
                            r"\badb\b|игров|дзен|ютуб|youtube|накрут|просмотр", re.I)
# бюджет из текста заказа, чтобы крупные (от BIG_BUDGET ₽) отдавать Кириллу лично
BUDGET = re.compile(r"(\d[\d  .,]*)\s*(тыс|к\b|k\b|₽|руб|р\.|rub)", re.I)
BIG_BUDGET = 5000


def budget(text: str) -> int:
    """Самая большая сумма в рублях: «30,000 ₽», «90 000 руб», «5к», «1.5 тыс»."""
    best = 0
    for raw, unit in BUDGET.findall(text):
        raw = raw.strip().replace(" ", " ")
        if unit.lower() in ("тыс", "к", "k"):
            number = raw.replace(" ", "")
            value = float(number.replace(",", ".")) * 1000 if re.fullmatch(r"\d+([.,]\d+)?", number) else 0
        else:
            value = float(re.sub(r"\D", "", re.sub(r"[.,]\d{1,2}$", "", raw)) or 0)  # копейки отбрасываем
        best = max(best, int(value))
    return best


def matches(title: str, body: str, tagged: bool = False) -> bool:
    text = re.sub(r"#\S+", " ", f"{title}\n{body}")  # метки рубрик вроде #скрипты_боты_miniapp — не текст заказа
    about_bot = KEYWORDS.search(text) or (ANY_BOT.search(text) and not OTHER_PLATFORM.search(text))
    if not about_bot or EXCLUDE.search(text) or ROLE.search(title):
        return False
    if not tagged and not ORDER.search(text):  # в рубрике заказов признак заказа не нужен
        return False
    # вакансия «личный ассистент, связь в телеграм» — не наше, если про бота там ни слова
    return not HUMAN.search(text) or bool(re.search(r"\bбот|\bbot|mini ?app|мини.?апп", text, re.I))


async def fetch_channel(http: httpx.AsyncClient, channel: str) -> list[dict]:
    """channel — имя канала или «канал#метка»: тогда берутся только посты с этой меткой (поиск по каналу)."""
    channel, _, tag = channel.partition("#")
    r = await http.get(f"https://t.me/s/{channel}", params={"q": f"#{tag}"} if tag else None)
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
    # только заказы с @юзером заказчика: где надо писать на сайте или бирже — не берём
    return [lead for lead in unique.values()
            if matches(lead["title"], lead["body"], tagged=lead.get("tagged", False)) and contact(lead)], errors


def format_lead(lead: dict) -> str:
    body = lead["body"]
    if body.startswith(lead["title"]):
        body = body[len(lead["title"]):].strip()
    head = f"🎯 {lead['source']}: {lead['title']}"
    if lead["price"]:
        head += f" ({lead['price']})"
    return f"{head}\n{body[:600]}{'…' if len(body) > 600 else ''}\n{lead['url']}"


# @username заказчика в тексте поста или ссылка t.me/username (не служебные и не сам канал)
CONTACT = re.compile(r"(?:@|t\.me/)([A-Za-z][A-Za-z0-9_]{4,31})\b")
NOT_CONTACT = re.compile(r"bot$|^(joinchat|share|addlist|proxy|iv|s)$", re.I)


def contact(lead: dict) -> str | None:
    channel = lead["source"].lstrip("@").lower()
    for name in CONTACT.findall(lead["body"]):
        if name.lower() != channel and not NOT_CONTACT.search(name):
            return name
    return None


async def draft(lead: dict) -> str | None:
    """Первое сообщение заказчику от ИИ-продавца — одним текстом, чтобы вставить его в чат."""
    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("GEMINI_API_KEY")):
        return None
    import seller  # только когда есть ключ ИИ: без него охотник работает как раньше
    try:
        answer = await seller.reply([], lead=f"{lead['title']}\n{lead['body']}")
    except RuntimeError as e:
        print("черновик не получился:", e)
        return None
    return "\n\n".join(answer["messages"])[:1500] or None


def write_button(username: str, text: str) -> dict:
    # t.me/<username>?text=… открывает чат с заказчиком, где сообщение уже вписано — остаётся нажать «Отправить»
    return {"inline_keyboard": [[{"text": f"✍️ Написать @{username}",
                                  "url": f"https://t.me/{username}?text={quote(text)}"}]]}


async def send(text: str, markup: dict | None = None):
    token = os.environ["TELEGRAM_TOKEN"]
    payload = {"chat_id": OWNER_CHAT, "text": text[:4000], "disable_web_page_preview": True}
    if markup:
        payload["reply_markup"] = markup
    async with httpx.AsyncClient(timeout=30) as http:
        await http.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)


async def send_lead(lead: dict):
    username = contact(lead)
    draft_text = await draft(lead) if username else None
    text = format_lead(lead)
    if (money := budget(lead["body"])) >= BIG_BUDGET:
        text = f"💎 Крупный заказ — бюджет до {money:,} ₽, напиши ему сам!\n\n".replace(",", " ") + text
    if draft_text:
        await send(f"{text}\n\n✍️ Черновик для @{username}:\n{draft_text}", write_button(username, draft_text))
    else:
        await send(text + (f"\n\nКонтакт: @{username}" if username else ""))


async def run_once(on_found=None) -> list[str]:
    """Один проход: собрать, отфильтровать, прислать новые. Возвращает ошибки источников.
    on_found(n) — сколько новых заказов прислали (для итога дня в кассе)."""
    leads, errors = await collect()
    first_run = not STATE.exists()
    state = {"seen": []} if first_run else json.loads(STATE.read_text(encoding="utf-8"))
    seen = set(state["seen"])
    fresh = [lead for lead in leads if lead["id"] not in seen]
    limit = FIRST_RUN if first_run else MAX_PER_RUN
    for lead in fresh[:limit]:
        await send_lead(lead)
    if len(fresh) > limit:
        await send(f"…и ещё {len(fresh) - limit} похожих заказов, показал самые первые.")
    # помним последние ~2000, чтобы состояние не росло бесконечно
    state["seen"] = (state["seen"] + [lead["id"] for lead in fresh])[-2000:]
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    if on_found and fresh:
        on_found(len(fresh))
    return errors


async def loop(every: int = 600, on_found=None):
    """Охотник внутри кассы на компьютере Кирилла: GitHub по расписанию «раз в 10 минут» запускал раз в час-два."""
    while True:
        try:
            await run_once(on_found)
        except Exception as e:  # сеть, Telegram — следующий проход через 10 минут
            print("охотник:", repr(e))
        await asyncio.sleep(every)


async def main(dry: bool = False) -> int:
    if dry:
        leads, errors = await collect()
        for lead in leads:
            print(format_lead(lead), end="\n\n")
        print(f"подходящих: {len(leads)}; ошибки: {errors}")
        return 0
    if errors := await run_once():
        print("ошибки источников:", errors)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--dry-run" in sys.argv)))
