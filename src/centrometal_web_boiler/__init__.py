"""Python library for Centrometal boilers connected to the web-boiler.com cloud (CM WiFi-Box).

Start with WebBoilerClient; see its module for a usage example.
"""

from importlib.metadata import PackageNotFoundError, version

from .const import *  # noqa: F403 (public constants, kept for backward compatibility)
from .exceptions import WebBoilerAuthError, WebBoilerError
from .HttpClient import HttpClient
from .HttpHelper import HttpHelper
from .WebBoilerClient import WebBoilerClient
from .WebBoilerDeviceCollection import (
    WebBoilerDevice,
    WebBoilerDeviceCollection,
    WebBoilerParameter,
)
from .WebBoilerWsClient import WebBoilerWsClient

try:
    __version__ = version("py-centrometal-web-boiler-androflo")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0"

__all__ = [
    "HttpClient",
    "HttpHelper",
    "WebBoilerClient",
    "WebBoilerDevice",
    "WebBoilerAuthError",
    "WebBoilerDeviceCollection",
    "WebBoilerError",
    "WebBoilerParameter",
    "WebBoilerWsClient",
]
