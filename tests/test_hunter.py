from hunter import format_lead, matches


def test_matches_telegram_bots():
    assert matches("Разработка бота для Телеграм", "")
    assert matches("Нужен телеграм-бот для записи", "")
    assert matches("TG bot для магазина", "")
    assert matches("Чат бот", "нужен бот в тг, который принимает заявки")
    assert matches("Мини-приложение в Telegram", "")
    assert matches("ИИ-ассистент в телеграм для салона", "отвечает клиентам и записывает")


def test_skips_not_telegram():
    assert not matches("Разработка 3d модели", "пишите в телеграм")
    assert not matches("Нужен бот для автоматизированной работы Black Russia", "")
    assert not matches("Скрипт на n8n", "ChatGPT пишет посты")
    assert not matches("Голосовой бот на сайт", "звоните. Мой телеграм @me")
    assert not matches("Бот-разработчик для телеграм", "работа в штат, полный рабочий день")
    assert not matches("Косметолог", "ботокс, запись в телеграм")
    assert not matches("Личный ассистент руководителя", "резюме присылайте в телеграм")
    assert not matches("Python-разработчик", "Обязанности: разработка Telegram-ботов. Оклад 150к")
    assert not matches("Копирайтер-сценарист", "улучшать сообщения в Telegram-боте")


def test_format_lead():
    lead = {"source": "@devjobs", "title": "Чат бот", "body": "Чат бот для записи", "price": "до 500 ₽",
            "url": "https://t.me/devjobs/1"}
    assert format_lead(lead) == "🎯 @devjobs: Чат бот (до 500 ₽)\nдля записи\nhttps://t.me/devjobs/1"


def test_contact_from_post():
    from hunter import contact
    lead = {"source": "@digitaltender", "body": "Нужен бот. Канал @digitaltender, пишите @ivan_petrov или t.me/other"}
    assert contact(lead) == "ivan_petrov"
    assert contact({"source": "@x", "body": "через @SomeHelperBot и t.me/joinchat"}) is None


def test_write_button_prefills_text():
    from hunter import write_button
    url = write_button("ivan", "Привет! Делаю ботов")["inline_keyboard"][0][0]["url"]
    assert url.startswith("https://t.me/ivan?text=") and " " not in url
