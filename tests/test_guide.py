from guide import build, variables

ENV = """# Токен от @BotFather
BOT_TOKEN=
# Кому доступна админка
ADMIN_IDS=
# Как часто проверять напоминания, секунд
CHECK_INTERVAL=10
"""


def test_variables_with_hints():
    assert variables(ENV) == [("BOT_TOKEN", "токен от @BotFather"),
                              ("ADMIN_IDS", "ваш id из @userinfobot (несколько — через запятую)"),
                              ("CHECK_INTERVAL", "Как часто проверять напоминания, секунд")]


def test_guide_has_steps_and_variables():
    text = build(ENV)
    assert "CHECK_INTERVAL=… — Как часто проверять" in text and "Add Python to PATH" in text
    assert r"venv\Scripts\activate" in text and len(text) < 4096  # одно сообщение Telegram


def test_guide_without_env_example():
    assert "BOT_TOKEN=…" in build("")


def test_guide_per_kind():
    assert "Discord Developer" in build("", "discord") or "discord.com/developers" in build("", "discord")
    assert "plugins" in build("", "minecraft") and "Roblox Studio" in build("", "roblox")
    assert "BotFather" in build("", "telegram")
