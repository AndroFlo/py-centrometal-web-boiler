"""Connect to a real Centrometal account and print the values received in real time.

    export CENTROMETAL_USERNAME=you@example.com
    export CENTROMETAL_PASSWORD=...
    python examples/test_client.py                # print updates for 5 minutes
    python examples/test_client.py --duration 60  # ... for 60 seconds
    python examples/test_client.py --verbose      # also show the library's debug logs

The credentials are read from the environment so they do not end up in the shell history.
Nothing is sent to the boiler: the example only reads.
"""

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from centrometal_web_boiler import WebBoilerClient  # noqa: E402


async def main(username: str, password: str, duration: int) -> int:
    client = WebBoilerClient()

    async def on_update(device, parameter, created=False):
        if not created:
            print(f"{device['serial']}  {parameter['name']} = {parameter['value']}")

    try:
        if not await client.login(username, password):
            print("Login failed: check the e-mail and password.")
            return 1
        if not await client.get_configuration():
            print("No boiler found on this account.")
            return 1

        for device in client.data.values():
            print(
                f"Boiler {device['serial']}: {device['product']} (type {device['type']}), "
                f"{len(device['parameters'])} parameters"
            )

        await client.start_websocket(on_update)
        await client.refresh()
        await asyncio.sleep(duration)
        return 0
    finally:
        await client.close_websocket()
        if client.http_client is not None:
            await client.http_client.close_session()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duration", type=int, default=300, help="seconds to listen")
    parser.add_argument("--verbose", action="store_true", help="show debug logs")
    args = parser.parse_args()

    username = os.environ.get("CENTROMETAL_USERNAME")
    password = os.environ.get("CENTROMETAL_PASSWORD")
    if not username or not password:
        parser.error("set CENTROMETAL_USERNAME and CENTROMETAL_PASSWORD")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(asyncio.run(main(username, password, args.duration)))
