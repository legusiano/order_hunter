"""Касса: принимает оплату заказов звёздами в @zakaz_hunter_kirill_bot. Работает на компьютере Кирилла (long polling).

Заказчик открывает ссылку t.me/<бот>?start=order_<id> → бот показывает заказ и счёт в звёздах → после оплаты
владельцу приходит уведомление. Команды владельца:
  /order <звёзды> <что делаем> — создать заказ и получить ссылку на оплату
  /orders — последние заказы
  /refund <id> — вернуть звёзды за заказ
Охотник (hunter.py) шлёт сообщения тем же ботом, но обновления не читает, поэтому они не мешают друг другу.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import LabeledPrice, Update
from telegram.error import TelegramError
from telegram.ext import (Application, CommandHandler, ContextTypes, MessageHandler, PreCheckoutQueryHandler,
                          filters)

from orders import Orders, pay_link

load_dotenv(Path(__file__).parent / ".env")
OWNER = int(os.getenv("OWNER_CHAT_ID", "2093180872"))
STATUS = {"new": "🕓 ждёт оплаты", "paid": "✅ оплачен", "refunded": "↩️ возврат"}
log = logging.getLogger("cashier")


def is_owner(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == OWNER


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    orders: Orders = ctx.bot_data["orders"]
    arg = ctx.args[0] if ctx.args else ""
    if not arg.startswith("order_") or not arg[6:].isdigit():
        await update.message.reply_text("Привет! Здесь оплачивают заказы на ботов. Ссылку на оплату пришлёт "
                                        "исполнитель после того, как вы обсудите задачу.")
        return
    order = orders.get(int(arg[6:]))
    if problem := orders.can_pay(int(arg[6:]), order["stars"] if order else 0):
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
    problem = ctx.bot_data["orders"].can_pay(order_id, q.total_amount)
    await q.answer(ok=problem is None, error_message=problem)


async def paid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pay = update.message.successful_payment
    order_id = int(pay.invoice_payload.split(":", 1)[1])
    user = update.effective_user
    if not ctx.bot_data["orders"].mark_paid(order_id, user.id, user.username, pay.telegram_payment_charge_id):
        return
    await update.message.reply_text("Оплата получена, спасибо! 🙌 Приступаем к работе и напишем, когда бот будет готов.")
    who = f"@{user.username}" if user.username else f"id {user.id}"
    await ctx.bot.send_message(OWNER, f"💰 Заказ №{order_id} оплачен: {pay.total_amount} ⭐ от {who}")


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
    if not order or order["status"] != "paid":
        await update.message.reply_text("Формат: /refund <номер оплаченного заказа>")
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


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        filename=Path(__file__).parent / "cashier.log", encoding="utf-8")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.bot_data["orders"] = Orders()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("order", new_order))
    app.add_handler(CommandHandler("orders", list_orders))
    app.add_handler(CommandHandler("refund", refund))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
