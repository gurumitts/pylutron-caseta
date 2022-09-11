"""Provides an API to interact with the Lutron Caseta Smart Bridge & RA3 Processor."""

import asyncio
from datetime import timedelta
import logging
import math
import socket
import ssl
from typing import Callable, Dict, List, Optional, Tuple, Union

try:
    from asyncio import get_running_loop as get_loop
except ImportError:
    # For Python 3.6 and earlier, we have to use get_event_loop instead
    from asyncio import get_event_loop as get_loop

from . import (
    _LEAP_DEVICE_TYPES,
    FAN_OFF,
    OCCUPANCY_GROUP_UNKNOWN,
    RA3_OCCUPANCY_SENSOR_DEVICE_TYPES,
    BUTTON_STATUS_RELEASED,
    BridgeDisconnectedError,
    BridgeResponseError,
    _KEYPAD_SPECIAL_BUTTON_MAP,
    KEYPAD_LED_STATE_UNKNOWN,
    KEYPAD_LED_STATE_ON,
    KEYPAD_LED_STATE_OFF,
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
        self.buttons: Dict[str, dict] = {}
        self.lip_devices: Dict[int, dict] = {}
        self.scenes: Dict[str, dict] = {}
        self.occupancy_groups: Dict[str, dict] = {}
        self.areas: Dict[str, dict] = {}
        self._connect = connect
        self._subscribers: Dict[str, Callable[[], None]] = {}
        self._occupancy_subscribers: Dict[str, Callable[[], None]] = {}
        self._button_subscribers: Dict[str, Callable[[str], None]] = {}
        self._led_device_map: Dict[str, dict] = {}
        self._ra3_button_map: Dict[str, dict] = {} # Maps buttons back to parent devices
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

    def add_button_subscriber(self, button_id: str, callback_: Callable[[str], None]):
        """
        Add a listener to be notified of button state changes.

        :param button_id: button id, e.g., 2
        :param callback_: callback to invoke
        """
        _LOG.debug("Adding subscriber to button ID %s", button_id)
        self._button_subscribers[button_id] = callback_

    def get_devices(self) -> Dict[str, dict]:
        """Will return all known devices connected to the bridge/processor."""
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

        # Handle Ketra lamps
        if device.get("type") == "SpectrumTune":
            params = {"Level": value}  # type: Dict[str, Union[str, int]]
            if fade_time is not None:
                params["FadeTime"] = _format_duration(fade_time)
            await self._request(
                "CreateRequest",
                f"/zone/{zone_id}/commandprocessor",
                {
                    "Command": {
                        "CommandType": "GoToSpectrumTuningLevel",
                        "SpectrumTuningLevelParameters": params,
                    }
                },
            )
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

    async def set_tilt(self, device_id: str, value: int):
        """
        Set the tilt for tiltable blinds.

        :param device_id: The device ID of the blinds.
        :param value: The desired tilt between 0 and 100.
        """
        zone_id = self._get_zone_id(device_id)
        if zone_id:
            await self._request(
                "CreateRequest",
                f"/zone/{zone_id}/commandprocessor",
                {
                    "Command": {
                        "CommandType": "GoToTilt",
                        "TiltParameters": {
                            "Tilt": value,
                        },
                    },
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

    async def set_led_value(
        self, keypad_device_id: str, button_group_id: str, button_id: str, value: int
    ):
        """
        Set the value for a keypad LED with the given ID.

        :param device_id: device id to set the value on
        :param value: integer value from 0 to 100 to set
        :param fade_time: duration for the light to fade from its current value to the
        new value (only valid for lights)
        """
        keypad_device = self.devices.get(keypad_device_id)
        if keypad_device is not None:
            button_group = keypad_device["button_groups"].get(button_group_id)
            if button_group is not None:
                if button_group["buttons"].get(button_id) is not None:
                    button = button_group["buttons"].get(button_id)
                    led = button.get("led")
                    if led is not None:
                        led_id = led.get("led_id")
                        target_state = "On" if value > 0 else "Off"
                        await self._request(
                            "UpdateRequest",
                            f"/led/{led_id}/status",
                            {"LEDStatus": {"State": target_state}},
                        )
                        return

        _LOG.error(
            "received a set_led_value request for button ID %s "
            "which doesn't exist or doesn't have an LED associated",
            button_id,
        )

    async def turn_led_on(
        self, keypad_device_id: str, button_group_id: str, button_id: str
    ):
        """
        Turn 'on' the keypad LED with the given ID.

        :param device_id: device id to turn on
        :param **kwargs: additional parameters for set_value
        """
        await self.set_led_value(keypad_device_id, button_group_id, button_id, 100)

    async def turn_led_off(
        self, keypad_device_id: str, button_group_id: str, button_id: str
    ):
        """
        Turn 'off' the keypad LED with the given ID.

        :param device_id: device id to turn off
        :param **kwargs: additional parameters for set_value
        """
        await self.set_led_value(keypad_device_id, button_group_id, button_id, 0)

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

    async def tap_button(
        self, keypad_device_id: str, button_group_id: str, button_id: str
    ):
        """
        Send a press and release message for the given button ID.

        :param keypad_device_id: device ID of the keypad to which this button belongs
        :param button_group_id: button group ID to which this button belongs
        :param button_id: button ID, e.g. 23
        """
        keypad_device = self.devices.get(keypad_device_id)
        if keypad_device is not None:
            button_group = keypad_device["button_groups"].get(button_group_id)
            if button_group is not None:
                if button_group["buttons"].get(button_id) is not None:
                    await self._request(
                        "CreateRequest",
                        f"/button/{button_id}/commandprocessor",
                        {"Command": {"CommandType": "PressAndRelease"}},
                    )
                    return

        _LOG.error("received a tap_button request for unknown button ID %s", button_id)

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
        _LOG.debug("Handling single zone status: %s", response)
        body = response.Body
        if body is None:
            return
        self._handle_zone_status(body["ZoneStatus"])

    def _handle_zone_status(self, status):
        zone = id_from_href(status["Zone"]["href"])
        level = status.get("Level", -1)
        fan_speed = status.get("FanSpeed", None)
        tilt = status.get("Tilt", None)
        _LOG.debug("zone=%s level=%s", zone, level)
        device = self.get_device_by_zone_id(zone)
        if level >= 0:
            device["current_state"] = level
        device["fan_speed"] = fan_speed
        device["tilt"] = tilt
        if device["device_id"] in self._subscribers:
            self._subscribers[device["device_id"]]()

    def _handle_button_status(self, response: Response):
        _LOG.debug("Handling button status: %s", response)

        if response.Body is None:
            return

        status = response.Body["ButtonStatus"]
        button_id = id_from_href(status["Button"]["href"])
        button_event = status["ButtonEvent"]["EventType"]

        # legacy buttons (Pico)
        if button_id in self.buttons:
            _LOG.info("processing legacy button event on id %s", button_id)
            self.buttons[button_id]["current_state"] = button_event
            # Notify any subscribers of the change to button status
            if button_id in self._button_subscribers:
                self._button_subscribers[button_id](button_event)

        # RA3/HWQSX buttons (control station devices)
        if button_id in self._ra3_button_map:
            _LOG.info("processing RA3/HWQSX button event on id %s", button_id)
            device_id = self._ra3_button_map[button_id].get("keypad_device_id")
            button_group_id = self._ra3_button_map[button_id].get("button_group_id")

            if device_id is None or button_group_id is None or button_id is None:
                _LOG.error(
                    "_ra3_button_map consistency error: button_id = %s, "
                    "device_id = %s, button_group_id = %s",
                    button_id,
                    device_id,
                    button_group_id,
                )
                return

            # Update state
            self.devices[device_id]["button_groups"][button_group_id]["buttons"][
                button_id
            ]["current_state"] = button_event

            # Notify any subscribers of the change to button status
            if device_id in self._subscribers:
                _LOG.debug("Notifying keypad device subscriber...")
                self._subscribers[device_id]()

            if button_id in self._button_subscribers:
                _LOG.debug("Notifying button subscriber...")
                self._button_subscribers[button_id](button_event)
            _LOG.debug("Finished processing button event")

    def _handle_button_led_status(self, response: Response):
        """
        Handle events for button LED status changes.

        :param response: processor response with event
        """
        _LOG.debug("Handling button LED status: %s", response)

        if response.Body is None:
            return

        status = response.Body["LEDStatus"]
        button_led_id = id_from_href(status["LED"]["href"])
        state = KEYPAD_LED_STATE_ON if status["State"] == "On" else KEYPAD_LED_STATE_OFF

        if button_led_id not in self._led_device_map:
            _LOG.error(
                "received LED status update for unknown LED id %s", button_led_id
            )
            return

        device_id = self._led_device_map[button_led_id].get("keypad_device_id")
        button_group_id = self._led_device_map[button_led_id].get("button_group_id")
        button_id = self._led_device_map[button_led_id].get("button_id")

        if device_id is None or button_group_id is None or button_id is None:
            _LOG.error(
                "_led_device_map consistency error: button_led_id = %s, "
                "device_id = %s, button_group_id = %s, button_id = %s",
                button_led_id,
                device_id,
                button_group_id,
                button_id,
            )
            return

        device = self.devices.get(device_id)

        if device is None:
            _LOG.error(
                "unable to find device ID %s when handling button " "LED status update",
                device_id,
            )
            return

        if device["button_groups"].get(button_group_id) is None:
            _LOG.error(
                "unable to find button group ID %s when handling "
                "button LED status update",
                button_group_id,
            )
            return

        if device["button_groups"][button_group_id]["buttons"].get(button_id) is None:
            _LOG.error(
                "unable to find button ID %s when handling button LED status update",
                button_id,
            )
            return

        # Update state
        self.devices[device_id]["button_groups"][button_group_id]["buttons"][button_id][
            "led"
        ]["current_state"] = state

        # Notify any subscribers of the change to LED status
        if button_led_id in self._subscribers:
            self._subscribers[button_led_id]()

    def _handle_multi_zone_status(self, response: Response):
        _LOG.debug("Handling multi zone status: %s", response)

        if response.Body is None:
            return

        for zonestatus in response.Body["ZoneStatuses"]:
            self._handle_zone_status(zonestatus)

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

    def _handle_ra3_occupancy_group_status(self, response: Response):
        _LOG.debug("Handling ra3 occupancy status: %s", response)

        if response.Body is None:
            return

        statuses = response.Body.get("AreaStatuses", [])
        for status in statuses:
            occgroup_id = id_from_href(status["href"])
            if occgroup_id.endswith("/status"):
                occgroup_id = occgroup_id[:-7]
            # Check to see if the OccupancyStatus Key exists in the response.
            # Sometimes in just responds swith the CurrentScene key
            if "OccupancyStatus" in status:
                ostat = status["OccupancyStatus"]
                if occgroup_id not in self.occupancy_groups:
                    if ostat != OCCUPANCY_GROUP_UNKNOWN:
                        _LOG.debug(
                            "Occupancy group %s has a status but no sensors",
                            occgroup_id,
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
        elif (
            response.CommuniqueType == "ReadResponse"
            and response.Header.MessageBodyType == "OneLEDStatus"
        ):
            self._handle_button_led_status(response)

    async def _login(self):
        """Connect and login to the Smart Bridge LEAP server using SSL."""
        try:
            await self._load_areas()

            # Read /project to determine bridge type
            project_json = await self._request("ReadRequest", "/project")
            project = project_json.Body["Project"]

            if (
                project["ProductType"] == "Lutron RadioRA 3 Project"
                or project["ProductType"] == "Lutron HWQS Project"
            ):

                # RadioRa3 or HomeWorks QSX Processor device detected
                _LOG.debug("RA3 or QSX processor detected")

                # Load processor as devices[1] for compatibility with lutron_caseta HA
                # integration
                await self._load_ra3_processor()
                await self._load_ra3_devices()
                await self._subscribe_to_button_status()
                await self._load_ra3_occupancy_groups()
                await self._subscribe_to_ra3_occupancy_groups()
            else:
                # Caseta Bridge Device detected
                _LOG.debug("Caseta bridge detected")

                await self._load_devices()
                await self._load_buttons()
                await self._load_lip_devices()
                await self._load_scenes()
                await self._load_occupancy_groups()
                await self._subscribe_to_occupancy_groups()
                await self._subscribe_to_button_status()

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

        # If /device has no body, this probably isn't Caseta
        if device_json.Body is None:
            return

        for device in device_json.Body["Devices"]:
            _LOG.debug(device)
            device_id = id_from_href(device["href"])
            device_zone = None
            button_groups = None
            occupancy_sensors = None
            if "LocalZones" in device:
                device_zone = id_from_href(device["LocalZones"][0]["href"])
            if "ButtonGroups" in device:
                button_groups = [
                    id_from_href(button_group["href"])
                    for button_group in device["ButtonGroups"]
                ]
            if "OccupancySensors" in device:
                occupancy_sensors = [
                    id_from_href(occupancy_sensor["href"])
                    for occupancy_sensor in device["OccupancySensors"]
                ]
            device_name = "_".join(device["FullyQualifiedName"])
            self.devices.setdefault(
                device_id,
                {
                    "device_id": device_id,
                    "current_state": -1,
                    "fan_speed": None,
                    "tilt": None,
                },
            ).update(
                zone=device_zone,
                name=device_name,
                button_groups=button_groups,
                occupancy_sensors=occupancy_sensors,
                type=device["DeviceType"],
                model=device["ModelNumber"],
                serial=device["SerialNumber"],
            )

    async def _load_ra3_devices(self):

        for area in self.areas.values():
            await self._load_ra3_control_stations(area)
            await self._load_ra3_zones(area)

        # caseta does this by default, but we need to do it manually for RA3
        await self._subscribe_to_multi_zone_status()

    async def _load_ra3_processor(self):
        # Load processor as devices[1] for compatibility with lutron_caseta HA
        # integration

        _LOG.debug("Loading RA3/HWQSX processor")
        processor_json = await self._request(
            "ReadRequest", "/device?where=IsThisDevice:true"
        )
        if processor_json.Body is None:
            return

        processor = processor_json.Body["Devices"][0]
        processor_area = self.areas[processor["AssociatedArea"]["href"].split("/")[2]][
            "name"
        ]

        level = -1
        device_id = "1"
        fan_speed = None
        zone_type = None
        self.devices.setdefault(
            device_id,
            {"device_id": device_id, "current_state": level, "fan_speed": fan_speed},
        ).update(
            zone=device_id,
            name="_".join((processor_area, processor["Name"], processor["DeviceType"])),
            button_groups=None,
            type=zone_type,
            model=processor["ModelNumber"],
            serial=processor["SerialNumber"],
            device_type=processor["DeviceType"],
            processor_name=processor["Name"],
            area_name=processor_area,
        )

    async def _load_ra3_control_stations(self, area):
        """
        Load and process the control stations for an area.

        :param area: data structure describing the area
        """
        area_id = area["id"]
        area_name = area["name"]
        _LOG.debug("Loading control stations for area %s (%s)", area_id, area_name)
        station_json = await self._request(
            "ReadRequest", f"/area/{area_id}/associatedcontrolstation"
        )
        if station_json.Body is None:
            _LOG.debug("No control stations for this zone")
            return
        station_json = station_json.Body["ControlStations"]
        for station in station_json:
            station_name = station["Name"]
            ganged_devices_json = station["AssociatedGangedDevices"]

            for device_json in ganged_devices_json:
                await self._load_ra3_station_device(
                    area_name, station_name, device_json
                )

    async def _load_ra3_station_device(self, area_name, station_name, device_json):
        """
        Load button groups and buttons for a control station device.

        :param area_name: area in which this control station device exists
        :param station_name: name of this control station
        :param device_json: data structure describing the station device
        """
        device_id = id_from_href(device_json["Device"]["href"])

        # ignore non-keypad devices
        if device_json["Device"]["DeviceType"] not in _LEAP_DEVICE_TYPES.get("keypad"):
            _LOG.debug(
                "Control station device id %s is not a known keypad type, skipping",
                device_id,
            )
            return

        _LOG.debug("Processing control station device id %s", device_id)
        keypad_device_json = await self._request("ReadRequest", f"/device/{device_id}")
        device_data = keypad_device_json.Body["Device"]

        # fetch button details for this device
        button_group_json = await self._request(
            "ReadRequest", f"/device/{device_id}/buttongroup/expanded"
        )

        # ignore keypad devices without buttons
        if button_group_json.Body is None:
            _LOG.debug("Keypad device id %s has no buttons", device_id)
            return

        button_groups = {}
        for group in button_group_json.Body["ButtonGroupsExpanded"]:
            button_group_id = id_from_href(group["href"])
            buttons = await self._get_ra3_buttons_from_group(
                device_id, device_data["ModelNumber"], group
            )
            button_groups[button_group_id] = {
                "button_group_id": button_group_id,
                "buttons": buttons,
            }

        self.devices.setdefault(
            device_id,
            {
                "device_id": device_id,
                "current_state": -1,
                "fan_speed": None,
            },
        ).update(
            zone=None,
            name=device_data["Name"],  # ex: "Keypad 1"
            area_name=area_name,  # ex: "Foyer"
            control_station_name=station_name,  # ex: "Front Door Entry Wall"
            button_groups=button_groups,
            type=device_data["DeviceType"],  # ex: "PalladiomKeypad"
            model=device_data["ModelNumber"],  # ex: "HQWT-U-P4W"
            serial=device_data["SerialNumber"]
            if "SerialNumber" in device_data
            else None,
        )

        # Subscribe to button status and LEDs
        for button_group in button_groups.values():
            for button in button_group["buttons"].values():
                _LOG.debug(
                    "Subscribing to button status for button ID %s", button["device_id"]
                )
                await self._subscribe_to_button_status_for_id(button["device_id"])

                if button["led"] is not None:
                    button_led_id = button["led"]["led_id"]
                    await self._subscribe_to_button_led_status(button_led_id)

    async def _get_ra3_buttons_from_group(
        self, keypad_device_id: str, device_model: str, button_group: Dict
    ) -> Dict:
        """Create a dictionary of button data and associated LEDs.

        :param keypad_device_id (str): Device ID of the keypad for these buttons
        :param device_model (str): Model of the keypad for these buttons
        :param button_group (Dict): Button group

        Returns:
            buttons (Dict): Buttons with associated LEDs if applicable
        """
        button_group_id = id_from_href(button_group["href"])
        buttons: Dict[str, dict] = {}

        for button_json in button_group["Buttons"]:
            button_id = id_from_href(button_json["href"])
            button_number = button_json["ButtonNumber"]
            button_engraving = button_json.get("Engraving", None)

            self._ra3_button_map[button_id] = {
                "button_id": button_id,
                "button_group_id": button_group_id,
                "keypad_device_id": keypad_device_id,
            }

            led = None
            button_led_obj = button_json.get("AssociatedLED", None)
            if button_led_obj is not None:
                button_led_id = id_from_href(button_led_obj["href"])
                led = {
                    "led_id": button_led_id,
                    "current_state": KEYPAD_LED_STATE_UNKNOWN,
                }

                self._led_device_map[button_led_id] = {
                    "button_led_id": button_led_id,
                    "keypad_device_id": keypad_device_id,
                    "button_group_id": button_group_id,
                    "button_id": button_id,
                }

            if button_engraving is not None and button_engraving["Text"]:
                button_name = button_engraving["Text"].replace("\n", " ")
            else:
                button_name = self._get_default_button_name(
                    device_model, button_number, button_json
                )

            buttons[button_id] = {
                "device_id": button_id,
                "button_number": button_number,
                "name": button_name,
                "state": BUTTON_STATUS_RELEASED,
                "led": led,
            }

        return buttons

    @staticmethod
    def _get_default_button_name(
        device_model: str, button_number: int, button_json: Dict
    ):
        """Construct the default name for a button.

        For buttons without engraving, determine the default name. This function
        takes into account the device type and handles special button types like
        raise and lower.

        :param device_model (str): Model of the keypad to which this button belongs
        :param button_number (str): Button number of this button on the keypad
        :param button_json (Dict): The JSON data for this button

        Returns:
            name (str): Name for this button
        """
        keypad_button_map = _KEYPAD_SPECIAL_BUTTON_MAP.get(device_model)
        if keypad_button_map is not None:
            special_button_name = keypad_button_map.get(button_number)
            if special_button_name is not None:
                return special_button_name
        return button_json.get("Name")

    async def _load_ra3_zones(self, area):
        # For each area, process zones.  They will masquerade as devices
        area_id = area["id"]
        zone_json = await self._request(
            "ReadRequest", f"/area/{area_id}/associatedzone"
        )
        if zone_json.Body is None:
            return
        zone_json = zone_json.Body["Zones"]
        for zone in zone_json:
            level = zone.get("Level", -1)
            zone_id = id_from_href(zone["href"])
            fan_speed = zone.get("FanSpeed", None)
            zone_name = zone["Name"]
            zone_type = zone["ControlType"]
            self.devices.setdefault(
                zone_id,
                {"device_id": zone_id, "current_state": level, "fan_speed": fan_speed},
            ).update(
                zone=zone_id,
                name="_".join((area["name"], zone_name)),
                button_groups=None,
                type=zone_type,
                model=None,
                serial=None,
            )

    async def _load_lip_devices(self):
        """Load the LIP device list from the SSL LEAP server interface."""
        _LOG.debug("Loading LIP devices")
        try:
            device_json = await self._request("ReadRequest", "/server/2/id")
        except BridgeResponseError:
            # Only the PRO and RASelect2 hubs support getting the LIP devices
            return

        devices = device_json.Body.get("LIPIdList", {}).get("Devices", {})
        _LOG.debug(devices)
        self.lip_devices = {
            device["ID"]: device
            for device in devices
            if "ID" in device and "Name" in device
        }

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

    async def _load_buttons(self):
        """Load Pico button groups and button mappings."""
        _LOG.debug("Loading buttons for Pico Button Groups")
        button_json = await self._request("ReadRequest", "/button")
        button_devices = {
            button_group: device
            for device in self.devices.values()
            if device["button_groups"] is not None
            for button_group in device["button_groups"]
        }
        # If there are no devices with buttons 'Buttons' will
        # not be present in the response
        for button in button_json.Body.get("Buttons", []):
            button_id = id_from_href(button["href"])
            parent_id = id_from_href(button["Parent"]["href"])
            button_device = button_devices.get(parent_id)
            if button_device is None:
                _LOG.error(
                    "Encountered a button %s belonging to unknown button group %s",
                    button_id,
                    parent_id,
                )
                continue
            button_number = button["ButtonNumber"]
            pico_name = button_device["name"]
            self.buttons.setdefault(
                button_id,
                {
                    "device_id": button_id,
                    "current_state": BUTTON_STATUS_RELEASED,
                    "button_number": button_number,
                },
            ).update(
                name=pico_name,
                type=button_device["type"],
                model=button_device["model"],
                serial=button_device["serial"],
            )

    async def _load_areas(self):
        """Load the areas from the Smart Bridge."""
        _LOG.debug("Loading areas from the Smart Bridge")
        area_json = await self._request("ReadRequest", "/area")
        # We only need leaf nodes in RA3
        for area in area_json.Body["Areas"]:
            if area.get("IsLeaf", True):
                area_id = id_from_href(area["href"])
                # We currently only need the name, so just load that
                self.areas.setdefault(area_id, dict(id=area_id, name=area["Name"]))

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
        occsensor_ids = []
        associated_sensors = occgroup.get("AssociatedSensors", [])
        if not associated_sensors:
            _LOG.debug("No sensors associated with %s", occgroup["href"])
            return
        _LOG.debug("Found occupancy group with sensors: %s", occgroup_id)

        for sensor in associated_sensors:
            occsensor_ids.append(id_from_href(sensor["OccupancySensor"]["href"]))

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
                sensors=occsensor_ids,
            ),
        ).update(
            name=f"{self.areas[occgroup_area_id]['name']} Occupancy",
        )

    async def _load_ra3_occupancy_groups(self):
        """Load the devices from the bridge and filter for occupancy sensors."""
        _LOG.debug("Finding occupancy sensors from bridge")
        occdevice_json = await self._request(
            "ReadRequest", "/device?where=IsThisDevice:false"
        )
        if occdevice_json.Body is None:
            return

        occdevices = occdevice_json.Body.get("Devices", {})
        for occdevice in occdevices:
            if occdevice["DeviceType"] in RA3_OCCUPANCY_SENSOR_DEVICE_TYPES:
                self._process_ra3_occupancy_group(occdevice)

    def _process_ra3_occupancy_group(self, occdevice):
        """Process ra3 occupancy group."""
        occdevice_id = id_from_href(occdevice["href"])
        associated_area = occdevice["AssociatedArea"]
        occgroup_area_id = id_from_href(associated_area["href"])

        if occgroup_area_id not in self.areas:
            _LOG.error(
                "Unknown parent area for occupancy group %s: %s",
                occdevice_id,
                occgroup_area_id,
            )
            return

        occgroup = self.occupancy_groups.setdefault(
            occgroup_area_id,
            dict(
                occupancy_group_id=occgroup_area_id,
                status=OCCUPANCY_GROUP_UNKNOWN,
                sensors=[],
                name=f"{self.areas[occgroup_area_id]['name']} Occupancy",
            ),
        )
        occgroup["sensors"].append(occdevice_id)

    async def _subscribe_to_ra3_occupancy_groups(self):
        """Subscribe to ra3 occupancy group (area) status updates."""
        _LOG.debug("Subscribing to occupancy group (ra3: area) status updates")
        try:
            response, _ = await self._subscribe(
                "/area/status", self._handle_ra3_occupancy_group_status
            )
            _LOG.debug("Subscribed to occupancygroup status")
        except BridgeResponseError as ex:
            _LOG.error("Failed occupancy subscription: %s", ex.response)
            return
        self._handle_ra3_occupancy_group_status(response)

    async def _subscribe_to_button_status(self):
        """Subscribe to button status updates."""
        _LOG.debug("Subscribing to button status updates")
        try:
            for button in self.buttons:
                response, _ = await self._subscribe(
                    f"/button/{button}/status/event",
                    self._handle_button_status,
                )
                _LOG.debug("Subscribed to button %s status", button)
                self._handle_button_status(response)
        except BridgeResponseError as ex:
            _LOG.error("Failed device status subscription: %s", ex.response)
            return

    async def _subscribe_to_button_status_for_id(self, button_id):
        """Subscribe to button status updates for a given button ID."""
        try:
            response, _ = await self._subscribe(
                f"/button/{button_id}/status/event",
                self._handle_button_status,
            )
            _LOG.debug("Subscribed to button %s status", button_id)
            self._handle_button_status(response)
        except BridgeResponseError as ex:
            _LOG.error("Failed device status subscription: %s", ex.response)
            return

    async def _subscribe_to_button_led_status(self, button_led_id):
        """Subscribe to button LED status updates."""
        _LOG.debug(
            "Subscribing to button LED status updates for LED ID %s", button_led_id
        )
        try:
            response, _ = await self._subscribe(
                f"/led/{button_led_id}/status",
                self._handle_button_led_status,
            )
            _LOG.debug("Subscribed to button LED %s status", button_led_id)
            self._handle_button_led_status(response)
        except BridgeResponseError as ex:
            _LOG.error("Failed device status subscription: %s", ex.response)
            return

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

    async def _subscribe_to_multi_zone_status(self):
        """Subscribe to multi-zone status updates - RA3."""
        _LOG.debug("Subscribing to multi-zone status updates")
        try:
            response, _ = await self._subscribe(
                "/zone/status", self._handle_multi_zone_status
            )
            _LOG.debug("Subscribed to zone status")
        except BridgeResponseError as ex:
            _LOG.error("Failed zone subscription: %s", ex.response)
            return
        self._handle_multi_zone_status(response)

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
