from app.config import _boolean, _optional_device


def test_optional_device_accepts_index_or_name() -> None:
    assert _optional_device(" 3 ") == 3
    assert _optional_device("USB Headset") == "USB Headset"
    assert _optional_device("  ") is None


def test_boolean_values() -> None:
    assert _boolean("true") is True
    assert _boolean("1") is True
    assert _boolean("no") is False
    assert _boolean(None) is False
