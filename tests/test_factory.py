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
    assert "tests/test_*.py" in missing({"bot/__main__.py": ""})
    full = {p: "" for p in ["requirements.txt", "README.md", ".env.example", "bot/__init__.py", "bot/__main__.py",
                             "tests/test_logic.py"]}
    assert missing(full) == []


def test_package_is_zip():
    data = package({"bot/__init__.py": "", "README.md": "# Бот\n"})
    assert data[:2] == b"PK"
