from netguard import wifi_profile


def test_wifi_profile_en_and_ru():
    en = "    State                  : connected\n    SSID                   : Home\n    Profile                : Home 5G\n"
    ru = "    Состояние              : подключено\n    Профиль                : Дом\n"
    assert wifi_profile(en) == "Home 5G" and wifi_profile(ru) == "Дом"
    assert wifi_profile("    Connection mode        : Profile\n") is None
