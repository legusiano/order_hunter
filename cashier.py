"""Касса: принимает оплату заказов звёздами в @zakaz_hunter_kirill_bot. Работает на компьютере Кирилла (long polling).

Заказчик открывает ссылку t.me/<бот>?start=order_<id> → бот показывает заказ и счёт в звёздах → после оплаты
владельцу приходит уведомление. Команды владельца:
  /order <звёзды> <что делаем> — создать заказ и получить ссылку на оплату
  /orders — последние заказы
  /refund <id> — вернуть звёзды за заказ
После оплаты — фабрика собирает бота (workshop.py, factory.py): до 1500 ⭐ бот отдаёт его сам, от 1500 ⭐ — сначала
владельцу с «Отдать» / «Доработать». Заказчик может попросить правки прямо в боте.
Плюс режим «переписка через бота» (assist.py): пересланное сообщение заказчика → готовый ответ от ИИ-продавца.
Охотник (hunter.py) шлёт сообщения тем же ботом, но обновления не читает, поэтому они не мешают друг другу.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from telegram import LabeledPrice, Update
from telegram.error import TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
                          PreCheckoutQueryHandler, filters)

import assist
import hunter
import sales
import workshop
from orders import Dialogs, Orders, pay_link

load_dotenv(Path(__file__).parent / ".env")
OWNER = int(os.getenv("OWNER_CHAT_ID", "2093180872"))
MSK = timezone(timedelta(hours=3))
STATUS = {"new": "🕓 ждёт оплаты", "paid": "✅ оплачен", "building": "🛠 собирается", "ready": "📦 готов, ждёт «Отдать»",
          "failed": "⚠️ не собрался", "delivered": "🎁 отдан", "refunded": "↩️ возврат"}
log = logging.getLogger("cashier")


def is_owner(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == OWNER


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    orders: Orders = ctx.bot_data["orders"]
    arg = ctx.args[0] if ctx.args else ""
    if not arg.startswith("order_") or not arg[6:].isdigit():
        await sales.greet(update, ctx)  # пришёл сам — знакомится продавец
        return
    order = orders.get(int(arg[6:]))
    if problem := orders.can_pay(int(arg[6:]), order["stars"] if order else 0, update.effective_user.id):
        await update.message.reply_text(problem)
        return
    await update.message.reply_text(
        f"Заказ №{order['id']}: {order['title']}\nК оплате: {order['stars']} ⭐\n\n"
        "Если что-то пойдёт не так или бот не будет соответствовать ТЗ — звёзды вернутся.")
    await ctx.bot.send_invoice(update.effective_chat.id, title=f"Заказ №{order['id']}",
                               description=order["title"][:255], payload=f"order:{order['id']}",
                               currency="XTR", prices=[LabeledPrice("Разработка", order["stars"])])


async def precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    order_id = int(q.invoice_payload.split(":", 1)[1])
    problem = ctx.bot_data["orders"].can_pay(order_id, q.total_amount, q.from_user.id)
    await q.answer(ok=problem is None, error_message=problem)


async def paid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pay = update.message.successful_payment
    order_id = int(pay.invoice_payload.split(":", 1)[1])
    user = update.effective_user
    if not ctx.bot_data["orders"].mark_paid(order_id, user.id, user.username, pay.telegram_payment_charge_id):
        return
    order = ctx.bot_data["orders"].get(order_id)
    days = workshop.delivery_delay(order["stars"]) // 86400 if not order["parent_id"] else 1
    await update.message.reply_text(f"Оплата получена, спасибо! 🙌 Приступаем к работе — бот будет готов в течение "
                                    f"{'суток' if days == 1 else f'{days} дней'}, пришлём его сюда.")
    who = f"@{user.username}" if user.username else f"id {user.id}"
    await ctx.bot.send_message(OWNER, f"💰 Заказ №{order_id} оплачен: {pay.total_amount} ⭐ от {who}")
    ctx.application.create_task(workshop.start_build(ctx.application, OWNER, order_id))


async def new_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    try:
        stars, title = int(ctx.args[0]), " ".join(ctx.args[1:])
        order_id = ctx.bot_data["orders"].create(title, stars)
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /order <звёзды> <что делаем>\nНапример: /order 600 Бот записи в салон")
        return
    await update.message.reply_text(f"Заказ №{order_id} на {stars} ⭐. Ссылка для заказчика:\n"
                                    f"{pay_link(ctx.bot.username, order_id)}", disable_web_page_preview=True)


async def list_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    rows = ctx.bot_data["orders"].recent()
    if not rows:
        await update.message.reply_text("Заказов пока нет. Создать: /order <звёзды> <что делаем>")
        return
    lines = [f"№{o['id']} · {o['stars']} ⭐ · {STATUS[o['status']]} · {o['title'][:50]}" for o in rows]
    await update.message.reply_text("\n".join(lines))


async def refund(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    orders: Orders = ctx.bot_data["orders"]
    order = orders.get(int(ctx.args[0])) if ctx.args and ctx.args[0].isdigit() else None
    if not order or not order["charge_id"] or order["status"] == "refunded":
        await update.message.reply_text("Формат: /refund <номер оплаченного заказа>")
        return
    # бот уже у заказчика: возврат отдаёт ему и код, и звёзды — только осознанно
    if order["status"] == "delivered" and "force" not in ctx.args[1:]:
        await update.message.reply_text(f"Заказ №{order['id']} уже отдан — код у заказчика. Если всё равно вернуть "
                                        f"звёзды: /refund {order['id']} force")
        return
    try:
        await ctx.bot.refund_star_payment(order["buyer_id"], order["charge_id"])
    except TelegramError as e:
        await update.message.reply_text(f"Telegram не дал вернуть: {e.message}")
        return
    orders.mark_refunded(order["id"])
    await update.message.reply_text(f"↩️ Вернул {order['stars']} ⭐ за заказ №{order['id']}")
    try:
        await ctx.bot.send_message(order["buyer_id"], f"Звёзды за заказ №{order['id']} возвращены.")
    except TelegramError:
        pass


async def refunded_by_telegram(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Звёзды вернул сам Telegram (жалоба покупателя) — отмечаем заказ и больше не принимаем оплату от этого человека."""
    refund_info = update.message.refunded_payment if update.message else None
    if not refund_info:
        return
    orders: Orders = ctx.bot_data["orders"]
    order = orders.by_charge(refund_info.telegram_payment_charge_id)
    orders.set_setting(f"blocked:{update.effective_user.id}", "refund")
    if order:
        was_delivered = order["status"] == "delivered"
        orders.mark_refunded(order["id"])
        await ctx.bot.send_message(OWNER, f"🚨 Telegram вернул {refund_info.total_amount} ⭐ за заказ №{order['id']} "
                                          f"покупателю {update.effective_user.id}"
                                          f"{' — бот уже был отдан' if was_delivered else ''}. Покупатель заблокирован.")


