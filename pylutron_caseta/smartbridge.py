"""Provides an API to interact with the Lutron Caseta Smart Bridge."""

import asyncio
import logging
import socket
import ssl

try:
    from asyncio import get_running_loop as get_loop
except ImportError:
    # For Python 3.6 and earlier, we have to use get_event_loop instead
    from asyncio import get_event_loop as get_loop

from . import _LEAP_DEVICE_TYPES, FAN_OFF, OCCUPANCY_GROUP_UNKNOWN
from .leap import open_connection, id_from_href

_LOG = logging.getLogger(__name__)

LEAP_PORT = 8081
PING_INTERVAL = 60.0
PING_DELAY = 5.0
CONNECT_TIMEOUT = 5.0
RECONNECT_DELAY = 2.0


class Smartbridge:
    """
    A representation of the Lutron Caseta Smart Bridge.

    It uses an SSL interface known as the LEAP server.
    """

    def __init__(self, connect):
        """Initialize the Smart Bridge."""
        self.devices = {}
        self.scenes = {}
        self.occupancy_groups = {}
        self.areas = {}
        self.logged_in = False
        self._connect = connect
        self._subscribers = {}
        self._occupancy_subscribers = {}
        self._login_lock = asyncio.Lock()
        self._reader = None
        self._writer = None
        self._monitor_task = None
        self._ping_task = None
        self._got_ping = asyncio.Event()

    async def connect(self):
        """Connect to the bridge."""
        await self._login()
        self._monitor_task = get_loop().create_task(self._monitor())

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

    def add_subscriber(self, device_id, callback_):
        """
        Add a listener to be notified of state changes.

        :param device_id: device id, e.g. 5
        :param callback_: callback to invoke
        """
        self._subscribers[device_id] = callback_

    def add_occupancy_subscriber(self, occupancy_group_id, callback_):
        """
        Add a listener to be notified of occupancy state changes.

        :param occupancy_group_id: occupancy group id, e.g., 2
        :param callback_: callback to invoke
        """
        self._occupancy_subscribers[occupancy_group_id] = callback_

    def get_devices(self):
        """Will return all known devices connected to the Smart Bridge."""
        return self.devices

    def get_devices_by_domain(self, domain):
        """
        Return a list of devices for the given domain.

        :param domain: one of 'light', 'switch', 'cover', 'fan' or 'sensor'
        :returns list of zero or more of the devices
        """
        devs = []

        # return immediately if not a supported domain
        if domain not in _LEAP_DEVICE_TYPES:
            return devs

        # loop over all devices and check their type
        for device_id in self.devices:
            if self.devices[device_id]["type"] in _LEAP_DEVICE_TYPES[domain]:
                devs.append(self.devices[device_id])
        return devs

    def get_devices_by_type(self, type_):
        """
        Will return all devices of a given device type.

        :param type_: LEAP device type, e.g. WallSwitch
        """
        devs = []
        for device_id in self.devices:
            if self.devices[device_id]["type"] == type_:
                devs.append(self.devices[device_id])
        return devs

    def get_device_by_zone_id(self, zone_id):
        """
        Return the first device associated with a given zone.

        Currently each device is mapped to exactly 1 zone

        :param zone_id: the zone id to search for
        :raises KeyError: if the zone id is not present
        """
        for device in self.devices.values():
            if zone_id == device.get("zone"):
                return device
        raise KeyError("No device associated with zone {}".format(zone_id))

    def get_devices_by_types(self, types):
        """
        Will return all devices of for a list of given device types.

        :param types: list of LEAP device types such as WallSwitch, WallDimmer
        """
        devs = []
        for device_id in self.devices:
            if self.devices[device_id]["type"] in types:
                devs.append(self.devices[device_id])
        return devs

    def get_device_by_id(self, device_id):
        """
        Will return a device with the given ID.

        :param device_id: device id, e.g. 5
        """
        return self.devices[device_id]

    def get_scenes(self):
        """Will return all known scenes from the Smart Bridge."""
        return self.scenes

    def get_scene_by_id(self, scene_id):
        """
        Will return a scene with the given scene ID.

        :param scene_id: scene id, e.g 23
        """
        return self.scenes[scene_id]

    def is_connected(self):
        """Will return True if currently connected to the Smart Bridge."""
        return self.logged_in

    def is_on(self, device_id):
        """
        Will return True is the device with the given ID is 'on'.

        :param device_id: device id, e.g. 5
        :returns True if level is greater than 0 level, False otherwise
        """
        return (
            self.devices[device_id]["current_state"] > 0
            or (self.devices[device_id]["fan_speed"] or FAN_OFF) != FAN_OFF
        )

    def set_value(self, device_id, value):
        """
        Will set the value for a device with the given ID.

        :param device_id: device id to set the value on
        :param value: integer value from 0 to 100 to set
        """
        zone_id = self._get_zone_id(device_id)
        if zone_id:
            cmd = {
                "CommuniqueType": "CreateRequest",
                "Header": {"Url": "/zone/%s/commandprocessor" % zone_id},
                "Body": {
                    "Command": {
                        "CommandType": "GoToLevel",
                        "Parameter": [{"Type": "Level", "Value": value}],
                    }
                },
            }
            self._writer.write(cmd)

    def _send_zone_create_request(self, device_id, command):
        zone_id = self._get_zone_id(device_id)
        if not zone_id:
            return
        self._writer.write(
            {
                "CommuniqueType": "CreateRequest",
                "Header": {"Url": "/zone/%s/commandprocessor" % zone_id},
                "Body": {"Command": {"CommandType": command}},
            }
        )

    def stop_cover(self, device_id):
        """Will stop a cover."""
        self._send_zone_create_request(device_id, "Stop")

    def raise_cover(self, device_id):
        """Will raise a cover."""
        self._send_zone_create_request(device_id, "Raise")
        # If set_value is called, we get an optimistic callback right
        # away with the value, if we use Raise we have to set it
        # as one won't come unless Stop is called or something goes wrong.
        self.devices[device_id]["current_state"] = 100

    def lower_cover(self, device_id):
        """Will lower a cover."""
        self._send_zone_create_request(device_id, "Lower")
        # If set_value is called, we get an optimistic callback right
        # away with the value, if we use Lower we have to set it
        # as one won't come unless Stop is called or something goes wrong.
        self.devices[device_id]["current_state"] = 0

    def set_fan(self, device_id, value):
        """
        Will set the value for a fan device with the given device ID.

        :param device_id: device id to set the value on
        :param value: string value to set the fan to:
        Off, Low, Medium, MediumHigh, High
        """
        zone_id = self._get_zone_id(device_id)
        if zone_id:
            cmd = {
                "CommuniqueType": "CreateRequest",
                "Header": {"Url": "/zone/%s/commandprocessor" % zone_id},
                "Body": {
                    "Command": {
                        "CommandType": "GoToFanSpeed",
                        "FanSpeedParameters": {"FanSpeed": value},
                    }
                },
            }
            self._writer.write(cmd)

    def turn_on(self, device_id):
        """
        Will turn 'on' the device with the given ID.

        :param device_id: device id to turn on
        """
        return self.set_value(device_id, 100)

    def turn_off(self, device_id):
        """
        Will turn 'off' the device with the given ID.

        :param device_id: device id to turn off
        """
        return self.set_value(device_id, 0)

    def activate_scene(self, scene_id):
        """
        Will activate the scene with the given ID.

        :param scene_id: scene id, e.g. 23
        """
        if scene_id in self.scenes:
            cmd = {
                "CommuniqueType": "CreateRequest",
                "Header": {"Url": "/virtualbutton/%s/commandprocessor" % scene_id},
                "Body": {"Command": {"CommandType": "PressAndRelease"}},
            }
            self._writer.write(cmd)

    def _get_zone_id(self, device_id):
        """
        Return the zone id for an given device.

        :param device_id: device id for which to retrieve a zone id
        """
        return self.devices[device_id].get("zone")

    def _send_command(self, cmd):
        """Send a command to the bridge."""
        self._writer.write(cmd)

    async def _monitor(self):
        """Event monitoring loop."""
        try:
            while True:
                try:
                    await asyncio.wait_for(self._login(), timeout=CONNECT_TIMEOUT)
                    received = await self._reader.read()
                    _LOG.debug("received LEAP: %s", received)
                    if received is not None:
                        self._handle_response(received)
                # ignore OSError too.
                # sometimes you get OSError instead of ConnectionError.
                except (ValueError, ConnectionError, OSError, asyncio.TimeoutError):
                    _LOG.warning("reconnecting", exc_info=1)
                    await asyncio.sleep(RECONNECT_DELAY)
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOG.critical("monitor loop has exited", exc_info=1)
            raise

    def _handle_response(self, resp_json):
        """
        Handle an event from the ssl interface.

        If a zone level was changed either by external means such as a Pico
        remote or by a command sent from us, the new level will appear on the
        reader and the response is handled by this function.

        :param resp_json: full JSON response from the LEAP connection
        """
        comm_type = resp_json["CommuniqueType"]
        if comm_type == "ReadResponse":
            self._handle_read_response(resp_json)

    def _handle_one_zone_status(self, resp_json):
        body = resp_json["Body"]
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

    def _handle_one_ping_response(self, _):
        self._got_ping.set()

    def _handle_occupancy_group_status(self, resp_json):
        _LOG.debug("Handling occupancy group status: %s", resp_json)
        statuses = resp_json.get("Body", {}).get("OccupancyGroupStatuses", {})
        for status in statuses:
            occgroup_id = id_from_href(status["OccupancyGroup"]["href"])
            ostat = status["OccupancyStatus"]
            if occgroup_id not in self.occupancy_groups:
                if ostat != OCCUPANCY_GROUP_UNKNOWN:
                    _LOG.warning(
                        "Occupancy group %s has a status but no " "sensors", occgroup_id
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

    _read_response_handler_callbacks = dict(
        OneZoneStatus=_handle_one_zone_status,
        OnePingResponse=_handle_one_ping_response,
        MultipleOccupancyGroupStatus=_handle_occupancy_group_status,
    )

    def _handle_read_response(self, resp_json):
        body_type = resp_json.get("Header", {}).get("MessageBodyType")
        if body_type in self._read_response_handler_callbacks:
            self._read_response_handler_callbacks[body_type](self, resp_json)

    async def _login(self):
        """Connect and login to the Smart Bridge LEAP server using SSL."""
        async with self._login_lock:
            if self._reader is not None and self._writer is not None:
                if (
                    self.logged_in
                    and self._reader.exception() is None
                    and not self._reader.at_eof()
                ):
                    return
                self._writer.abort()
                self._reader = self._writer = None

            self.logged_in = False
            _LOG.debug("Connecting to Smart Bridge via SSL")
            self._reader, self._writer = await self._connect()
            _LOG.debug("Successfully connected to Smart Bridge.")

            await self._load_devices()
            await self._load_scenes()
            await self._load_areas()
            await self._load_occupancy_groups()
            await self._subscribe_to_occupancy_groups()
            for device in self.devices.values():
                if device.get("zone") is not None:
                    _LOG.debug("Requesting zone information from %s", device)
                    cmd = {
                        "CommuniqueType": "ReadRequest",
                        "Header": {"Url": "/zone/%s/status" % device["zone"]},
                    }
                    self._writer.write(cmd)
            self._ping_task = get_loop().create_task(self._ping())
            self.logged_in = True

    async def _ping(self):
        """Periodically ping the LEAP server to keep the connection open."""
        writer = self._writer
        try:
            try:
                while True:
                    await asyncio.sleep(PING_INTERVAL)
                    self._got_ping.clear()
                    writer.write(
                        {
                            "CommuniqueType": "ReadRequest",
                            "Header": {"Url": "/server/1/status/ping"},
                        }
                    )
                    await asyncio.wait_for(self._got_ping.wait(), PING_DELAY)
            except asyncio.TimeoutError:
                _LOG.warning("ping was not answered. closing connection.")
                writer.abort()
            except ConnectionError:
                _LOG.warning("ping failed. closing connection.")
                writer.abort()
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOG.error("ping failed. closing connection.", exc_info=1)
            writer.abort()
            raise

    async def _load_devices(self):
        """Load the device list from the SSL LEAP server interface."""
        _LOG.debug("Loading devices")
        self._writer.write(
            {"CommuniqueType": "ReadRequest", "Header": {"Url": "/device"}}
        )
        device_json = await self._reader.wait_for("ReadResponse")
        for device in device_json["Body"]["Devices"]:
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
        self._writer.write(
            {"CommuniqueType": "ReadRequest", "Header": {"Url": "/virtualbutton"}}
        )
        scene_json = await self._reader.wait_for("ReadResponse")
        for scene in scene_json["Body"]["VirtualButtons"]:
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
        self._writer.write(dict(CommuniqueType="ReadRequest", Header=dict(Url="/area")))
        area_json = await self._reader.wait_for("ReadResponse")
        for area in area_json["Body"]["Areas"]:
            area_id = id_from_href(area["href"])
            # We currently only need the name, so just load that
            self.areas[area_id] = dict(name=area["Name"])

    async def _load_occupancy_groups(self):
        """Load the occupancy groups from the Smart Bridge."""
        _LOG.debug("Loading occupancy groups from the Smart Bridge")
        self._writer.write(
            dict(CommuniqueType="ReadRequest", Header=dict(Url="/occupancygroup"))
        )
        occgroup_json = await self._reader.wait_for("ReadResponse")
        occgroups = occgroup_json.get("Body", {}).get("OccupancyGroups", {})
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
        self.occupancy_groups[occgroup_id] = dict(
            occupancy_group_id=occgroup_id,
            name="{} Occupancy".format(self.areas[occgroup_area_id]["name"]),
            status=OCCUPANCY_GROUP_UNKNOWN,
        )

    async def _subscribe_to_occupancy_groups(self):
        """Subscribe to occupancy group status updates."""
        _LOG.debug("Subscribing to occupancy group status updates")
        self._writer.write(
            dict(
                CommuniqueType="SubscribeRequest",
                Header=dict(Url="/occupancygroup/status"),
            )
        )
        response = await self._reader.wait_for("SubscribeResponse")
        if response["Header"]["StatusCode"].startswith("20"):
            _LOG.debug("Subscribed to occupancygroup status")
        else:
            _LOG.error("Failed occupancy subscription: %s", response)
            return
        self._handle_occupancy_group_status(response)

    async def close(self):
        """Disconnect from the bridge."""
        _LOG.info("Processing Smartbridge.close() call")
        if self._monitor_task is not None and not self._monitor_task.cancelled():
            self._monitor_task.cancel()
        if self._ping_task is not None and not self._ping_task.cancelled():
            self._ping_task.cancel()
        await self._writer.drain()
        self._writer.abort()
