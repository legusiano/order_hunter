from hunter import format_lead, matches


def test_matches_bot_orders():
    assert matches("Разработка бота для Телеграм", "")
    assert matches("Нужен ИИ-ассистент для салона", "")
    assert matches("Мини-приложение в Telegram", "")
    assert matches("Сайт", "нужно подключить API нейросети GPT к форме")


def test_skips_noise():
    assert not matches("Разработка 3d модели", "пишите в телеграм")
    assert not matches("Логотип", "можно через нейросеть")
    assert not matches("Бот-разработчик", "работа в штат, полный рабочий день")
    assert not matches("Косметолог", "ботокс")


def test_format_lead():
    lead = {"source": "Kwork", "title": "Чат бот", "body": "Чат бот для записи", "price": "до 500 ₽",
            "url": "https://kwork.ru/projects/1"}
    assert format_lead(lead) == "🎯 Kwork: Чат бот (до 500 ₽)\nдля записи\nhttps://kwork.ru/projects/1"
