"""HTTPS client for the web-boiler.com website.

The website has no documented API: the library reproduces what the Centrometal web application
does. Login is a classic HTML form (CSRF token + e-mail + password); every other call is a POST
returning JSON. Each response is kept as an attribute (installations, configuration, ...) and
turned into devices by WebBoilerDeviceCollection.
"""

import json
import logging
from typing import Any

import aiohttp
from lxml import html

from centrometal_web_boiler.const import WEB_BOILER_WEBROOT
from centrometal_web_boiler.exceptions import WebBoilerAuthError, WebBoilerError

_LOGGER = logging.getLogger(__name__)

# Without it a request to an unresponsive server waits for aiohttp's default of 5 minutes
TIMEOUT = aiohttp.ClientTimeout(total=30)


class HttpClient:
    """Logged-in session on web-boiler.com for one user account."""

    def __init__(self, username: str, password: str, webroot: str = WEB_BOILER_WEBROOT):
        self.logger = _LOGGER
        self.username = username
        self.password = password
        self.webroot = webroot
        self.headers = {"Origin": webroot, "Referer": webroot + "/"}
        self.headers_json = {**self.headers, "Content-Type": "application/json;charset=UTF-8"}
        self.http_session: aiohttp.ClientSession | None = None
        self.csrf_token: str | None = None
        # Responses of the last calls, read by WebBoilerDeviceCollection
        self.installations: list[dict] = []
        self.configuration: dict = {}
        self.widgetgrid_list: dict = {}
        self.widgetgrid: dict = {}
        self.installation_status_all: dict = {}
        self.parameter_list: dict[str, dict] = {}

    # ------------------------------------------------------------------ session

    def _session(self) -> aiohttp.ClientSession:
        """Return the HTTP session, creating it on first use (it keeps the login cookie)."""
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(timeout=TIMEOUT)
        return self.http_session

    async def reinitialize_session(self) -> None:
        """Drop the session (and its login cookie); the next request opens a new one."""
        await self.close_session()

    async def close_session(self) -> None:
        if self.http_session is not None:
            await self.http_session.close()
            self.http_session = None

    # ------------------------------------------------------------------ requests

    async def _request(self, method: str, url: str, *, data=None, json_response: bool) -> Any:
        """Send a request and return the parsed body (HTML tree or JSON)."""
        headers = self.headers_json if json_response else self.headers
        # The body is not logged: the login form contains the password.
        self.logger.debug("%s %s (%s)", method, url, self.username)
        async with self._session().request(
            method, self.webroot + url, headers=headers, data=data
        ) as response:
            text = await response.text()
            if response.status != 200:
                raise WebBoilerError(f"{method} {url} failed with HTTP code {response.status}")
        try:
            return json.loads(text) if json_response else html.fromstring(text)
        except Exception as ex:
            kind = "JSON" if json_response else "HTML"
            raise WebBoilerError(f"{method} {url}: cannot parse the {kind} response") from ex

    async def _http_get(self, url: str) -> html.HtmlElement:
        return await self._request("GET", url, json_response=False)

    async def _http_post(self, url: str, data=None) -> html.HtmlElement:
        return await self._request("POST", url, data=data, json_response=False)

    async def _http_post_json(self, url: str, data: dict | None = None) -> Any:
        return await self._request(
            "POST", url, data=json.dumps(data if data is not None else {}), json_response=True
        )

    # ------------------------------------------------------------------ login

    async def login(self) -> bool:
        """Log in with the account credentials.

        Returns False when the e-mail / password are refused. Any other failure (server
        unreachable, timeout, unexpected page) raises, so callers can tell a wrong password
        from a temporary outage.
        """
        try:
            await self._fetch_csrf_token()
            await self._login_check()
            return True
        except WebBoilerAuthError as ex:
            self.logger.error("Login failed: %s (%s)", ex, self.username)
            return False

    async def _fetch_csrf_token(self) -> None:
        """Read the anti-forgery token the login form must send back."""
        page = await self._http_get("/login")
        values = page.xpath('//input[@name="_csrf_token"]/@value')
        if len(values) != 1:
            raise WebBoilerError("Cannot find the CSRF token on the login page")
        self.csrf_token = values[0]

    async def _login_check(self) -> None:
        """Post the login form. Success is detected by the loading screen of the application."""
        form = {
            "_csrf_token": self.csrf_token,
            "_username": self.username,
            "_password": self.password,
            "submit": "Log In",
        }
        page = await self._http_post("/login_check", data=form)
        if len(page.xpath('//div[@id="id-loading-screen-blackout"]')) != 1:
            raise WebBoilerAuthError("Login refused (wrong e-mail or password?)")
        self.logger.info("Logged in (%s)", self.username)

    # ------------------------------------------------------------------ reading data

    async def get_notifications(self) -> None:
        await self._http_post("/notifications/data/get")

    async def get_installations(self) -> None:
        """List the boilers of the account (id, serial, type, product...)."""
        response = await self._http_post_json("/data/autocomplete/installation")
        self.installations = response["installations"]
        self.logger.debug("Installations: %s (%s)", self.installations, self.username)

    async def get_configuration(self) -> None:
        self.configuration = await self._http_post_json("/api/configuration")

    async def get_widgetgrid_list(self) -> None:
        self.widgetgrid_list = await self._http_post_json("/api/widgets-grid/list")

    async def get_widgetgrid(self, id) -> None:
        self.widgetgrid = await self._http_post_json(
            "/api/widgets-grid", {"id": str(id), "inst": "null"}
        )

    async def get_installation_status_all(self, ids: list) -> None:
        """Current value of every parameter, for the given boiler ids."""
        self.installation_status_all = await self._http_post_json(
            "/wdata/data/installation-status-all", {"installations": ids}
        )

    async def get_parameter_list(self, serial: str) -> None:
        """Description of the parameters of one boiler (temperatures, circuits...)."""
        self.parameter_list[serial] = await self._http_post_json(
            "/wdata/data/parameter-list/" + serial
        )

    # ------------------------------------------------------------------ commands

    async def _control(self, id, data: dict) -> dict:
        """Send a command to one boiler."""
        response = await self._http_post_json(f"/api/inst/control/{id}", data)
        self.logger.info("Control %s -> %s (%s)", data, response, self.username)
        return response

    async def _control_multiple(self, data: dict) -> dict:
        """Send messages to one or more boilers: {"messages": {"<id>": {<name>: <value>}}}."""
        response = await self._http_post_json("/api/inst/control/multiple", data)
        self.logger.debug("Control multiple %s -> %s (%s)", data, response, self.username)
        return response

    async def _control_advanced(self, id, data: dict) -> dict:
        response = await self._http_post_json(f"/api/inst/control/advanced/{id}", data)
        self.logger.debug("Control advanced %s -> %s (%s)", data, response, self.username)
        return response

    async def refresh_device(self, id) -> dict:
        """Ask the boiler to push all its values again (they arrive on the WebSocket)."""
        return await self._control_multiple({"messages": {str(id): {"REFRESH": 0}}})

    async def rstat_all_device(self, id) -> dict:
        return await self._control_multiple({"messages": {str(id): {"RSTAT": "ALL"}}})

    async def get_table_data(self, id, table_start_index: int, table_sub_index: int) -> dict:
        params = {
            f"PRD {table_start_index}": "VAL",
            f"PRD {table_start_index + table_sub_index}": "ALV",
        }
        return await self._control_advanced(id, {"parameters": params})

    def get_table_data_all(self, id, table_start_index: int, table_size: int) -> list:
        """Coroutines reading a whole table, to be awaited with asyncio.gather."""
        return [self.get_table_data(id, table_start_index, i) for i in range(1, table_size + 1)]

    async def turn_device_by_id(self, id, on: bool) -> dict:
        """Turn the boiler on or off."""
        return await self._control(id, {"cmd-name": "CMD", "cmd-value": 1 if on else 0})

    async def set_pellet_mode_by_id(self, id) -> dict:
        """Wood/pellet boilers (BioTec Plus): switch to pellets. No command goes back to wood."""
        return await self._control(id, {"cmd-name": "SCCMD", "cmd-value": 1})

    async def turn_device_circuit(self, id, circuit, on: bool) -> dict:
        """Turn one heating circuit on or off (circuit = its PWR index)."""
        return await self._control_multiple(
            {"messages": {str(id): {f"PWR {circuit}": 1 if on else 0}}}
        )
