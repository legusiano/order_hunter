from stars_report import summarize

NOW = 1_800_000_000


def tx(amount, days_ago, **kw):
    return {"amount": amount, "date": NOW - days_ago * 86400, **kw}


def test_week_summary():
    transactions = [
        tx(600, 1, source={"type": "user"}),
        tx(900, 3, source={"type": "user"}),
        tx(600, 2, receiver={"type": "user"}),            # возврат
        tx(1000, 4, receiver={"type": "fragment"}),       # вывод
        tx(5000, 30, source={"type": "user"}),            # старая — не в этой неделе
    ]
    text = summarize(4300, transactions, NOW)
    assert "Пришло: 1500 ⭐ (2 оплат)" in text
    assert "Вернули: 600 ⭐ (1)" in text
    assert "Выведено: 1000 ⭐" in text
    assert "Баланс бота: 4300 ⭐" in text


def test_empty_week():
    text = summarize(0, [], NOW)
    assert "Пришло: 0 ⭐" in text and "Оплат пока не было" in text and "Вернули" not in text
