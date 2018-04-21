"""Tests to validate ssl interactions."""
import asyncio
import pytest
from collections import namedtuple

import pylutron_caseta.smartbridge

Bridge = namedtuple('Bridge', ('target', 'reader', 'writer'))


class _FakeLeapWriter:
    def __init__(self, loop):
        try:
            self.queue = asyncio.JoinableQueue(loop=loop)
        except AttributeError:
            self.queue = asyncio.Queue(loop=loop)

        self.closed = False

    def write(self, obj):
        self.queue.put_nowait(obj)

    @asyncio.coroutine
    def drain(self):
        yield from self.queue.join()

    def close(self):
        self.closed = True


class _FakeLeapReader:
    def __init__(self, loop):
        self._loop = loop
        try:
            self.queue = asyncio.JoinableQueue(loop=loop)
        except AttributeError:
            self.queue = asyncio.Queue(loop=loop)

    def exception(self):
        return None

    @asyncio.coroutine
    def read(self):
        value = yield from self.queue.get()
        self._loop.call_soon(self.queue.task_done)
        return value

    def at_eof(self):
        return False


@pytest.yield_fixture
def bridge(event_loop):
    """Create a bridge attached to a fake reader and writer."""
    reader = _FakeLeapReader(event_loop)
    writer = _FakeLeapWriter(event_loop)

    @asyncio.coroutine
    def fake_connect():
        return (reader, writer)
    bridge = pylutron_caseta.smartbridge.Smartbridge(fake_connect,
                                                     loop=event_loop)

    @asyncio.coroutine
    def initialize_bridge():
        connect_task = event_loop.create_task(bridge.connect())

        @asyncio.coroutine
        def wait(coro):
            task = event_loop.create_task(coro)
            r = yield from asyncio.wait((connect_task, task),
                                        loop=event_loop,
                                        timeout=10,
                                        return_when=asyncio.FIRST_COMPLETED)
            done, pending = r
            assert len(done) > 0, "operation timed out"
            if len(done) == 1 and connect_task in done:
                raise connect_task.exception()
            result = yield from task
            return result

        # do the login handshake
        value = yield from wait(writer.queue.get())
        assert value == {
                "CommuniqueType": "ReadRequest",
                "Header": {"Url": "/device"}}
        writer.queue.task_done()
        yield from reader.queue.put({
            "CommuniqueType": "ReadResponse", "Header": {
                "MessageBodyType": "MultipleDeviceDefinition",
                "StatusCode": "200 OK",
                "Url": "/device"},
            "Body": {
                "Devices": [{
                    "href": "/device/1",
                    "Name": "Smart Bridge",
                    "FullyQualifiedName": ["Smart Bridge"],
                    "Parent": {"href": "/project"},
                    "SerialNumber": 1234,
                    "ModelNumber": "L-BDG2-WH",
                    "DeviceType": "SmartBridge",
                    "RepeaterProperties": {"IsRepeater": True}
                }, {
                    "href": "/device/2",
                    "Name": "Lights",
                    "FullyQualifiedName": ["Hallway", "Lights"],
                    "Parent": {"href": "/project"},
                    "SerialNumber": 2345,
                    "ModelNumber": "PD-6WCL-XX",
                    "DeviceType": "WallDimmer",
                    "LocalZones": [{"href": "/zone/1"}],
                    "AssociatedArea": {"href": "/area/1"}}]}})
        value = yield from wait(writer.queue.get())
        assert value == {
                "CommuniqueType": "ReadRequest",
                "Header": {"Url": "/virtualbutton"}}
        writer.queue.task_done()
        yield from reader.queue.put({
            "CommuniqueType": "ReadResponse",
            "Header": {
                "MessageBodyType": "MultipleVirtualButtonDefinition",
                "StatusCode": "200 OK",
                "Url": "/virtualbutton"},
            "Body": {
                "VirtualButtons": [{
                    "href": "/virtualbutton/1",
                    "Name": "scene 1",
                    "ButtonNumber": 0,
                    "ProgrammingModel": {"href": "/programmingmodel/1"},
                    "Parent": {"href": "/project"},
                    "IsProgrammed": True
                }, {
                    "href": "/virtualbutton/2",
                    "Name": "Button 2",
                    "ButtonNumber": 1,
                    "ProgrammingModel": {"href": "/programmingmodel/2"},
                    "Parent": {"href": "/project"},
                    "IsProgrammed": False}]}})
        value = yield from wait(writer.queue.get())
        assert value == {
            "CommuniqueType": "ReadRequest",
            "Header": {"Url": "/zone/1/status"}}
        writer.queue.task_done()
        yield from connect_task

    event_loop.run_until_complete(initialize_bridge())

    yield Bridge(bridge, reader, writer)

    event_loop.run_until_complete(bridge.close())


@pytest.mark.asyncio
def test_notifications(event_loop, bridge):
    """Test notifications are sent to subscribers."""
    notified = False

    def callback():
        nonlocal notified
        notified = True

    bridge.target.add_subscriber('2', callback)
    yield from bridge.reader.queue.put({
        "CommuniqueType": "ReadResponse",
        "Header": {
            "MessageBodyType": "OneZoneStatus",
            "StatusCode": "200 OK",
            "Url": "/zone/1/status"},
        "Body": {
            "ZoneStatus": {
                "Level": 100,
                "Zone": {"href": "/zone/1"}}}})
    yield from asyncio.wait_for(bridge.reader.queue.join(),
                                10, loop=event_loop)
    assert notified


