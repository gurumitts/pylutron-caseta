"""Provides an API to interact with the Lutron Caseta Smart Bridge."""

import json
import logging
import threading
import time
from io import StringIO

import paramiko

from pylutron_caseta import _LUTRON_SSH_KEY, _LEAP_DEVICE_TYPES

_LOG = logging.getLogger('smartbridge')
_LOG.setLevel(logging.DEBUG)


class Smartbridge:
    """
    A representation of the Lutron Caseta Smart Bridge.

    It uses an SSH interface known as the LEAP server.
    """

    def __init__(self, hostname=None):
        """Initialize the Smart Bridge."""
        self.devices = {}
        self.scenes = {}
        self._hostname = hostname
        self.logged_in = False
        self._sshclient = None
        self._ssh_shell = None
        self._login_ssh()
        self._load_devices()
        self._load_scenes()
        _LOG.debug(self.devices)
        _LOG.debug(self.scenes)
        monitor = threading.Thread(target=self._monitor)
        monitor.setDaemon(True)
        monitor.start()
        for _id in self.devices:
            self.get_value(_id)
        self._subscribers = {}

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

        :param domain: one of 'light', 'switch', 'cover' or 'sensor'
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
        cmd = '{"CommuniqueType":"ReadRequest",' \
              '"Header":{"Url":"/zone/%s/status"}}\n' % zone_id
        if zone_id:
            return self._send_ssh_command(cmd)

    def is_connected(self):
        """Will return True if currently connected to the Smart Bridge."""
        return self.logged_in

    def is_on(self, device_id):
        """
        Will return True is the device with the given ID is 'on'.

        :param device_id: device id, e.g. 5
        :returns True if level is greater than 0 level, False otherwise
        """
        return self.devices[device_id]['current_state'] > 0

    def set_value(self, device_id, value):
        """
        Will set the value for a device with the given ID.

        :param device_id: device id to set the value on
        :param value: integer value from 0 to 100 to set
        """
        zone_id = self._get_zone_id(device_id)
        if zone_id:
            cmd = '{"CommuniqueType":"CreateRequest",' \
                  '"Header":{"Url":"/zone/%s/commandprocessor"},' \
                  '"Body":{"Command":{"CommandType":"GoToLevel",' \
                  '"Parameter":[{"Type":"Level",' \
                  '"Value":%s}]}}}\n' % (zone_id, value)
            return self._send_ssh_command(cmd)

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
            cmd = '{"CommuniqueType":"CreateRequest",' \
                  '"Header":{"Url":"/virtualbutton/%s/commandprocessor"},' \
                  '"Body":{"Command":{"CommandType":"PressAndRelease"}}}' \
                  '\n' % scene_id
            return self._send_ssh_command(cmd)

    def _get_zone_id(self, device_id):
        """
        Return the zone id for an given device.

        :param device_id: device id for which to retrieve a zone id
        """
        device = self.devices[device_id]
        if 'zone' in device:
            return device['zone']
        return None

    def _send_ssh_command(self, cmd):
        """Send an SSH command to the SSH shell."""
        self._ssh_shell.send(cmd)

    def _monitor(self):
        """Event monitoring loop for the SSH shell."""
        while True:
            try:
                self._login_ssh()
                response = self._ssh_shell.recv(9999)
                _LOG.debug(response)
                resp_parts = response.split(b'\r\n')
                try:
                    for resp in resp_parts:
                        if resp:
                            resp_json = json.loads(resp.decode("UTF-8"))
                            self._handle_response(resp_json)
                except ValueError:
                    _LOG.error("Invalid response "
                               "from SmartBridge: " + response.decode("UTF-8"))
            except ConnectionError:
                self.logged_in = False

    def _handle_response(self, resp_json):
        """
        Handle an event from the SSH interface.

        If a zone level was changed either by external means such as a Pico
        remote or by a command sent from us, the new level will appear on the
        SSH shell and the response is handled by this function.

        :param resp_json: full JSON response from the SSH shell
        """
        comm_type = resp_json['CommuniqueType']
        if comm_type == 'ReadResponse':
            body = resp_json['Body']
            zone = body['ZoneStatus']['Zone']['href']
            zone = zone[zone.rfind('/') + 1:]
            level = body['ZoneStatus']['Level']
            _LOG.debug('zone=%s level=%s', zone, level)
            for _device_id in self.devices:
                device = self.devices[_device_id]
                if 'zone' in device:
                    if zone == device['zone']:
                        device['current_state'] = level
                        if _device_id in self._subscribers:
                            self._subscribers[_device_id]()

    def _login_ssh(self):
        """
        Connect and login to the Smart Bridge LEAP server using SSH.

        This interaction over SSH is not really documented anywhere.
        I was looking for a way to get a list of devices connected to
        the Smart Bridge. I found several references indicating
        this was possible over SSH.
        The most complete reference is located here:
        https://github.com/njschwartz/Lutron-Smart-Pi/blob/master/RaspberryPi/LutronPi.py
        """
        if self.logged_in:
            return

        _LOG.debug("Connecting to Smart Bridge via SSH")
        ssh_user = 'leap'
        ssh_port = 22
        ssh_key = paramiko.RSAKey.from_private_key(StringIO(_LUTRON_SSH_KEY))

        self._sshclient = paramiko.SSHClient()
        self._sshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        self._sshclient.connect(hostname=self._hostname, port=ssh_port,
                                username=ssh_user, pkey=ssh_key)

        self._ssh_shell = self._sshclient.invoke_shell()
        _LOG.debug("Successfully connected to Smart Bridge "
                   "using SSH. Ready...")
        self.logged_in = True

    def _load_devices(self):
        """Load the device list from the SSH LEAP server interface."""
        _LOG.debug("Loading devices")
        self._ssh_shell.send(
            '{"CommuniqueType":"ReadRequest","Header":{"Url":"/device"}}\n')
        time.sleep(1)
        shell_output = self._ssh_shell.recv(9999)
        output_parts = shell_output.split(b"\r\n")
        _LOG.debug(output_parts)
        device_json = json.loads(output_parts[1].decode("UTF-8"))
        for device in device_json['Body']['Devices']:
            _LOG.debug(device)
            device_id = device['href'][device['href'].rfind('/') + 1:]
            device_zone = None
            if 'LocalZones' in device:
                device_zone = device['LocalZones'][0]['href']
                device_zone = device_zone[device_zone.rfind('/') + 1:]
            device_name = device['Name']
            device_type = device['DeviceType']
            self.devices[device_id] = {'device_id': device_id,
                                       'name': device_name,
                                       'type': device_type,
                                       'zone': device_zone,
                                       'current_state': -1}

    def _load_scenes(self):
        """
        Load the scenes from the Smart Bridge.

        Scenes are known as virtual buttons in the SSH LEAP interface.
        """
        _LOG.debug("Loading scenes from the Smart Bridge")
        self._ssh_shell.send(
            '{"CommuniqueType":"ReadRequest","Header":'
            '{"Url":"/virtualbutton"}}\n')
        time.sleep(1)
        shell_output = self._ssh_shell.recv(35000)
        output_parts = shell_output.split(b"\r\n")
        _LOG.debug(output_parts)
        scene_json = json.loads(output_parts[1].decode("UTF-8"))
        for scene in scene_json['Body']['VirtualButtons']:
            _LOG.debug(scene)
            if scene['IsProgrammed']:
                scene_id = scene['href'][scene['href'].rfind('/') + 1:]
                scene_name = scene['Name']
                self.scenes[scene_id] = {'scene_id': scene_id,
                                         'name': scene_name}
