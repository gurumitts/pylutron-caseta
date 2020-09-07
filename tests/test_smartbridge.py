"""Tests to validate ssl interactions."""
import asyncio
import json
import logging
import os
import pytest

try:
    from asyncio import get_running_loop as get_loop
except ImportError:
    # get_running_loop is better, but it was introduced in Python 3.7
    from asyncio import get_event_loop as get_loop

import pylutron_caseta.smartbridge as smartbridge
from pylutron_caseta import (
    FAN_MEDIUM,
    OCCUPANCY_GROUP_OCCUPIED,
    OCCUPANCY_GROUP_UNOCCUPIED,
)

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(logging.StreamHandler())


def response_from_json_file(filename):
    """Fetch a response from a saved JSON file."""
    responsedir = os.path.join(os.path.split(__file__)[0], "responses")
    with open(os.path.join(responsedir, filename), "r") as ifh:
        return json.load(ifh)


class Bridge:
    """A test harness around SmartBridge."""

    def __init__(self):
        """Create a new Bridge in a disconnected state."""
        self._connections = None
        self.reader = self.writer = None

        async def fake_connect():
            """Use by SmartBridge to connect to the test."""
            closed = asyncio.Event()
            reader = _FakeLeapReader(closed, get_loop())
            writer = _FakeLeapWriter(closed, get_loop())
            await self.connections.put((reader, writer))
            return (reader, writer)

        self.target = smartbridge.Smartbridge(fake_connect)

    @property
    def connections(self):
        """Defer creating the connection queue until we are in a loop."""
        if self._connections is None:
            self._connections = asyncio.Queue()
        return self._connections

    async def initialize(self):
        """Perform the initial connection with SmartBridge."""
        connect_task = get_loop().create_task(self.target.connect())
        reader, writer = await self.connections.get()

        async def wait(coro):
            # abort if SmartBridge reports it has finished connecting early
            task = get_loop().create_task(coro)
            done, _ = await asyncio.wait(
                (connect_task, task), timeout=10, return_when=asyncio.FIRST_COMPLETED
            )
            assert len(done) > 0, "operation timed out"
            if len(done) == 1 and connect_task in done:
                raise connect_task.exception()
            result = await task
            return result

        await self._accept_connection(reader, writer, wait)
        await connect_task

        self.reader = reader
        self.writer = writer
        self.connections.task_done()

    async def _accept_connection(self, reader, writer, wait):
        """Accept a connection from SmartBridge (implementation)."""
        # First message should be read request on /device
        value = await wait(writer.queue.get())
        assert value == {"CommuniqueType": "ReadRequest", "Header": {"Url": "/device"}}
        writer.queue.task_done()
        await reader.write(response_from_json_file("devices.json"))
        # Second message should be read request on /virtualbutton
        value = await wait(writer.queue.get())
        assert value == {
            "CommuniqueType": "ReadRequest",
            "Header": {"Url": "/virtualbutton"},
        }
        writer.queue.task_done()
        await reader.write(response_from_json_file("scenes.json"))
        # Third message should be read request on /areas
        value = await wait(writer.queue.get())
        assert value == {"CommuniqueType": "ReadRequest", "Header": {"Url": "/area"}}
        writer.queue.task_done()
        await reader.write(response_from_json_file("areas.json"))
        # Fourth message should be read request on /occupancygroup
        value = await wait(writer.queue.get())
        assert value == {
            "CommuniqueType": "ReadRequest",
            "Header": {"Url": "/occupancygroup"},
        }
        writer.queue.task_done()
        await reader.write(response_from_json_file("occupancygroups.json"))
        # Fifth message should be subscribe request on /occupancygroup/status
        value = await wait(writer.queue.get())
        assert value == {
            "CommuniqueType": "SubscribeRequest",
            "Header": {"Url": "/occupancygroup/status"},
        }
        writer.queue.task_done()
        await reader.write(response_from_json_file("occupancygroupsubscribe.json"))
        # Finally, we should check the zone status on each zone
        requested_zones = []
        for _ in range(0, 3):
            value = await wait(writer.queue.get())
            logging.info("Read %s", value)
            assert value["CommuniqueType"] == "ReadRequest"
            requested_zones.append(value["Header"]["Url"])
            writer.queue.task_done()
        requested_zones.sort()
        assert requested_zones == ["/zone/1/status", "/zone/2/status", "/zone/6/status"]

    async def disconnect(self, exception=None):
        """Disconnect SmartBridge."""
        await self.reader.end(exception)

    async def accept_connection(self):
        """Wait for SmartBridge to reconnect."""
        reader, writer = await self.connections.get()

        async def wait(coro):
            # nothing special
            result = await coro
            return result

        await self._accept_connection(reader, writer, wait)

        self.reader = reader
        self.writer = writer
        self.connections.task_done()


