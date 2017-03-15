import json
import logging
import sys
import time
from io import StringIO

import paramiko
import telnetlib

from pylutron_caseta import lutron_ssh_key

log = logging.getLogger('smartbridge')


class Smartbridge:
    """
    Telnet commands found here:
    http://www.lutron.com/TechnicalDocumentLibrary/040249.pdf
    """
    def __init__(self, hostname=None, port=23, username='lutron', password='intergration'):
        self.devices = []
        self._telnet = None
        self._load_devices_using_ssh(hostname)
        if not len(self.devices) > 0:
            raise RuntimeError("No devices were found.")
        self._login()
        log.debug(self.devices)

    def get_devices(self):
        return self.devices

    def turn_on(self, device_id):
        return self.set_value(device_id, 100)

    def turn_off(self, device_id):
        return self.set_value(device_id, 0)

    def is_on(self, device_id):
        state = self.get_state(device_id)
        if float(state['value']) > 0:
            return True
        else:
            return False

    def set_value(self, device_id, value):
        cmd = "#OUTPUT,{},1,{}\r\n".format(device_id, value)
        return self._exec_telnet_command(cmd)

    def get_state(self, device_id):
        cmd = "?OUTPUT,{},1\r\n".format(device_id)
        return self._exec_telnet_command(cmd)

    def _exec_telnet_command(self, cmd):
        log.debug("exec")
        self._login()
        self._telnet.read_very_eager()
        self._telnet.write(bytes(cmd, encoding='ascii'))
        resp = self._telnet.read_until(b"\r\n")
        resp = resp.split(b"\r")[0].split(b",")
        state = {'id': resp[1].decode("utf-8"),
                 'action': resp[2].decode("utf-8"),
                 'value': resp[3].decode("utf-8").replace("GNET>", "")}
        return state

    def _login(self):
        # Only log in if needed
        if not self.logged_in or self._telnet is None:
            log.debug("logging into smart bridge")
            self._telnet = telnetlib.Telnet(self.host, self.port, timeout=2)
            self._telnet.read_until(b"login:")
            self._telnet.write(bytes(self.username + "\r\n", encoding='ascii'))
            self._telnet.read_until(b"password:")
            self._telnet.write(bytes(self.password + "\r\n", encoding='ascii'))
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
            self.devices.append({"device_id": device_id, "name": device_name, "type": device_type})





