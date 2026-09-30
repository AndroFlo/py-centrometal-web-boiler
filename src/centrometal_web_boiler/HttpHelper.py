"""Shortcuts over the list of installations (boilers) returned by the website."""

from centrometal_web_boiler.exceptions import WebBoilerError
from centrometal_web_boiler.HttpClient import HttpClient


class HttpHelper:
    """In the website's data, a boiler's "value" is its id and its "label" is its serial."""

    def __init__(self, client: HttpClient):
        self.client = client

    def get_device_count(self) -> int:
        return len(self.client.installations)

    def get_device_by_id(self, id) -> dict:
        for device in self.client.installations:
            if str(device["value"]) == str(id):
                return device
        raise WebBoilerError(f"No installation with id {id}")

    def get_device_by_serial(self, serial) -> dict:
        for device in self.client.installations:
            if device["label"] == serial:
                return device
        raise WebBoilerError(f"No installation with serial {serial}")

    def get_all_devices_ids(self) -> list:
        return [device["value"] for device in self.client.installations]

    def get_all_devices_serials(self) -> list:
        return [device["label"] for device in self.client.installations]