class _FakeLeapWriter:
    """A "Writer" which just puts messages onto a queue."""

    def __init__(self, closed, loop):
        self.queue = asyncio.Queue()
        self.closed = closed
        self._loop = loop

    def write(self, obj):
        """Send an object to the bridge."""
        self.queue.put_nowait(obj)

    async def drain(self):
        """Wait for all objects to be received by the bridge."""
        task = self._loop.create_task(self.queue.join())
        await asyncio.wait(
            (self.closed.wait(), task), return_when=asyncio.FIRST_COMPLETED
        )

    def abort(self):
        """Close the connection."""
        self.closed.set()


class _FakeLeapReader:
    """A "Reader" which just pulls messages from a queue."""

    def __init__(self, closed, loop):
        self._loop = loop
        self.closed = closed
        self.queue = asyncio.Queue()
        self.exception_value = None
        self.eof = False

    def exception(self):
        """Get the exception."""
        return self.exception_value

    async def read(self):
        """Read an object from the bridge."""
        task = self._loop.create_task(self.queue.get())
        done, _ = await asyncio.wait(
            (self.closed.wait(), task), return_when=asyncio.FIRST_COMPLETED
        )
        if task not in done:
            return None

        action = await task
        self._loop.call_soon(self.queue.task_done)
        try:
            value = action()
        except Exception as exception:
            self.exception_value = exception
            self.eof = True
            raise
        else:
            if value is None:
                self.eof = True
            return value

    async def wait_for(self, communique_type):
        """Wait for a type of message."""
        while True:
            response = await self.read()
            if response.get("CommuniqueType", None) == communique_type:
                return response

    async def write(self, item):
        """Write an object to the queue."""

        def action():
            return item

        await self.queue.put(action)

    def at_eof(self):
        """Check if the connection is closed."""
        return self.closed.is_set() or self.eof

    async def end(self, exception=None):
        """Close the connection."""
        if exception is None:
            await self.write(None)
        else:

            def action():
                raise exception

            await self.queue.put(action)


@pytest.yield_fixture(name="bridge")
def fixture_bridge(event_loop):
    """Create a bridge attached to a fake reader and writer."""
    harness = Bridge()

    event_loop.run_until_complete(harness.initialize())

    yield harness

    event_loop.run_until_complete(harness.target.close())


@pytest.mark.asyncio
async def test_notifications(bridge):
    """Test notifications are sent to subscribers."""
    notified = False

    def callback():
        nonlocal notified
        notified = True

    bridge.target.add_subscriber("2", callback)
    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "OneZoneStatus",
                "StatusCode": "200 OK",
                "Url": "/zone/1/status",
            },
            "Body": {"ZoneStatus": {"Level": 100, "Zone": {"href": "/zone/1"}}},
        }
    )
    await asyncio.wait_for(bridge.reader.queue.join(), 10)
    assert notified


@pytest.mark.asyncio
async def test_device_list(bridge):
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
            "current_state": -1,
            "fan_speed": None,
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
            "current_state": -1,
            "fan_speed": None,
            "zone": "6",
        },
    }

    assert devices == expected_devices

    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "OneZoneStatus",
                "StatusCode": "200 OK",
                "Url": "/zone/1/status",
            },
            "Body": {"ZoneStatus": {"Level": 100, "Zone": {"href": "/zone/1"}}},
        }
    )
    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "OneZoneStatus",
                "StatusCode": "200 OK",
                "Url": "/zone/2/status",
            },
            "Body": {"ZoneStatus": {"FanSpeed": "Medium", "Zone": {"href": "/zone/2"}}},
        }
    )
    await asyncio.wait_for(bridge.reader.queue.join(), 10)
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


