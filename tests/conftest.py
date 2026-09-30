import asyncio

import pytest
from aiohttp.test_utils import TestServer

from centrometal_web_boiler import WebBoilerClient
from tests.fake_server import FakeBroker, FakeWebsite


@pytest.fixture
async def website():
    fake = FakeWebsite()
    server = TestServer(fake.app, host="127.0.0.1")
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    yield fake
    await server.close()


@pytest.fixture
async def broker():
    fake = FakeBroker()
    fake.url = await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
async def client(website, broker):
    client = WebBoilerClient(webroot=website.url, stomp_url=broker.url)
    yield client
    await client.close_websocket()
    if client.http_client is not None:
        await client.http_client.close_session()


async def wait_until(condition, timeout=2.0):
    """Wait for a condition set by a background task (the WebSocket runs in one)."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)
