import pytest

from orders import Orders, pay_link


@pytest.fixture
def orders():
    return Orders(":memory:")


def test_order_lifecycle(orders):
    order_id = orders.create("Бот записи в салон", 600)
    assert orders.can_pay(order_id, 600, 7) is None
    assert orders.mark_paid(order_id, 7, "client", "charge-1")
    assert orders.get(order_id)["status"] == "paid"
    assert "уже оплачен" in orders.can_pay(order_id, 600, 7)
    orders.mark_refunded(order_id)
    assert orders.get(order_id)["status"] == "refunded"


def test_payment_is_counted_once(orders):
    order_id = orders.create("Бот", 100)
    assert orders.mark_paid(order_id, 7, None, "charge-1")
    assert not orders.mark_paid(order_id, 7, None, "charge-1")


def test_wrong_amount_or_missing_order(orders):
    order_id = orders.create("Бот", 100)
    assert "Цена" in orders.can_pay(order_id, 50, 7)
    assert "нет" in orders.can_pay(999, 100, 7)


def test_bad_order_rejected(orders):
    with pytest.raises(ValueError):
        orders.create("Бот", 0)
    with pytest.raises(ValueError):
        orders.create("  ", 100)


def test_pay_link():
    assert pay_link("zakaz_hunter_kirill_bot", 42) == "https://t.me/zakaz_hunter_kirill_bot?start=order_42"


def test_revisions_parent_and_settings(orders):
    from workshop import root
    base = orders.create("Бот записи", 900, "ТЗ: запись")
    child = orders.create("Оплата картой", 300, "добавить оплату", parent_id=base)
    assert root(orders, child) == base and root(orders, base) == base
    assert orders.add_revision(base) == 1 and orders.add_revision(base) == 2
    orders.set_setting("auto_deliver", "off")
    assert orders.setting("auto_deliver") == "off"
    orders.set_setting("auto_deliver", None)
    assert orders.setting("auto_deliver") is None


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, stars INTEGER NOT NULL, "
                 "status TEXT NOT NULL DEFAULT 'new', buyer_id INTEGER, buyer_username TEXT, charge_id TEXT UNIQUE, "
                 "created_at INTEGER NOT NULL, paid_at INTEGER)")
    conn.commit()
    conn.close()
    order_id = Orders(path).create("Бот", 100, "ТЗ", parent_id=None)
    assert Orders(path).get(order_id)["revisions"] == 0


def test_only_parent_buyer_can_pay_for_revision(orders):
    base = orders.create("Бот", 900, "ТЗ")
    orders.mark_paid(base, 7, "client", "charge-base")
    child = orders.create("Доработка", 300, "добавить", parent_id=base)
    assert "чужому" in orders.can_pay(child, 300, 99)  # посторонний не получит код чужого бота за доплату
    assert orders.can_pay(child, 300, 7) is None


def test_blocked_buyer_cannot_pay(orders):
    order_id = orders.create("Бот", 100)
    orders.set_setting("blocked:7", "refund")
    assert "недоступна" in orders.can_pay(order_id, 100, 7)
    assert orders.can_pay(order_id, 100, 8) is None


def test_find_order_by_charge(orders):
    order_id = orders.create("Бот", 100)
    orders.mark_paid(order_id, 7, None, "charge-xyz")
    assert orders.by_charge("charge-xyz")["id"] == order_id and orders.by_charge("nope") is None
