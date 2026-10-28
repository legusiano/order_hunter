from datetime import datetime, timezone

from telegram import Chat, Message, MessageOriginChannel, MessageOriginHiddenUser, MessageOriginUser, User

from assist import code, who
from orders import Dialogs, Orders

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)
CHAT = Chat(1, "private")


def msg(origin=None) -> Message:
    return Message(10, NOW, CHAT, text="привет", forward_origin=origin)


def test_who_forwarded_client():
    client = User(42, "Иван", False, username="ivan")
    assert who(msg(MessageOriginUser(NOW, client))) == ("id42", "@ivan", False)


def test_who_hidden_user_and_leads():
    assert who(msg(MessageOriginHiddenUser(NOW, "Пётр")))[:2] == ("name:Пётр", "Пётр")
    hunter = User(7, "Охотник", True)
    assert who(msg(MessageOriginUser(NOW, hunter)))[2] is True
    channel = Chat(-100, "channel", username="devjobs")
    assert who(msg(MessageOriginChannel(NOW, channel, 5)))[2] is True


def test_who_plain_text():
    assert who(msg()) == (None, "", False)


def test_dialogs_keep_history_and_order():
    dialogs = Dialogs(Orders(":memory:").conn)
    dialogs.save("id42", [{"role": "user", "content": "привет"}])
    dialogs.set_active("id42")
    dialogs.save("id42", dialogs.history("id42") + [{"role": "assistant", "content": "{}"}], order_id=3)
    dialogs.save("id42", dialogs.history("id42"))  # без order_id — номер заказа не теряется
    assert len(dialogs.history("id42")) == 2 and dialogs.order_id("id42") == 3
    assert dialogs.active() == "id42" and dialogs.recent() == ["id42"]
    dialogs.reset("id42")
    assert dialogs.history("id42") == []


def test_code_escapes_html():
    assert code("<b>1 & 2</b>") == "<code>&lt;b&gt;1 &amp; 2&lt;/b&gt;</code>"
