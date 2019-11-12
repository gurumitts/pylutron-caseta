"""Tests to validate ssl interactions."""
import asyncio
import logging
import pytest

import pylutron_caseta.smartbridge as smartbridge

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(logging.StreamHandler())


def JoinableQueue(loop):
    """Create a JoinableQueue, even in new Python where it is called Queue."""
    try:
        return asyncio.JoinableQueue(loop=loop)
    except AttributeError:
        return asyncio.Queue(loop=loop)


class Bridge:
    """A test harness around SmartBridge."""

    def __init__(self, event_loop):
        """Create a new Bridge in a disconnected state."""
        self.event_loop = event_loop
        self.connections = JoinableQueue(loop=event_loop)
        self.reader = self.writer = None

        @asyncio.coroutine
        def fake_connect():
            """Used by SmartBridge to connect to the test."""
            closed = asyncio.Event(loop=event_loop)
            reader = _FakeLeapReader(closed, event_loop)
            writer = _FakeLeapWriter(closed, event_loop)
            yield from self.connections.put((reader, writer))
            return (reader, writer)

        self.target = smartbridge.Smartbridge(fake_connect,
                                              loop=event_loop)

    @asyncio.coroutine
    def initialize(self):
        """Perform the initial connection with SmartBridge."""
        connect_task = self.event_loop.create_task(self.target.connect())
        reader, writer = yield from self.connections.get()

        @asyncio.coroutine
        def wait(coro):
            # abort if SmartBridge reports it has finished connecting early
            task = self.event_loop.create_task(coro)
            r = yield from asyncio.wait((connect_task, task),
                                        loop=self.event_loop,
                                        timeout=10,
                                        return_when=asyncio.FIRST_COMPLETED)
            done, pending = r
            assert len(done) > 0, "operation timed out"
            if len(done) == 1 and connect_task in done:
                print("SmartBridge returned before end of connection routine")
                raise connect_task.exception()
            result = yield from task
            return result

        yield from self._accept_connection(reader, writer, wait)
        yield from connect_task

        self.reader = reader
        self.writer = writer
        self.connections.task_done()

    @asyncio.coroutine
    def _accept_connection(self, reader, writer, wait):
        """Accept a connection from SmartBridge (implementation)."""
        value = yield from wait(writer.queue.get())
        assert value == {
                "CommuniqueType": "ReadRequest",
                "Header": {"Url": "/device"}}
        writer.queue.task_done()
        yield from reader.write({
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
        yield from reader.write({
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

    @asyncio.coroutine
    def disconnect(self, exception=None):
        """Disconnect SmartBridge."""
        yield from self.reader.end(exception)

    @asyncio.coroutine
    def accept_connection(self):
        """Wait for SmartBridge to reconnect."""
        reader, writer = yield from self.connections.get()

        @asyncio.coroutine
        def wait(coro):
            # nothing special
            result = yield from coro
            return result

        yield from self._accept_connection(reader, writer, wait)

        self.reader = reader
        self.writer = writer
        self.connections.task_done()


class _FakeLeapWriter:
    """A "Writer" which just puts messages onto a queue."""

    def __init__(self, closed, loop):
        self.queue = JoinableQueue(loop=loop)
        self.closed = closed
        self._loop = loop

    def write(self, obj):
        print("SmartBridge sent", obj)
        self.queue.put_nowait(obj)

    @asyncio.coroutine
    def drain(self):
        task = self._loop.create_task(self.queue.join())
        yield from asyncio.wait((self.closed.wait(), task),
                                loop=self._loop,
                                return_when=asyncio.FIRST_COMPLETED)

    def abort(self):
        self.closed.set()


class _FakeLeapReader:
    """A "Reader" which just pulls messages from a queue."""

    def __init__(self, closed, loop):
        self._loop = loop
        self.closed = closed
        self.queue = JoinableQueue(loop=loop)
        self.exception_value = None
        self.eof = False

    def exception(self):
        return self.exception_value

    @asyncio.coroutine
    def read(self):
        task = self._loop.create_task(self.queue.get())
        r = yield from asyncio.wait((self.closed.wait(), task),
                                    loop=self._loop,
                                    return_when=asyncio.FIRST_COMPLETED)
        done, pending = r
        if task not in done:
            return None

        action = yield from task
        self._loop.call_soon(self.queue.task_done)
        try:
            value = action()
        except Exception as exception:
            print("SmartBridge received exception", exception)
            self.exception_value = exception
            self.eof = True
            raise
        else:
            if value is None:
                self.eof = True
            print("SmartBridge received", value)
            return value

    @asyncio.coroutine
    def write(self, item):
        def action():
            return item
        yield from self.queue.put(action)

    def at_eof(self):
        return self.closed.is_set() or self.eof

    @asyncio.coroutine
    def end(self, exception=None):
        if exception is None:
            yield from self.write(None)
        else:
            def action():
                raise exception
            yield from self.queue.put(action)


@pytest.yield_fixture
def bridge(event_loop):
    """Create a bridge attached to a fake reader and writer."""
    harness = Bridge(event_loop)

    event_loop.run_until_complete(harness.initialize())

    yield harness

    event_loop.run_until_complete(harness.target.close())


@pytest.mark.asyncio
def test_notifications(event_loop, bridge):
    """Test notifications are sent to subscribers."""
    notified = False

    def callback():
        nonlocal notified
        notified = True

    bridge.target.add_subscriber('2', callback)
    yield from bridge.reader.write({
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

    yield from bridge.reader.write({
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

    other = smartbridge.Smartbridge(None,
                                    loop=event_loop)
    assert other.is_connected() is False


@pytest.mark.asyncio
def test_is_on(event_loop, bridge):
    """Test the is_on method returns device state."""
    yield from bridge.reader.write({
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

    yield from bridge.reader.write({
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


@pytest.mark.asyncio
def test_reconnect_eof(event_loop, bridge):
    """Test that SmartBridge can reconnect on disconnect."""
    yield from bridge.disconnect()
    yield from bridge.accept_connection()
    bridge.target.set_value('2', 50)
    command = yield from asyncio.wait_for(bridge.writer.queue.get(),
                                          10, loop=event_loop)
    bridge.writer.queue.task_done()
    assert command is not None


@pytest.mark.asyncio
def test_reconnect_error(event_loop, bridge):
    """Test that SmartBridge can reconnect on error."""
    yield from bridge.disconnect()
    yield from bridge.accept_connection()
    bridge.target.set_value('2', 50)
    command = yield from asyncio.wait_for(bridge.writer.queue.get(),
                                          10, loop=event_loop)
    bridge.writer.queue.task_done()
    assert command is not None


@pytest.mark.asyncio
def test_reconnect_timeout(event_loop):
    """Test that SmartBridge can reconnect if the remote does not respond."""
    bridge = Bridge(event_loop)

    time = 0.0

    def time_func():
        return time
    event_loop.time = time_func

    yield from bridge.initialize()

    time = smartbridge.PING_INTERVAL
    ping = yield from bridge.writer.queue.get()
    assert ping == {
        "CommuniqueType": "ReadRequest",
        "Header": {"Url": "/server/1/status/ping"}}
    print('got ping')
    yield

    time += smartbridge.PING_DELAY
    yield from bridge.accept_connection()

    bridge.target.set_value('2', 50)
    command = yield from bridge.writer.queue.get()
    bridge.writer.queue.task_done()
    assert command is not None

    yield from bridge.target.close()
