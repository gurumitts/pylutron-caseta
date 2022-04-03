# pylutron-caseta

A Python API to control Lutron Caséta devices.

[![Coverage Status](https://coveralls.io/repos/github/gurumitts/pylutron-caseta/badge.svg?branch=dev)](https://coveralls.io/github/gurumitts/pylutron-caseta?branch=dev)

## Getting started

If you don't know the IP address of the bridge, the `leap-scan` tool (requires the cli extra, `pip install pylutron_caseta[cli]`) will search for LEAP devices on the local network and display their address and LEAP port number.

### Authentication

In order to communicate with the bridge device, you must complete the pairing process. This generates certificate files for authentication. pylutron_caseta can do this two ways.

#### lap-pair

If pylutron_caseta is installed with the cli extra (`pip install pylutron_caseta[cli]`), the `lap-pair` tool can be used to generate the certificate files. Simply running `lap-pair <BRIDGE HOST>` (note the LEAP port number should not be included) will begin the pairing process. The certificate files will be saved in `$XDG_CONFIG_HOME/pylutron_caseta` (normally `~/.config/pylutron_caseta`) in the files `[BRIDGE HOST]-bridge.crt`, `[BRIDGE HOST].crt`,  `[BRIDGE HOST].key`. Check `lap-pair --help` if you want to use different files.

#### The pairing module

If pylutron_caseta is being integrated into a larger application, the pairing functionality can be reused to allow pairing from within that application.

```py
async def pair(host: str):
    def _ready():
        print("Press the small black button on the back of the bridge.")

    data = await async_pair(host, _ready)
    with open("caseta-bridge.crt", "w") as cacert:
        cacert.write(data["ca"])
    with open("caseta.crt", "w") as cert:
        cert.write(data["cert"])
    with open("caseta.key", "w") as key:
        key.write(data["key"])
    print(f"Successfully paired with {data['version']}")
```

### Connecting to the bridge

Once you have the certificate files, you can connect to the bridge and start controlling devices.

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

### The leap tool

For development and testing of new features, there is a `leap` command in the cli extras (`pip install pylutron_caseta[cli]`) which can be used for communicating directly with the bridge, similar to using `curl`.

Getting information about the bridge:

```
$ leap 192.168.86.49/server | jq
{
  "Servers": [
    {
      "href": "/server/1",
      "Type": "LEAP",
      "NetworkInterfaces": [
        {
          "href": "/networkinterface/1"
        }
      ],
      "EnableState": "Enabled",
      "LEAPProperties": {
        "PairingList": {
          "href": "/server/leap/pairinglist"
        }
      },
      "Endpoints": [
        {
          "Protocol": "TCP",
          "Port": 8081,
          "AssociatedNetworkInterfaces": null
        }
      ]
    }
  ]
}
```

Turning on the first dimmer:

```
$ ip=192.168.86.49
$ device=$(leap "${ip}/zone/status/expanded?where=Zone.ControlType:\"Dimmed\"" | jq -r '.ZoneExpandedStatuses[0].Zone.href')
$ leap -X CreateRequest "${ip}${device}/commandprocessor" -d '{"Command":{"CommandType":"GoToLevel","Parameter":[{"Type":"Level","Value":100}]}}'
```
