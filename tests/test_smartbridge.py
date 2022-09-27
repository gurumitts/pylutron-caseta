"""Tests to validate ssl interactions."""
import asyncio
from collections import defaultdict
from datetime import timedelta
import json
import logging
import os
import re
from typing import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Tuple,
    TypeVar,
)

import pytest

from pylutron_caseta.leap import id_from_href
from pylutron_caseta.messages import Response, ResponseHeader, ResponseStatus
from pylutron_caseta import (
    _LEAP_DEVICE_TYPES,
    FAN_MEDIUM,
    OCCUPANCY_GROUP_OCCUPIED,
    OCCUPANCY_GROUP_UNOCCUPIED,
    OCCUPANCY_GROUP_UNKNOWN,
    BUTTON_STATUS_PRESSED,
    BridgeDisconnectedError,
    smartbridge,
)

logging.getLogger().setLevel(logging.DEBUG)
_LOG = logging.getLogger(__name__)

CASETA_PROCESSOR = "Caseta"
RA3_PROCESSOR = "RA3"
HWQSX_PROCESSOR = "QSX"

RESPONSE_PATH = {
    CASETA_PROCESSOR: "",
    RA3_PROCESSOR: "ra3/",
    HWQSX_PROCESSOR: "hwqsx/",
}


def response_from_json_file(filename: str) -> Response:
    """Fetch a response from a saved JSON file."""
    responsedir = os.path.join(os.path.split(__file__)[0], "responses")
    with open(os.path.join(responsedir, filename), "r", encoding="utf-8") as ifh:
        return Response.from_json(json.load(ifh))


class Request(NamedTuple):
    """An in-flight LEAP request."""

    communique_type: str
    url: str
    body: Optional[dict] = None


