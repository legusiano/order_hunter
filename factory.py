"""Фабрика ботов: по ТЗ оплаченного заказа ИИ пишет Telegram-бота, GitHub Actions проверяет его в чистой машине
(репозиторий legusiano/bot_builds, ветка order-<номер>-<попытка>), при ошибках ИИ чинит код по логам — до 3 попыток.
Готовый бот упаковывается в zip; отдаёт его заказчику касса после кнопки «Отдать» у Кирилла.

Сгенерированный код на этом компьютере не запускается — только в GitHub Actions.

Попробовать без заказа: python factory.py "ТЗ текстом"
"""

import asyncio
import io
import json
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

import seller

ROOT = Path(__file__).parent
BUILDS = ROOT / "builds"                       # локальные копии: builds/order_<id>/ и builds/order_<id>.zip
REPO = Path(r"C:\Users\USER\Desktop\bot_builds")  # клон legusiano/bot_builds, откуда пушатся ветки на проверку
ATTEMPTS = 3
REQUIRED = ["requirements.txt", "README.md", ".env.example", "bot/__init__.py", "bot/__main__.py"]

PROMPT = """Ты — сильный Python-разработчик Telegram-ботов. Напиши готовый к запуску проект бота строго по ТЗ.

Стек и правила:
- Python 3.11, python-telegram-bot 22 (async, Application.builder().token(...).build(), run_polling()).
- Хранение — SQLite (sqlite3 из стандартной библиотеки), файл data/bot.db, папку создавай сам.
- Настройки только из окружения через python-dotenv: BOT_TOKEN, ADMIN_IDS (id через запятую) и что ещё нужно по ТЗ.
- Пакет bot/: bot/__main__.py запускает бота (python -m bot); bot/__init__.py пустой или с версией.
  Логику (база, расчёты, тексты, проверки) вынеси в отдельные модули без обращения к сети — их покрывают тесты.
- ВАЖНО: импорт пакета bot и его модулей не должен ничего запускать и не должен ходить в сеть (только при python -m bot).
- tests/: pytest-тесты на логику (база во временном файле или :memory:), не меньше 5 тестов, без сети и без токена.
- requirements.txt с версиями: python-telegram-bot>=22,<23 и python-dotenv; другое — только если без этого никак.
  Если используешь application.job_queue — пиши python-telegram-bot[job-queue]>=22,<23, иначе job_queue будет None.
- Бот обязан отвечать на /start (приветствие и главное меню) — его запускают против тестового Telegram и шлют /start.
- .env.example со всеми переменными и комментариями на русском.
- README.md на русском для заказчика без опыта: что умеет бот (пункты ТЗ), как получить токен у @BotFather,
  как запустить на Windows и на Linux-сервере (python -m venv, pip install -r requirements.txt, python -m bot),
  как держать бота запущенным на сервере (systemd-юнит в README).
- Интерфейс бота — на русском, кнопки (InlineKeyboard/ReplyKeyboard) там, где это удобно пользователю.
- Админские функции — только для ADMIN_IDS.
- Если в ТЗ есть оплата — звёзды Telegram (currency="XTR", без provider_token).
- Без заглушек и TODO: всё из ТЗ должно работать.

Ответ — только файлы в таком формате, без пояснений до и после:
=== FILE: путь/к/файлу ===
содержимое
=== END ===
"""

FIX = """Проверка в чистой машине упала. Вот лог (конец):
{log}

Исправь проект. Пришли ТОЛЬКО изменённые или новые файлы целиком в том же формате (=== FILE: ... === / === END ===).
Если нужно удалить файл — пришли его с единственной строкой DELETE."""

REVISE = """Заказчик/исполнитель просит доработать: {comment}

Внеси правки. Пришли ТОЛЬКО изменённые или новые файлы целиком в том же формате (=== FILE: ... === / === END ===)."""

FILE_RE = re.compile(r"^=== FILE: (.+?) ===\n(.*?)^=== END ===", re.S | re.M)
SAFE_PATH = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_\-./]+$")


class BuildError(Exception):
    pass


def parse_files(text: str) -> dict[str, str]:
    files = {}
    for path, content in FILE_RE.findall(text.replace("\r\n", "\n")):
        path = path.strip().strip("`")
        if not SAFE_PATH.match(path) or path.startswith(".git"):
            continue  # никаких ../ и служебных папок git
        files[path] = content if content.endswith("\n") else content + "\n"
    return files


