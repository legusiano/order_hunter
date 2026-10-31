"""Типы проектов, которые умеет собирать фабрика: стек для ИИ, обязательные файлы и инструкция заказчику.
Тип пишется в файл .kind в ветке bot_builds — по нему проверка на GitHub выбирает шаги (Python, Java, Luau).
"""

COMMON = """
Общее для любого проекта:
- README.md на русском для заказчика без опыта: что умеет (пункты ТЗ), как получить токены/доступы, как запустить
  на Windows и на Linux-сервере, как держать запущенным круглосуточно.
- Тексты для пользователей — на русском. Без заглушек и TODO: всё из ТЗ должно работать.
- Админские функции — только для ADMIN_IDS (если это бот).
"""

PYTHON_BOT = """
- Python 3.11. Хранение — SQLite (sqlite3), файл data/bot.db, папку создавай сам.
- Настройки только из окружения через python-dotenv; .env.example со всеми переменными и комментариями на русском.
- Пакет bot/: bot/__main__.py запускает бота (python -m bot); bot/__init__.py пустой.
  Логику (база, расчёты, тексты, проверки) вынеси в отдельные модули без сети — их покрывают тесты.
- ВАЖНО: импорт пакета bot и его модулей не должен ничего запускать и не должен ходить в сеть.
- tests/: pytest-тесты на логику, не меньше 5, без сети и без токена.
- requirements.txt с версиями.
"""

KINDS = {
    "telegram": {
        "title": "Telegram-бот",
        "stack": PYTHON_BOT + """
- python-telegram-bot 22 (async, Application.builder().token(...).build(), run_polling()); переменные BOT_TOKEN, ADMIN_IDS.
  requirements: python-telegram-bot>=22,<23 (с job_queue — python-telegram-bot[job-queue]>=22,<23) и python-dotenv.
- Бот обязан отвечать на /start (приветствие и меню) — его запускают против тестового Telegram и шлют /start.
- Кнопки (InlineKeyboard/ReplyKeyboard) там, где удобно. Оплата, если есть в ТЗ, — звёзды (currency="XTR").
- В README: токен у @BotFather, запуск, systemd-юнит для сервера.""",
        "required": ["requirements.txt", "README.md", ".env.example", "bot/__init__.py", "bot/__main__.py", "tests/*.py"],
    },
    "discord": {
        "title": "Discord-бот",
        "stack": PYTHON_BOT + """
- discord.py 2 (discord.Client или commands.Bot, slash-команды через app_commands); переменные DISCORD_TOKEN, ADMIN_IDS.
  requirements: discord.py>=2.3,<3 и python-dotenv. Включай только нужные intents и напиши в README, какие
  включить на портале.
- В README: Discord Developer Portal → New Application → Bot → токен, intents, ссылка-приглашение (OAuth2 URL
  Generator: bot + applications.commands), запуск, systemd-юнит.""",
        "required": ["requirements.txt", "README.md", ".env.example", "bot/__init__.py", "bot/__main__.py", "tests/*.py"],
    },
    "vk": {
        "title": "бот для VK",
        "stack": PYTHON_BOT + """
- vkbottle 4 (Bot(token=...), bot.run_forever()) для сообщества VK; переменные VK_TOKEN, ADMIN_IDS (id VK).
  requirements: vkbottle>=4.3,<5 и python-dotenv. Клавиатуры через vkbottle Keyboard.
- В README: управление сообществом → Работа с API → ключ доступа (права: сообщения), включить сообщения сообщества и
  Long Poll API (версия 5.199, тип «Входящее сообщение»), запуск, systemd-юнит.""",
        "required": ["requirements.txt", "README.md", ".env.example", "bot/__init__.py", "bot/__main__.py", "tests/*.py"],
    },
    "minecraft": {
        "title": "плагин для Minecraft-сервера",
        "stack": """
- Плагин для Paper 1.21 на Java 21, сборка Maven: pom.xml с репозиторием https://repo.papermc.io/repository/maven-public/
  и зависимостью io.papermc.paper:paper-api:1.21.1-R0.1-SNAPSHOT (scope provided), maven-compiler-plugin release 21.
- Код в src/main/java/<пакет>/, src/main/resources/plugin.yml (name, version, main, api-version: '1.21', команды и
  права), config.yml с настройками и комментариями на русском, если есть что настраивать.
- `mvn -q package` должен собирать target/*.jar без ошибок. Без Lombok и лишних зависимостей.
- В README: положить jar в папку plugins сервера Paper, перезапустить, команды и права, настройки config.yml.""",
        "required": ["pom.xml", "README.md", "src/main/resources/plugin.yml", "src/main/java/*.java"],
    },
    "roblox": {
        "title": "скрипты для Roblox",
        "stack": """
- Скрипты на Luau для Roblox Studio: src/server/*.server.luau (Script), src/client/*.client.luau (LocalScript),
  src/shared/*.luau (ModuleScript). Строгий синтаксис Luau — его проверяют luau-analyze.
- Только официальные возможности Roblox (никаких эксплойтов и обходов). Данные — DataStoreService с pcall.
- В README: куда положить каждый скрипт в Roblox Studio (ServerScriptService, StarterPlayerScripts,
  ReplicatedStorage), что настроить, как проверить в Play.""",
        "required": ["README.md", "src/*.luau"],
    },
    "script": {
        "title": "скрипт / парсер / автоматизация на Python",
        "stack": """
- Python 3.11. Точка входа main.py (python main.py), логику вынеси в модули рядом — их покрывают тесты.
- Настройки — через .env (python-dotenv) или config.json с комментариями в README; входные/выходные файлы — рядом.
- Парсинг сайтов — httpx + selectolax/BeautifulSoup с паузами между запросами; Excel — openpyxl; Google Таблицы —
  gspread (ключ сервис-аккаунта кладёт заказчик, в README — как его получить).
- tests/: pytest-тесты на логику без сети (сохранённый пример HTML в tests/), не меньше 3.
- requirements.txt с версиями. Импорт модулей не должен ничего запускать — запуск только из main.py.
- В README: что делает, установка Python, pip install -r requirements.txt, как запустить и где результат.
- Только законное: не парсить личные данные, не обходить защиту сайтов и капчи.""",
        "required": ["main.py", "requirements.txt", "README.md", "tests/*.py"],
    },
    "site": {
        "title": "одностраничный сайт / лендинг",
        "stack": """
- Чистые HTML + CSS + немного JS, без сборщиков: index.html, style.css, script.js, картинки — SVG прямо в коде
  или простые CSS-градиенты (чужие картинки не используй).
- Адаптивно для телефона, аккуратная современная вёрстка, мета-теги title/description, форма заявки ведёт на
  Telegram/почту из ТЗ (mailto: или ссылка t.me), без серверной части.
- Все ссылки на локальные файлы должны существовать — это проверяется.
- В README: как открыть, как поменять тексты и контакты, как бесплатно опубликовать (GitHub Pages / Netlify Drop).""",
        "required": ["index.html", "README.md"],
    },
}

