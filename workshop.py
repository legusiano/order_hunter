"""Мастерская в кассе: после оплаты запускает фабрику (factory.py) и отдаёт готового бота заказчику.

- Заказ дешевле REVIEW_FROM звёзд — бот отдаёт архив сам, но не сразу: через 1–2 дня от оплаты (delivery_delay),
  правки — через FIX_DELAY; владелец может отдать раньше кнопкой. Выключить автовыдачу — /auto off.
- Заказ от REVIEW_FROM звёзд — сначала Кириллу с кнопками «Отдать» / «Доработать».
- После выдачи заказчик видит «Всё отлично» / «Нужно поправить». Правки ИИ разбирает: в рамках ТЗ — бесплатно,
  до FREE_REVISIONS раз; новое, чего в ТЗ не было, — доплата отдельным счётом (заказ с parent_id).
  Если бесплатные правки кончились — передаём Кириллу.
Сборки идут по одной, чтобы не путать ветки в bot_builds.

Команды владельца: /build <номер>, /fix <номер> <что поправить>, /auto on|off.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import factory
from orders import Orders, pay_link

log = logging.getLogger("workshop")
MSK = timezone(timedelta(hours=3))
lock = asyncio.Lock()
REVIEW_FROM = 1500   # с этой суммы Кирилл смотрит бота перед выдачей
FREE_REVISIONS = 3
# готового бота отдаём не сразу, а через правдоподобный срок от оплаты (как обещает продавец)
SMALL_ORDER = 1000   # до этой суммы — 1 день, дороже — 2 дня
FIX_DELAY = 2 * 3600


def delivery_delay(stars: int) -> int:
    return (1 if stars < SMALL_ORDER else 2) * 86400

CLASSIFY = """Заказчик получил Telegram-бота по ТЗ и пишет, что поправить. Реши, это правка в рамках ТЗ
(ошибка, не работает, не так, как в ТЗ, мелкие тексты/кнопки) или новая функция, которой в ТЗ не было.

ТЗ:
{spec}

Сообщение заказчика:
{text}

