"""Provides an API to interact with the Lutron Caseta Smart Bridge."""

import asyncio
from datetime import timedelta
import logging
import math
import socket
import ssl
from typing import Callable, Dict, List, Optional, Tuple

try:
    from asyncio import get_running_loop as get_loop
except ImportError:
    # For Python 3.6 and earlier, we have to use get_event_loop instead
    from asyncio import get_event_loop as get_loop

from . import (
    _LEAP_DEVICE_TYPES,
    FAN_OFF,
    OCCUPANCY_GROUP_UNKNOWN,
    BridgeDisconnectedError,
    BridgeResponseError,
)
from .leap import open_connection, id_from_href, LeapProtocol
from .messages import Response

_LOG = logging.getLogger(__name__)

LEAP_PORT = 8081
PING_INTERVAL = 60.0
CONNECT_TIMEOUT = 5.0
REQUEST_TIMEOUT = 5.0
RECONNECT_DELAY = 2.0


class Smartbridge:
    """
    A representation of the Lutron Caseta Smart Bridge.

    It uses an SSL interface known as the LEAP server.
    """

    def __init__(self, connect: Callable[[], LeapProtocol]):
        """Initialize the Smart Bridge."""
        self.devices: Dict[str, dict] = {}
        self.scenes: Dict[str, dict] = {}
        self.occupancy_groups: Dict[str, dict] = {}
        self.areas: Dict[str, dict] = {}
        self._connect = connect
        self._subscribers: Dict[str, Callable[[], None]] = {}
        self._occupancy_subscribers: Dict[str, Callable[[], None]] = {}
        self._login_task: Optional[asyncio.Task] = None
        # Use future so we can wait before the login starts and
        # don't need to wait for "login" on reconnect.
        self._login_completed: asyncio.Future = (
            asyncio.get_running_loop().create_future()
        )
        self._leap: Optional[LeapProtocol] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None

    @property
    def logged_in(self):
        """Check if the bridge is connected and ready."""
        return (
            # are we connected?
            self._monitor_task is not None
            and not self._monitor_task.done()
            # are we ready?
            and self._login_completed.done()
            and not self._login_completed.cancelled()
            and self._login_completed.exception() is None
        )

    async def connect(self):
        """Connect to the bridge."""
        # reset any existing connection state
        if self._login_task is not None:
            self._login_task.cancel()
            self._login_task = None

        if self._monitor_task is not None:
            self._monitor_task.cancel()
            self._monitor_task = None

        if self._ping_task is not None:
            self._ping_task.cancel()
            self._ping_task = None

        if self._leap is not None:
            self._leap.close()
            self._leap = None

        if not self._login_completed.done():
            self._login_completed.cancel()
            self._login_completed = asyncio.get_running_loop().create_future()

        self._monitor_task = get_loop().create_task(self._monitor())

        await self._login_completed

    @classmethod
    def create_tls(cls, hostname, keyfile, certfile, ca_certs, port=LEAP_PORT):
        """Initialize the Smart Bridge using TLS over IPv4."""
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        ssl_context.load_verify_locations(ca_certs)
        ssl_context.load_cert_chain(certfile, keyfile)
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        async def _connect():
            res = await open_connection(
                hostname,
                port,
                server_hostname="",
                ssl=ssl_context,
                family=socket.AF_INET,
            )
            return res

        return cls(_connect)

    def add_subscriber(self, device_id: str, callback_: Callable[[], None]):
        """
        Add a listener to be notified of state changes.

        :param device_id: device id, e.g. 5
        :param callback_: callback to invoke
        """
        self._subscribers[device_id] = callback_

    def add_occupancy_subscriber(
        self, occupancy_group_id: str, callback_: Callable[[], None]
    ):
        """
        Add a listener to be notified of occupancy state changes.

        :param occupancy_group_id: occupancy group id, e.g., 2
        :param callback_: callback to invoke
        """
        self._occupancy_subscribers[occupancy_group_id] = callback_

    def get_devices(self) -> Dict[str, dict]:
        """Will return all known devices connected to the Smart Bridge."""
        return self.devices

    def get_devices_by_domain(self, domain: str) -> List[dict]:
        """
        Return a list of devices for the given domain.

        :param domain: one of 'light', 'switch', 'cover', 'fan' or 'sensor'
        :returns list of zero or more of the devices
        """
        types = _LEAP_DEVICE_TYPES.get(domain, None)

        # return immediately if not a supported domain
        if types is None:
            return []

        return self.get_devices_by_types(types)

    def get_devices_by_type(self, type_: str) -> List[dict]:
        """
        Will return all devices of a given device type.

        :param type_: LEAP device type, e.g. WallSwitch
        """
        return [device for device in self.devices.values() if device["type"] == type_]

    def get_device_by_zone_id(self, zone_id: str) -> dict:
        """
        Return the first device associated with a given zone.

        Currently each device is mapped to exactly 1 zone

        :param zone_id: the zone id to search for
        :raises KeyError: if the zone id is not present
        """
        for device in self.devices.values():
            if zone_id == device.get("zone"):
                return device
        raise KeyError(f"No device associated with zone {zone_id}")

    def get_devices_by_types(self, types: List[str]) -> List[dict]:
        """
        Will return all devices for a list of given device types.

        :param types: list of LEAP device types such as WallSwitch, WallDimmer
        """
        return [device for device in self.devices.values() if device["type"] in types]

    def get_device_by_id(self, device_id: str) -> dict:
        """
        Will return a device with the given ID.

        :param device_id: device id, e.g. 5
        """
        return self.devices[device_id]

    def get_scenes(self) -> Dict[str, dict]:
        """Will return all known scenes from the Smart Bridge."""
        return self.scenes

    def get_scene_by_id(self, scene_id: str) -> dict:
        """
        Will return a scene with the given scene ID.

        :param scene_id: scene id, e.g 23
        """
        return self.scenes[scene_id]

    def is_connected(self) -> bool:
        """Will return True if currently connected to the Smart Bridge."""
        return self.logged_in

    def is_on(self, device_id: str) -> bool:
        """
        Will return True is the device with the given ID is 'on'.

        :param device_id: device id, e.g. 5
        :returns True if level is greater than 0 level, False otherwise
        """
        return (
            self.devices[device_id]["current_state"] > 0
            or (self.devices[device_id]["fan_speed"] or FAN_OFF) != FAN_OFF
        )

    async def _request(
        self, communique_type: str, url: str, body: Optional[dict] = None
    ) -> Response:
        if self._leap is None:
            raise BridgeDisconnectedError()

        response = await asyncio.wait_for(
            self._leap.request(communique_type, url, body),
            timeout=REQUEST_TIMEOUT,
        )

        status = response.Header.StatusCode
        if status is None or not status.is_successful():
            raise BridgeResponseError(response)

        return response

    async def _subscribe(
        self,
        url: str,
        callback: Callable[[Response], None],
        communique_type: str = "SubscribeRequest",
        body: Optional[dict] = None,
    ) -> Tuple[Response, str]:
        if self._leap is None:
            raise BridgeDisconnectedError()

        response, tag = await asyncio.wait_for(
            self._leap.subscribe(
                url, callback, communique_type=communique_type, body=body
            ),
            timeout=REQUEST_TIMEOUT,
        )

        status = response.Header.StatusCode
        if status is None or not status.is_successful():
            raise BridgeResponseError(response)

        return (response, tag)

    async def set_value(
        self, device_id: str, value: int, fade_time: Optional[timedelta] = None
    ):
        """
        Will set the value for a device with the given ID.

        :param device_id: device id to set the value on
        :param value: integer value from 0 to 100 to set
        :param fade_time: duration for the light to fade from its current value to the
        new value (only valid for lights)
        """
        device = self.devices[device_id]

        zone_id = device.get("zone")
        if not zone_id:
            return

        if device.get("type") in _LEAP_DEVICE_TYPES["light"] and fade_time is not None:
            await self._request(
                "CreateRequest",
                f"/zone/{zone_id}/commandprocessor",
                {
                    "Command": {
                        "CommandType": "GoToDimmedLevel",
                        "DimmedLevelParameters": {
                            "Level": value,
                            "FadeTime": _format_duration(fade_time),
                        },
                    }
                },
            )
        else:
            await self._request(
                "CreateRequest",
                f"/zone/{zone_id}/commandprocessor",
                {
                    "Command": {
                        "CommandType": "GoToLevel",
                        "Parameter": [{"Type": "Level", "Value": value}],
                    }
                },
            )

    async def _send_zone_create_request(self, device_id: str, command: str):
        zone_id = self._get_zone_id(device_id)
        if not zone_id:
            return

        await self._request(
            "CreateRequest",
            f"/zone/{zone_id}/commandprocessor",
            {"Command": {"CommandType": command}},
        )

    async def stop_cover(self, device_id: str):
        """Will stop a cover."""
        await self._send_zone_create_request(device_id, "Stop")

    async def raise_cover(self, device_id: str):
        """Will raise a cover."""
        await self._send_zone_create_request(device_id, "Raise")
        # If set_value is called, we get an optimistic callback right
        # away with the value, if we use Raise we have to set it
        # as one won't come unless Stop is called or something goes wrong.
        self.devices[device_id]["current_state"] = 100

    async def lower_cover(self, device_id: str):
        """Will lower a cover."""
        await self._send_zone_create_request(device_id, "Lower")
        # If set_value is called, we get an optimistic callback right
        # away with the value, if we use Lower we have to set it
        # as one won't come unless Stop is called or something goes wrong.
        self.devices[device_id]["current_state"] = 0

    async def set_fan(self, device_id: str, value: str):
        """
        Will set the value for a fan device with the given device ID.

        :param device_id: device id to set the value on
        :param value: string value to set the fan to:
        Off, Low, Medium, MediumHigh, High
        """
        zone_id = self._get_zone_id(device_id)
        if zone_id:
            await self._request(
                "CreateRequest",
                f"/zone/{zone_id}/commandprocessor",
                {
                    "Command": {
                        "CommandType": "GoToFanSpeed",
                        "FanSpeedParameters": {"FanSpeed": value},
                    }
                },
            )

    async def turn_on(self, device_id: str, **kwargs):
        """
        Will turn 'on' the device with the given ID.

        :param device_id: device id to turn on
        :param **kwargs: additional parameters for set_value
        """
        await self.set_value(device_id, 100, **kwargs)

    async def turn_off(self, device_id: str, **kwargs):
        """
        Will turn 'off' the device with the given ID.

        :param device_id: device id to turn off
        :param **kwargs: additional parameters for set_value
        """
        await self.set_value(device_id, 0, **kwargs)

    async def activate_scene(self, scene_id: str):
        """
        Will activate the scene with the given ID.

        :param scene_id: scene id, e.g. 23
        """
        if scene_id in self.scenes:
            await self._request(
                "CreateRequest",
                f"/virtualbutton/{scene_id}/commandprocessor",
                {"Command": {"CommandType": "PressAndRelease"}},
            )

    def _get_zone_id(self, device_id: str) -> Optional[str]:
        """
        Return the zone id for an given device.

        :param device_id: device id for which to retrieve a zone id
        """
        return self.devices[device_id].get("zone")

    async def _monitor(self):
        """Event monitoring loop."""
        try:
            while True:
                await self._monitor_once()
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            _LOG.critical("monitor loop has exited", exc_info=1)
            if not self._login_completed.done():
                self._login_completed.set_exception(ex)
            raise
        finally:
            self._login_completed.cancel()

    async def _monitor_once(self):
        """Monitor for events until an error occurs."""
        try:
            _LOG.debug("Connecting to Smart Bridge via SSL")
            self._leap = await self._connect()
            self._leap.subscribe_unsolicited(self._handle_unsolicited)
            _LOG.debug("Successfully connected to Smart Bridge.")

            if self._login_task is not None:
                self._login_task.cancel()

            if self._ping_task is not None:
                self._ping_task.cancel()

            self._login_task = asyncio.get_running_loop().create_task(self._login())
            self._ping_task = asyncio.get_running_loop().create_task(self._ping())

            await self._leap.run()
            _LOG.warning("LEAP session ended. Reconnecting...")
            await asyncio.sleep(RECONNECT_DELAY)
        # ignore OSError too.
        # sometimes you get OSError instead of ConnectionError.
        except (
            ValueError,
            ConnectionError,
            OSError,
            asyncio.TimeoutError,
            BridgeDisconnectedError,
        ):
            _LOG.warning("Reconnecting...", exc_info=1)
            await asyncio.sleep(RECONNECT_DELAY)
        finally:
            if self._login_task is not None:
                self._login_task.cancel()
                self._login_task = None

            if self._ping_task is not None:
                self._ping_task.cancel()
                self._ping_task = None

            if self._leap is not None:
                self._leap.close()
                self._leap = None

    def _handle_one_zone_status(self, response: Response):
        body = response.Body
        if body is None:
            return

        status = body["ZoneStatus"]
        zone = id_from_href(status["Zone"]["href"])
        level = status.get("Level", -1)
        fan_speed = status.get("FanSpeed", None)
        _LOG.debug("zone=%s level=%s", zone, level)
        device = self.get_device_by_zone_id(zone)
        device["current_state"] = level
        device["fan_speed"] = fan_speed
        if device["device_id"] in self._subscribers:
            self._subscribers[device["device_id"]]()

    def _handle_occupancy_group_status(self, response: Response):
        _LOG.debug("Handling occupancy group status: %s", response)

        if response.Body is None:
            return

        statuses = response.Body.get("OccupancyGroupStatuses", {})
        for status in statuses:
            occgroup_id = id_from_href(status["OccupancyGroup"]["href"])
            ostat = status["OccupancyStatus"]
            if occgroup_id not in self.occupancy_groups:
                if ostat != OCCUPANCY_GROUP_UNKNOWN:
                    _LOG.warning(
                        "Occupancy group %s has a status but no sensors", occgroup_id
                    )
                continue
            if ostat == OCCUPANCY_GROUP_UNKNOWN:
                _LOG.warning(
                    "Occupancy group %s has sensors but no status", occgroup_id
                )
            self.occupancy_groups[occgroup_id]["status"] = ostat
            # Notify any subscribers of the change to occupancy status
            if occgroup_id in self._occupancy_subscribers:
                self._occupancy_subscribers[occgroup_id]()

    def _handle_unsolicited(self, response: Response):
        if (
            response.CommuniqueType == "ReadResponse"
            and response.Header.MessageBodyType == "OneZoneStatus"
        ):
            self._handle_one_zone_status(response)

    async def _login(self):
        """Connect and login to the Smart Bridge LEAP server using SSL."""
        try:
            await self._load_devices()
            await self._load_scenes()
            await self._load_areas()
            await self._load_occupancy_groups()
            await self._subscribe_to_occupancy_groups()

            for device in self.devices.values():
                if device.get("zone") is not None:
                    _LOG.debug("Requesting zone information from %s", device)
                    response = await self._request(
                        "ReadRequest", f"/zone/{device['zone']}/status"
                    )
                    self._handle_one_zone_status(response)

            if not self._login_completed.done():
                self._login_completed.set_result(None)
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            self._login_completed.set_exception(ex)
            raise

    async def _ping(self):
        """Periodically ping the LEAP server to keep the connection open."""
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                await self._request("ReadRequest", "/server/1/status/ping")
        except asyncio.TimeoutError:
            _LOG.warning("ping was not answered. closing connection.")
            self._leap.close()
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOG.warning("ping failed. closing connection.", exc_info=1)
            self._leap.close()
            raise

    async def _load_devices(self):
        """Load the device list from the SSL LEAP server interface."""
        _LOG.debug("Loading devices")
        device_json = await self._request("ReadRequest", "/device")
        for device in device_json.Body["Devices"]:
            _LOG.debug(device)
            device_id = id_from_href(device["href"])
            device_zone = None
            if "LocalZones" in device:
                device_zone = id_from_href(device["LocalZones"][0]["href"])
            device_name = "_".join(device["FullyQualifiedName"])
            self.devices.setdefault(
                device_id,
                {"device_id": device_id, "current_state": -1, "fan_speed": None},
            ).update(
                zone=device_zone,
                name=device_name,
                type=device["DeviceType"],
                model=device["ModelNumber"],
                serial=device["SerialNumber"],
            )

    async def _load_scenes(self):
        """
        Load the scenes from the Smart Bridge.

        Scenes are known as virtual buttons in the SSL LEAP interface.
        """
        _LOG.debug("Loading scenes from the Smart Bridge")
        scene_json = await self._request("ReadRequest", "/virtualbutton")
        for scene in scene_json.Body["VirtualButtons"]:
            _LOG.debug(scene)
            # If 'Name' is not a key in scene, then it is likely a scene pico
            # vbutton. For now, simply ignore these scenes.
            if scene["IsProgrammed"] and "Name" in scene:
                scene_id = id_from_href(scene["href"])
                scene_name = scene["Name"]
                self.scenes[scene_id] = {"scene_id": scene_id, "name": scene_name}

    async def _load_areas(self):
        """Load the areas from the Smart Bridge."""
        _LOG.debug("Loading areas from the Smart Bridge")
        area_json = await self._request("ReadRequest", "/area")
        for area in area_json.Body["Areas"]:
            area_id = id_from_href(area["href"])
            # We currently only need the name, so just load that
            self.areas.setdefault(area_id, dict(name=area["Name"]))

    async def _load_occupancy_groups(self):
        """Load the occupancy groups from the Smart Bridge."""
        _LOG.debug("Loading occupancy groups from the Smart Bridge")
        occgroup_json = await self._request("ReadRequest", "/occupancygroup")
        if occgroup_json.Body is None:
            return

        occgroups = occgroup_json.Body.get("OccupancyGroups", {})
        for occgroup in occgroups:
            self._process_occupancy_group(occgroup)

    def _process_occupancy_group(self, occgroup):
        """Process occupancy group."""
        occgroup_id = id_from_href(occgroup["href"])
        if not occgroup.get("AssociatedSensors"):
            _LOG.debug("No sensors associated with %s", occgroup["href"])
            return
        _LOG.debug("Found occupancy group with sensors: %s", occgroup_id)
        associated_areas = occgroup.get("AssociatedAreas", [])
        if not associated_areas:
            _LOG.error(
                "No associated areas found with occupancy group "
                "containing sensors: %s -- skipping",
                occgroup_id,
            )
            return
        if len(associated_areas) > 1:
            _LOG.warning(
                "Occupancy group %s associated with multiple "
                "areas. Naming based on first area.",
                occgroup_id,
            )
        occgroup_area_id = id_from_href(associated_areas[0]["Area"]["href"])
        if occgroup_area_id not in self.areas:
            _LOG.error(
                "Unknown parent area for occupancy group %s: %s",
                occgroup_id,
                occgroup_area_id,
            )
            return
        self.occupancy_groups.setdefault(
            occgroup_id,
            dict(
                occupancy_group_id=occgroup_id,
                status=OCCUPANCY_GROUP_UNKNOWN,
            ),
        ).update(
            name=f"{self.areas[occgroup_area_id]['name']} Occupancy",
        )

    async def _subscribe_to_occupancy_groups(self):
        """Subscribe to occupancy group status updates."""
        _LOG.debug("Subscribing to occupancy group status updates")
        try:
            response, _ = await self._subscribe(
                "/occupancygroup/status", self._handle_occupancy_group_status
            )
            _LOG.debug("Subscribed to occupancygroup status")
        except BridgeResponseError as ex:
            _LOG.error("Failed occupancy subscription: %s", ex.response)
            return
        self._handle_occupancy_group_status(response)

    async def close(self):
        """Disconnect from the bridge."""
        _LOG.info("Processing Smartbridge.close() call")
        if self._monitor_task is not None and not self._monitor_task.cancelled():
            self._monitor_task.cancel()
        if self._ping_task is not None and not self._ping_task.cancelled():
            self._ping_task.cancel()


def _format_duration(duration: timedelta) -> str:
    """Convert a timedelta to the hh:mm:ss format used in LEAP."""
    total_seconds = math.floor(duration.total_seconds())
    seconds = int(total_seconds % 60)
    total_minutes = math.floor(total_seconds / 60)
    minutes = int(total_minutes % 60)
    hours = int(total_minutes / 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"