@pytest.mark.asyncio
def test_device_list(event_loop, bridge):
    """Test methods getting devices."""
    devices = bridge.target.get_devices()
    assert devices == {
        "1": {
            "device_id": "1",
            "name": "Smart Bridge",
            "type": "SmartBridge",
            "zone": None,
            "current_state": -1,
            "model": "L-BDG2-WH",
            "serial": 1234},
        "2": {
            "device_id": "2",
            "name": "Hallway_Lights",
            "type": "WallDimmer",
            "zone": "1",
            "model": "PD-6WCL-XX",
            "serial": 2345,
            "current_state": -1}}

    yield from bridge.reader.queue.put({
        "CommuniqueType": "ReadResponse",
        "Header": {
            "MessageBodyType": "OneZoneStatus",
            "StatusCode": "200 OK",
            "Url": "/zone/1/status"},
        "Body": {
            "ZoneStatus": {
                "Level": 100,
                "Zone": {"href": "/zone/1"}}}})
    yield from asyncio.wait_for(bridge.reader.queue.join(),
                                10, loop=event_loop)
    devices = bridge.target.get_devices()
    assert devices['2']['current_state'] == 100

    devices = bridge.target.get_devices_by_domain('light')
    assert len(devices) == 1
    assert devices[0]['device_id'] == '2'

    devices = bridge.target.get_devices_by_type('WallDimmer')
    assert len(devices) == 1
    assert devices[0]['device_id'] == '2'

    devices = bridge.target.get_devices_by_types(('SmartBridge',
                                                  'WallDimmer'))
    assert len(devices) == 2

    device = bridge.target.get_device_by_id('2')
    assert device['device_id'] == '2'


def test_scene_list(bridge):
    """Test methods getting scenes."""
    scenes = bridge.target.get_scenes()
    assert scenes == {
        "1": {
            "scene_id": "1",
            "name": "scene 1"}}
    scene = bridge.target.get_scene_by_id('1')
    assert scene == {
        "scene_id": "1",
        "name": "scene 1"}


def test_is_connected(event_loop, bridge):
    """Test the is_connected method returns connection state."""
    assert bridge.target.is_connected() is True

    other = pylutron_caseta.smartbridge.Smartbridge(None,
                                                    loop=event_loop)
    assert other.is_connected() is False


@pytest.mark.asyncio
def test_is_on(event_loop, bridge):
    """Test the is_on method returns device state."""
    yield from bridge.reader.queue.put({
        "CommuniqueType": "ReadResponse",
        "Header": {
            "MessageBodyType": "OneZoneStatus",
            "StatusCode": "200 OK",
            "Url": "/zone/1/status"},
        "Body": {
            "ZoneStatus": {
                "Level": 50,
                "Zone": {"href": "/zone/1"}}}})
    yield from asyncio.wait_for(bridge.reader.queue.join(),
                                10, loop=event_loop)
    assert bridge.target.is_on('2') is True

    yield from bridge.reader.queue.put({
        "CommuniqueType": "ReadResponse",
        "Header": {
            "MessageBodyType": "OneZoneStatus",
            "StatusCode": "200 OK",
            "Url": "/zone/1/status"},
        "Body": {
            "ZoneStatus": {
                "Level": 0,
                "Zone": {"href": "/zone/1"}}}})
    yield from asyncio.wait_for(bridge.reader.queue.join(),
                                10, loop=event_loop)
    assert bridge.target.is_on('2') is False


@pytest.mark.asyncio
def test_set_value(event_loop, bridge):
    """Test that setting values produces the right commands."""
    bridge.target.set_value('2', 50)
    command = yield from asyncio.wait_for(bridge.writer.queue.get(),
                                          10, loop=event_loop)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/1/commandprocessor"},
        "Body": {
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 50}]}}}

    bridge.target.turn_on('2')
    command = yield from asyncio.wait_for(bridge.writer.queue.get(),
                                          10, loop=event_loop)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/1/commandprocessor"},
        "Body": {
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 100}]}}}

    bridge.target.turn_off('2')
    command = yield from asyncio.wait_for(bridge.writer.queue.get(),
                                          10, loop=event_loop)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {"Url": "/zone/1/commandprocessor"},
        "Body": {
            "Command": {
                "CommandType": "GoToLevel",
                "Parameter": [{"Type": "Level", "Value": 0}]}}}


@pytest.mark.asyncio
def test_activate_scene(event_loop, bridge):
    """Test that activating scenes produces the right commands."""
    bridge.target.activate_scene('1')
    command = yield from asyncio.wait_for(bridge.writer.queue.get(),
                                          10, loop=event_loop)
    bridge.writer.queue.task_done()
    assert command == {
        "CommuniqueType": "CreateRequest",
        "Header": {
            "Url": "/virtualbutton/1/commandprocessor"},
        "Body": {"Command": {"CommandType": "PressAndRelease"}}}
