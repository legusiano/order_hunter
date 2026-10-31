from hunter import format_lead, matches


def test_matches_telegram_bots():
    assert matches("Разработка бота для Телеграм", "")
    assert matches("Нужен телеграм-бот для записи", "")
    assert matches("Нужен TG bot для магазина", "")
    assert matches("Чат бот", "нужен бот в тг, который принимает заявки")
    assert matches("Нужно мини-приложение в Telegram", "")
    assert matches("Нужен ИИ-ассистент в телеграм для салона", "отвечает клиентам и записывает")


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


def test_only_one_off_orders():
    assert matches("Нужен бот для Telegram", "бюджет 2000, срок неделя, пишите @me")
    assert matches("Кто может сделать телеграм-бота для кофейни?", "")
    assert not matches("Вакансия: Python-разработчик (Telegram-боты)", "удалённо, опыт от 2 лет")
    assert not matches("Разработчик Telegram-ботов в команду", "занятость полная")
    assert not matches("Пишу Telegram-ботов", "портфолио в профиле")  # реклама исполнителя, а не заказ


def test_relaxed_and_tagged():
    assert matches("Срочно нужен бот на пайтон в течении 1 недели", "")
    assert not matches("Бот для Android (Python + ADB)", "нужен бот")
    assert matches("Нужен чат-бот для сайта стоматологии", "бюджет 20000")  # с 28.10 берём любых ботов
    assert not matches("HeroComputer — разработка IT-проектов под ключ", "делаем ботов, оставьте заявку")
    # в рубрике заказов признак заказа не обязателен, а метка рубрики не считается словом «бот»
    assert matches("Чат бот", "Бот для приёма заявок в телеграм", tagged=True)
    assert not matches("ИИ-видео про исторические места", "#скрипты_боты_miniapp", tagged=True)


def test_budget():
    from hunter import budget
    assert budget("Бюджет: От 30,000 ₽ до 90,000 ₽") == 90000
    assert budget("до 5к, срочно") == 5000 and budget("бюджет 1.5 тыс") == 1500
    assert budget("15 000 р.") == 15000 and budget("без бюджета") == 0


def test_any_bot_platform_now_ok():
    assert matches("Нужен бот для VK", "бюджет 3000, пишите @me")
    assert matches("Нужен бот для Roblox-группы", "бюджет 3000, пишите @me")  # игры теперь берём
    assert not matches("Нужен чит-бот автофарм для Roblox", "бюджет 3000")  # а читы — нет


def test_one_off_work():
    assert matches("Нужен парсер Авито в Excel", "бюджет 2000, пишите @me")
    assert matches("Нужен лендинг для кофейни", "срок 3 дня, @me")
    assert not matches("Разработка сайтов, скриптов и автоматизации под ключ", "пишите @studio")


def test_junk_filtered():
    assert not matches("🚀 Как начать зарабатывать вместе с ГАЗПРОМ", "бот поможет, нужен только телефон")
    assert not matches("Софт для тг аккаунтов", "нужен инвайтинг и массовая рассылка", tagged=True)
    assert matches("Сделать бота на python", "бот принимает заявки", tagged=True)
