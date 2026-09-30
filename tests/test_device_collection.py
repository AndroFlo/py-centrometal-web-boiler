"""Tests of the data model, without any network."""

from centrometal_web_boiler import WebBoilerDevice, WebBoilerParameter


async def test_callbacks_are_keyed():
    parameter = WebBoilerParameter()
    calls = []

    async def first(p):
        calls.append("first")

    async def second(p):
        calls.append("second")

    parameter.set_update_callback(first, "a")
    parameter.set_update_callback(second, "b")
    await parameter.update("X", 1)
    assert calls == ["first", "second"]

    parameter.set_update_callback(None, "a")
    parameter.set_update_callback(None, "missing")  # no error
    await parameter.update("X", 2)
    assert calls == ["first", "second", "second"]


async def test_get_parameter_creates_a_placeholder():
    device = WebBoilerDevice("user")
    assert not device.has_parameter("B_X")
    assert device.get_parameter("B_X")["value"] == "?"
    assert device.has_parameter("B_X")


async def test_update_without_timestamp_uses_now():
    device = WebBoilerDevice("user")
    parameter = await device.update_parameter("B_X", "3")
    assert parameter["value"] == "3"
    assert parameter["timestamp"] > 1_700_000_000