class _FakeLeap:
    def __init__(self):
        self.requests: "asyncio.Queue[Tuple[Request, asyncio.Future[Response]]]" = (
            asyncio.Queue()
        )
        self.running = None
        self._subscriptions: Dict[str, List[Callable[[Response], None]]] = defaultdict(
            list
        )
        self._unsolicited: List[Callable[[Response], None]] = []

    async def request(
        self, communique_type: str, url: str, body: Optional[dict] = None
    ) -> Response:
        """Make a request to the bridge and return the response."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        obj = Request(communique_type=communique_type, url=url, body=body)

        await self.requests.put((obj, future))

        return await future

    async def subscribe(
        self,
        url: str,
        callback: Callable[[Response], None],
        body: Optional[dict] = None,
        communique_type: str = "SubscribeRequest",
    ) -> Tuple[Response, str]:
        """Subscribe to events from the bridge."""
        response = await self.request(communique_type, url, body)
        self._subscriptions[url].append(callback)
        return (response, "not-implemented")

    async def run(self):
        """Event monitoring loop."""
        self.running = asyncio.get_running_loop().create_future()
        await self.running

    def subscribe_unsolicited(self, callback: Callable[[Response], None]):
        """Subscribe to unsolicited responses."""
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._unsolicited.append(callback)

    def unsubscribe_unsolicited(self, callback: Callable[[Response], None]):
        """Unsubscribe from unsolicited responses."""
        self._unsolicited.remove(callback)

    def send_unsolicited(self, response: Response):
        """Send an unsolicited response message to SmartBridge."""
        for handler in self._unsolicited:
            handler(response)

    def send_to_subscribers(self, response: Response):
        """Send an response message to topic subscribers."""
        url = response.Header.Url
        if url is None:
            raise TypeError("url must not be None")
        for handler in self._subscriptions[url]:
            handler(response)

    def close(self):
        """Disconnect."""
        if self.running is not None and not self.running.done():
            self.running.set_result(None)
            self.running = None

        while not self.requests.empty():
            (_, response) = self.requests.get_nowait()
            if not response.done():
                response.set_exception(BridgeDisconnectedError())
            self.requests.task_done()


T = TypeVar("T")


class Bridge:
    """A test harness around SmartBridge."""

    def __init__(self):
        """Create a new Bridge in a disconnected state."""
        self.connections = asyncio.Queue()
        self.leap: _FakeLeap = None

        self.button_list_result = response_from_json_file("buttons.json")
        self.occupancy_group_list_result = response_from_json_file(
            "occupancygroups.json"
        )
        self.occupancy_group_subscription_data_result = response_from_json_file(
            "occupancygroupsubscribe.json"
        )
        self.button_subscription_data_result = response_from_json_file(
            "buttonsubscribe.json"
        )
        self.button_led_subscription_data_result = response_from_json_file(
            f"{RESPONSE_PATH[HWQSX_PROCESSOR]}ledsubscribe.json"
        )
        self.ra3_button_list = []
        self.ra3_button_led_list = []
        self.qsx_button_list = []
        self.qsx_button_led_list = []

        async def fake_connect():
            """Open a fake LEAP connection for the test."""
            leap = _FakeLeap()
            await self.connections.put(leap)
            return leap

        self.target = smartbridge.Smartbridge(fake_connect)

    async def initialize(self, processor=CASETA_PROCESSOR):
        """Perform the initial connection with SmartBridge."""
        connect_task = asyncio.get_running_loop().create_task(self.target.connect())
        fake_leap = await self.connections.get()

        async def wait(coro: Awaitable[T]) -> T:
            # abort if SmartBridge reports it has finished connecting early
            task = asyncio.get_running_loop().create_task(coro)
            race = await asyncio.wait(
                (connect_task, task), timeout=10, return_when=asyncio.FIRST_COMPLETED
            )
            done, _ = race
            assert len(done) > 0, "operation timed out"
            if len(done) == 1 and connect_task in done:
                raise connect_task.exception()
            result = await task
            return result

        if processor == CASETA_PROCESSOR:
            await self._accept_connection(fake_leap, wait)
        elif processor == RA3_PROCESSOR:
            await self._accept_connection_ra3(fake_leap, wait)
        elif processor == HWQSX_PROCESSOR:
            await self._accept_connection_qsx(fake_leap, wait)

        await connect_task

        self.leap = fake_leap
        self.connections.task_done()

    async def _accept_connection(self, leap, wait):
        """Accept a connection from SmartBridge (implementation)."""
        # Read request on /areas
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/area")
        response.set_result(response_from_json_file("areas.json"))
        leap.requests.task_done()

        # Read request on /project
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/project")
        response.set_result(response_from_json_file("project.json"))
        leap.requests.task_done()

        # Read request on /device
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/device")
        response.set_result(response_from_json_file("devices.json"))
        leap.requests.task_done()

        # Read request on /button
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/button")
        response.set_result(self.button_list_result)
        leap.requests.task_done()

        # Read request on /server/2/id
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/server/2/id")
        response.set_result(response_from_json_file("lip.json"))
        leap.requests.task_done()

        # Read request on /virtualbutton
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/virtualbutton")
        response.set_result(response_from_json_file("scenes.json"))
        leap.requests.task_done()

        # Read request on /occupancygroup
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/occupancygroup")
        response.set_result(self.occupancy_group_list_result)
        leap.requests.task_done()

        # Subscribe request on /occupancygroup/status
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="SubscribeRequest", url="/occupancygroup/status"
        )
        response.set_result(self.occupancy_group_subscription_data_result)
        leap.requests.task_done()

        # Subscribe request on /button/{button}/status/event
        for button in (
            re.sub(r".*/", "", button["href"])
            for button in self.button_list_result.Body.get("Buttons", [])
        ):
            request, response = await wait(leap.requests.get())
            assert request == Request(
                communique_type="SubscribeRequest", url=f"/button/{button}/status/event"
            )
            response.set_result(self.button_subscription_data_result)
            leap.requests.task_done()

        # Check the zone status on each zone
        requested_zones = []
        for _ in range(0, 4):
            request, response = await wait(leap.requests.get())
            logging.info("Read %s", request)
            assert request.communique_type == "ReadRequest"
            requested_zones.append(request.url)
            response.set_result(
                Response(
                    CommuniqueType="ReadResponse",
                    Header=ResponseHeader(
                        MessageBodyType="OneZoneStatus",
                        StatusCode=ResponseStatus(200, "OK"),
                        Url=request.url,
                    ),
                    Body={
                        "ZoneStatus": {
                            "href": request.url,
                            "Zone": {"href": request.url.replace("/status", "")},
                            "StatusAccuracy": "Good",
                        }
                    },
                )
            )
            leap.requests.task_done()
        requested_zones.sort()
        assert requested_zones == [
            "/zone/1/status",
            "/zone/2/status",
            "/zone/3/status",
            "/zone/6/status",
        ]

    async def _process_station(self, result, leap, wait, bridge_type):
        if result.Body is None:
            return

        response_path = RESPONSE_PATH[bridge_type]

        for station in result.Body.get("ControlStations", []):
            for device in station.get("AssociatedGangedDevices", []):
                if device["Device"]["DeviceType"] not in _LEAP_DEVICE_TYPES.get(
                    "keypad"
                ):
                    _LOG.debug("Control station is not a known keypad type - skipping")
                    continue

                device_id = re.sub(r".*/", "", device["Device"]["href"])

                request, response = await wait(leap.requests.get())
                assert request == Request(
                    communique_type="ReadRequest", url=f"/device/{device_id}"
                )
                response.set_result(
                    response_from_json_file(
                        f"{response_path}device/{device_id}/device.json"
                    )
                )
                leap.requests.task_done()

                request, response = await wait(leap.requests.get())
                assert request == Request(
                    communique_type="ReadRequest",
                    url=f"/device/{device_id}/buttongroup/expanded",
                )
                button_group_result = response_from_json_file(
                    f"{response_path}device/{device_id}/buttongroup.json"
                )
                response.set_result(button_group_result)
                leap.requests.task_done()

                for group in button_group_result.Body["ButtonGroupsExpanded"]:
                    for button in group["Buttons"]:
                        request, response = await wait(leap.requests.get())
                        assert request == Request(
                            communique_type="SubscribeRequest",
                            url=f"{button['href']}/status/event",
                        )
                        response.set_result(self.button_subscription_data_result)
                        leap.requests.task_done()

                        if button.get("AssociatedLED", None) is not None:
                            led_id = id_from_href(button["AssociatedLED"]["href"])
                            request, response = await wait(leap.requests.get())
                            assert request == Request(
                                communique_type="SubscribeRequest",
                                url=f"/led/{led_id}/status",
                            )
                            response.set_result(self.button_subscription_data_result)
                            leap.requests.task_done()

                self._populate_button_list_from_buttongroups(
                    button_group_result.Body["ButtonGroupsExpanded"], bridge_type
                )
                self._populate_button_led_list_from_buttongroups(
                    button_group_result.Body["ButtonGroupsExpanded"], bridge_type
                )

    def _populate_button_list_from_buttongroups(self, buttongroups, bridge_type):
        """Add buttons from a set of buttongroups to the proper processor list
        to support subscribe tests

        Args:
            buttongroups: A set of buttongroups
            bridge_type: The bridge or processor type
        """
        buttons = []
        buttons.extend(
            [
                id_from_href(button["href"])
                for group in buttongroups
                for button in group["Buttons"]
            ]
        )
        if bridge_type == RA3_PROCESSOR:
            self.ra3_button_list.extend(buttons)
        elif bridge_type == HWQSX_PROCESSOR:
            self.qsx_button_list.extend(buttons)

    def _populate_button_led_list_from_buttongroups(self, buttongroups, bridge_type):
        """Add button LEDs from a set of buttongroups to the proper processor list
        to support subscribe tests

        Args:
            buttongroups: A set of buttongroups
            bridge_type: The bridge or processor type
        """
        button_leds = []
        for group in buttongroups:
            for button in group["Buttons"]:
                if button.get("AssociatedLED", None) is not None:
                    button_leds.append(id_from_href(button["AssociatedLED"]["href"]))
        if bridge_type == RA3_PROCESSOR:
            self.ra3_button_led_list.extend(button_leds)
        elif bridge_type == HWQSX_PROCESSOR:
            self.qsx_button_led_list.extend(button_leds)

    async def _accept_connection_ra3(self, leap, wait):
        """Accept a connection from SmartBridge (implementation)."""
        ra3_response_path = RESPONSE_PATH[RA3_PROCESSOR]

        # Read request on /areas
        ra3_area_list_result = response_from_json_file(f"{ra3_response_path}areas.json")
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/area")
        response.set_result(ra3_area_list_result)
        leap.requests.task_done()

        # Read request on /project
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/project")
        response.set_result(response_from_json_file(f"{ra3_response_path}project.json"))
        leap.requests.task_done()

        # Read request on /device?where=IsThisDevice:true
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="ReadRequest", url="/device?where=IsThisDevice:true"
        )
        response.set_result(
            response_from_json_file(f"{ra3_response_path}/processor.json")
        )
        leap.requests.task_done()

        # Read request on each area's control stations & zones
        for area_id in (
            re.sub(r".*/", "", area["href"])
            for area in ra3_area_list_result.Body.get("Areas", [])
            if area["IsLeaf"]
        ):
            request, response = await wait(leap.requests.get())
            assert request == Request(
                communique_type="ReadRequest",
                url=f"/area/{area_id}/associatedcontrolstation",
            )
            station_result = response_from_json_file(
                f"{ra3_response_path}area/{area_id}/controlstation.json"
            )
            response.set_result(station_result)
            leap.requests.task_done()
            await self._process_station(station_result, leap, wait, RA3_PROCESSOR)

            request, response = await wait(leap.requests.get())
            assert request == Request(
                communique_type="ReadRequest", url=f"/area/{area_id}/associatedzone"
            )
            zone_result = response_from_json_file(
                f"{ra3_response_path}area/{area_id}/associatedzone.json"
            )
            response.set_result(zone_result)
            leap.requests.task_done()

        # Read request on /zone/status
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="SubscribeRequest", url="/zone/status"
        )
        response.set_result(
            response_from_json_file(f"{ra3_response_path}zonestatus.json")
        )
        leap.requests.task_done()

        # Read request on /device?where=IsThisDevice:false
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="ReadRequest", url="/device?where=IsThisDevice:false"
        )
        response.set_result(
            response_from_json_file(f"{ra3_response_path}device-list.json")
        )
        leap.requests.task_done()

        # Subscribe request on /area/status
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="SubscribeRequest", url="/area/status"
        )
        response.set_result(
            response_from_json_file(f"{ra3_response_path}area/status-subscribe.json")
        )
        leap.requests.task_done()

    async def _accept_connection_qsx(self, leap, wait):
        """Accept a connection as a mock QSX processor (implementation)."""
        hwqsx_response_path = RESPONSE_PATH[HWQSX_PROCESSOR]

        # Read request on /areas
        qsx_area_list_result = response_from_json_file(
            f"{hwqsx_response_path}areas.json"
        )
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/area")
        response.set_result(qsx_area_list_result)
        leap.requests.task_done()

        # Read request on /project
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/project")
        response.set_result(
            response_from_json_file(f"{hwqsx_response_path}project.json")
        )
        leap.requests.task_done()

        # Read request on /device?where=IsThisDevice:true
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="ReadRequest", url="/device?where=IsThisDevice:true"
        )
        response.set_result(
            response_from_json_file(f"{hwqsx_response_path}processor.json")
        )
        leap.requests.task_done()

        # Read request on each area's control stations & zones
        for area_id in (
            re.sub(r".*/", "", area["href"])
            for area in qsx_area_list_result.Body.get("Areas", [])
            if area["IsLeaf"]
        ):
            request, response = await wait(leap.requests.get())
            assert request == Request(
                communique_type="ReadRequest",
                url=f"/area/{area_id}/associatedcontrolstation",
            )
            station_result = response_from_json_file(
                f"{hwqsx_response_path}area/{area_id}/controlstation.json"
            )
            response.set_result(station_result)
            leap.requests.task_done()
            await self._process_station(
                station_result, leap, wait, bridge_type=HWQSX_PROCESSOR
            )

            request, response = await wait(leap.requests.get())
            assert request == Request(
                communique_type="ReadRequest", url=f"/area/{area_id}/associatedzone"
            )
            zone_result = response_from_json_file(
                f"{hwqsx_response_path}area/{area_id}/associatedzone.json"
            )
            response.set_result(zone_result)
            leap.requests.task_done()

        # Read request on /zone/status
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="SubscribeRequest", url="/zone/status"
        )
        response.set_result(
            response_from_json_file(f"{hwqsx_response_path}zonestatus.json")
        )
        leap.requests.task_done()

        # Read request on /device?where=IsThisDevice:false
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="ReadRequest", url="/device?where=IsThisDevice:false"
        )
        response.set_result(
            response_from_json_file(f"{hwqsx_response_path}device-list.json")
        )
        leap.requests.task_done()

        # Subscribe request on /area/status
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="SubscribeRequest", url="/area/status"
        )
        response.set_result(
            response_from_json_file(f"{hwqsx_response_path}area/status-subscribe.json")
        )
        leap.requests.task_done()

    def disconnect(self, exception=None):
        """Disconnect SmartBridge."""
        if exception is None:
            self.leap.running.set_result(None)
        else:
            self.leap.running.set_exception(exception)

    async def accept_connection(self):
        """Wait for SmartBridge to reconnect."""
        leap = await self.connections.get()

        async def wait(coro):
            # nothing special
            result = await coro
            return result

        await self._accept_connection(leap, wait)

        self.leap = leap
        self.connections.task_done()


@pytest.fixture(name="bridge_uninit")
async def fixture_bridge_uninit() -> AsyncGenerator[Bridge, None]:
    """
    Create a bridge attached to a fake reader and writer but not yet initialized.

    This is used for tests that need to customize the virtual devices present during
    initialization.
    """
    harness = Bridge()

    yield harness

    await harness.target.close()


@pytest.fixture(name="bridge")
async def fixture_bridge(bridge_uninit) -> AsyncGenerator[Bridge, None]:
    """Create a bridge attached to a fake reader and writer."""
    await bridge_uninit.initialize(CASETA_PROCESSOR)

    yield bridge_uninit


@pytest.fixture(name="ra3_bridge")
async def fixture_bridge_ra3(bridge_uninit) -> AsyncGenerator[Bridge, None]:
    """Create a RA3 bridge attached to a fake reader and writer."""
    await bridge_uninit.initialize(RA3_PROCESSOR)

    yield bridge_uninit


@pytest.fixture(name="qsx_processor")
async def fixture_bridge_qsx(bridge_uninit) -> AsyncGenerator[Bridge, None]:
    """Create a QSX processor attached to a fake reader and writer."""
    await bridge_uninit.initialize(HWQSX_PROCESSOR)

    yield bridge_uninit


@pytest.mark.asyncio
async def test_notifications(bridge: Bridge):
    """Test notifications are sent to subscribers."""
    notified = False

    def callback():
        nonlocal notified
        notified = True

    bridge.target.add_subscriber("2", callback)
    bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/1/status",
            ),
            Body={"ZoneStatus": {"Level": 100, "Zone": {"href": "/zone/1"}}},
        )
    )
    await asyncio.wait_for(bridge.leap.requests.join(), 10)
    assert notified


@pytest.mark.asyncio
async def test_device_list(bridge: Bridge):
    """Test methods getting devices."""
    devices = bridge.target.get_devices()
    expected_devices = {
        "1": {
            "device_id": "1",
            "name": "Smart Bridge",
            "type": "SmartBridge",
            "zone": None,
            "current_state": -1,
            "fan_speed": None,
            "model": "L-BDG2-WH",
            "serial": 1234,
            "button_groups": None,
            "tilt": None,
            "occupancy_sensors": None,
        },
        "2": {
            "device_id": "2",
            "name": "Hallway_Lights",
            "type": "WallDimmer",
            "zone": "1",
            "model": "PD-6WCL-XX",
            "serial": 2345,
            "current_state": -1,
            "fan_speed": None,
            "button_groups": None,
            "tilt": None,
            "occupancy_sensors": None,
        },
        "3": {
            "device_id": "3",
            "name": "Hallway_Fan",
            "type": "CasetaFanSpeedController",
            "zone": "2",
            "model": "PD-FSQN-XX",
            "serial": 3456,
            "current_state": -1,
            "fan_speed": None,
            "button_groups": None,
            "tilt": None,
            "occupancy_sensors": None,
        },
        "4": {
            "device_id": "4",
            "name": "Living Room_Occupancy Sensor",
            "type": "RPSOccupancySensor",
            "model": "LRF2-XXXXB-P-XX",
            "serial": 4567,
            "current_state": -1,
            "fan_speed": None,
            "zone": None,
            "button_groups": None,
            "tilt": None,
            "occupancy_sensors": ["2"],
        },
        "5": {
            "device_id": "5",
            "name": "Master Bathroom_Occupancy Sensor Door",
            "type": "RPSOccupancySensor",
            "model": "PD-VSENS-XX",
            "serial": 5678,
            "current_state": -1,
            "fan_speed": None,
            "zone": None,
            "button_groups": None,
            "tilt": None,
            "occupancy_sensors": ["3"],
        },
        "6": {
            "device_id": "6",
            "name": "Master Bathroom_Occupancy Sensor Tub",
            "type": "RPSOccupancySensor",
            "model": "PD-OSENS-XX",
            "serial": 6789,
            "current_state": -1,
            "fan_speed": None,
            "zone": None,
            "button_groups": None,
            "tilt": None,
            "occupancy_sensors": ["4"],
        },
        "7": {
            "device_id": "7",
            "name": "Living Room_Living Shade 3",
            "type": "QsWirelessShade",
            "model": "QSYC-J-RCVR",
            "serial": 1234,
            "current_state": -1,
            "fan_speed": None,
            "zone": "6",
            "button_groups": None,
            "tilt": None,
            "occupancy_sensors": None,
        },
        "8": {
            "device_id": "8",
            "name": "Master Bedroom_Pico",
            "type": "Pico3ButtonRaiseLower",
            "model": "PJ2-3BRL-GXX-X01",
            "serial": 4321,
            "current_state": -1,
            "fan_speed": None,
            "button_groups": ["2"],
            "zone": None,
            "tilt": None,
            "occupancy_sensors": None,
        },
        "9": {
            "button_groups": ["5", "6"],
            "current_state": -1,
            "device_id": "9",
            "fan_speed": None,
            "model": "CS-YJ-4GC-WH",
            "name": "Living Room_Blinds Remote",
            "serial": 92322656,
            "type": "FourGroupRemote",
            "zone": None,
            "tilt": None,
            "occupancy_sensors": None,
        },
        "10": {
            "device_id": "10",
            "name": "Living Room_Blinds",
            "type": "SerenaTiltOnlyWoodBlind",
            "zone": "3",
            "model": "SYC-EDU-B-J",
            "serial": 4567,
            "current_state": -1,
            "fan_speed": None,
            "button_groups": None,
            "tilt": None,
            "occupancy_sensors": None,
        },
    }

    assert devices == expected_devices

    bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/1/status",
            ),
            Body={"ZoneStatus": {"Level": 100, "Zone": {"href": "/zone/1"}}},
        )
    )
    bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/2/status",
            ),
            Body={"ZoneStatus": {"FanSpeed": "Medium", "Zone": {"href": "/zone/2"}}},
        )
    )
    bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/3/status",
            ),
            Body={"ZoneStatus": {"Tilt": 25, "Zone": {"href": "/zone/3"}}},
        )
    )
    devices = bridge.target.get_devices()
    assert devices["2"]["current_state"] == 100
    assert devices["2"]["fan_speed"] is None
    assert devices["3"]["current_state"] == -1
    assert devices["3"]["fan_speed"] == FAN_MEDIUM
    assert devices["10"]["current_state"] == -1
    assert devices["10"]["tilt"] == 25

    devices = bridge.target.get_devices_by_domain("light")
    assert len(devices) == 1
    assert devices[0]["device_id"] == "2"

    devices = bridge.target.get_devices_by_type("WallDimmer")
    assert len(devices) == 1
    assert devices[0]["device_id"] == "2"

    devices = bridge.target.get_devices_by_types(("SmartBridge", "WallDimmer"))
    assert len(devices) == 2

    device = bridge.target.get_device_by_id("2")
    assert device["device_id"] == "2"

    devices = bridge.target.get_devices_by_domain("fan")
    assert len(devices) == 1
    assert devices[0]["device_id"] == "3"

    devices = bridge.target.get_devices_by_type("CasetaFanSpeedController")
    assert len(devices) == 1
    assert devices[0]["device_id"] == "3"

    devices = bridge.target.get_devices_by_domain("cover")
    assert [device["device_id"] for device in devices] == ["7", "10"]

    devices = bridge.target.get_devices_by_type("SerenaTiltOnlyWoodBlind")
    assert [device["device_id"] for device in devices] == ["10"]


@pytest.mark.asyncio
async def test_lip_device_list(bridge: Bridge):
    """Test methods getting devices."""
    devices = bridge.target.lip_devices
    expected_devices = {
        33: {
            "Name": "Pico",
            "ID": 33,
            "Area": {"Name": "Kitchen"},
            "Buttons": [
                {"Number": 2},
                {"Number": 3},
                {"Number": 4},
                {"Number": 5},
                {"Number": 6},
            ],
        },
        36: {
            "Name": "Left Pico",
            "ID": 36,
            "Area": {"Name": "Master Bedroom"},
            "Buttons": [{"Number": 2}, {"Number": 4}],
        },
    }

    assert devices == expected_devices


def test_scene_list(bridge: Bridge):
    """Test methods getting scenes."""
    scenes = bridge.target.get_scenes()
    assert scenes == {"1": {"scene_id": "1", "name": "scene 1"}}
    scene = bridge.target.get_scene_by_id("1")
    assert scene == {"scene_id": "1", "name": "scene 1"}


@pytest.mark.asyncio
async def test_is_connected(bridge: Bridge):
    """Test the is_connected method returns connection state."""
    assert bridge.target.is_connected() is True

    def connect():
        raise NotImplementedError()

    other = smartbridge.Smartbridge(connect)
    assert other.is_connected() is False


@pytest.mark.asyncio
async def test_area_list(bridge: Bridge):
    """Test the list of areas loaded by the bridge."""
    expected_areas = {
        "1": {"id": "1", "name": "root"},
        "2": {"id": "2", "name": "Hallway"},
        "3": {"id": "3", "name": "Living Room"},
        "4": {"id": "4", "name": "Master Bathroom"},
    }

    assert bridge.target.areas == expected_areas


@pytest.mark.asyncio
async def test_occupancy_group_list(bridge: Bridge):
    """Test the list of occupancy groups loaded by the bridge."""
    # Occupancy group 1 has no sensors, so it shouldn't appear here
    expected_groups = {
        "2": {
            "occupancy_group_id": "2",
            "name": "Living Room Occupancy",
            "status": OCCUPANCY_GROUP_OCCUPIED,
            "sensors": ["1"],
        },
        "3": {
            "occupancy_group_id": "3",
            "name": "Master Bathroom Occupancy",
            "status": OCCUPANCY_GROUP_UNOCCUPIED,
            "sensors": ["2", "3"],
        },
    }

    assert bridge.target.occupancy_groups == expected_groups


@pytest.mark.asyncio
async def test_initialization_without_buttons(bridge_uninit: Bridge):
    """Test the that the bridge initializes even if no button status is returned."""
    bridge = bridge_uninit

    # Apparently if a user has no buttons the list of buttons is omitted.
    # See #87.
    bridge.button_list_result = Response(
        Header=ResponseHeader(
            StatusCode=ResponseStatus(code=200, message="OK"),
            Url="/button",
            MessageBodyType="MultipleButtonDefinition",
        ),
        CommuniqueType="ReadResponse",
        Body={},
    )

    await bridge.initialize()

    assert bridge.target.buttons == {}


@pytest.mark.asyncio
async def test_occupancy_no_bodies(bridge_uninit: Bridge):
    """Test the that the bridge initializes even if no occupancy status is returned."""
    bridge = bridge_uninit

    # unconfirmed: user says sometimes they get back a response where the body is None.
    # It's unclear if there is some other indication via StatusCode or MessageBodyType
    # that the body is missing.
    # See #61
    bridge.occupancy_group_list_result = Response(
        Header=ResponseHeader(
            StatusCode=ResponseStatus(code=200, message="OK"),
            Url="/occupancygroup",
            MessageBodyType="MultipleOccupancyGroupDefinition",
        ),
        CommuniqueType="ReadResponse",
        Body=None,
    )
    bridge.occupancy_group_subscription_data_result = Response(
        Header=ResponseHeader(
            StatusCode=ResponseStatus(code=200, message="OK"),
            Url="/occupancygroup/status",
            MessageBodyType="MultipleOccupancyGroupStatus",
        ),
        CommuniqueType="SubscribeResponse",
        Body=None,
    )

    await bridge.initialize()

    assert bridge.target.occupancy_groups == {}


@pytest.mark.asyncio
async def test_occupancy_group_status_change(bridge: Bridge):
    """Test that the status is updated when occupancy changes."""
    bridge.leap.send_to_subscribers(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="MultipleOccupancyGroupStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/occupancygroup/status",
            ),
            Body={
                "OccupancyGroupStatuses": [
                    {
                        "href": "/occupancygroup/2/status",
                        "OccupancyGroup": {"href": "/occupancygroup/2"},
                        "OccupancyStatus": "Unoccupied",
                    }
                ]
            },
        )
    )
    new_status = bridge.target.occupancy_groups["2"]["status"]
    assert new_status == OCCUPANCY_GROUP_UNOCCUPIED


@pytest.mark.asyncio
async def test_occupancy_group_status_change_notification(bridge: Bridge):
    """Test that occupancy status changes send notifications."""
    notified = False

    def notify():
        nonlocal notified
        notified = True

    bridge.target.add_occupancy_subscriber("2", notify)
    bridge.leap.send_to_subscribers(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="MultipleOccupancyGroupStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/occupancygroup/status",
            ),
            Body={
                "OccupancyGroupStatuses": [
                    {
                        "href": "/occupancygroup/2/status",
                        "OccupancyGroup": {"href": "/occupancygroup/2"},
                        "OccupancyStatus": "Unoccupied",
                    }
                ]
            },
        )
    )
    assert notified


@pytest.mark.asyncio
async def test_button_status_change(bridge: Bridge):
    """Test that the status is updated when Pico button is pressed."""
    bridge.leap.send_to_subscribers(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneButtonStatusEvent",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/button/101/status/event",
            ),
            Body={
                "ButtonStatus": {
                    "Button": {"href": "/button/101"},
                    "ButtonEvent": {"EventType": "Press"},
                }
            },
        )
    )
    new_status = bridge.target.buttons["101"]["current_state"]
    assert new_status == BUTTON_STATUS_PRESSED


@pytest.mark.asyncio
async def test_button_status_change_notification(bridge: Bridge):
    """Test that button status changes send notifications."""
    notified = False

    def notify(status):
        assert status == BUTTON_STATUS_PRESSED
        nonlocal notified
        notified = True

    bridge.target.add_button_subscriber("101", notify)
    bridge.leap.send_to_subscribers(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneButtonStatusEvent",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/button/101/status/event",
            ),
            Body={
                "ButtonStatus": {
                    "Button": {"href": "/button/101"},
                    "ButtonEvent": {"EventType": "Press"},
                }
            },
        )
    )
    assert notified


@pytest.mark.asyncio
async def test_is_on(bridge: Bridge):
    """Test the is_on method returns device state."""
    bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/1/status",
            ),
            Body={"ZoneStatus": {"Level": 50, "Zone": {"href": "/zone/1"}}},
        )
    )
    assert bridge.target.is_on("2") is True

    bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/1/status",
            ),
            Body={"ZoneStatus": {"Level": 0, "Zone": {"href": "/zone/1"}}},
        )
    )
    assert bridge.target.is_on("2") is False


@pytest.mark.asyncio
async def test_is_on_fan(bridge: Bridge):
    """Test the is_on method returns device state for fans."""
    bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/1/status",
            ),
            Body={"ZoneStatus": {"FanSpeed": "Medium", "Zone": {"href": "/zone/1"}}},
        )
    )
    assert bridge.target.is_on("2") is True

    bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/1/status",
            ),
            Body={"ZoneStatus": {"FanSpeed": "Off", "Zone": {"href": "/zone/1"}}},
        )
    )
    assert bridge.target.is_on("2") is False


@pytest.mark.asyncio
async def test_set_value(bridge: Bridge, event_loop):
    """Test that setting values produces the right commands."""
    task = event_loop.create_task(bridge.target.set_value("2", 50))
    command, response = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/1/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 50}],
            }
        },
    )
    response.set_result(
        Response(
            CommuniqueType="CreateResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(201, "Created"),
                Url="/zone/1/commandprocessor",
            ),
            Body={
                "ZoneStatus": {
                    "href": "/zone/1/status",
                    "Level": 50,
                    "Zone": {"href": "/zone/1"},
                }
            },
        )
    )
    bridge.leap.requests.task_done()
    await task

    task = event_loop.create_task(bridge.target.turn_on("2"))
    command, response = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/1/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 100}],
            }
        },
    )
    response.set_result(
        Response(
            CommuniqueType="CreateResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(201, "Created"),
                Url="/zone/1/commandprocessor",
            ),
            Body={
                "ZoneStatus": {
                    "href": "/zone/1/status",
                    "Level": 100,
                    "Zone": {"href": "/zone/1"},
                }
            },
        ),
    )
    bridge.leap.requests.task_done()
    await task

    task = event_loop.create_task(bridge.target.turn_off("2"))
    command, response = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/1/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 0}],
            }
        },
    )
    response.set_result(
        Response(
            CommuniqueType="CreateResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(201, "Created"),
                Url="/zone/1/commandprocessor",
            ),
            Body={
                "ZoneStatus": {
                    "href": "/zone/1/status",
                    "Level": 0,
                    "Zone": {"href": "/zone/1"},
                }
            },
        ),
    )
    bridge.leap.requests.task_done()
    await task


@pytest.mark.asyncio
async def test_set_value_with_fade(bridge: Bridge, event_loop):
    """Test that setting values with fade_time produces the right commands."""
    task = event_loop.create_task(
        bridge.target.set_value("2", 50, fade_time=timedelta(seconds=4))
    )
    command, _ = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/1/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToDimmedLevel",
                "DimmedLevelParameters": {"Level": 50, "FadeTime": "00:00:04"},
            }
        },
    )
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_set_fan(bridge: Bridge, event_loop):
    """Test that setting fan speed produces the right commands."""
    task = event_loop.create_task(bridge.target.set_fan("2", FAN_MEDIUM))
    command, _ = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/1/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToFanSpeed",
                "FanSpeedParameters": {"FanSpeed": "Medium"},
            }
        },
    )
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_set_tilt(bridge: Bridge, event_loop):
    """Test that setting tilt produces the right commands."""
    task = event_loop.create_task(bridge.target.set_tilt("10", 50))
    command, _ = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/3/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToTilt",
                "TiltParameters": {"Tilt": 50},
            }
        },
    )
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_lower_cover(bridge: Bridge, event_loop):
    """Test that lowering a cover produces the right commands."""
    devices = bridge.target.get_devices()
    task = event_loop.create_task(bridge.target.lower_cover("7"))
    command, response = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/6/commandprocessor",
        body={"Command": {"CommandType": "Lower"}},
    )
    # the real response probably contains more data
    response.set_result(
        Response(
            CommuniqueType="CreateResponse",
            Header=ResponseHeader(
                StatusCode=ResponseStatus(201, "Created"),
                Url="/zone/6/commandprocessor",
            ),
        ),
    )
    bridge.leap.requests.task_done()
    await task
    assert devices["7"]["current_state"] == 0


@pytest.mark.asyncio
async def test_raise_cover(bridge: Bridge, event_loop):
    """Test that raising a cover produces the right commands."""
    devices = bridge.target.get_devices()
    task = event_loop.create_task(bridge.target.raise_cover("7"))
    command, response = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/6/commandprocessor",
        body={"Command": {"CommandType": "Raise"}},
    )
    # the real response probably contains more data
    response.set_result(
        Response(
            CommuniqueType="CreateResponse",
            Header=ResponseHeader(
                StatusCode=ResponseStatus(201, "Created"),
                Url="/zone/6/commandprocessor",
            ),
        ),
    )
    bridge.leap.requests.task_done()
    await task
    assert devices["7"]["current_state"] == 100


@pytest.mark.asyncio
async def test_stop_cover(bridge: Bridge, event_loop):
    """Test that stopping a cover produces the right commands."""
    task = event_loop.create_task(bridge.target.stop_cover("7"))
    command, _ = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/6/commandprocessor",
        body={"Command": {"CommandType": "Stop"}},
    )
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_activate_scene(bridge: Bridge, event_loop):
    """Test that activating scenes produces the right commands."""
    task = event_loop.create_task(bridge.target.activate_scene("1"))
    command, _ = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/virtualbutton/1/commandprocessor",
        body={"Command": {"CommandType": "PressAndRelease"}},
    )
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_reconnect_eof(bridge: Bridge, event_loop):
    """Test that SmartBridge can reconnect on disconnect."""
    time = 0.0
    event_loop.time = lambda: time

    bridge.disconnect()

    await asyncio.sleep(0.0)
    time += smartbridge.RECONNECT_DELAY

    await bridge.accept_connection()

    task = event_loop.create_task(bridge.target.set_value("2", 50))
    command, _ = await bridge.leap.requests.get()
    assert command is not None
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_connect_error(event_loop):
    """Test that SmartBridge can retry failed connections."""
    time = 0.0
    event_loop.time = lambda: time

    tried = asyncio.Event()

    async def fake_connect():
        """Simulate connection error for the test."""
        tried.set()
        raise OSError()

    target = smartbridge.Smartbridge(fake_connect)
    connect_task = event_loop.create_task(target.connect())

    await tried.wait()
    tried.clear()
    time += smartbridge.RECONNECT_DELAY

    await tried.wait()
    connect_task.cancel()


@pytest.mark.asyncio
async def test_reconnect_error(bridge: Bridge, event_loop):
    """Test that SmartBridge can reconnect on error."""
    time = 0.0
    event_loop.time = lambda: time

    bridge.disconnect()

    await asyncio.sleep(0.0)
    time += smartbridge.RECONNECT_DELAY

    await bridge.accept_connection()

    task = event_loop.create_task(bridge.target.set_value("2", 50))
    command, _ = await bridge.leap.requests.get()
    assert command is not None
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_reconnect_timeout(event_loop):
    """Test that SmartBridge can reconnect if the remote does not respond."""
    bridge = Bridge()

    time = 0.0
    event_loop.time = lambda: time

    await bridge.initialize()

    time = smartbridge.PING_INTERVAL
    ping, _ = await bridge.leap.requests.get()
    assert ping == Request(communique_type="ReadRequest", url="/server/1/status/ping")
    bridge.leap.requests.task_done()

    time += smartbridge.REQUEST_TIMEOUT
    await bridge.leap.running
    time += smartbridge.RECONNECT_DELAY
    await bridge.accept_connection()

    task = event_loop.create_task(bridge.target.set_value("2", 50))
    command, _ = await bridge.leap.requests.get()
    assert command is not None
    bridge.leap.requests.task_done()
    task.cancel()

    await bridge.target.close()


@pytest.mark.asyncio
async def test_is_ra3_connected(ra3_bridge: Bridge):
    """Test the is_connected method returns connection state."""
    assert ra3_bridge.target.is_connected() is True

    def connect():
        raise NotImplementedError()

    other = smartbridge.Smartbridge(connect)
    assert other.is_connected() is False
    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_ra3_notifications(ra3_bridge: Bridge):
    """Test notifications are sent to subscribers."""
    notified = False

    def callback():
        nonlocal notified
        notified = True

    ra3_bridge.target.add_subscriber("1377", callback)
    ra3_bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/1337/status",
            ),
            Body={"ZoneStatus": {"Level": 100, "Zone": {"href": "/zone/1377"}}},
        )
    )
    await asyncio.wait_for(ra3_bridge.leap.requests.join(), 10)
    assert notified
    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_ra3_device_list(ra3_bridge: Bridge):
    """Test methods getting devices."""
    devices = ra3_bridge.target.get_devices()
    expected_devices = {
        "1": {
            "area_name": "Equipment Room",
            "button_groups": None,
            "current_state": -1,
            "device_id": "1",
            "device_type": "RadioRa3Processor",
            "fan_speed": None,
            "model": "JanusProcRA3",
            "name": "Equipment Room_Enclosure Device 001_RadioRa3Processor",
            "processor_name": "Enclosure Device 001",
            "serial": 11111111,
            "type": None,
            "zone": "1",
        },
        "1361": {
            "button_groups": None,
            "current_state": 0,
            "device_id": "1361",
            "fan_speed": None,
            "model": None,
            "name": "Primary Bath_Vanities",
            "serial": None,
            "tilt": None,
            "type": "Dimmed",
            "zone": "1361",
        },
        "1377": {
            "button_groups": None,
            "current_state": 0,
            "device_id": "1377",
            "fan_speed": None,
            "model": None,
            "name": "Primary Bath_Shower & Tub",
            "serial": None,
            "tilt": None,
            "type": "Dimmed",
            "zone": "1377",
        },
        "1393": {
            "button_groups": None,
            "current_state": 0,
            "device_id": "1393",
            "fan_speed": None,
            "model": None,
            "name": "Primary Bath_Vent",
            "serial": None,
            "tilt": None,
            "type": "Switched",
            "zone": "1393",
        },
        "1488": {
            "area_name": "Primary Bath",
            "button_groups": {
                "1491": {
                    "button_group_id": "1491",
                    "buttons": {
                        "1492": {
                            "button_number": 0,
                            "device_id": "1492",
                            "led": None,
                            "name": "Play/Pause",
                            "state": "Release",
                        },
                        "1495": {
                            "button_number": 1,
                            "device_id": "1495",
                            "led": None,
                            "name": "Favorite",
                            "state": "Release",
                        },
                        "1498": {
                            "button_number": 2,
                            "device_id": "1498",
                            "led": None,
                            "name": "Next Track",
                            "state": "Release",
                        },
                        "1501": {
                            "button_number": 3,
                            "device_id": "1501",
                            "led": None,
                            "name": "Volume Up",
                            "state": "Release",
                        },
                        "1504": {
                            "button_number": 4,
                            "device_id": "1504",
                            "led": None,
                            "name": "Volume Down",
                            "state": "Release",
                        },
                    },
                }
            },
            "control_station_name": "Entry",
            "current_state": -1,
            "device_id": "1488",
            "fan_speed": None,
            "model": "PJ2-3BRL-XXX-A02",
            "name": "Audio Pico",
            "serial": None,
            "type": "Pico3ButtonRaiseLower",
            "zone": None,
        },
        "2010": {
            "button_groups": None,
            "current_state": 0,
            "device_id": "2010",
            "fan_speed": None,
            "model": None,
            "name": "Porch_Porch",
            "serial": None,
            "tilt": None,
            "type": "Dimmed",
            "zone": "2010",
        },
        "2091": {
            "button_groups": None,
            "current_state": 0,
            "device_id": "2091",
            "fan_speed": None,
            "model": None,
            "name": "Entry_Overhead",
            "serial": None,
            "tilt": None,
            "type": "Dimmed",
            "zone": "2091",
        },
        "2107": {
            "button_groups": None,
            "current_state": 0,
            "device_id": "2107",
            "fan_speed": None,
            "model": None,
            "name": "Entry_Landscape",
            "serial": None,
            "tilt": None,
            "type": "Dimmed",
            "zone": "2107",
        },
        "2139": {
            "area_name": "Entry",
            "button_groups": {
                "2148": {
                    "button_group_id": "2148",
                    "buttons": {
                        "2149": {
                            "button_number": 1,
                            "device_id": "2149",
                            "led": {"current_state": -1, "led_id": "2144"},
                            "name": "Bright",
                            "state": "Release",
                        },
                        "2153": {
                            "button_number": 2,
                            "device_id": "2153",
                            "led": {"current_state": -1, "led_id": "2145"},
                            "name": "Entertain",
                            "state": "Release",
                        },
                        "2157": {
                            "button_number": 3,
                            "device_id": "2157",
                            "led": {"current_state": -1, "led_id": "2146"},
                            "name": "Dining",
                            "state": "Release",
                        },
                        "2161": {
                            "button_number": 4,
                            "device_id": "2161",
                            "led": {"current_state": -1, "led_id": "2147"},
                            "name": "Off",
                            "state": "Release",
                        },
                    },
                }
            },
            "control_station_name": "Entry by Living Room",
            "current_state": -1,
            "device_id": "2139",
            "fan_speed": None,
            "model": "RRST-W4B-XX",
            "name": "Scene Keypad",
            "serial": None,
            "type": "SunnataKeypad",
            "zone": None,
        },
        "2171": {
            "area_name": "Entry",
            "button_groups": {
                "2180": {
                    "button_group_id": "2180",
                    "buttons": {
                        "2181": {
                            "button_number": 1,
                            "device_id": "2181",
                            "led": {"current_state": -1, "led_id": "2176"},
                            "name": "Fan High",
                            "state": "Release",
                        },
                        "2185": {
                            "button_number": 2,
                            "device_id": "2185",
                            "led": {"current_state": -1, "led_id": "2177"},
                            "name": "Medium",
                            "state": "Release",
                        },
                        "2189": {
                            "button_number": 3,
                            "device_id": "2189",
                            "led": {"current_state": -1, "led_id": "2178"},
                            "name": "Low",
                            "state": "Release",
                        },
                        "2193": {
                            "button_number": 4,
                            "device_id": "2193",
                            "led": {"current_state": -1, "led_id": "2179"},
                            "name": "Off",
                            "state": "Release",
                        },
                    },
                }
            },
            "control_station_name": "Entry by Living Room",
            "current_state": -1,
            "device_id": "2171",
            "fan_speed": None,
            "model": "RRST-W4B-XX",
            "name": "Fan Keypad",
            "serial": None,
            "type": "SunnataKeypad",
            "zone": None,
        },
        "2939": {
            "area_name": "Primary Bath",
            "button_groups": {
                "2942": {
                    "button_group_id": "2942",
                    "buttons": {
                        "2943": {
                            "button_number": 0,
                            "device_id": "2943",
                            "led": None,
                            "name": "Play/Pause",
                            "state": "Release",
                        },
                        "2946": {
                            "button_number": 1,
                            "device_id": "2946",
                            "led": None,
                            "name": "Favorite",
                            "state": "Release",
                        },
                        "2949": {
                            "button_number": 2,
                            "device_id": "2949",
                            "led": None,
                            "name": "Next Track",
                            "state": "Release",
                        },
                        "2952": {
                            "button_number": 3,
                            "device_id": "2952",
                            "led": None,
                            "name": "Volume Up",
                            "state": "Release",
                        },
                        "2955": {
                            "button_number": 4,
                            "device_id": "2955",
                            "led": None,
                            "name": "Volume Down",
                            "state": "Release",
                        },
                    },
                }
            },
            "control_station_name": "Vanity",
            "current_state": -1,
            "device_id": "2939",
            "fan_speed": None,
            "model": "PJ2-3BRL-XXX-A02",
            "name": "Audio Pico",
            "serial": None,
            "type": "Pico3ButtonRaiseLower",
            "zone": None,
        },
        "5341": {
            "area_name": "Equipment Room",
            "button_groups": {
                "5344": {
                    "button_group_id": "5344",
                    "buttons": {
                        "5345": {
                            "button_number": 0,
                            "device_id": "5345",
                            "led": None,
                            "name": "On",
                            "state": "Release",
                        },
                        "5348": {
                            "button_number": 1,
                            "device_id": "5348",
                            "led": None,
                            "name": "Favorite",
                            "state": "Release",
                        },
                        "5351": {
                            "button_number": 2,
                            "device_id": "5351",
                            "led": None,
                            "name": "Off",
                            "state": "Release",
                        },
                        "5354": {
                            "button_number": 3,
                            "device_id": "5354",
                            "led": None,
                            "name": "Raise",
                            "state": "Release",
                        },
                        "5357": {
                            "button_number": 4,
                            "device_id": "5357",
                            "led": None,
                            "name": "Lower",
                            "state": "Release",
                        },
                    },
                }
            },
            "control_station_name": "TestingPico",
            "current_state": -1,
            "device_id": "5341",
            "fan_speed": None,
            "model": "PJ2-3BRL-XXX-L01",
            "name": "TestingPicoDev",
            "serial": 68130838,
            "type": "Pico3ButtonRaiseLower",
            "zone": None,
        },
        "536": {
            "button_groups": None,
            "current_state": 0,
            "device_id": "536",
            "fan_speed": None,
            "model": None,
            "name": "Equipment Room_Overhead",
            "serial": None,
            "tilt": None,
            "type": "Switched",
            "zone": "536",
        },
    }

    assert devices == expected_devices

    ra3_bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/1377/status",
            ),
            Body={"ZoneStatus": {"Level": 100, "Zone": {"href": "/zone/1377"}}},
        )
    )

    devices = ra3_bridge.target.get_devices()
    assert devices["1377"]["current_state"] == 100
    assert devices["1488"]["current_state"] == -1

    devices = ra3_bridge.target.get_devices_by_domain("light")
    assert len(devices) == 5
    assert devices[0]["device_id"] == "1361"

    devices = ra3_bridge.target.get_devices_by_type("Dimmed")
    assert len(devices) == 5
    assert devices[0]["device_id"] == "1361"

    devices = ra3_bridge.target.get_devices_by_types(
        ("Pico3ButtonRaiseLower", "Dimmed")
    )
    assert len(devices) == 8

    device = ra3_bridge.target.get_device_by_id("2939")
    assert device["device_id"] == "2939"

    devices = ra3_bridge.target.get_devices_by_domain("fan")
    assert len(devices) == 0

    devices = ra3_bridge.target.get_devices_by_type("CasetaFanSpeedController")
    assert len(devices) == 0

    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_ra3_area_list(ra3_bridge: Bridge):
    """Test the list of areas loaded by the bridge."""
    expected_areas = {
        "2796": {"id": "2796", "name": "Porch"},
        "547": {"id": "547", "name": "Primary Bath"},
        "766": {"id": "766", "name": "Entry"},
        "83": {"id": "83", "name": "Equipment Room"},
    }

    assert ra3_bridge.target.areas == expected_areas
    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_ra3_button_status_change(ra3_bridge: Bridge):
    """Test that the status is updated when Pico button is pressed."""
    ra3_bridge.leap.send_to_subscribers(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneButtonStatusEvent",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/button/2946/status/event",
            ),
            Body={
                "ButtonStatus": {
                    "Button": {"href": "/button/2946"},
                    "ButtonEvent": {"EventType": "Press"},
                }
            },
        )
    )

    new_status = ra3_bridge.target.devices["2939"]["button_groups"]["2942"]["buttons"][
        "2946"
    ]["current_state"]
    assert new_status == BUTTON_STATUS_PRESSED
    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_ra3_button_status_change_notification(ra3_bridge: Bridge):
    """Test that button status changes send notifications."""
    button_notified = False
    keypad_notified = False

    def button_notify(status):
        assert status == BUTTON_STATUS_PRESSED
        nonlocal button_notified
        button_notified = True

    def keypad_notify():
        nonlocal keypad_notified
        keypad_notified = True

    ra3_bridge.target.add_button_subscriber("2946", button_notify)
    ra3_bridge.target.add_subscriber("2939", keypad_notify)
    ra3_bridge.leap.send_to_subscribers(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneButtonStatusEvent",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/button/2946/status/event",
            ),
            Body={
                "ButtonStatus": {
                    "Button": {"href": "/button/2946"},
                    "ButtonEvent": {"EventType": "Press"},
                }
            },
        )
    )
    assert button_notified
    assert keypad_notified
    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_ra3_is_on(ra3_bridge: Bridge):
    """Test the is_on method returns device state."""
    ra3_bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/2107/status",
            ),
            Body={"ZoneStatus": {"Level": 50, "Zone": {"href": "/zone/2107"}}},
        )
    )

    assert ra3_bridge.target.is_on("2107") is True

    ra3_bridge.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/zone/2107/status",
            ),
            Body={"ZoneStatus": {"Level": 0, "Zone": {"href": "/zone/2107"}}},
        )
    )

    assert ra3_bridge.target.is_on("2107") is False
    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_ra3_set_value(ra3_bridge: Bridge, event_loop):
    """Test that setting values produces the right commands."""
    task = event_loop.create_task(ra3_bridge.target.set_value("2107", 50))
    command, response = await ra3_bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/2107/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 50}],
            }
        },
    )
    response.set_result(
        Response(
            CommuniqueType="CreateResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(201, "Created"),
                Url="/zone/2107/commandprocessor",
            ),
            Body={
                "ZoneStatus": {
                    "href": "/zone/2107/status",
                    "Level": 50,
                    "Zone": {"href": "/zone/2107"},
                }
            },
        )
    )
    ra3_bridge.leap.requests.task_done()
    await task

    task = event_loop.create_task(ra3_bridge.target.turn_on("2107"))
    command, response = await ra3_bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/2107/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 100}],
            }
        },
    )
    response.set_result(
        Response(
            CommuniqueType="CreateResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(201, "Created"),
                Url="/zone/2107/commandprocessor",
            ),
            Body={
                "ZoneStatus": {
                    "href": "/zone/2107/status",
                    "Level": 100,
                    "Zone": {"href": "/zone/2107"},
                }
            },
        ),
    )
    ra3_bridge.leap.requests.task_done()
    await task

    task = event_loop.create_task(ra3_bridge.target.turn_off("2107"))
    command, response = await ra3_bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/2107/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 0}],
            }
        },
    )
    response.set_result(
        Response(
            CommuniqueType="CreateResponse",
            Header=ResponseHeader(
                MessageBodyType="OneZoneStatus",
                StatusCode=ResponseStatus(201, "Created"),
                Url="/zone/2107/commandprocessor",
            ),
            Body={
                "ZoneStatus": {
                    "href": "/zone/2107/status",
                    "Level": 0,
                    "Zone": {"href": "/zone/2107"},
                }
            },
        ),
    )
    ra3_bridge.leap.requests.task_done()
    await task
    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_ra3_set_value_with_fade(ra3_bridge: Bridge, event_loop):
    """Test that setting values with fade_time produces the right commands."""
    task = event_loop.create_task(
        ra3_bridge.target.set_value("2107", 50, fade_time=timedelta(seconds=4))
    )
    command, _ = await ra3_bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/2107/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToDimmedLevel",
                "DimmedLevelParameters": {"Level": 50, "FadeTime": "00:00:04"},
            }
        },
    )
    ra3_bridge.leap.requests.task_done()
    task.cancel()
    await ra3_bridge.target.close()


@pytest.mark.asyncio
async def test_qsx_set_keypad_led_value(qsx_processor: Bridge, event_loop):
    """Test that setting the value of a keypad LED produces the right command."""
    task = event_loop.create_task(
        qsx_processor.target.turn_led_on("1626", "1635", "1636")
    )
    command, _ = await qsx_processor.leap.requests.get()
    assert command == Request(
        communique_type="UpdateRequest",
        url="/led/1631/status",
        body={"LEDStatus": {"State": "On"}},
    )
    qsx_processor.leap.requests.task_done()
    task.cancel()
    await qsx_processor.target.close()


@pytest.mark.asyncio
async def test_qsx_set_ketra_level(qsx_processor: Bridge, event_loop):
    """
    Test that setting the level of a Ketra lamp without a fade time produces the
    right command.
    """
    task = event_loop.create_task(qsx_processor.target.set_value("985", 50))
    command, _ = await qsx_processor.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/985/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToSpectrumTuningLevel",
                "SpectrumTuningLevelParameters": {"Level": 50},
            }
        },
    )
    qsx_processor.leap.requests.task_done()
    task.cancel()
    await qsx_processor.target.close()


@pytest.mark.asyncio
async def test_qsx_set_ketra_level_with_fade(qsx_processor: Bridge, event_loop):
    """
    Test that setting the level of a Ketra lamp with a fade time produces the
    right command.
    """
    task = event_loop.create_task(
        qsx_processor.target.set_value("985", 50, fade_time=timedelta(seconds=4))
    )
    command, _ = await qsx_processor.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/985/commandprocessor",
        body={
            "Command": {
                "CommandType": "GoToSpectrumTuningLevel",
                "SpectrumTuningLevelParameters": {"Level": 50, "FadeTime": "00:00:04"},
            }
        },
    )
    qsx_processor.leap.requests.task_done()
    task.cancel()
    await qsx_processor.target.close()


@pytest.mark.asyncio
async def test_qsx_tap_button(qsx_processor: Bridge, event_loop):
    """Test that tapping a keypad button produces the right command."""
    task = event_loop.create_task(
        qsx_processor.target.tap_button("1409", "1421", "1422")
    )
    command, _ = await qsx_processor.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/button/1422/commandprocessor",
        body={
            "Command": {
                "CommandType": "PressAndRelease",
            }
        },
    )
    qsx_processor.leap.requests.task_done()
    task.cancel()
    await qsx_processor.target.close()


@pytest.mark.asyncio
async def test_qsx_button_led_notification(qsx_processor: Bridge):
    """Test button LED status events are sent to subscribers."""
    notified = False

    def callback():
        nonlocal notified
        notified = True

    qsx_processor.target.add_subscriber("1631", callback)
    qsx_processor.leap.send_unsolicited(
        Response(
            CommuniqueType="ReadResponse",
            Header=ResponseHeader(
                MessageBodyType="OneLEDStatus",
                StatusCode=ResponseStatus(200, "OK"),
                Url="/led/1631/status",
            ),
            Body={
                "LEDStatus": {
                    "href": "/led/1631/status",
                    "LED": {"href": "/led/1631"},
                    "State": "On",
                }
            },
        )
    )
    await asyncio.wait_for(qsx_processor.leap.requests.join(), 10)
    assert notified


@pytest.mark.asyncio
async def test_get_devices_by_invalid_domain(bridge: Bridge):
    """Tests that getting devices for an invalid domain returns an empty list."""
    devices = bridge.target.get_devices_by_domain("this_is_an_invalid_domain")
    assert devices == []


@pytest.mark.asyncio
async def test_qsx_get_devices_for_invalid_zone(qsx_processor: Bridge):
    """Tests that getting devices for an invalid zone raises an exception."""
    try:
        _ = qsx_processor.target.get_device_by_zone_id("2")
        assert False
    except KeyError:
        assert True


@pytest.mark.asyncio
async def test_ra3_occupancy_group_list(ra3_bridge: Bridge):
    """Test the list of occupancy groups loaded by the bridge."""
    # Occupancy group 766 has multiple sensor devices, but should only appear once
    expected_groups = {
        "766": {
            "occupancy_group_id": "766",
            "name": "Entry Occupancy",
            "status": OCCUPANCY_GROUP_UNKNOWN,
            "sensors": ["1870", "1888"],
        },
        "2796": {
            "occupancy_group_id": "2796",
            "name": "Porch Occupancy",
            "status": OCCUPANCY_GROUP_UNKNOWN,
            "sensors": ["1970"],
        },
    }

    assert ra3_bridge.target.occupancy_groups == expected_groups