def test_scene_list(bridge):
    """Test methods getting scenes."""
    scenes = bridge.target.get_scenes()
    assert scenes == {"1": {"scene_id": "1", "name": "scene 1"}}
    scene = bridge.target.get_scene_by_id("1")
    assert scene == {"scene_id": "1", "name": "scene 1"}


def test_is_connected(bridge):
    """Test the is_connected method returns connection state."""
    assert bridge.target.is_connected() is True

    other = smartbridge.Smartbridge(None)
    assert other.is_connected() is False


@pytest.mark.asyncio
async def test_area_list(bridge):
    """Test the list of areas loaded by the bridge."""
    expected_areas = {
        "1": {"name": "root"},
        "2": {"name": "Hallway"},
        "3": {"name": "Living Room"},
        "4": {"name": "Master Bathroom"},
    }

    assert bridge.target.areas == expected_areas


@pytest.mark.asyncio
async def test_occupancy_group_list(bridge):
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
async def test_occupancy_group_status_change(bridge):
    """Test that the status is updated when occupancy changes."""
    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "MultipleOccupancyGroupStatus",
                "StatusCode": "200 OK",
                "Url": "/occupancygroup/status",
            },
            "Body": {
                "OccupancyGroupStatuses": [
                    {
                        "href": "/occupancygroup/2/status",
                        "OccupancyGroup": {"href": "/occupancygroup/2"},
                        "OccupancyStatus": "Unoccupied",
                    }
                ]
            },
        }
    )
    await asyncio.wait_for(bridge.reader.queue.join(), 10)
    new_status = bridge.target.occupancy_groups["2"]["status"]
    assert new_status == OCCUPANCY_GROUP_UNOCCUPIED


@pytest.mark.asyncio
async def test_occupancy_group_status_change_notification(bridge):
    """Test that occupancy status changes send notifications."""
    notified = False

    def notify():
        nonlocal notified
        notified = True

    bridge.target.add_occupancy_subscriber("2", notify)
    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "MultipleOccupancyGroupStatus",
                "StatusCode": "200 OK",
                "Url": "/occupancygroup/status",
            },
            "Body": {
                "OccupancyGroupStatuses": [
                    {
                        "href": "/occupancygroup/2/status",
                        "OccupancyGroup": {"href": "/occupancygroup/2"},
                        "OccupancyStatus": "Unoccupied",
                    }
                ]
            },
        }
    )
    await asyncio.wait_for(bridge.reader.queue.join(), 10)
    assert notified


@pytest.mark.asyncio
async def test_is_on(bridge):
    """Test the is_on method returns device state."""
    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "OneZoneStatus",
                "StatusCode": "200 OK",
                "Url": "/zone/1/status",
            },
            "Body": {"ZoneStatus": {"Level": 50, "Zone": {"href": "/zone/1"}}},
        }
    )
    await asyncio.wait_for(bridge.reader.queue.join(), 10)
    assert bridge.target.is_on("2") is True

    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "OneZoneStatus",
                "StatusCode": "200 OK",
                "Url": "/zone/1/status",
            },
            "Body": {"ZoneStatus": {"Level": 0, "Zone": {"href": "/zone/1"}}},
        }
    )
    await asyncio.wait_for(bridge.reader.queue.join(), 10)
    assert bridge.target.is_on("2") is False