Цены на новое: мелкое дополнение 150–300 ⭐, заметная функция 300–700 ⭐, большая часть — 700–1500 ⭐.
Ответ — только JSON: {{"kind": "fix" | "new" | "unclear", "comment": "что именно сделать — для разработчика",
"title": "коротко для счёта (для new)", "stars": 300, "reply": "ответ заказчику — вежливо, по-человечески, 1–3 предложения"}}"""


def owner_buttons(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Отдать заказчику", callback_data=f"deliver:{order_id}"),
                                  InlineKeyboardButton("✏️ Доработать", callback_data=f"fix:{order_id}")]])


def buyer_buttons(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Всё отлично", callback_data=f"ok:{order_id}"),
                                  InlineKeyboardButton("✏️ Нужно поправить", callback_data=f"change:{order_id}")]])


def root(orders: Orders, order_id: int) -> int:
    """Доплата за доработку собирается поверх файлов исходного заказа."""
    order = orders.get(order_id)
    return order["parent_id"] or order_id


async def deliver(app, owner: int, order_id: int, note: str = ""):
    orders: Orders = app.bot_data["orders"]
    order = orders.get(order_id)
    base = root(orders, order_id)
    # отдаём только оплаченное и не возвращённое — ни при каких кнопках и правках
    if not order["charge_id"] or "refunded" in (order["status"], orders.get(base)["status"]):
        raise TelegramError("заказ не оплачен или звёзды возвращены — не отдаю")
    if orders.setting(f"blocked:{order['buyer_id']}"):
        raise TelegramError("покупатель заблокирован — не отдаю")
    with open(factory.BUILDS / f"order_{base}.zip", "rb") as f:
        await app.bot.send_document(
            order["buyer_id"], f, filename=f"bot_order_{base}.zip", reply_markup=buyer_buttons(base),
            caption=(note or f"🎉 Ваш бот готов! Заказ №{base}: {orders.get(base)['title']}") +
                    "\n\nВнутри README.md — пошаговая инструкция: как получить токен у @BotFather и запустить бота. "
                    "Если что-то не так — нажмите «Нужно поправить» и опишите, исправим.")
    orders.set_status(order_id, "delivered")
    orders.set_setting(f"deliver_at:{order_id}", None)
    orders.set_setting(f"deliver_note:{order_id}", None)
    if base != order_id:
        orders.set_status(base, "delivered")


async def delivery_loop(app, owner: int):
    """Раз в 5 минут отдаёт заказы, у которых наступил срок выдачи."""
    orders: Orders = app.bot_data["orders"]
    while True:
        for order_id in orders.due("deliver_at:", int(time.time())):
            if orders.get(order_id)["status"] != "ready":  # вернули звёзды, отдали вручную — снимаем из очереди
                orders.set_setting(f"deliver_at:{order_id}", None)
                continue
            try:
                await deliver(app, owner, order_id, orders.setting(f"deliver_note:{order_id}") or "")
                await app.bot.send_message(owner, f"🎁 Заказ №{order_id} отдан заказчику по сроку.")
            except TelegramError as e:
                orders.set_setting(f"deliver_at:{order_id}", None)
                await app.bot.send_message(owner, f"⚠️ Заказ №{order_id} не отдан по сроку: {e}")
        await asyncio.sleep(300)


async def start_build(app, owner: int, order_id: int, comment: str | None = None, free_fix: bool = False):
    """Фоновая сборка заказа. comment — доработка; free_fix — правка по просьбе заказчика в рамках ТЗ."""
    orders: Orders = app.bot_data["orders"]
    order = orders.get(order_id)
    base = root(orders, order_id)
    if order["parent_id"] and not comment:  # оплаченная доплата: дорабатываем исходного бота по её описанию
        comment = order["spec"] or order["title"]

    async def progress(text: str):
        await app.bot.send_message(owner, f"Заказ №{order_id}: {text}")

    async with lock:
        orders.set_status(order_id, "building")
        await progress("🛠 доработка начата…" if comment else "🛠 начал собирать бота по ТЗ…")
        try:
            base_order = orders.get(base)
            result = await factory.build(base, base_order["title"], base_order["spec"], progress, comment)
        except Exception as e:  # BuildError, git, gh, сеть — касса не должна падать из-за фабрики
            log.exception("сборка заказа %s", order_id)
            orders.set_status(order_id, "failed")
            await progress(f"⚠️ {e}"[:3500] + f"\n\nМожно: /build {order_id} — ещё раз, /fix {base} <подсказка>, "
                           f"/refund {order_id} — вернуть звёзды.")
            if order["buyer_id"] and free_fix:
                await app.bot.send_message(order["buyer_id"], "Правка оказалась сложнее, чем казалось — передал "
                                                              "исполнителю, он напишет вам.")
            return
        if orders.get(order_id)["status"] == "refunded":  # пока собирали, звёзды вернули
            await progress("собран, но звёзды за него уже вернули — заказчику не отдаю.")
            return
        orders.set_status(order_id, "ready")
        total = orders.get(base)["stars"]
        report = (f"📦 Заказ №{order_id} {'доработан' if comment else 'готов'}: {base_order['title']}\n"
                  f"Проверка на GitHub пройдена, попыток: {result['attempts']}, тестов: {result['tests']}.")
        if result.get("gaps_fixed"):
            report += "\nСамопроверка по ТЗ доделала: " + "; ".join(result["gaps_fixed"])[:400]

        auto = orders.setting("auto_deliver") != "off"
        if order["buyer_id"] and auto and total < REVIEW_FROM:
            paid_at = order["paid_at"] or int(time.time())
            due = int(time.time()) + FIX_DELAY if comment else paid_at + delivery_delay(total)
            orders.set_setting(f"deliver_at:{order_id}", str(due))
            if comment:
                orders.set_setting(f"deliver_note:{order_id}", f"🔧 Готово, поправили: {comment}"[:500])
            when = datetime.fromtimestamp(due, MSK).strftime("%d.%m %H:%M")
            await progress(report + f"\n⏳ Отдам заказчику автоматически {when} МСК. Отдать сразу — кнопка ниже.")
            with open(result["zip"], "rb") as f:
                await app.bot.send_document(owner, f, filename=f"bot_order_{base}.zip",
                                            reply_markup=owner_buttons(order_id))
            return
        with open(result["zip"], "rb") as f:
            await app.bot.send_document(owner, f, filename=f"bot_order_{base}.zip",
                                        caption=report + "\nПосмотри и жми «Отдать».",
                                        reply_markup=owner_buttons(order_id) if order["buyer_id"] else None)


async def on_owner_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ctx.bot_data["owner"]:  # кнопку «Отдать» можно подделать из чужого клиента
        return
    action, order_id = q.data.split(":", 1)
    order_id = int(order_id)
    orders: Orders = ctx.bot_data["orders"]
    if action == "fix":
        await q.message.reply_text(f"Напиши, что поправить:\n/fix {root(orders, order_id)} что именно изменить")
        return
    if orders.get(order_id)["status"] != "ready":
        await q.message.reply_text(f"Заказ №{order_id} сейчас не готов к выдаче.")
        return
    try:
        await deliver(ctx.application, q.from_user.id, order_id)
    except TelegramError as e:
        await q.message.reply_text(f"Не получилось отправить заказчику: {e.message}")
        return
    await q.edit_message_reply_markup(None)
    await q.message.reply_text(f"🎁 Заказ №{order_id} отдан заказчику.")


async def on_buyer_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, order_id = q.data.split(":", 1)
    order_id = int(order_id)
    orders: Orders = ctx.bot_data["orders"]
    order = orders.get(order_id)
    if not order or order["buyer_id"] != q.from_user.id or orders.setting(f"blocked:{q.from_user.id}"):
        return
    owner = ctx.bot_data["owner"]
    if action == "ok":
        await q.edit_message_reply_markup(None)
        await q.message.reply_text("Спасибо! Рады, что всё работает 🙌 Если понадобится что-то ещё — пишите.")
        await ctx.bot.send_message(owner, f"⭐ Заказчик доволен заказом №{order_id}.")
        return
    orders.set_setting(f"await_change:{q.from_user.id}", str(order_id))
    await q.message.reply_text("Опишите одним сообщением, что поправить или что не работает — чем подробнее, "
                               "тем быстрее исправим.")


async def on_buyer_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Сообщение заказчика после «Нужно поправить»."""
    orders: Orders = ctx.bot_data["orders"]
    user_id = update.effective_user.id
    if orders.setting(f"blocked:{user_id}"):
        return
    pending = orders.setting(f"await_change:{user_id}")
    if not pending:
        await update.message.reply_text("Если нужно поправить готового бота — нажмите «Нужно поправить» под архивом.")
        return
    orders.set_setting(f"await_change:{user_id}", None)
    order_id, owner = int(pending), ctx.bot_data["owner"]
    order = orders.get(order_id)
    text = update.message.text
    try:
        raw = await factory.ask([{"role": "user", "content": CLASSIFY.format(spec=order["spec"] or order["title"],
                                                                          text=text)}])
        verdict = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except (factory.BuildError, ValueError):
        verdict = {"kind": "unclear"}
    await ctx.bot.send_message(owner, f"✏️ Заказчик №{order_id} просит: {text}"[:3000])

    if verdict.get("kind") == "fix":
        if order["revisions"] >= FREE_REVISIONS:
            await update.message.reply_text("Передал исполнителю — он посмотрит лично и напишет вам.")
            await ctx.bot.send_message(owner, f"⚠️ У заказа №{order_id} кончились бесплатные правки "
                                              f"({FREE_REVISIONS}). Реши сам: /fix {order_id} … или /refund {order_id}")
            return
        orders.add_revision(order_id)
        await update.message.reply_text(verdict.get("reply") or "Понял, исправляю — пришлю новую версию.")
        ctx.application.create_task(start_build(ctx.application, owner, order_id, verdict.get("comment") or text,
                                                free_fix=True))
    elif verdict.get("kind") == "new":
        # цену назвал ИИ по сообщению заказчика — его можно «уговорить», поэтому держим в разумных рамках
        stars = min(3000, max(150, int(verdict.get("stars") or 300)))
        child = orders.create(verdict.get("title") or "Доработка", stars, verdict.get("comment") or text,
                              parent_id=order_id)
        await update.message.reply_text(
            (verdict.get("reply") or "Этого не было в ТЗ, поэтому это отдельная доработка.") +
            f"\n\nСтоимость: {stars} ⭐. Оплатить: {pay_link(ctx.bot.username, child)}", disable_web_page_preview=True)
        await ctx.bot.send_message(owner, f"💡 Предложил доработку №{child} за {stars} ⭐ к заказу №{order_id}.")
    else:
        orders.set_setting(f"await_change:{user_id}", str(order_id))
        await update.message.reply_text(verdict.get("reply") or "Не совсем понял, что поправить — опишите, "
                                                                "пожалуйста, подробнее: что делаете и что происходит.")


async def build_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        order_id = int(ctx.args[0])
        assert ctx.bot_data["orders"].get(order_id)
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Формат: /build <номер заказа>")
        return
    ctx.application.create_task(start_build(ctx.application, update.effective_user.id, order_id))


async def fix_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        order_id, comment = int(ctx.args[0]), " ".join(ctx.args[1:]).strip()
        assert comment and (factory.BUILDS / f"order_{order_id}").exists()
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Формат: /fix <номер собранного заказа> <что поправить>")
        return
    ctx.application.create_task(start_build(ctx.application, update.effective_user.id, order_id, comment))


async def auto_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    orders: Orders = ctx.bot_data["orders"]
    if ctx.args and ctx.args[0] in ("on", "off"):
        orders.set_setting("auto_deliver", ctx.args[0])
    state = "выключена" if orders.setting("auto_deliver") == "off" else "включена"
    await update.message.reply_text(f"Автовыдача {state}: заказы до {REVIEW_FROM} ⭐ бот отдаёт сам, от {REVIEW_FROM} ⭐ "
                                    "— сначала тебе. Переключить: /auto on | /auto off")

