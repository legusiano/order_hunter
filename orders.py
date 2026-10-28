"""Заказы и их оплата — общий SQLite-файл для кассы (cashier.py) и, позже, для ИИ, который пишет с аккаунта Кирилла:
тот создаёт заказ через create(), отдаёт заказчику pay_link(), а касса принимает звёзды.
"""

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "orders.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,              -- что делаем, коротко: это видит заказчик в счёте
    stars INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',  -- new → paid → (building → ready →) delivered | refunded
    buyer_id INTEGER,
    buyer_username TEXT,
    charge_id TEXT UNIQUE,            -- telegram_payment_charge_id, нужен для возврата
    created_at INTEGER NOT NULL,
    paid_at INTEGER
);
CREATE TABLE IF NOT EXISTS dialogs (
    client TEXT PRIMARY KEY,          -- id или имя заказчика, с которым переписывается Кирилл
    history TEXT NOT NULL,            -- JSON для ИИ-продавца: [{"role": "user"|"assistant", "content": ...}]
    order_id INTEGER,                 -- заказ, созданный по этой переписке
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Orders:
    def __init__(self, path: Path | str = DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(orders)")}
        if "spec" not in columns:  # ТЗ появилось вместе с фабрикой — старые базы дополняем
            self.conn.execute("ALTER TABLE orders ADD COLUMN spec TEXT NOT NULL DEFAULT ''")
            self.conn.commit()

    def create(self, title: str, stars: int, spec: str = "") -> int:
        if stars < 1 or not title.strip():
            raise ValueError("нужны название и цена от 1 звезды")
        cur = self.conn.execute("INSERT INTO orders (title, stars, spec, created_at) VALUES (?, ?, ?, ?)",
                                (title.strip()[:200], stars, spec.strip(), int(time.time())))
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
        self.set_status(order_id, "refunded")

    def set_status(self, order_id: int, status: str):
        self.conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        self.conn.commit()

    def recent(self, limit: int = 15) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


class Dialogs:
    """Переписки с заказчиками для режима «пересылаю сообщение — бот подсказывает ответ». Живут в том же файле."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def history(self, client: str) -> list[dict]:
        row = self.conn.execute("SELECT history FROM dialogs WHERE client = ?", (client,)).fetchone()
        return json.loads(row["history"]) if row else []

    def save(self, client: str, history: list[dict], order_id: int | None = None):
        self.conn.execute(
            "INSERT INTO dialogs (client, history, order_id, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(client) DO "
            "UPDATE SET history = excluded.history, order_id = COALESCE(excluded.order_id, dialogs.order_id), "
            "updated_at = excluded.updated_at",
            (client, json.dumps(history[-40:], ensure_ascii=False), order_id, int(time.time())))
        self.conn.commit()

    def order_id(self, client: str) -> int | None:
        row = self.conn.execute("SELECT order_id FROM dialogs WHERE client = ?", (client,)).fetchone()
        return row["order_id"] if row else None

    def reset(self, client: str):
        self.conn.execute("DELETE FROM dialogs WHERE client = ?", (client,))
        self.conn.commit()

    def recent(self, limit: int = 10) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT client FROM dialogs ORDER BY updated_at DESC LIMIT ?",
                                                (limit,))]

    # с кем сейчас переписка: к нему относятся сообщения, вставленные без пересылки
    def active(self) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE name = 'active_client'").fetchone()
        return row[0] if row else None

    def set_active(self, client: str):
        self.conn.execute("INSERT INTO settings (name, value) VALUES ('active_client', ?) ON CONFLICT(name) DO "
                          "UPDATE SET value = excluded.value", (client,))
        self.conn.commit()


def pay_link(bot_username: str, order_id: int) -> str:
    return f"https://t.me/{bot_username}?start=order_{order_id}"
