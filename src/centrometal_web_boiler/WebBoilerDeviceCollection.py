"""Data model: the boilers of an account and their parameters.

    WebBoilerDeviceCollection   dict  serial -> WebBoilerDevice
    └─ WebBoilerDevice          dict  "id", "serial", "type", "product", ..., "parameters"
       └─ WebBoilerParameter    dict  "name", "value", "timestamp"

A parameter is a raw Centrometal code (B_Tak1_1, B_STATE, PVAL_12_0...). Its value is filled from
the HTTPS snapshot at startup, then updated by the WebSocket in real time. Code interested in a
parameter registers a callback with set_update_callback; it is awaited on every update.
"""

import datetime
import json
import logging
import time
from collections.abc import Awaitable, Callable

from centrometal_web_boiler.const import (
    WEB_BOILER_STOMP_DEVICE_TOPIC,
    WEB_BOILER_STOMP_NOTIFICATION_TOPIC,
)
from centrometal_web_boiler.exceptions import WebBoilerError

_LOGGER = logging.getLogger(__name__)

ParameterCallback = Callable[["WebBoilerParameter"], Awaitable[None]]
# (device, parameter, created) -> None; created is True for the "everything changed" notification
DeviceCallback = Callable[..., Awaitable[None]]


class WebBoilerParameter(dict):
    """One value of a boiler, with the callbacks to notify when it changes."""

    def __init__(self):
        super().__init__()
        self.update_callbacks: dict[str, ParameterCallback] = {}

    def set_update_callback(
        self, update_callback: ParameterCallback | None, update_key: str = "default"
    ) -> None:
        """Register (or with None, remove) the callback stored under update_key.

        Each subscriber must use its own key, otherwise it replaces the previous one.
        """
        if update_callback is None:
            self.update_callbacks.pop(update_key, None)
        else:
            self.update_callbacks[update_key] = update_callback

    async def update(self, name: str, value, timestamp: int | None = None) -> None:
        self["name"] = name
        self["value"] = value
        self["timestamp"] = timestamp
        await self.notify_updated()

    async def notify_updated(self) -> None:
        # Copy: a callback may unsubscribe while we iterate
        for callback in list(self.update_callbacks.values()):
            await callback(self)


class WebBoilerDevice(dict):
    """One boiler: its description (keys) and its parameters (self["parameters"])."""

    def __init__(self, username: str):
        super().__init__()
        self.logger = _LOGGER
        self.username = username
        self["parameters"] = {}
        self["temperatures"] = {}
        self["info"] = {}
        self["weather"] = {}
        self["circuits"] = {}
        self["widgets"] = {}

    def has_parameter(self, name: str) -> bool:
        return name in self["parameters"]

    def create_parameter(self, name: str, value="?") -> WebBoilerParameter:
        parameter = WebBoilerParameter()
        parameter["name"] = name
        parameter["value"] = value
        self["parameters"][name] = parameter
        return parameter

    def get_parameter(self, name: str) -> WebBoilerParameter:
        """Return the parameter, creating an empty one (value "?") if the boiler never sent it."""
        if name not in self["parameters"]:
            self.logger.debug(
                "Parameter %s does not exist yet, creating it (%s)", name, self.username
            )
            return self.create_parameter(name)
        return self["parameters"][name]

    def get_or_create_parameter(self, name: str) -> WebBoilerParameter:
        if name not in self["parameters"]:
            return self.create_parameter(name)
        return self["parameters"][name]

    def get_widget_by_template(self, template: str) -> dict | None:
        for widget in self["widgets"].values():
            if widget["template"] == template:
                return widget
        return None

    async def update_parameter(
        self, name: str, value, timestamp: str | None = None
    ) -> WebBoilerParameter:
        """Set a value. timestamp is the server's UTC "YYYY-mm-dd HH:MM:SS", or None for now."""
        if timestamp is None:
            epoch = int(time.time())
        else:
            parsed = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            epoch = int(parsed.replace(tzinfo=datetime.UTC).timestamp())
        parameter = self.get_or_create_parameter(name)
        await parameter.update(name, value, epoch)
        return parameter


