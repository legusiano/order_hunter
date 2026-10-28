"""Мастерская в кассе: после оплаты запускает фабрику (factory.py), присылает Кириллу архив с кнопками
«Отдать» / «Доработать», по «Отдать» отправляет бота заказчику. Сборки идут по одной, чтобы не путать ветки.

Команды владельца: /build <номер> — собрать заново, /fix <номер> <что поправить> — доработать готового бота.
"""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import factory
from orders import Orders

log = logging.getLogger("workshop")
lock = asyncio.Lock()


def buttons(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Отдать заказчику", callback_data=f"deliver:{order_id}"),
                                  InlineKeyboardButton("✏️ Доработать", callback_data=f"fix:{order_id}")]])


async def start_build(app, owner: int, order_id: int, comment: str | None = None):
    """Фоновая сборка заказа; всё, что происходит, сообщается владельцу."""
    orders: Orders = app.bot_data["orders"]
    order = orders.get(order_id)

    async def progress(text: str):
        await app.bot.send_message(owner, f"Заказ №{order_id}: {text}")

    async with lock:
        orders.set_status(order_id, "building")
        await progress("🛠 доработка начата…" if comment else "🛠 начал собирать бота по ТЗ…")
        try:
            result = await factory.build(order_id, order["title"], order["spec"], progress, comment)
        except factory.BuildError as e:
            orders.set_status(order_id, "failed")
            await progress(f"⚠️ {e}"[:3500] + f"\n\nМожно: /build {order_id} — ещё раз, /fix {order_id} <подсказка>, "
                           f"/refund {order_id} — вернуть звёзды.")
            return
        except Exception as e:  # git, gh, сеть — чтобы касса не падала из-за фабрики
            log.exception("сборка заказа %s", order_id)
            orders.set_status(order_id, "failed")
            await progress(f"⚠️ сборка сломалась: {e!r}"[:1000] + f"\nПовторить: /build {order_id}")
            return
        orders.set_status(order_id, "ready")
        caption = (f"📦 Заказ №{order_id} готов: {order['title']}\n"
                   f"Проверка на GitHub пройдена с {result['attempts']}-й попытки, тестов: {result['tests']}.\n"
                   f"Файлов в проекте: {len(result['files'])}. Посмотри и жми «Отдать».")
        with open(result["zip"], "rb") as f:
            await app.bot.send_document(owner, f, filename=f"bot_order_{order_id}.zip", caption=caption,
                                        reply_markup=buttons(order_id))


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, order_id = q.data.split(":", 1)
    order_id = int(order_id)
    orders: Orders = ctx.bot_data["orders"]
    order = orders.get(order_id)
    if action == "fix":
        await q.message.reply_text(f"Напиши, что поправить:\n/fix {order_id} что именно изменить")
        return
    if order["status"] != "ready":
        await q.message.reply_text(f"Заказ №{order_id} сейчас не готов к выдаче.")
        return
    if not order["buyer_id"]:
        await q.message.reply_text("У заказа нет покупателя (создан вручную) — архив выше, отправь его сам.")
        return
    try:
        with open(factory.BUILDS / f"order_{order_id}.zip", "rb") as f:
            await ctx.bot.send_document(
                order["buyer_id"], f, filename=f"bot_order_{order_id}.zip",
                caption=f"🎉 Ваш бот готов! Заказ №{order_id}: {order['title']}\n\n"
                        "Внутри README.md — пошаговая инструкция: как получить токен у @BotFather и запустить бота. "
                        "Если что-то не получается — напишите, поможем.")
    except TelegramError as e:
        await q.message.reply_text(f"Не получилось отправить заказчику: {e.message}")
        return
    orders.set_status(order_id, "delivered")
    await q.edit_message_reply_markup(None)
    await q.message.reply_text(f"🎁 Заказ №{order_id} отдан заказчику.")


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
