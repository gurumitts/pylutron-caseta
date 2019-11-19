"""Provides an API to interact with the Lutron Caseta Smart Bridge."""

import asyncio
import logging
import socket
import ssl

from . import _LEAP_DEVICE_TYPES, FAN_OFF
from .leap import open_connection

_LOG = logging.getLogger(__name__)
_LOG.setLevel(logging.DEBUG)

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

    def __init__(self, connect, loop=None):
        """Initialize the Smart Bridge."""
        self.devices = {}
        self.scenes = {}
        self.logged_in = False
        self._connect = connect
        self._subscribers = {}
        self._loop = loop or asyncio.get_event_loop()
        self._login_lock = asyncio.Lock(loop=self._loop)
        self._reader = None
        self._writer = None
        self._monitor_task = None
        self._ping_task = None
        self._got_ping = asyncio.Event(loop=self._loop)

    @asyncio.coroutine
    def connect(self):
        """Connect to the bridge."""
        yield from self._login()
        self._monitor_task = self._loop.create_task(self._monitor())

    @classmethod
    def create_tls(cls, hostname, keyfile, certfile, ca_certs,
                   port=LEAP_PORT, loop=None):
        """Initialize the Smart Bridge using TLS over IPv4."""
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        ssl_context.load_verify_locations(ca_certs)
        ssl_context.load_cert_chain(certfile, keyfile)
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        @asyncio.coroutine
        def _connect():
            res = yield from open_connection(hostname,
                                             port,
                                             server_hostname='',
                                             ssl=ssl_context,
                                             loop=loop,
                                             family=socket.AF_INET)
            return res
        return cls(_connect, loop=loop)

    def add_subscriber(self, device_id, callback_):
        """
        Add a listener to be notified of state changes.

        :param device_id: device id, e.g. 5
        :param callback_: callback to invoke
        """
        self._subscribers[device_id] = callback_

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
            if self.devices[device_id]['type'] in _LEAP_DEVICE_TYPES[domain]:
                devs.append(self.devices[device_id])
        return devs

    def get_devices_by_type(self, type_):
        """
        Will return all devices of a given device type.

        :param type_: LEAP device type, e.g. WallSwitch
        """
        devs = []
        for device_id in self.devices:
            if self.devices[device_id]['type'] == type_:
                devs.append(self.devices[device_id])
        return devs

    def get_devices_by_types(self, types):
        """
        Will return all devices of for a list of given device types.

        :param types: list of LEAP device types such as WallSwitch, WallDimmer
        """
        devs = []
        for device_id in self.devices:
            if self.devices[device_id]['type'] in types:
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

    def get_value(self, device_id):
        """
        Will return the current level value for the device with the given ID.

        :param device_id: device id, e.g. 5
        :returns level value from 0 to 100
        :rtype int
        """
        zone_id = self._get_zone_id(device_id)
        if zone_id:
            cmd = {
                "CommuniqueType": "ReadRequest",
                "Header": {"Url": "/zone/%s/status" % zone_id}}
            return self._writer.write(cmd)

    def is_connected(self):
        """Will return True if currently connected to the Smart Bridge."""
        return self.logged_in

    def is_on(self, device_id):
        """
        Will return True is the device with the given ID is 'on'.

        :param device_id: device id, e.g. 5
        :returns True if level is greater than 0 level, False otherwise
        """
        return (self.devices[device_id]['current_state'] > 0 or
                self.devices[device_id]['fan_speed'] != FAN_OFF)

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
                        "Parameter": [{"Type": "Level", "Value": value}]}}}
            return self._writer.write(cmd)

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
                        "FanSpeedParameters": {"FanSpeed": value}}}}
            return self._writer.write(cmd)

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
                "Header": {
                    "Url": "/virtualbutton/%s/commandprocessor" % scene_id},
                "Body": {"Command": {"CommandType": "PressAndRelease"}}}
            return self._writer.write(cmd)

    def _get_zone_id(self, device_id):
        """
        Return the zone id for an given device.

        :param device_id: device id for which to retrieve a zone id
        """
        return self.devices[device_id].get('zone')

    def _send_command(self, cmd):
        """Send a command to the bridge."""
        self._writer.write(cmd)

    @asyncio.coroutine
    def _monitor(self):
        """Event monitoring loop."""
        try:
            while True:
                try:
                    yield from asyncio.wait_for(self._login(),
                                                timeout=CONNECT_TIMEOUT,
                                                loop=self._loop)
                    received = yield from self._reader.read()
                    if received is not None:
                        self._handle_response(received)
                except (ValueError, ConnectionError, asyncio.TimeoutError):
                    _LOG.warning("reconnecting", exc_info=1)
                    yield from asyncio.sleep(RECONNECT_DELAY,
                                             loop=self._loop)
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOG.critical('monitor loop has exited', exc_info=1)
            raise

    def _handle_read_response(self, resp_json):
        body_type = resp_json['Header']['MessageBodyType']
        if body_type == 'OneZoneStatus':
            body = resp_json['Body']
            status = body['ZoneStatus']
            zone = status['Zone']['href']
            zone = zone[zone.rfind('/') + 1:]
            level = status.get('Level', -1)
            fan_speed = status.get('FanSpeed')
            _LOG.debug('zone=%s level=%s', zone, level)
            for _device_id in self.devices:
                device = self.devices[_device_id]
                if zone == device.get('zone'):
                    device['current_state'] = level
                    device['fan_speed'] = fan_speed
                    if _device_id in self._subscribers:
                        self._subscribers[_device_id]()
        elif body_type == "OnePingResponse":
            self._got_ping.set()

    def _handle_response(self, resp_json):
        """
        Handle an event from the ssl interface.

        If a zone level was changed either by external means such as a Pico
        remote or by a command sent from us, the new level will appear on the
        reader and the response is handled by this function.

        :param resp_json: full JSON response from the LEAP connection
        """

        comm_type = resp_json['CommuniqueType']
        if comm_type == 'ReadResponse':
            self._handle_read_response(resp_json)

    @asyncio.coroutine
    def _login(self):
        """Connect and login to the Smart Bridge LEAP server using SSL."""
        with (yield from self._login_lock):
            if self._reader is not None and self._writer is not None:
                if (self.logged_in and
                        self._reader.exception() is None and
                        not self._reader.at_eof()):
                    return
                self._writer.abort()
                self._reader = self._writer = None

            self.logged_in = False
            _LOG.debug("Connecting to Smart Bridge via SSL")
            self._reader, self._writer = yield from self._connect()
            _LOG.debug("Successfully connected to Smart Bridge.")

            yield from self._load_devices()
            yield from self._load_scenes()
            for device in self.devices.values():
                if device.get('zone') is not None:
                    cmd = {
                        "CommuniqueType": "ReadRequest",
                        "Header": {"Url": "/zone/%s/status" % device['zone']}}
                    self._writer.write(cmd)
            self._ping_task = self._loop.create_task(self._ping())
            self.logged_in = True

    @asyncio.coroutine
    def _ping(self):
        """Periodically ping the LEAP server to keep the connection open."""
        writer = self._writer
        try:
            try:
                while True:
                    yield from asyncio.sleep(PING_INTERVAL, loop=self._loop)
                    self._got_ping.clear()
                    writer.write({
                        "CommuniqueType": "ReadRequest",
                        "Header": {"Url": "/server/1/status/ping"}})
                    yield from asyncio.wait_for(self._got_ping.wait(),
                                                PING_DELAY, loop=self._loop)
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

    @asyncio.coroutine
    def _load_devices(self):
        """Load the device list from the SSL LEAP server interface."""
        _LOG.debug("Loading devices")
        self._writer.write({
            "CommuniqueType": "ReadRequest", "Header": {"Url": "/device"}})
        while True:
            device_json = yield from self._reader.read()
            if device_json['CommuniqueType'] == 'ReadResponse':
                break
        for device in device_json['Body']['Devices']:
            _LOG.debug(device)
            device_id = device['href'][device['href'].rfind('/') + 1:]
            device_zone = None
            if 'LocalZones' in device:
                device_zone = device['LocalZones'][0]['href']
                device_zone = device_zone[device_zone.rfind('/') + 1:]
            device_name = '_'.join(device['FullyQualifiedName'])
            self.devices.setdefault(device_id, {
                'device_id': device_id,
                'current_state': -1,
                'fan_speed': None
                }).update(
                    zone=device_zone,
                    name=device_name,
                    type=device['DeviceType'],
                    model=device['ModelNumber'],
                    serial=device['SerialNumber']
                )

    @asyncio.coroutine
    def _load_scenes(self):
        """
        Load the scenes from the Smart Bridge.

        Scenes are known as virtual buttons in the SSL LEAP interface.
        """
        _LOG.debug("Loading scenes from the Smart Bridge")
        self._writer.write({
            "CommuniqueType": "ReadRequest",
            "Header": {"Url": "/virtualbutton"}})
        while True:
            scene_json = yield from self._reader.read()
            if scene_json['CommuniqueType'] == 'ReadResponse':
                break
        for scene in scene_json['Body']['VirtualButtons']:
            _LOG.debug(scene)
            if scene['IsProgrammed']:
                scene_id = scene['href'][scene['href'].rfind('/') + 1:]
                scene_name = scene['Name']
                self.scenes[scene_id] = {'scene_id': scene_id,
                                         'name': scene_name}

    @asyncio.coroutine
    def close(self):
        """Disconnect from the bridge."""
        if (self._monitor_task is not None and
                not self._monitor_task.cancelled()):
            self._monitor_task.cancel()
        if (self._ping_task is not None and
                not self._ping_task.cancelled()):
            self._ping_task.cancel()
        yield from self._writer.drain()
        self._writer.abort()