def merge(files: dict[str, str], changes: dict[str, str]) -> dict[str, str]:
    result = dict(files)
    for path, content in changes.items():
        if content.strip() == "DELETE":
            result.pop(path, None)
        else:
            result[path] = content
    return result


def missing(files: dict[str, str]) -> list[str]:
    absent = [p for p in REQUIRED if p not in files]
    if not any(p.startswith("tests/") and p.endswith(".py") for p in files):
        absent.append("tests/test_*.py")
    return absent


def files_prompt(files: dict[str, str]) -> str:
    return "\n".join(f"=== FILE: {p} ===\n{c}=== END ===" for p, c in sorted(files.items()))


async def ask(messages: list[dict]) -> str:
    errors = []
    for client, model in seller.clients():
        # DeepSeek сначала «думает» и на полном усилии съедает весь лимит рассуждениями — код не помещается
        extra = {"reasoning_effort": "low"} if model.startswith("deepseek") else None
        try:
            r = await client.chat.completions.create(model=model, messages=messages, temperature=0.2,
                                                     max_tokens=32000, extra_body=extra)
            text = r.choices[0].message.content or ""
            if text.strip():
                return text
            errors.append(f"{model}: пустой ответ ({r.choices[0].finish_reason})")
        except Exception as e:  # кончились деньги, нет сети, регион — пробуем следующий ИИ
            errors.append(f"{model}: {e}")
    raise BuildError("ни один ИИ не ответил: " + "; ".join(errors))


async def run(*cmd: str, cwd: Path = REPO, check: bool = True) -> str:
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    out = (await proc.communicate())[0].decode("utf-8", "replace")
    if check and proc.returncode:
        raise BuildError(f"{' '.join(cmd[:3])}: {out[-500:]}")
    return out


async def check_on_github(branch: str, files: dict[str, str]) -> tuple[bool, str]:
    """Кладёт файлы в ветку bot_builds, пушит и ждёт проверку. (прошла ли, конец лога при ошибке)."""
    await run("git", "checkout", "-q", "main")
    await run("git", "checkout", "-q", "-B", branch)
    for item in REPO.iterdir():  # всё, кроме .git, .github и README, заменяем файлами бота
        if item.name not in (".git", ".github", "README.md"):
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    for path, content in files.items():
        target = REPO / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    await run("git", "add", "-A")
    await run("git", "commit", "-q", "-m", f"{branch}")
    await run("git", "push", "-q", "-f", "origin", branch)
    sha = (await run("git", "rev-parse", "HEAD")).strip()
    await run("git", "checkout", "-q", "main")

    run_id = None
    for _ in range(60):  # ждём, пока GitHub заведёт запуск (до ~5 минут)
        await asyncio.sleep(5)
        runs = json.loads(await run("gh", "run", "list", "--branch", branch, "--json", "databaseId,headSha,status,conclusion"))
        mine = [r for r in runs if r["headSha"] == sha]
        if mine and mine[0]["status"] == "completed":
            run_id = mine[0]["databaseId"]
            if mine[0]["conclusion"] == "success":
                return True, ""
            break
    if run_id is None:
        return False, "проверка на GitHub не завершилась за 5 минут"
    log = await run("gh", "run", "view", str(run_id), "--log-failed", check=False)
    lines = [line.split("\t", 2)[-1] for line in log.splitlines()]
    return False, "\n".join(lines[-150:])


def package(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in sorted(files.items()):
            z.writestr(path, content)
    return buf.getvalue()


def save(order_id: int, files: dict[str, str]):
    BUILDS.mkdir(exist_ok=True)
    folder = BUILDS / f"order_{order_id}"
    if folder.exists():
        shutil.rmtree(folder)
    for path, content in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_text(content, encoding="utf-8", newline="\n")
    (BUILDS / f"order_{order_id}.zip").write_bytes(package(files))


async def cleanup(order_id: int):
    """Заказ закрыт: удаляем с компьютера папку, архив и ветки сборки (локальные и на GitHub), чтобы не копилось."""
    shutil.rmtree(BUILDS / f"order_{order_id}", ignore_errors=True)
    (BUILDS / f"order_{order_id}.zip").unlink(missing_ok=True)
    branches = (await run("git", "branch", "--list", f"order-{order_id}-*", check=False)).split()
    branches = [b for b in branches if b.startswith(f"order-{order_id}-")]
    if branches:
        await run("git", "checkout", "-q", "main", check=False)
        await run("git", "branch", "-D", *branches, check=False)
        await run("git", "push", "-q", "origin", "--delete", *branches, check=False)
        await run("git", "gc", "-q", "--prune=now", check=False)


def load(order_id: int) -> dict[str, str]:
    folder = BUILDS / f"order_{order_id}"
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in folder.rglob("*") if p.is_file()}