@pytest.mark.asyncio
async def test_is_on_fan(bridge):
    """Test the is_on method returns device state for fans."""
    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "OneZoneStatus",
                "StatusCode": "200 OK",
                "Url": "/zone/1/status",
            },
            "Body": {"ZoneStatus": {"FanSpeed": "Medium", "Zone": {"href": "/zone/1"}}},
        }
    )
    await asyncio.wait_for(bridge.reader.queue.join(), 10)
    assert bridge.target.is_on("2") is True

    await bridge.reader.write(
        {
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "OneZoneStatus",
                "StatusCode": "200 OK",
                "Url": "/zone/1/status",
            },
            "Body": {"ZoneStatus": {"FanSpeed": "Off", "Zone": {"href": "/zone/1"}}},
        }
    )
    await asyncio.wait_for(bridge.reader.queue.join(), 10)
    assert bridge.target.is_on("2") is False


@pytest.mark.asyncio
async def test_set_value(bridge):
    """Test that setting values produces the right commands."""
    bridge.target.set_value("2", 50)
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/1/commandprocessor"},
        "Body": {
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 50}],
            }
        },
    }

    bridge.target.turn_on("2")
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/1/commandprocessor"},
        "Body": {
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 100}],
            }
        },
    }

    bridge.target.turn_off("2")
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/1/commandprocessor"},
        "Body": {
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 0}],
            }
        },
    }


@pytest.mark.asyncio
async def test_set_fan(bridge):
    """Test that setting fan speed produces the right commands."""
    bridge.target.set_fan("2", FAN_MEDIUM)
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/1/commandprocessor"},
        "Body": {
            "Command": {
                "CommandType": "GoToFanSpeed",
                "FanSpeedParameters": {"FanSpeed": "Medium"},
            }
        },
    }


@pytest.mark.asyncio
async def test_lower_cover(bridge):
    """Test that lowering a cover produces the right commands."""
    devices = bridge.target.get_devices()
    bridge.target.lower_cover("7")
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/6/commandprocessor"},
        "Body": {"Command": {"CommandType": "Lower"}},
    }
    assert devices["7"]["current_state"] == 0


@pytest.mark.asyncio
async def test_raise_cover(bridge):
    """Test that raising a cover produces the right commands."""
    devices = bridge.target.get_devices()
    bridge.target.raise_cover("7")
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/6/commandprocessor"},
        "Body": {"Command": {"CommandType": "Raise"}},
    }
    assert devices["7"]["current_state"] == 100


@pytest.mark.asyncio
async def test_stop_cover(bridge):
    """Test that stopping a cover produces the right commands."""
    bridge.target.stop_cover("7")
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/6/commandprocessor"},
        "Body": {"Command": {"CommandType": "Stop"}},
    }


@pytest.mark.asyncio
async def test_activate_scene(bridge):
    """Test that activating scenes produces the right commands."""
    bridge.target.activate_scene("1")
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/virtualbutton/1/commandprocessor"},
        "Body": {"Command": {"CommandType": "PressAndRelease"}},
    }


@pytest.mark.asyncio
async def test_reconnect_eof(bridge):
    """Test that SmartBridge can reconnect on disconnect."""
    await bridge.disconnect()
    await bridge.accept_connection()
    bridge.target.set_value("2", 50)
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command is not None


@pytest.mark.asyncio
async def test_reconnect_error(bridge):
    """Test that SmartBridge can reconnect on error."""
    await bridge.disconnect()
    await bridge.accept_connection()
    bridge.target.set_value("2", 50)
    command = await asyncio.wait_for(bridge.writer.queue.get(), 10)
    bridge.writer.queue.task_done()
    assert command is not None


@pytest.mark.asyncio
async def test_reconnect_timeout():
    """Test that SmartBridge can reconnect if the remote does not respond."""
    bridge = Bridge()

    time = 0.0

    get_loop().time = lambda: time

    await bridge.initialize()

    time = smartbridge.PING_INTERVAL
    ping = await bridge.writer.queue.get()
    assert ping == {
        "CommuniqueType": "ReadRequest",
        "Header": {"Url": "/server/1/status/ping"},
    }

    time += smartbridge.PING_DELAY
    await bridge.accept_connection()

    bridge.target.set_value("2", 50)
    command = await bridge.writer.queue.get()
    bridge.writer.queue.task_done()
    assert command is not None

    await bridge.target.close()
