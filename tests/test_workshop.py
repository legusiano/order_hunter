import asyncio

import pytest
from telegram.error import TelegramError

import workshop
from orders import Orders


class App:
    def __init__(self, orders):
        self.bot_data = {"orders": orders, "owner": 1}


def test_deliver_refuses_unpaid_refunded_and_blocked():
    orders = Orders(":memory:")
    app = App(orders)
    unpaid = orders.create("Бот", 100)
    with pytest.raises(TelegramError):
        asyncio.run(workshop.deliver(app, 1, unpaid))

    refunded = orders.create("Бот", 100)
    orders.mark_paid(refunded, 7, None, "c1")
    orders.mark_refunded(refunded)
    with pytest.raises(TelegramError):
        asyncio.run(workshop.deliver(app, 1, refunded))

    blocked = orders.create("Бот", 100)
    orders.mark_paid(blocked, 8, None, "c2")
    orders.set_setting("blocked:8", "refund")
    with pytest.raises(TelegramError):
        asyncio.run(workshop.deliver(app, 1, blocked))


def test_clean_old_drops_stale_counters():
    import time as _time
    orders = Orders(":memory:")
    today = _time.strftime("%Y-%m-%d")
    orders.set_setting("msgs:7:2020-01-01", "40")
    orders.set_setting(f"msgs:7:{today}", "3")
    orders.set_setting("found:2020-01-01", "5")
    orders.set_setting(f"found:{today}", "2")
    asyncio.run(workshop.clean_old(orders))
    assert orders.setting("msgs:7:2020-01-01") is None and orders.setting(f"msgs:7:{today}") == "3"
    assert orders.setting("found:2020-01-01") is None and orders.setting(f"found:{today}") == "2"
