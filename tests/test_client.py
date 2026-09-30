"""End-to-end tests of WebBoilerClient against the local fake Centrometal server."""

import logging

from tests.conftest import wait_until
from tests.fake_server import DEVICE_ID, DEVICE_TYPE, EMAIL, PASSWORD, SERIAL

TOPIC = f"/topic/cm.inst.{DEVICE_TYPE}.{SERIAL}"


async def connect(client, updates=None):
    """Log in, load the configuration and start the WebSocket like the integration does."""

    async def on_update(device, parameter, created=False):
        if updates is not None:
            updates.append((parameter["name"], parameter["value"], created))

    assert await client.login(EMAIL, PASSWORD)
    assert await client.get_configuration()
    await client.start_websocket(on_update)
    await wait_until(client.is_websocket_connected)


async def test_login_refused(client):
    assert not await client.login(EMAIL, "wrong")


async def test_password_is_never_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    await client.login(EMAIL, PASSWORD)
    assert PASSWORD not in caplog.text


async def test_configuration_builds_the_devices(client):
    assert await client.login(EMAIL, PASSWORD)
    assert await client.get_configuration()

    device = client.data[SERIAL]
    assert device["id"] == DEVICE_ID
    assert device["type"] == DEVICE_TYPE
    assert device["product"] == "BioTec Plus"
    assert device["country"] == "France"
    assert device["city"] == "Lyon"
    assert device.get_parameter("B_Tak1_1")["value"] == "55"
    # 2026-09-30 10:00:00 UTC
    assert device.get_parameter("B_Tak1_1")["timestamp"] == 1790762400
    assert 12 in device["temperatures"]
    assert "Circuit 1" in device["circuits"]
    assert device.get_widget_by_template("v3.timetable")["id"] == "w1"


async def test_real_time_updates(client, broker):
    updates = []
    await connect(client, updates)
    assert broker.subscriptions[TOPIC] == "sub-1"
    assert "/queue/notification" in broker.subscriptions

    received = []

    async def on_parameter(parameter):
        received.append(parameter["value"])

    parameter = client.data[SERIAL].get_parameter("B_Tak1_1")
    parameter.set_update_callback(on_parameter, "test")

    await broker.push(TOPIC, {"B_Tak1_1": "61", "UNKNOWN": "1"})
    await wait_until(lambda: "61" in received)
    assert parameter["value"] == "61"
    assert ("B_Tak1_1", "61", False) in updates
    # Parameters absent from the startup snapshot are not followed
    assert not client.data[SERIAL].has_parameter("UNKNOWN")


async def test_bad_frames_do_not_stop_updates(client, broker):
    await connect(client)
    await broker.push(TOPIC, "not json")
    await broker.push("/queue/notification", "maintenance tonight")
    await broker.push(TOPIC, {"B_STATE": "OFF"})
    await wait_until(lambda: client.data[SERIAL].get_parameter("B_STATE")["value"] == "OFF")
    assert client.is_websocket_connected()


async def test_heartbeats_are_answered(client, broker):
    await connect(client)
    before = broker.received.count("\n")
    await broker.connections[0].send("\n")
    await wait_until(lambda: broker.received.count("\n") > before)


async def test_disconnection_and_restart(client, broker):
    states = []

    async def on_connectivity(connected):
        states.append(connected)

    client.set_connectivity_callback(on_connectivity)
    await connect(client)
    await broker.drop_connections()
    await wait_until(lambda: not client.is_websocket_connected())
    assert states == [True, False]

    # What the integration does after a lost connection
    assert await client.relogin()
    await client.start_websocket(None)
    await wait_until(client.is_websocket_connected)
    assert states == [True, False, True]


async def test_close_websocket(client):
    await connect(client)
    assert await client.close_websocket()
    assert not client.is_websocket_connected()


async def test_connection_failure_is_reported(website):
    from centrometal_web_boiler import WebBoilerClient

    client = WebBoilerClient(webroot=website.url, stomp_url="ws://127.0.0.1:1/ws")
    states = []

    async def on_connectivity(connected):
        states.append(connected)

    client.set_connectivity_callback(on_connectivity)
    assert await client.login(EMAIL, PASSWORD)
    assert await client.get_configuration()
    await client.start_websocket(None)
    await wait_until(lambda: states == [False])
    assert not client.is_websocket_connected()
    await client.close_websocket()
    await client.http_client.close_session()


async def test_commands(client, website):
    assert await client.login(EMAIL, PASSWORD)
    assert await client.get_configuration()

    assert await client.turn(SERIAL, False)
    assert await client.turn_circuit(SERIAL, 72, True)
    assert await client.set_pellet_mode(SERIAL)
    assert website.commands == [
        (f"/api/inst/control/{DEVICE_ID}", {"cmd-name": "CMD", "cmd-value": 0}),
        ("/api/inst/control/multiple", {"messages": {str(DEVICE_ID): {"PWR 72": 1}}}),
        (f"/api/inst/control/{DEVICE_ID}", {"cmd-name": "SCCMD", "cmd-value": 1}),
    ]


async def test_refused_command_returns_false(client, website):
    assert await client.login(EMAIL, PASSWORD)
    assert await client.get_configuration()
    website.command_status = "error"
    assert not await client.set_pellet_mode(SERIAL)
    assert not await client.turn("UNKNOWN-SERIAL", True)


async def test_refresh(client, website):
    assert await client.login(EMAIL, PASSWORD)
    assert await client.get_configuration()
    assert await client.refresh(delay=0)
    assert website.commands == [
        ("/api/inst/control/multiple", {"messages": {str(DEVICE_ID): {"REFRESH": 0}}}),
        ("/api/inst/control/multiple", {"messages": {str(DEVICE_ID): {"RSTAT": "ALL"}}}),
    ]
