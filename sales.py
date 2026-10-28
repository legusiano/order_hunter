"""Приём заказов прямо в боте: человек сам пишет @zakaz_hunter_kirill_bot — ИИ-продавец (seller.py) выясняет задачу,
торгуется, присылает ТЗ и счёт в звёздах. Дальше всё как обычно: оплата → фабрика → выдача по сроку.

В боте человек знает, что говорит с ботом, поэтому продавец честно представляется помощником Кирилла.
Крупные заказы (stage need_owner) — сообщение Кириллу, цену называет он.
"""

import asyncio
import json
import time

from telegram import LabeledPrice, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import seller
from orders import Dialogs, Orders

BIG_ORDER_RUB = 5000  # дороже — Кирилл ведёт сам
STAR_RUB = 1.3
DAILY_LIMIT = 40  # сообщений от одного человека в день — чтобы никто не «съел» деньги на ИИ
CONTEXT = ("Ты отвечаешь не в личке Кирилла, а в его Telegram-боте для заказов. Человек сам написал в бот. "
           "Представляйся помощником Кирилла (не самим Кириллом): «Я помощник Кирилла, принимаю заказы на ботов». "
           "Когда договоритесь — счёт на оплату звёздами бот пришлёт сам сразу после твоего сообщения.")
GREETING = ("Привет! 👋 Я помощник Кирилла — принимаю заказы на Telegram-ботов, ИИ-ассистентов и мини-приложения.\n\n"
            "Расскажите, что за бизнес или задача и что бот должен делать — подскажу решение, цену и срок.")


def key(user_id: int) -> str:
    return f"bot:{user_id}"


async def greet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(GREETING)


async def send_invoice(bot, chat_id: int, order) -> None:
    await bot.send_invoice(chat_id, title=f"Заказ №{order['id']}", description=order["title"][:255],
                           payload=f"order:{order['id']}", currency="XTR",
                           prices=[LabeledPrice("Разработка", order["stars"])])


def over_limit(orders: Orders, user_id: int) -> bool:
    name = f"msgs:{user_id}:{time.strftime('%Y-%m-%d')}"
    count = int(orders.setting(name) or 0) + 1
    orders.set_setting(name, str(count))
    return count > DAILY_LIMIT


async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    orders: Orders = ctx.bot_data["orders"]
    dialogs: Dialogs = ctx.bot_data["dialogs"]
    user = update.effective_user
    owner = ctx.bot_data["owner"]
    if over_limit(orders, user.id):
        await update.message.reply_text("На сегодня я уже много ответил 🙂 Напишите завтра — продолжим.")
        return

    history = dialogs.history(key(user.id))
    if not history:
        who = f"@{user.username}" if user.username else user.full_name
        await ctx.bot.send_message(owner, f"👤 Новый человек пишет в бота: {who}\n«{update.message.text[:300]}»")
    history.append({"role": "user", "content": update.message.text})
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        answer = await seller.reply(history, context=CONTEXT)
    except RuntimeError:
        await update.message.reply_text("Секунду, я сейчас немного занят — напишите чуть позже, пожалуйста.")
        await ctx.bot.send_message(owner, "⚠️ ИИ-продавец не ответил клиенту в боте — проверь баланс DeepSeek.")
        return
    history.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})

    order_id = dialogs.order_id(key(user.id))
    new_order = None
    big = answer.get("order") and int(answer["order"].get("stars") or 0) * STAR_RUB > BIG_ORDER_RUB
    if big:  # дороже 5000 ₽ договаривается Кирилл лично — счёт сами не выставляем
        answer["stage"] = "need_owner"
    if answer["stage"] == "agreed" and answer.get("order") and not order_id:
        try:
            new_order = orders.create(answer["order"]["title"], int(answer["order"]["stars"]),
                                      answer["order"].get("spec", ""), kind=answer["order"].get("kind") or "telegram")
        except (KeyError, TypeError, ValueError):
            new_order = None
    dialogs.save(key(user.id), history, new_order)

    for i, part in enumerate(answer["messages"]):
        if i:  # между сообщениями — «печатает…», как живой собеседник, но без долгих пауз
            await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
            await asyncio.sleep(min(6.0, 1.0 + len(part) / 60))
        await update.message.reply_text(part)

    if new_order:
        order = orders.get(new_order)
        if order["spec"]:
            await update.message.reply_text(f"📋 ТЗ по заказу №{new_order}:\n{order['spec']}")
        await send_invoice(ctx.bot, update.effective_chat.id, order)
        await ctx.bot.send_message(owner, f"🤝 В боте договорились: заказ №{new_order} на {order['stars']} ⭐ — "
                                          f"{order['title']}. Счёт отправлен.")
    elif answer["stage"] == "need_owner":
        who = f"@{user.username}" if user.username else f"id {user.id}"
        try:
            await ctx.bot.send_message(owner, f"💎 Крупный или нестандартный заказ в боте от {who} — напиши ему сам "
                                              f"в лс. Последнее: «{update.message.text[:300]}». Счёт: "
                                              f"/order <звёзды> <что делаем>, ссылку перешли ему.")
        except TelegramError:
            pass
