"""Real-time connection: STOMP over a secure WebSocket.

STOMP is a small text protocol for message brokers. The exchange is:
1. open the WebSocket and send CONNECT; the broker answers CONNECTED;
2. SUBSCRIBE to one topic per boiler (/topic/cm.inst.<type>.<serial>) and to the notifications;
3. receive MESSAGE frames whose body is JSON {"<parameter>": <value>, ...}.

The broker also sends heart-beats (a lone newline). Answering a newline to every frame keeps the
connection alive on both sides.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

import stomper
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from centrometal_web_boiler.const import (
    WEB_BOILER_STOMP_DEVICE_TOPIC,
    WEB_BOILER_STOMP_HEARTBEATS,
    WEB_BOILER_STOMP_LOGIN_PASSCODE,
    WEB_BOILER_STOMP_LOGIN_USERNAME,
    WEB_BOILER_STOMP_NOTIFICATION_TOPIC,
    WEB_BOILER_STOMP_URL,
)

_LOGGER = logging.getLogger(__name__)

HEARTBEAT = "\n"


class WebBoilerWsClient:
    """Runs the WebSocket in a background task and reports events through callbacks.

    - connected_callback(frame): the broker accepted the connection (CONNECTED frame);
    - disconnected_callback(code, reason): the connection ended, for whatever reason;
    - error_callback(frame): the broker sent an ERROR frame;
    - data_callback(frame): a MESSAGE frame was received.
    """

    def __init__(
        self,
        connected_callback: Callable[[dict], Awaitable[None]],
        disconnected_callback: Callable[[int | None, str], Awaitable[None]],
        error_callback: Callable[[dict], Awaitable[None]],
        data_callback: Callable[[dict], Awaitable[None]],
        url: str = WEB_BOILER_STOMP_URL,
    ):
        self.logger = _LOGGER
        self.connected_callback = connected_callback
        self.disconnected_callback = disconnected_callback
        self.error_callback = error_callback
        self.data_callback = data_callback
        self.url = url
        self.username = ""
        self.subscription_index = 0
        self._websocket: ClientConnection | None = None
        self._task: asyncio.Task | None = None

    async def start(self, username: str) -> None:
        """Open the connection in the background (a running one is closed first)."""
        await self.close()
        self.username = username
        self.subscription_index = 0
        self.logger.info("Connecting to %s (%s)", self.url, self.username)
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def close(self) -> None:
        """Close the connection and wait for the background task to finish."""
        if self._websocket is not None:
            await self._websocket.close()
        if self._task is not None and self._task is not asyncio.current_task():
            if not self._task.done() and self._websocket is None:
                # Still connecting: nothing to close gracefully
                self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        code, reason = None, ""
        try:
            async with connect(self.url) as websocket:
                self._websocket = websocket
                await websocket.send(
                    stomper.connect(
                        WEB_BOILER_STOMP_LOGIN_USERNAME,
                        WEB_BOILER_STOMP_LOGIN_PASSCODE,
                        "/",
                        WEB_BOILER_STOMP_HEARTBEATS,
                    )
                )
                try:
                    async for message in websocket:
                        await self._on_message(message)
                except ConnectionClosed:
                    pass
                code, reason = websocket.close_code, websocket.close_reason or ""
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            # DNS, TLS, refused connection...
            self.logger.error("WebSocket connection failed: %s (%s)", ex, self.username)
            reason = str(ex)
        finally:
            self._websocket = None
        self.logger.warning(
            "WebSocket closed, code: %s, reason: %s (%s)", code, reason, self.username
        )
        await self.disconnected_callback(code, reason)

    async def _on_message(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            message = message.decode()
        await self.send(HEARTBEAT)
        if message == HEARTBEAT:
            return
        try:
            frame = stomper.unpack_frame(message)
            if frame["cmd"] == "CONNECTED":
                self.logger.info("STOMP connected (%s)", self.username)
                await self.connected_callback(frame)
            elif frame["cmd"] == "ERROR":
                await self.error_callback(frame)
            else:
                self.logger.debug("Frame received: %s (%s)", frame, self.username)
                await self.data_callback(frame)
        except Exception:
            # A frame we cannot handle must not stop the real-time updates
            self.logger.exception("Cannot handle the frame %r (%s)", message, self.username)

    async def send(self, content: str) -> None:
        if self._websocket is not None:
            await self._websocket.send(content)

    async def subscribe_to_notifications(self) -> None:
        await self.send(stomper.subscribe(WEB_BOILER_STOMP_NOTIFICATION_TOPIC, "sub-0", "auto"))

    async def subscribe_to_installation(self, device: dict) -> None:
        """Receive the real-time values of one boiler."""
        topic = f"{WEB_BOILER_STOMP_DEVICE_TOPIC}{device['type']}.{device['serial']}"
        self.subscription_index += 1
        self.logger.info("Subscribing to %s (%s)", topic, self.username)
        await self.send(stomper.subscribe(topic, f"sub-{self.subscription_index}", "auto"))
