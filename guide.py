"""Инструкция по запуску для заказчика, который никогда не запускал программы: отправляется текстом вместе с архивом.
Переменные из .env.example конкретного бота подставляются в шаг 3 — чтобы было понятно, что именно вписать.
"""

import re

STEPS = """📘 Как запустить бота — по шагам, даже если вы никогда этого не делали

1️⃣ Токен бота
• Откройте @BotFather в Telegram → /newbot → придумайте имя и username (должен заканчиваться на bot).
• BotFather пришлёт токен вида 1234567890:AAH… — это ключ от бота, никому его не показывайте.
• Свой Telegram id узнайте у @userinfobot (число вида 123456789) — он нужен для админки.

2️⃣ Python (один раз)
• Скачайте Python 3.11 или новее: python.org → Downloads.
• При установке ОБЯЗАТЕЛЬНО поставьте галочку «Add Python to PATH», потом Install Now.

3️⃣ Настройки бота
• Распакуйте архив в папку, например на рабочий стол.
• Найдите файл .env.example, сделайте копию и назовите её .env (без .example).
• Откройте .env Блокнотом и впишите:
{variables}
• Сохраните файл.

4️⃣ Запуск (Windows)
• Откройте папку бота, щёлкните в адресную строку проводника, сотрите путь, напишите cmd и нажмите Enter — откроется чёрное окно уже в этой папке.
• По очереди вставьте команды (каждую — Enter):
python -m venv venv
venv\\Scripts\\activate
pip install -r requirements.txt
python -m bot
• Если появилось «Бот запущен» или строки без ошибок — напишите своему боту /start в Telegram. Готово! 🎉
• Бот работает, пока открыто это окно и включён компьютер. В следующий раз хватит двух команд: venv\\Scripts\\activate и python -m bot.

5️⃣ Чтобы бот работал круглосуточно
• Арендуйте недорогой сервер (VPS) с Ubuntu — от 150–300 ₽ в месяц, и запустите там. Как это сделать (команды и автозапуск) — в файле README.md в архиве.

❗ Частые проблемы
• «python не является командой» — переустановите Python с галочкой «Add Python to PATH» и откройте окно заново.
• «InvalidToken» / «Unauthorized» — в .env неправильный токен: скопируйте его из BotFather целиком, без пробелов и кавычек.
• Бот молчит — проверьте, что окно с ботом открыто и запущен только один экземпляр бота.
• Не открываются админ-команды — в ADMIN_IDS должен быть ваш id из @userinfobot.

Не получилось — нажмите «🆘 Не получается запустить» и опишите, что видите (можно скопировать текст ошибки), поможем."""

HINTS = {
    "BOT_TOKEN": "токен от @BotFather",
    "ADMIN_IDS": "ваш id из @userinfobot (несколько — через запятую)",
}


def variables(env_example: str) -> list[tuple[str, str]]:
    """Переменные из .env.example с подсказкой: комментарий над строкой или известная подсказка."""
    result, comment = [], ""
    for line in env_example.splitlines():
        line = line.strip()
        if line.startswith("#"):
            comment = line.lstrip("# ").strip()
            continue
        match = re.match(r"([A-Z][A-Z0-9_]*)\s*=", line)
        if match:
            name = match.group(1)
            result.append((name, HINTS.get(name) or comment or "см. README.md"))
        comment = ""
    return result


def build(env_example: str) -> str:
    items = variables(env_example) or [("BOT_TOKEN", HINTS["BOT_TOKEN"]), ("ADMIN_IDS", HINTS["ADMIN_IDS"])]
    lines = "\n".join(f"   {name}=… — {hint}" for name, hint in items)
    return STEPS.format(variables=lines)
