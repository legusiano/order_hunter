"""Режим «переписка через бота»: Кирилл пересылает боту сообщение заказчика — ИИ-продавец (seller.py) отвечает
готовым текстом, который остаётся скопировать и отправить. Бот помнит переписку с каждым заказчиком отдельно;
когда договорились, сам создаёт заказ в кассе и даёт ссылку на оплату с ТЗ.

Как пользоваться:
- переслать сообщение заказчика → бот пришлёт ответ (по сообщению на каждую часть, нажатие копирует текст);
- переслать заказ от охотника или пост из канала → бот напишет первое сообщение заказчику;
- просто вставить текст без пересылки → он относится к последнему заказчику;
- /clients — с кем переписка, /client N — переключиться, /reset — начать переписку с текущим заново.
"""

import html
import json

from telegram import Message, MessageOriginChannel, MessageOriginChat, MessageOriginHiddenUser, MessageOriginUser, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

import seller
from orders import Dialogs, Orders, pay_link


def who(message: Message) -> tuple[str | None, str, bool]:
    """(ключ заказчика, как его показать, это пост/заказ, а не сообщение заказчика)."""
    origin = message.forward_origin
    if isinstance(origin, MessageOriginUser):
        user = origin.sender_user
        if user.is_bot:  # переслали заказ от охотника
            return f"lead:{message.message_id}", "новый заказ", True
        name = f"@{user.username}" if user.username else user.full_name
        return f"id{user.id}", name, False
    if isinstance(origin, MessageOriginHiddenUser):  # у заказчика скрыт профиль при пересылке
        return f"name:{origin.sender_user_name}", origin.sender_user_name, False
    if isinstance(origin, (MessageOriginChannel, MessageOriginChat)):
        return f"lead:{message.message_id}", "заказ из канала", True
    return None, "", False


def code(text: str) -> str:
    # моноширинный текст в Telegram копируется одним нажатием
    return f"<code>{html.escape(text)}</code>"


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    orders: Orders = ctx.bot_data["orders"]
    dialogs: Dialogs = ctx.bot_data["dialogs"]
    message = update.message
    text = message.text or message.caption or ""
    client, label, is_lead = who(message)
    if client is None:
        client = dialogs.active()
        if client is None:
            await message.reply_text("Перешли мне сообщение заказчика (или заказ от охотника) — подскажу ответ.")
            return
        label = client.split(":", 1)[-1]
    dialogs.set_active(client)

    history = dialogs.history(client)
    if not is_lead:
        history.append({"role": "user", "content": text})
    await ctx.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
    try:
        answer = await seller.reply(history, lead=text if is_lead else None)
    except RuntimeError as e:
        await message.reply_text(f"ИИ сейчас не отвечает: {e}"[:500])
        return
    history.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})

    order_id = dialogs.order_id(client)
    new_order = None
    if answer["stage"] == "agreed" and answer.get("order") and not order_id:
        try:
            new_order = orders.create(answer["order"]["title"], int(answer["order"]["stars"]),
                                      answer["order"].get("spec", ""), kind=answer["order"].get("kind") or "telegram")
        except (KeyError, TypeError, ValueError):
            new_order = None
    dialogs.save(client, history, new_order)

    await message.reply_text(f"💬 Ответ для {html.escape(label)} — нажми на текст, чтобы скопировать:",
                             parse_mode=ParseMode.HTML)
    for part in answer["messages"]:
        await message.reply_text(code(part), parse_mode=ParseMode.HTML)

    if new_order:
        order = answer["order"]
        link = pay_link(ctx.bot.username, new_order)
        to_client = f"{order.get('spec', '').strip()}\n\nОплатить можно здесь: {link}".strip()
        await message.reply_text(f"✅ Договорились! Заказ №{new_order} на {order['stars']} ⭐ создан. "
                                 "Отправь заказчику ТЗ и ссылку на оплату:", parse_mode=ParseMode.HTML)
        await message.reply_text(code(to_client), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif answer["stage"] == "need_owner":
        await message.reply_text("⚠️ Заказ крупнее обычного — цену лучше назвать самому. Когда договоритесь: "
                                 "/order <звёзды> <что делаем>")
    elif answer["stage"] == "not_ours":
        await message.reply_text("ℹ️ Это не наш профиль — ИИ вежливо отказал.")


async def list_clients(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    dialogs: Dialogs = ctx.bot_data["dialogs"]
    clients = dialogs.recent()
    if not clients:
        await update.message.reply_text("Переписок пока нет — перешли сообщение заказчика.")
        return
    active = dialogs.active()
    lines = [f"{i}. {c.split(':', 1)[-1]}{' ← сейчас' if c == active else ''}" for i, c in enumerate(clients, 1)]
    await update.message.reply_text("\n".join(lines) + "\n\nПереключиться: /client <номер>")


async def switch_client(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    dialogs: Dialogs = ctx.bot_data["dialogs"]
    clients = dialogs.recent()
    try:
        client = clients[int(ctx.args[0]) - 1]
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /client <номер из /clients>")
        return
    dialogs.set_active(client)
    await update.message.reply_text(f"Теперь вставленный текст относится к {client.split(':', 1)[-1]}")


async def reset_client(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    dialogs: Dialogs = ctx.bot_data["dialogs"]
    if client := dialogs.active():
        dialogs.reset(client)
        await update.message.reply_text(f"Переписка с {client.split(':', 1)[-1]} начата заново.")
