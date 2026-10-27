"""Заказы и их оплата — общий SQLite-файл для кассы (cashier.py) и, позже, для ИИ, который пишет с аккаунта Кирилла:
тот создаёт заказ через create(), отдаёт заказчику pay_link(), а касса принимает звёзды.
"""

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "orders.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,              -- что делаем, коротко: это видит заказчик в счёте
    stars INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',  -- new → paid → refunded
    buyer_id INTEGER,
    buyer_username TEXT,
    charge_id TEXT UNIQUE,            -- telegram_payment_charge_id, нужен для возврата
    created_at INTEGER NOT NULL,
    paid_at INTEGER
);
"""


class Orders:
    def __init__(self, path: Path | str = DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def create(self, title: str, stars: int) -> int:
        if stars < 1 or not title.strip():
            raise ValueError("нужны название и цена от 1 звезды")
        cur = self.conn.execute("INSERT INTO orders (title, stars, created_at) VALUES (?, ?, ?)",
                                (title.strip()[:200], stars, int(time.time())))
        self.conn.commit()
        return cur.lastrowid

    def get(self, order_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    def can_pay(self, order_id: int, stars: int) -> str | None:
        """None, если заказ можно оплатить этой суммой, иначе — почему нельзя (это увидит заказчик)."""
        order = self.get(order_id)
        if not order:
            return "Такого заказа нет. Напиши, пожалуйста, исполнителю."
        if order["status"] != "new":
            return "Этот заказ уже оплачен."
        if order["stars"] != stars:
            return "Цена заказа изменилась — открой ссылку на оплату ещё раз."
        return None

    def mark_paid(self, order_id: int, buyer_id: int, username: str | None, charge_id: str) -> bool:
        """False, если заказ уже был оплачен (Telegram может прислать оплату повторно)."""
        cur = self.conn.execute(
            "UPDATE orders SET status = 'paid', buyer_id = ?, buyer_username = ?, charge_id = ?, paid_at = ? "
            "WHERE id = ? AND status = 'new'", (buyer_id, username, charge_id, int(time.time()), order_id))
        self.conn.commit()
        return cur.rowcount == 1

    def mark_refunded(self, order_id: int):
        self.conn.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
        self.conn.commit()

    def recent(self, limit: int = 15) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def pay_link(bot_username: str, order_id: int) -> str:
    return f"https://t.me/{bot_username}?start=order_{order_id}"