class WebBoilerDeviceCollection(dict):
    """All the boilers of an account, indexed by serial number."""

    def __init__(
        self,
        username: str,
        on_update_callback: DeviceCallback | None = None,
        update_key: str = "default",
    ):
        super().__init__()
        self.logger = _LOGGER
        self.username = username
        self.on_update_callbacks: dict[str, DeviceCallback] = {}
        self.set_on_update_callback(on_update_callback, update_key)

    def set_on_update_callback(
        self, on_update_callback: DeviceCallback | None, update_key: str = "default"
    ) -> None:
        """Callback awaited as (device, parameter) on every real-time update."""
        if on_update_callback is None:
            self.on_update_callbacks.pop(update_key, None)
        else:
            self.on_update_callbacks[update_key] = on_update_callback

    async def notify_all_updated(self) -> None:
        """Notify every parameter, e.g. when the connection state changes."""
        for on_update_callback in list(self.on_update_callbacks.values()):
            for device in self.values():
                for parameter in list(device["parameters"].values()):
                    await on_update_callback(device, parameter, True)
                    await parameter.notify_updated()

    def get_device_by_id(self, id) -> WebBoilerDevice:
        for device in self.values():
            if str(id) == str(device["id"]):
                return device
        raise WebBoilerError(f"No device with id {id}")

    def get_device_by_serial(self, serial) -> WebBoilerDevice:
        for device in self.values():
            if str(serial) == str(device["serial"]):
                return device
        raise WebBoilerError(f"No device with serial {serial}")

    # ------------------------------------------------------------------ HTTPS snapshot

    def parse_installations(self, installations: list[dict]) -> None:
        """Create one device per installation of the account."""
        for installation in installations:
            serial = installation["label"]
            self.logger.info("Creating device %s (%s)", serial, self.username)
            device = WebBoilerDevice(self.username)
            device["id"] = installation["value"]
            device["serial"] = serial
            device["place"] = installation["place"]
            device["address"] = installation["address"]
            device["type"] = installation["type"]
            device["product"] = installation["product"]
            self[serial] = device

    async def parse_installation_statuses(self, installation_status_all: dict) -> None:
        """Fill the current parameter values: {"<id>": {"installation": {...}, "params": {...}}}."""
        for device_id, groups in installation_status_all.items():
            device = self.get_device_by_id(device_id)
            for group, data in groups.items():
                if group == "installation":
                    device["country"] = data["country"]
                    device["countryCode"] = data["countryCode"]
                elif group == "params":
                    for name, param in data.items():
                        await device.update_parameter(name, param["v"], param["ut"])
                else:
                    self._ignore("installation-status-all group", group)

    # Groups of the parameter list, and the field used as key in the device dict
    _PARAMETER_GROUPS = {
        "Temperatures": ("temperatures", "dbindex"),
        "Info": ("info", "installation_status"),
        "Weather forecast": ("weather", "naslov"),
        "Heating circuits": ("circuits", "naslov"),
    }

    def parse_parameter_lists(self, parameter_list: dict[str, dict]) -> None:
        """Store the description of each boiler's parameters (temperatures, circuits...)."""
        for serial, device_data in parameter_list.items():
            device = self.get_device_by_serial(serial)
            for key, value in device_data.items():
                if key == "city":
                    device["city"] = value
                elif key == "parameters":
                    for group in value:
                        if group["group"] not in self._PARAMETER_GROUPS:
                            self._ignore("parameter-list group", group["group"])
                            continue
                        target, index_field = self._PARAMETER_GROUPS[group["group"]]
                        for item in group["list"]:
                            device[target][item[index_field]] = item
                else:
                    self._ignore("parameter-list key", key)

    def parse_grid(self, http_client) -> None:
        """Attach the dashboard widgets of the website to their boiler."""
        http_client.grid = json.loads(http_client.widgetgrid["grid"])
        for list_name in ("widgets", "widgets2"):
            for widget in http_client.grid.get(list_name, []):
                device = self.get_device_by_id(widget["data"]["installation"])
                device["widgets"][widget["id"]] = widget

    def _ignore(self, what: str, name) -> None:
        # Centrometal may add data at any time: log it instead of failing the whole setup
        self.logger.warning("Ignoring unknown %s: %s (%s)", what, name, self.username)

    # ------------------------------------------------------------------ real time

    async def parse_real_time_frame(self, stomp_frame: dict) -> None:
        """Apply a STOMP MESSAGE frame received on the WebSocket."""
        headers = stomp_frame.get("headers", {})
        body = stomp_frame.get("body")
        subscription = headers.get("subscription")
        destination = headers.get("destination")
        if body is None or subscription is None or destination is None:
            return
        if subscription == WEB_BOILER_STOMP_NOTIFICATION_TOPIC or not destination.startswith(
            WEB_BOILER_STOMP_DEVICE_TOPIC
        ):
            self.logger.info("Notification received: %s (%s)", body, self.username)
            return
        # Destination: /topic/cm.inst.<type>.<serial>
        serial = destination.rsplit(".", 1)[1]
        await self._update_device_with_real_time_data(self.get_device_by_serial(serial), body)

    async def _update_device_with_real_time_data(self, device: WebBoilerDevice, body: str):
        for name, value in json.loads(body).items():
            # Only parameters known from the snapshot are followed
            if device.has_parameter(name):
                parameter = await device.update_parameter(name, value)
                for on_update_callback in list(self.on_update_callbacks.values()):
                    await on_update_callback(device, parameter)
