import json
import logging
import time
from io import StringIO
import threading

import paramiko
import telnetlib

from pylutron_caseta import lutron_ssh_key

log = logging.getLogger('smartbridge')
log.setLevel(logging.DEBUG)


class Smartbridge:
    """
    Telnet commands found here:
    http://www.lutron.com/TechnicalDocumentLibrary/040249.pdf
    """
    def __init__(self, hostname=None, username='lutron', password='integration'):
        self.devices = {}
        self._telnet = None
        self._hostname = hostname
        self._username = username
        self._password = password
        self.logged_in = False
        self._load_devices_using_ssh(hostname)
        if not len(self.devices) > 0:
            raise RuntimeError("No devices were found.")
        self._login()
        log.debug(self.devices)
        log.debug("about to start monitor")
        monitor = threading.Thread(target=self._monitor)
        monitor.setDaemon(True)
        log.debug("before start")
        monitor.start()
        log.debug("after start")
        self._subscribers = {}

    def add_subscriber(self, device_id, _callback):
        self._subscribers[device_id] = _callback

    def get_devices(self):
        return self.devices

    def get_device_by_id(self, device_id):
        return self.devices[device_id]

    def is_on(self, device_id):
        return self.devices[device_id]['current_state'] > 0

    def set_value(self, device_id, value):
        cmd = "#OUTPUT,{},1,{}\r\n".format(device_id, value)
        return self._exec_telnet_command(cmd)

    def turn_on(self, device_id):
        return self.set_value(device_id, 100)

    def turn_off(self, device_id):
        return self.set_value(device_id, 0)

    def _exec_telnet_command(self, cmd):
        log.debug("exec: " + cmd)
        self._login()
        self._telnet.write(bytes(cmd, encoding='ascii'))

    def _monitor(self):
        while True:
            try:
                self._login()
                _resp = self._telnet.read_until(b"\r\n")
                log.debug(_resp)
                if b'OUTPUT' in _resp:
                    _resp = _resp[_resp.rfind(b"OUTPUT,"):]
                    _resp = _resp.split(b"\r")[0].split(b",")
                    _id = _resp[1].decode("utf-8")
                    # _action = resp[2].decode("utf-8")
                    _value = float(_resp[3].decode("utf-8").replace("GNET>", ""))
                    if _value != self.devices[_id]['current_state']:
                        self.devices[_id]['current_state'] = _value
                        if _id in self._subscribers:
                            self._subscribers[_id]()
                        log.debug(self.devices[_id])
            except ConnectionError:
                self._telnet = None
                self.logged_in = False

    def _login(self):
        # Only log in if needed
        if not self.logged_in or self._telnet is None:
            log.debug("logging into smart bridge")
            self._telnet = telnetlib.Telnet(self._hostname, 23, timeout=2)
            self._telnet.read_until(b"login:")
            self._telnet.write(bytes(self._username + "\r\n", encoding='ascii'))
            self._telnet.read_until(b"password:")
            self._telnet.write(bytes(self._password + "\r\n", encoding='ascii'))
            log.debug("login complete")
            self.logged_in = True

    def _load_devices_using_ssh(self, hostname):
        """
        This interaction over ssh is not really documented anywhere.  I was looking for a
          way to get a list of devices connected to the Smartbridge.  I found several references
           indicating this was possible over ssh.  The most complete reference is located here:
        https://github.com/njschwartz/Lutron-Smart-Pi/blob/master/RaspberryPi/LutronPi.py
        """
        log.debug('Connecting to smartbridge via ssh')
        ssh_user = 'leap'
        ssh_port = 22
        ssh_key = paramiko.RSAKey.from_private_key(StringIO(lutron_ssh_key))

        sshclient = paramiko.SSHClient()
        sshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        sshclient.connect(hostname=hostname, port=ssh_port, username=ssh_user, pkey=ssh_key)
        log.debug('Connected to smartbridge ssh')

        shell = sshclient.invoke_shell()
        shell.send('{"CommuniqueType":"ReadRequest","Header":{"Url":"/device"}}\n')
        time.sleep(5)
        shell_output = shell.recv(9999)
        output_parts = shell_output.split(b"\r\n")
        log.debug(output_parts)
        device_json = json.loads(output_parts[1].decode("UTF-8"))
        for device in device_json['Body']['Devices']:
            log.debug(device)
            device_id = device['href'][device['href'].rfind('/')+1:]
            device_name = device['Name']
            device_type = device['DeviceType']
            self.devices[device_id] = {"device_id": device_id, "name": device_name,
                                       "type": device_type, "current_state": -1}
