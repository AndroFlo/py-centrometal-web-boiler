"""Public entry point of the library.

Typical use (this is what the Home Assistant integration does):

    client = WebBoilerClient()
    await client.login(email, password)          # HTTPS login
    await client.get_configuration()             # boilers and current values -> client.data
    await client.start_websocket(on_update)      # real-time updates
    await client.refresh()                       # ask the boilers to push every value
    await client.turn(serial, True)              # commands
    ...
    await client.close_websocket()
    await client.http_client.close_session()
"""

import asyncio
import logging

from centrometal_web_boiler.const import WEB_BOILER_STOMP_URL, WEB_BOILER_WEBROOT
from centrometal_web_boiler.HttpClient import HttpClient
from centrometal_web_boiler.HttpHelper import HttpHelper
from centrometal_web_boiler.WebBoilerDeviceCollection import WebBoilerDeviceCollection
from centrometal_web_boiler.WebBoilerWsClient import WebBoilerWsClient

_LOGGER = logging.getLogger(__name__)


class WebBoilerClient:
    """Connection to the Centrometal cloud for one user account."""

    def __init__(self, webroot: str = WEB_BOILER_WEBROOT, stomp_url: str = WEB_BOILER_STOMP_URL):
        self.logger = _LOGGER
        self.webroot = webroot
        self.username = ""
        self.password = ""
        self.http_client: HttpClient | None = None
        self.http_helper: HttpHelper | None = None
        self.data = WebBoilerDeviceCollection("")
        self.websocket_connected = False
        self.connectivity_callback = None
        self.on_parameter_updated_callback = None
        self.ws_client = WebBoilerWsClient(
            self.ws_connected_callback,
            self.ws_disconnected_callback,
            self.ws_error_callback,
            self.ws_data_callback,
            url=stomp_url,
        )

    # ------------------------------------------------------------------ connection

    async def login(self, username: str, password: str) -> bool:
        """Log in to the website. Returns False if the credentials are refused."""
        self.logger.info("Logging in (%s)", username)
        if self.http_client is not None:
            await self.http_client.close_session()
        self.username = username
        self.password = password
        self.http_client = HttpClient(username, password, webroot=self.webroot)
        self.http_helper = HttpHelper(self.http_client)
        self.data = WebBoilerDeviceCollection(username)
        return await self.http_client.login()

    async def relogin(self) -> bool:
        """Log in again with a fresh session (after an expired session or a lost connection)."""
        await self.http_client.reinitialize_session()
        return await self.http_client.login()

    async def get_configuration(self) -> bool:
        """Load the boilers of the account and their current values into self.data.

        Returns False if the account has no boiler.
        """
        http = self.http_client
        await http.get_installations()
        if self.http_helper.get_device_count() == 0:
            self.logger.warning("There is no boiler on this account (%s)", self.username)
            return False
        self.data.parse_installations(http.installations)
        await asyncio.gather(http.get_configuration(), http.get_widgetgrid_list())
        await asyncio.gather(
            http.get_widgetgrid(http.widgetgrid_list["selected"]),
            http.get_installation_status_all(self.http_helper.get_all_devices_ids()),
            *(
                http.get_parameter_list(serial)
                for serial in self.http_helper.get_all_devices_serials()
            ),
            http.get_notifications(),
        )
        await self.data.parse_installation_statuses(http.installation_status_all)
        self.data.parse_parameter_lists(http.parameter_list)
        self.data.parse_grid(http)
        return True

    async def start_websocket(self, on_parameter_updated_callback) -> None:
        """Start receiving real-time values.

        on_parameter_updated_callback(device, parameter, created=False) is awaited for every
        update (and for every parameter, with created=True, when the connection state changes).
        """
        self.logger.info("Starting the WebSocket (%s)", self.username)
        self.on_parameter_updated_callback = on_parameter_updated_callback
        await self.ws_client.start(self.username)

    async def close_websocket(self) -> bool:
        try:
            await self.ws_client.close()
            return True
        except Exception:
            self.logger.exception("Closing the WebSocket failed (%s)", self.username)
            return False

    def is_websocket_connected(self) -> bool:
        return self.websocket_connected

    def set_connectivity_callback(self, connectivity_callback) -> None:
        """connectivity_callback(connected: bool) is awaited when the WebSocket goes up or down."""
        self.connectivity_callback = connectivity_callback

    async def refresh(self, delay: float = 2) -> bool:
        """Ask every boiler to push all its values again (they arrive on the WebSocket)."""
        try:
            for id in self.http_helper.get_all_devices_ids():
                await self.http_client.refresh_device(id)
                await asyncio.sleep(delay)
                await self.http_client.rstat_all_device(id)
                await asyncio.sleep(delay)
            return True
        except Exception:
            self.logger.exception("Refresh failed (%s)", self.username)
            return False

    # ------------------------------------------------------------------ commands
    # They return True when the server accepted the command, False otherwise.

    async def turn(self, serial: str, on: bool) -> bool:
        """Turn the boiler on or off."""
        return await self._command(
            "turn", lambda id: self.http_client.turn_device_by_id(id, on), serial
        )

    async def turn_circuit(self, serial: str, circuit, on: bool) -> bool:
        """Turn one heating circuit on or off."""
        return await self._command(
            "turn_circuit",
            lambda id: self.http_client.turn_device_circuit(id, circuit, on),
            serial,
        )

    async def set_pellet_mode(self, serial: str) -> bool:
        """Wood/pellet boilers (BioTec Plus): switch to pellets. No command goes back to wood."""
        return await self._command(
            "set_pellet_mode", self.http_client.set_pellet_mode_by_id, serial
        )

    async def _command(self, name: str, send, serial: str) -> bool:
        try:
            device = self.data.get_device_by_serial(serial)
            response = await send(device["id"])
            return response.get("status") == "success"
        except Exception:
            self.logger.exception("Command %s failed for %s (%s)", name, serial, self.username)
            return False

    # ------------------------------------------------------------------ WebSocket events

    async def ws_connected_callback(self, frame) -> None:
        self.websocket_connected = True
        if self.connectivity_callback is not None:
            await self.connectivity_callback(True)
        await self.ws_client.subscribe_to_notifications()
        for serial in self.http_helper.get_all_devices_serials():
            await self.ws_client.subscribe_to_installation(self.data.get_device_by_serial(serial))
        self.data.set_on_update_callback(self.on_parameter_updated_callback)
        await self.data.notify_all_updated()

    async def ws_disconnected_callback(self, code, reason) -> None:
        self.websocket_connected = False
        if self.connectivity_callback is not None:
            await self.connectivity_callback(False)
        await self.data.notify_all_updated()

    async def ws_error_callback(self, frame) -> None:
        self.logger.error("STOMP error: %s (%s)", frame, self.username)

    async def ws_data_callback(self, frame) -> None:
        await self.data.parse_real_time_frame(frame)