def today() -> str:
    return datetime.now(MSK).strftime("%Y-%m-%d")


async def evening_summary(app: Application):
    """В 21:00 по Москве — итог дня владельцу."""
    orders: Orders = app.bot_data["orders"]
    while True:
        now = datetime.now(MSK)
        if now.hour >= 21 and orders.setting("summary_day") != today():
            start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            s = orders.day_stats(start)
            found = orders.setting(f"found:{today()}") or "0"
            text = (f"📊 Итог дня\n🎯 Найдено заказов: {found}\n🤝 Договорились: {s['created']}\n"
                    f"💰 Оплачено: {s['paid']} на {s['stars']} ⭐\n🎁 Отдано: {s['delivered']}")
            if s["in_work"]:
                text += f"\n🛠 В работе: {s['in_work']} (/orders)"
            await app.bot.send_message(OWNER, text)
            orders.set_setting("summary_day", today())
        await asyncio.sleep(300)


async def heartbeat():
    """Раз в 5 минут — пульс в базе dz_bot: сторож (dz_bot/watchdog.py) напишет, если компьютер выключен или
    касса упала. Без DATABASE_URL просто не работает."""
    url = os.getenv("DATABASE_URL")

    def beat():  # асинхронный psycopg на Windows не работает с циклом событий Telegram — пишем в отдельном потоке
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("INSERT INTO settings (name, value) VALUES ('cashier_heartbeat', %s) ON CONFLICT (name) "
                         "DO UPDATE SET value = EXCLUDED.value", (str(int(time.time())),))

    while url:
        try:
            await asyncio.to_thread(beat)
        except Exception:
            log.exception("не удалось записать пульс")
        await asyncio.sleep(300)


async def start_hunter(app: Application):
    orders: Orders = app.bot_data["orders"]
    app.create_task(heartbeat())

    def found(n: int):
        orders.set_setting(f"found:{today()}", str(int(orders.setting(f"found:{today()}") or 0) + n))

    app.create_task(hunter.loop(on_found=found))  # поиск заказов каждые 10 минут — в этом же процессе
    app.create_task(evening_summary(app))
    app.create_task(workshop.delivery_loop(app, OWNER))  # выдача готовых заказов по сроку


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        filename=Path(__file__).parent / "cashier.log", encoding="utf-8")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).post_init(start_hunter).build()
    app.bot_data["orders"] = Orders()
    app.bot_data["dialogs"] = Dialogs(app.bot_data["orders"].conn)
    app.bot_data["owner"] = OWNER
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("order", new_order))
    app.add_handler(CommandHandler("orders", list_orders))
    app.add_handler(CommandHandler("refund", refund))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    owner = filters.User(OWNER) & filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("clients", assist.list_clients, filters=owner))
    app.add_handler(CommandHandler("client", assist.switch_client, filters=owner))
    app.add_handler(CommandHandler("reset", assist.reset_client, filters=owner))
    app.add_handler(CommandHandler("build", workshop.build_cmd, filters=owner))
    app.add_handler(CommandHandler("fix", workshop.fix_cmd, filters=owner))
    app.add_handler(CommandHandler("auto", workshop.auto_cmd, filters=owner))
    app.add_handler(CallbackQueryHandler(workshop.on_owner_button, pattern=r"^(deliver|fix):\d+$"))
    app.add_handler(CallbackQueryHandler(workshop.on_buyer_button, pattern=r"^(ok|change|help):\d+$"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & ~filters.User(OWNER),
                                   workshop.on_buyer_text))
    app.add_handler(MessageHandler(filters.ALL, refunded_by_telegram), group=1)
    app.add_handler(MessageHandler(owner & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND, assist.on_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
