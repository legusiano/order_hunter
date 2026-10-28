from sales import decide


def agreed(stars, kind="telegram"):
    return {"stage": "agreed", "order": {"title": "Бот", "stars": stars, "spec": "ТЗ", "kind": kind}}


def test_new_order_and_limits():
    assert decide(agreed(900), None) == "create"
    assert decide(agreed(5000), None) == "owner"   # дороже 5000 ₽ — Кирилл сам
    assert decide(agreed(50), None) == "owner"     # «уговорили» ИИ на копейки — не выставляем
    assert decide({"stage": "talk", "order": None}, None) == "none"


def test_resend_and_repeat_customers():
    assert decide(agreed(900), "new") == "resend"          # счёт уже есть — прислать заново
    assert decide(agreed(900), "building") == "none"       # прошлый ещё в работе
    assert decide(agreed(900), "delivered") == "create"    # постоянный клиент заказывает второго бота
    assert decide(agreed(900), "refunded") == "create"


def test_minimum_is_300_stars():
    assert decide(agreed(300), None) == "create" and decide(agreed(299), None) == "owner"
