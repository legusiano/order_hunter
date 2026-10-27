import pytest

from orders import Orders, pay_link


@pytest.fixture
def orders():
    return Orders(":memory:")


def test_order_lifecycle(orders):
    order_id = orders.create("Бот записи в салон", 600)
    assert orders.can_pay(order_id, 600) is None
    assert orders.mark_paid(order_id, 7, "client", "charge-1")
    assert orders.get(order_id)["status"] == "paid"
    assert "уже оплачен" in orders.can_pay(order_id, 600)
    orders.mark_refunded(order_id)
    assert orders.get(order_id)["status"] == "refunded"


def test_payment_is_counted_once(orders):
    order_id = orders.create("Бот", 100)
    assert orders.mark_paid(order_id, 7, None, "charge-1")
    assert not orders.mark_paid(order_id, 7, None, "charge-1")


def test_wrong_amount_or_missing_order(orders):
    order_id = orders.create("Бот", 100)
    assert "Цена" in orders.can_pay(order_id, 50)
    assert "нет" in orders.can_pay(999, 100)


def test_bad_order_rejected(orders):
    with pytest.raises(ValueError):
        orders.create("Бот", 0)
    with pytest.raises(ValueError):
        orders.create("  ", 100)


def test_pay_link():
    assert pay_link("zakaz_hunter_kirill_bot", 42) == "https://t.me/zakaz_hunter_kirill_bot?start=order_42"
