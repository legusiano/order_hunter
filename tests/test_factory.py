from factory import merge, missing, package, parse_files

ANSWER = """Вот проект:
=== FILE: bot/__main__.py ===
print("hi")
=== END ===
=== FILE: ../evil.py ===
x = 1
=== END ===
=== FILE: .github/workflows/x.yml ===
on: push
=== END ===
=== FILE: requirements.txt ===
python-telegram-bot>=22,<23
=== END ===
"""


def test_parse_files_skips_unsafe_paths():
    files = parse_files(ANSWER)
    assert set(files) == {"bot/__main__.py", "requirements.txt"}
    assert files["bot/__main__.py"] == 'print("hi")\n'


def test_merge_and_delete():
    files = {"a.py": "1\n", "b.py": "2\n"}
    assert merge(files, {"a.py": "3\n", "b.py": "DELETE\n", "c.py": "4\n"}) == {"a.py": "3\n", "c.py": "4\n"}


def test_missing_required_files():
    assert "tests/*.py" in missing({"bot/__main__.py": ""})
    full = {p: "" for p in ["requirements.txt", "README.md", ".env.example", "bot/__init__.py", "bot/__main__.py",
                             "tests/test_logic.py"]}
    assert missing(full) == []


def test_package_is_zip():
    data = package({"bot/__init__.py": "", "README.md": "# Бот\n"})
    assert data[:2] == b"PK"


def test_cleanup_removes_local_files(tmp_path, monkeypatch):
    import asyncio
    import factory
    monkeypatch.setattr(factory, "BUILDS", tmp_path)
    calls = []

    async def fake_run(*cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ("git", "branch") and "--list" in cmd:
            return "order-7-1\norder-7-2-fix123\n"
        if cmd[:3] == ("gh", "run", "list"):
            return '[{"databaseId": 11, "headBranch": "order-7-1"}, {"databaseId": 12, "headBranch": "order-70-1"}]'
        return ""
    monkeypatch.setattr(factory, "run", fake_run)
    (tmp_path / "order_7" / "bot").mkdir(parents=True)
    (tmp_path / "order_7" / "bot" / "__main__.py").write_text("x", encoding="utf-8")
    (tmp_path / "order_7.zip").write_bytes(b"PK")
    asyncio.run(factory.cleanup(7))
    assert not (tmp_path / "order_7").exists() and not (tmp_path / "order_7.zip").exists()
    assert ("git", "push", "-q", "origin", "--delete", "order-7-1", "order-7-2-fix123") in calls
    assert ("gh", "run", "delete", "11") in calls and ("gh", "run", "delete", "12") not in calls  # чужой заказ 70 не трогаем


def test_missing_by_kind():
    plugin = {"pom.xml": "", "README.md": "", "src/main/resources/plugin.yml": "", "src/main/java/me/kirill/Main.java": ""}
    assert missing(plugin, "minecraft") == []
    assert missing({"README.md": "", "src/server/Shop.server.luau": ""}, "roblox") == []
    assert missing({"README.md": ""}, "roblox") == ["src/*.luau"]