async def build(order_id: int, title: str, spec: str, progress=None, comment: str | None = None) -> dict:
    """Собирает (или дорабатывает по comment) бота. Возвращает {"files", "zip", "attempts", "tests"}."""
    async def say(text: str):
        if progress:
            await progress(text)

    task = f"Заказ: {title}\n\nТЗ:\n{spec or title}"
    if comment:
        files = load(order_id)
        messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": task},
                    {"role": "assistant", "content": files_prompt(files)},
                    {"role": "user", "content": REVISE.format(comment=comment)}]
        files = merge(files, parse_files(await ask(messages)))
    else:
        messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": task}]
        files = parse_files(await ask(messages))

    suffix = f"-fix{int(time.time()) % 100000}" if comment else ""
    reviewed, attempt, gaps = False, 0, []
    while True:
        attempt += 1
        if absent := missing(files):
            ok, log = False, "в проекте не хватает файлов: " + ", ".join(absent)
        else:
            await say(f"🔎 Попытка {attempt}: проверяю код на GitHub…")
            ok, log = await check_on_github(f"order-{order_id}-{attempt}{suffix}", files)
        if ok and not reviewed:
            # тесты прошли — второй проход: всё ли из ТЗ сделано. Без этого автовыдача отдала бы «пустышку»
            reviewed = True
            gaps = await review(task, files)
            if gaps:
                await say("🧐 Самопроверка по ТЗ: доделываю — " + "; ".join(gaps)[:500])
                messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": task},
                            {"role": "assistant", "content": files_prompt(files)},
                            {"role": "user", "content": REVISE.format(comment="не реализовано по ТЗ: " + "; ".join(gaps))}]
                files = merge(files, parse_files(await ask(messages)))
                continue
        if ok:
            save(order_id, files)
            tests = sum(len(re.findall(r"^(?:async )?def test_", c, re.M)) for p, c in files.items() if p.startswith("tests/"))
            return {"files": files, "zip": BUILDS / f"order_{order_id}.zip", "attempts": attempt, "tests": tests,
                    "gaps_fixed": gaps}
        if attempt >= ATTEMPTS + (1 if reviewed else 0):
            save(order_id, files)  # чтобы можно было доработать вручную
            raise BuildError(f"не собрался за {attempt} попытки. Последняя ошибка:\n{log[-1500:]}")
        await say(f"🔧 Попытка {attempt} не прошла, ИИ исправляет…")
        messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": task},
                    {"role": "assistant", "content": files_prompt(files)},
                    {"role": "user", "content": FIX.format(log=log[-6000:])}]
        files = merge(files, parse_files(await ask(messages)))


REVIEW = """Ты — строгий проверяющий. Сверь проект с ТЗ по каждому пункту: реализован ли он по-настоящему (не заглушка,
не TODO, есть обработчик/кнопка/логика, которые этот пункт делают).

{task}

Проект:
{files}

Ответ — только JSON: {{"missing": ["пункт ТЗ, который не сделан или сделан не полностью — коротко"]}}.
Если всё сделано — {{"missing": []}}."""


async def review(task: str, files: dict[str, str]) -> list[str]:
    text = await ask([{"role": "user", "content": REVIEW.format(task=task, files=files_prompt(files))}])
    try:
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
        return [str(x).strip() for x in data.get("missing", []) if str(x).strip()][:8]
    except ValueError:
        return []  # проверяющий ответил не по формату — не блокируем выдачу, тесты уже прошли


async def _demo(spec: str):
    async def show(text):
        print(text)
    result = await build(0, "Тестовый заказ", spec, progress=show)
    print(f"Готово за {result['attempts']} попыток, тестов: {result['tests']}, архив: {result['zip']}")


if __name__ == "__main__":
    asyncio.run(_demo(" ".join(sys.argv[1:]) or "Бот-напоминалка: пользователь пишет «напомни через 10 минут "
                                                    "купить хлеб», бот напоминает. Список напоминаний и удаление."))
