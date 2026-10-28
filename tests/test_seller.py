from seller import parse, typing_delay


def test_parse_json_answer():
    raw = 'вот: {"messages": ["привет", " ", "как дела"], "stage": "talk", "order": null} всё'
    assert parse(raw) == {"messages": ["привет", "как дела"], "stage": "talk", "order": None}


def test_parse_plain_text_fallback():
    assert parse("просто текст") == {"messages": ["просто текст"], "stage": "talk", "order": None}


def test_typing_delay_is_human():
    think, typing = typing_delay("x" * 300, first=True)
    assert 8 <= think <= 25 and 40 <= typing <= 45
    think, typing = typing_delay("ок")
    assert 1.5 <= think <= 5 and typing == 2.5


def test_parse_fixes_refund_wording():
    raw = '{"messages": ["если не по ТЗ — звёзды вернёте"], "stage": "agreed", "order": null}'
    assert parse(raw)["messages"] == ["если не по ТЗ — звёзды вернутся"]
