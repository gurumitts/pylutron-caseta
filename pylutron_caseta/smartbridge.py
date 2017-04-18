"""Provides an API to interact with the Lutron Caseta Smartbridge."""

import json
import logging
import threading
import time
from io import StringIO

import paramiko

from pylutron_caseta import _LUTRON_SSH_KEY

_LOG = logging.getLogger('smartbridge')
_LOG.setLevel(logging.DEBUG)


class Smartbridge:
    """
    This class acts as a representation of the lutron caseta smartbridge.

    It uses telnet as documented here:
    http://www.lutron.com/TechnicalDocumentLibrary/040249.pdf
    """

    def __init__(self, hostname=None):
        """Setup the Smartbridge."""
        self.devices = {}
        self._hostname = hostname
        self.logged_in = False
        self._sshclient = None
        self._ssh_shell = None
        self._login_ssh()
        self._load_devices()
        _LOG.debug(self.devices)
        monitor = threading.Thread(target=self._monitor)
        monitor.setDaemon(True)
        monitor.start()
        for _id in self.devices:
            self.get_value(_id)
        self._subscribers = {}

    def add_subscriber(self, device_id, _callback):
        """Add a listener to be notified of state changes."""
        self._subscribers[device_id] = _callback

    def get_devices(self):
        """Will return all known devices connected to the Smartbridge."""
        return self.devices

    def get_devices_by_type(self, _type):
        """Will return all devices of a given type."""
        devs = []
        for device_id in self.devices:
            if self.devices[device_id]['type'] == _type:
                devs.append(self.devices[device_id])
        return devs

    def get_devices_by_types(self, _types):
        """Will return all devices of for a list of given types."""
        devs = []
        for device_id in self.devices:
            if self.devices[device_id]['type'] in _types:
                devs.append(self.devices[device_id])
        return devs

    def get_device_by_id(self, device_id):
        """Will return a device with the given ID."""
        return self.devices[device_id]

    def get_value(self, device_id):
        """Will return the current value for the device with the given ID."""
        zone_id = self._get_zone_id(device_id)
        cmd = '{"CommuniqueType":"ReadRequest",' \
              '"Header":{"Url":"/zone/%s/status"}}\n' % zone_id
        if zone_id:
            return self._send_ssh_command(cmd)

    def is_connected(self):
        """Will return True if currently connected ot the Smartbridge."""
        return self.logged_in

    def is_on(self, device_id):
        """Will return True is the device with the given ID is 'on'."""
        return self.devices[device_id]['current_state'] > 0

    def set_value(self, device_id, value):
        """Will set the value for a device with the given ID."""
        zone_id = self._get_zone_id(device_id)
        if zone_id:
            cmd = '{"CommuniqueType":"CreateRequest",' \
                  '"Header":{"Url":"/zone/%s/commandprocessor"},' \
                  '"Body":{"Command":{"CommandType":"GoToLevel",' \
                  '"Parameter":[{"Type":"Level",' \
                  '"Value":%s}]}}}\n' % (zone_id, value)
            return self._send_ssh_command(cmd)

    def turn_on(self, device_id):
        """Will turn 'on' the device with the given ID."""
        return self.set_value(device_id, 100)

    def turn_off(self, device_id):
        """Will turn 'off' the device with the given ID."""
        return self.set_value(device_id, 0)

    def _get_zone_id(self, device_id):
        device = self.devices[device_id]
        if 'zone' in device:
            return device['zone']
        return None

    def _send_ssh_command(self, cmd):
        self._ssh_shell.send(cmd)

    def _monitor(self):
        while True:
            try:
                self._login_ssh()
                response = self._ssh_shell.recv(9999)
                _LOG.debug(response)
                resp_parts = response.split(b'\r\n')
                try:
                    for resp in resp_parts:
                        if len(resp) > 0:
                            resp_json = json.loads(resp.decode("UTF-8"))
                            self._handle_respose(resp_json)
                except ValueError:
                    _LOG.error('Invalid response '
                               'from SmartBridge: ' + response.decode("UTF-8"))
            except ConnectionError:
                self.logged_in = False

    def _handle_respose(self, resp_json):
        comm_type = resp_json['CommuniqueType']
        if comm_type == 'ReadResponse':
            body = resp_json['Body']
            zone = body['ZoneStatus']['Zone']['href']
            zone = zone[zone.rfind('/')+1:]
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
        Communicate to the smartbridge sing SSH.

        This interaction over ssh is not really documented anywhere.
        I was looking for a way to get a list of devices connected to
        the Smartbridge.  I found several references indicating
        this was possible over ssh.
        The most complete reference is located here:
        https://github.com/njschwartz/Lutron-Smart-Pi/blob/master/RaspberryPi/LutronPi.py
        """
        if self.logged_in:
            return

        _LOG.debug('Connecting to smartbridge via ssh')
        ssh_user = 'leap'
        ssh_port = 22
        ssh_key = paramiko.RSAKey.from_private_key(StringIO(_LUTRON_SSH_KEY))

        self._sshclient = paramiko.SSHClient()
        self._sshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        self._sshclient.connect(hostname=self._hostname, port=ssh_port,
                                username=ssh_user, pkey=ssh_key)

        self._ssh_shell = self._sshclient.invoke_shell()
        _LOG.debug('Connected to smartbridge ssh...ready...')
        self.logged_in = True

    def _load_devices(self):
        _LOG.debug('Loading devices')
        self._ssh_shell.send(
            '{"CommuniqueType":"ReadRequest","Header":{"Url":"/device"}}\n')
        time.sleep(1)
        shell_output = self._ssh_shell.recv(9999)
        output_parts = shell_output.split(b"\r\n")
        _LOG.debug(output_parts)
        device_json = json.loads(output_parts[1].decode("UTF-8"))
        for device in device_json['Body']['Devices']:
            _LOG.debug(device)
            device_id = device['href'][device['href'].rfind('/')+1:]
            device_zone = None
            if 'LocalZones' in device:
                device_zone = device['LocalZones'][0]['href']
                device_zone = device_zone[device_zone.rfind('/')+1:]
            device_name = device['Name']
            device_type = device['DeviceType']
            self.devices[device_id] = {'device_id': device_id,
                                       'name': device_name,
                                       'type': device_type,
                                       'zone': device_zone,
                                       'current_state': -1}
