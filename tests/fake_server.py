"""A local imitation of web-boiler.com (website + STOMP broker) for the tests.

Only the behaviour the library relies on is reproduced. The payload shapes mirror the real ones.
"""

import json

import stomper
from aiohttp import web
from websockets.asyncio.server import serve

EMAIL = "user@example.com"
PASSWORD = "secret"
CSRF = "csrf-123"
DEVICE_ID = 4242
SERIAL = "ABC123"
DEVICE_TYPE = "biopl"

INSTALLATIONS = {
    "installations": [
        {
            "value": DEVICE_ID,
            "label": SERIAL,
            "place": "Home",
            "address": "1 Main Street",
            "type": DEVICE_TYPE,
            "product": "BioTec Plus",
        }
    ]
}

INSTALLATION_STATUS_ALL = {
    str(DEVICE_ID): {
        "installation": {"country": "France", "countryCode": "FR"},
        "params": {
            "B_Tak1_1": {"v": "55", "ut": "2026-09-30 10:00:00"},
            "B_STATE": {"v": "ON", "ut": "2026-09-30 10:00:00"},
        },
    }
}

PARAMETER_LIST = {
    "city": "Lyon",
    "parameters": [
        {"group": "Temperatures", "list": [{"dbindex": 12, "naslov": "Boiler"}]},
        {"group": "Heating circuits", "list": [{"naslov": "Circuit 1", "dbindex": 72}]},
        {"group": "Something new", "list": [{"x": 1}]},
    ],
}

GRID = {"widgets": [{"id": "w1", "template": "v3.timetable", "data": {"installation": DEVICE_ID}}]}


class FakeWebsite:
    """aiohttp application recording the commands it receives."""

    def __init__(self):
        self.commands: list[tuple[str, dict]] = []
        self.command_status = "success"
        app = web.Application()
        app.router.add_get("/login", self.login_page)
        app.router.add_post("/login_check", self.login_check)
        app.router.add_post("/data/autocomplete/installation", self.json(INSTALLATIONS))
        app.router.add_post("/api/configuration", self.json({"lang": "en"}))
        app.router.add_post("/api/widgets-grid/list", self.json({"selected": 7}))
        app.router.add_post("/api/widgets-grid", self.json({"grid": json.dumps(GRID)}))
        app.router.add_post(
            "/wdata/data/installation-status-all", self.json(INSTALLATION_STATUS_ALL)
        )
        app.router.add_post(f"/wdata/data/parameter-list/{SERIAL}", self.json(PARAMETER_LIST))
        app.router.add_post("/notifications/data/get", self.html("<div></div>"))
        app.router.add_post("/api/inst/control/multiple", self.control)
        app.router.add_post("/api/inst/control/{id}", self.control)
        self.app = app

    @staticmethod
    def json(payload):
        async def handler(request):
            return web.json_response(payload)

        return handler

    @staticmethod
    def html(body):
        async def handler(request):
            return web.Response(text=f"<html><body>{body}</body></html>", content_type="text/html")

        return handler

    async def login_page(self, request):
        return web.Response(
            text=f'<html><input type="hidden" name="_csrf_token" value="{CSRF}" /></html>',
            content_type="text/html",
        )

    async def login_check(self, request):
        form = await request.post()
        ok = (
            form["_csrf_token"] == CSRF
            and form["_username"] == EMAIL
            and form["_password"] == PASSWORD
        )
        body = '<div id="id-loading-screen-blackout"></div>' if ok else "<form>login</form>"
        return web.Response(text=f"<html><body>{body}</body></html>", content_type="text/html")

    async def control(self, request):
        self.commands.append((request.path, await request.json()))
        return web.json_response({"status": self.command_status})


class FakeBroker:
    """Minimal STOMP broker: answers CONNECTED, records subscriptions, pushes messages."""

    def __init__(self):
        self.received: list[str] = []
        self.subscriptions: dict[str, str] = {}  # destination -> subscription id
        self.connections = []
        self.server = None

    async def start(self):
        self.server = await serve(self.handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}/ws"

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def handler(self, websocket):
        self.connections.append(websocket)
        async for message in websocket:
            self.received.append(message)
            if message == "\n":
                continue
            frame = stomper.unpack_frame(message)
            if frame["cmd"] == "CONNECT":
                await websocket.send("CONNECTED\nversion:1.2\nheart-beat:0,0\n\n\x00")
            elif frame["cmd"] == "SUBSCRIBE":
                self.subscriptions[frame["headers"]["destination"]] = frame["headers"]["id"]

    async def push(self, destination: str, body: dict | str):
        body = body if isinstance(body, str) else json.dumps(body)
        frame = (
            f"MESSAGE\nsubscription:{self.subscriptions[destination]}\n"
            f"destination:{destination}\n\n{body}\x00"
        )
        for websocket in self.connections:
            await websocket.send(frame)

    async def drop_connections(self):
        for websocket in self.connections:
            await websocket.close(code=1011, reason="broker restart")
        self.connections.clear()
