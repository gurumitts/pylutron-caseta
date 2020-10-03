# pylutron-caseta

A Python API to control Lutron Caséta devices.

## Getting started

Use `get_lutron_cert.py` to obtain `caseta.key` `caseta.crt` and `caseta-bridge.crt`. These files are used for authentication between your code and the Caséta bridge. See instructions at the top of [`get_lutron_cert.py`](get_lutron_cert.py) for more information.

Once you have those files, you can connect to the bridge and start controlling devices.

```py
import asyncio

from pylutron_caseta.smartbridge import Smartbridge

async def example():
    # `Smartbridge` provides an API for interacting with the Caséta bridge.
    bridge = Smartbridge.create_tls(
        "YOUR_BRIDGE_IP", "caseta.key", "caseta.crt", "caseta-bridge.crt"
    )
    await bridge.connect()

    # Get the first light.
    # The device is represented by a dict.
    device = bridge.get_devices_by_domain("light")[0]
    # Turn on the light.
    # Methods that act on devices expect to be given the device id.
    await bridge.turn_on(device["device_id"])

    await bridge.close()


# Because pylutron_caseta uses asyncio,
# it must be run within the context of an asyncio event loop.
loop = asyncio.get_event_loop()
loop.run_until_complete(example())
```
