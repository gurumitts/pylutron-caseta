"""Tests to validate ssl interactions."""
import asyncio
import json
import logging
import os
from typing import (
    AsyncGenerator,
    Awaitable,
    Callable,
    List,
    NamedTuple,
    Optional,
    TypeVar,
    TYPE_CHECKING,
)

import pytest

from pylutron_caseta.messages import Response, ResponseHeader, ResponseStatus
import pylutron_caseta.smartbridge as smartbridge
from pylutron_caseta import (
    FAN_MEDIUM,
    OCCUPANCY_GROUP_OCCUPIED,
    OCCUPANCY_GROUP_UNOCCUPIED,
    BridgeDisconnectedError,
)

if TYPE_CHECKING:
    from typing import Tuple

logging.getLogger().setLevel(logging.DEBUG)
_LOG = logging.getLogger(__name__)


def response_from_json_file(filename: str) -> Response:
    """Fetch a response from a saved JSON file."""
    responsedir = os.path.join(os.path.split(__file__)[0], "responses")
    with open(os.path.join(responsedir, filename), "r") as ifh:
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
        self._unsolicited: List[Callable[[Response], None]] = []

    async def request(
        self, communique_type: str, url: str, body: Optional[dict] = None
    ) -> dict:
        """Make a request to the bridge and return the response."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        obj = Request(communique_type=communique_type, url=url, body=body)

        await self.requests.put((obj, future))

        return await future

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

        async def fake_connect():
            """Open a fake LEAP connection for the test."""
            leap = _FakeLeap()
            await self.connections.put(leap)
            return leap

        self.target = smartbridge.Smartbridge(fake_connect)

    async def initialize(self):
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

        await self._accept_connection(fake_leap, wait)
        await connect_task

        self.leap = fake_leap
        self.connections.task_done()

    async def _accept_connection(self, leap, wait):
        """Accept a connection from SmartBridge (implementation)."""
        # First message should be read request on /device
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/device")
        response.set_result(response_from_json_file("devices.json"))
        leap.requests.task_done()

        # Second message should be read request on /virtualbutton
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/virtualbutton")
        response.set_result(response_from_json_file("scenes.json"))
        leap.requests.task_done()

        # Third message should be read request on /areas
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/area")
        response.set_result(response_from_json_file("areas.json"))
        leap.requests.task_done()

        # Fourth message should be read request on /occupancygroup
        request, response = await wait(leap.requests.get())
        assert request == Request(communique_type="ReadRequest", url="/occupancygroup")
        response.set_result(response_from_json_file("occupancygroups.json"))
        leap.requests.task_done()

        # Fifth message should be subscribe request on /occupancygroup/status
        request, response = await wait(leap.requests.get())
        assert request == Request(
            communique_type="SubscribeRequest", url="/occupancygroup/status"
        )
        response.set_result(response_from_json_file("occupancygroupsubscribe.json"))
        leap.requests.task_done()

        # Finally, we should check the zone status on each zone
        requested_zones = []
        for _ in range(0, 3):
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
                            "Level": 0,
                            "Zone": {"href": request.url.replace("/status", "")},
                            "StatusAccuracy": "Good",
                        }
                    },
                )
            )
            leap.requests.task_done()
        requested_zones.sort()
        assert requested_zones == ["/zone/1/status", "/zone/2/status", "/zone/6/status"]

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


@pytest.fixture(name="bridge")
async def fixture_bridge() -> AsyncGenerator[Bridge, None]:
    """Create a bridge attached to a fake reader and writer."""
    harness = Bridge()

    await harness.initialize()

    yield harness

    await harness.target.close()


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
        },
        "2": {
            "device_id": "2",
            "name": "Hallway_Lights",
            "type": "WallDimmer",
            "zone": "1",
            "model": "PD-6WCL-XX",
            "serial": 2345,
            "current_state": 0,
            "fan_speed": None,
        },
        "3": {
            "device_id": "3",
            "name": "Hallway_Fan",
            "type": "CasetaFanSpeedController",
            "zone": "2",
            "model": "PD-FSQN-XX",
            "serial": 3456,
            "current_state": 0,
            "fan_speed": None,
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
        },
        "7": {
            "device_id": "7",
            "name": "Living Room_Living Shade 3",
            "type": "QsWirelessShade",
            "model": "QSYC-J-RCVR",
            "serial": 1234,
            "current_state": 0,
            "fan_speed": None,
            "zone": "6",
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
    devices = bridge.target.get_devices()
    assert devices["2"]["current_state"] == 100
    assert devices["2"]["fan_speed"] is None
    assert devices["3"]["current_state"] == -1
    assert devices["3"]["fan_speed"] == FAN_MEDIUM

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
        "1": {"name": "root"},
        "2": {"name": "Hallway"},
        "3": {"name": "Living Room"},
        "4": {"name": "Master Bathroom"},
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
        },
        "3": {
            "occupancy_group_id": "3",
            "name": "Master Bathroom Occupancy",
            "status": OCCUPANCY_GROUP_UNOCCUPIED,
        },
    }

    assert bridge.target.occupancy_groups == expected_groups


@pytest.mark.asyncio
async def test_occupancy_group_status_change(bridge: Bridge):
    """Test that the status is updated when occupancy changes."""
    bridge.leap.send_unsolicited(
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
    bridge.leap.send_unsolicited(
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
async def test_set_value(bridge: Bridge):
    """Test that setting values produces the right commands."""
    task = asyncio.get_running_loop().create_task(bridge.target.set_value("2", 50))
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

    task = asyncio.get_running_loop().create_task(bridge.target.turn_on("2"))
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

    task = asyncio.get_running_loop().create_task(bridge.target.turn_off("2"))
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
async def test_set_fan(bridge: Bridge):
    """Test that setting fan speed produces the right commands."""
    task = asyncio.get_running_loop().create_task(
        bridge.target.set_fan("2", FAN_MEDIUM)
    )
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
async def test_lower_cover(bridge: Bridge):
    """Test that lowering a cover produces the right commands."""
    devices = bridge.target.get_devices()
    task = asyncio.get_running_loop().create_task(bridge.target.lower_cover("7"))
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
async def test_raise_cover(bridge: Bridge):
    """Test that raising a cover produces the right commands."""
    devices = bridge.target.get_devices()
    task = asyncio.get_running_loop().create_task(bridge.target.raise_cover("7"))
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
async def test_stop_cover(bridge: Bridge):
    """Test that stopping a cover produces the right commands."""
    task = asyncio.get_running_loop().create_task(bridge.target.stop_cover("7"))
    command, _ = await bridge.leap.requests.get()
    assert command == Request(
        communique_type="CreateRequest",
        url="/zone/6/commandprocessor",
        body={"Command": {"CommandType": "Stop"}},
    )
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_activate_scene(bridge: Bridge):
    """Test that activating scenes produces the right commands."""
    task = asyncio.get_running_loop().create_task(bridge.target.activate_scene("1"))
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

    task = asyncio.get_running_loop().create_task(bridge.target.set_value("2", 50))
    command, _ = await bridge.leap.requests.get()
    assert command is not None
    bridge.leap.requests.task_done()
    task.cancel()


@pytest.mark.asyncio
async def test_reconnect_error(bridge: Bridge, event_loop):
    """Test that SmartBridge can reconnect on error."""
    time = 0.0
    event_loop.time = lambda: time

    bridge.disconnect()

    await asyncio.sleep(0.0)
    time += smartbridge.RECONNECT_DELAY

    await bridge.accept_connection()

    task = asyncio.get_running_loop().create_task(bridge.target.set_value("2", 50))
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

    task = asyncio.get_running_loop().create_task(bridge.target.set_value("2", 50))
    command, _ = await bridge.leap.requests.get()
    assert command is not None
    bridge.leap.requests.task_done()
    task.cancel()

    await bridge.target.close()
