# py-centrometal-web-boiler

Python library for Centrometal boilers connected to the **web-boiler.com** cloud (CM WiFi-Box).
It is the communication layer of the Home Assistant integration
[hass-centrometal-boiler](https://github.com/AndroFlo/hass-centrometal-boiler).

This is a fork of [9a4gl/py-centrometal-web-boiler](https://github.com/9a4gl/py-centrometal-web-boiler),
published on PyPI as **`py-centrometal-web-boiler-androflo`** (the original package name belongs to
the upstream author). The Python module is still `centrometal_web_boiler`.

Centrometal publishes no API: the library does what the Centrometal web application does.
Use it at your own risk.

## How it works

```
web-boiler.com
├── website (HTTPS)        login, list of boilers, current values, commands   → HttpClient
└── broker (STOMP over     real-time values pushed by the boilers             → WebBoilerWsClient
    secure WebSocket)
                     both combined by WebBoilerClient, data stored in WebBoilerDeviceCollection
```

1. **Login**: the login page gives a CSRF token, then the login form is posted with the e-mail
   and password. The session cookie is kept for the next calls.
2. **Configuration**: the list of boilers of the account, the description of their parameters and
   the current value of each parameter.
3. **Real time**: a STOMP connection subscribes to one topic per boiler and receives
   `{"<parameter>": <value>}` messages.
4. **Commands**: on/off, heating circuits on/off, pellet mode — HTTPS POSTs.

A parameter is a raw Centrometal code such as `B_Tak1_1` (temperature) or `B_STATE`.

## Usage

```python
from centrometal_web_boiler import WebBoilerClient

client = WebBoilerClient()
if await client.login("you@example.com", "password") and await client.get_configuration():
    for serial, device in client.data.items():
        print(serial, device["product"], device.get_parameter("B_STATE")["value"])

    async def on_update(device, parameter, created=False):
        print(device["serial"], parameter["name"], parameter["value"])

    await client.start_websocket(on_update)
    await client.refresh()  # ask the boilers to push every value
    await client.turn(serial, True)  # turn_circuit(serial, circuit, on), set_pellet_mode(serial)
    ...
    await client.close_websocket()
    await client.http_client.close_session()
```

Try it with your account (read-only, nothing is sent to the boiler):

```
pip install -e .
export CENTROMETAL_USERNAME=you@example.com CENTROMETAL_PASSWORD=...
python examples/test_client.py --duration 60
```

## Development

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest              # tests against a local fake of web-boiler.com, no account needed
ruff check . && ruff format .
```

## Release

1. Bump `version` in `pyproject.toml` and push to `main`.
2. Publish a GitHub release whose tag is exactly that version (e.g. `0.1.0`).
   The *Upload Python Package* workflow checks the tag, runs the tests and publishes to PyPI
   through Trusted Publishing (GitHub environment `pypi`, no token).
3. In the Home Assistant integration, update the pin `py-centrometal-web-boiler-androflo==<version>`
   in `manifest.json` and bump the integration version.