GUIDES = {
    "discord": """📘 Как запустить Discord-бота
1️⃣ discord.com/developers → New Application → Bot → Reset Token — это токен, никому не показывайте.
   На той же странице включите intents, которые указаны в README.md.
2️⃣ OAuth2 → URL Generator: отметьте bot и applications.commands, права из README → откройте ссылку и добавьте бота
   на свой сервер.
3️⃣ Python 3.11+ с python.org (галочка «Add Python to PATH»).
4️⃣ В папке бота скопируйте .env.example в .env и впишите:
{variables}
5️⃣ В папке бота: в адресной строке проводника напишите cmd → Enter, затем по очереди:
python -m venv venv
venv\\Scripts\\activate
pip install -r requirements.txt
python -m bot
Бот работает, пока открыто окно. Для работы 24/7 — сервер (VPS), инструкция в README.md.
Не получилось — нажмите «🆘 Не получается запустить».""",
    "vk": """📘 Как запустить бота для VK
1️⃣ Ваше сообщество → Управление → Работа с API → Ключи доступа → Создать ключ (права: сообщения сообщества).
2️⃣ Там же Long Poll API: включить, версия 5.199, тип событий «Входящее сообщение». В «Сообщениях» включите
   сообщения сообщества.
3️⃣ Python 3.11+ с python.org (галочка «Add Python to PATH»).
4️⃣ В папке бота скопируйте .env.example в .env и впишите:
{variables}
5️⃣ В папке бота: в адресной строке проводника напишите cmd → Enter, затем по очереди:
python -m venv venv
venv\\Scripts\\activate
pip install -r requirements.txt
python -m bot
Напишите сообществу — бот ответит. Для работы 24/7 — сервер (VPS), инструкция в README.md.
Не получилось — нажмите «🆘 Не получается запустить».""",
    "minecraft": """📘 Как поставить плагин
1️⃣ Нужен сервер на Paper 1.21 (papermc.io). На обычном Vanilla-сервере плагины не работают.
2️⃣ Возьмите из архива файл .jar (папка dist) и положите в папку plugins вашего сервера.
3️⃣ Перезапустите сервер. В консоли появится строка о загрузке плагина.
4️⃣ Настройки — в plugins/<имя плагина>/config.yml, команды и права — в README.md.
Исходный код тоже в архиве. Не получилось — нажмите «🆘 Не получается запустить».""",
    "script": """📘 Как запустить скрипт
1️⃣ Python 3.11+ с python.org (при установке галочка «Add Python to PATH»).
2️⃣ Распакуйте архив. Если в архиве есть .env.example — скопируйте его в .env и впишите:
{variables}
3️⃣ В папке скрипта: в адресной строке проводника напишите cmd → Enter, затем по очереди:
pip install -r requirements.txt
python main.py
Где появится результат и какие настройки есть — написано в README.md.
Не получилось — нажмите «🆘 Не получается запустить».""",
    "site": """📘 Как открыть и опубликовать сайт
1️⃣ Распакуйте архив и дважды щёлкните index.html — сайт откроется в браузере.
2️⃣ Тексты и контакты меняются прямо в index.html (Блокнотом), подсказки — в README.md.
3️⃣ Бесплатно выложить в интернет: зайдите на app.netlify.com/drop и перетащите туда папку сайта — через минуту
   получите ссылку. Или GitHub Pages — инструкция в README.md.
Не получилось — нажмите «🆘 Не получается запустить».""",
    "roblox": """📘 Как добавить скрипты в Roblox
1️⃣ Откройте свой плейс в Roblox Studio.
2️⃣ Скрипты из src/server — в ServerScriptService (Script), из src/client — в StarterPlayer → StarterPlayerScripts
   (LocalScript), из src/shared — в ReplicatedStorage (ModuleScript). Имена — как у файлов, без расширения.
3️⃣ Если используются сохранения: Game Settings → Security → Enable Studio Access to API Services.
4️⃣ Нажмите Play и проверьте. Подробности — в README.md.
Не получилось — нажмите «🆘 Не получается запустить».""",
}


def get(kind: str | None) -> dict:
    return KINDS.get(kind or "telegram", KINDS["telegram"])
