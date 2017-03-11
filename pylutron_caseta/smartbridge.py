import json

import paramiko
from io import StringIO

import time

from pylutron_caseta import lutron_ssh_key
import logging
import sys

log = logging.getLogger('smartbridge')
log.setLevel(logging.DEBUG)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
log.addHandler(ch)

class Smartbridge:

    def __init__(self, hostname=None, port=23, username='lutron', password='intergration'):
        self.devices = []
        self._load_devices_using_ssh(hostname)
        if not len(self.devices) > 0:
            raise RuntimeError("No devices were found.")
        print(self.devices)

    def get_devices(self):
        return  self.devices




    def _load_devices_using_ssh(self, hostname):
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
            self.devices.append({"id": device_id, "name": device_name, "type": device_type})

if __name__ == '__main__':
    bridge = Smartbridge(hostname='192.168.7.53')
    #bridge = Smartbridge(hostname='192.168.86.101')
    device_str = '{"Body": {"Devices": [{"DeviceType": "SmartBridge", "RepeaterProperties": {"IsRepeater": "True"}, "Parent": {"href": "/project"}, "href": "/device/1", "ModelNumber": "L-BDGPRO2-WH", "SerialNumber": 32506945, "Name": "Smart Bridge"}, {"DeviceType": "WallDimmer", "LocalZones": [{"href": "/zone/1"}], "Parent": {"href": "/project"}, "href": "/device/2", "ModelNumber": "PD-6WCL-XX", "SerialNumber": 26531187, "Name": "Living Room Can Lights"}, {"ButtonGroups": [{"href": "/buttongroup/3"}], "DeviceType": "Pico3ButtonRaiseLower", "Parent": {"href": "/project"}, "href": "/device/4", "ModelNumber": "PJ2-3BRL-GXX-X01", "SerialNumber": 29167242, "Name": "Pico Remote"}, {"DeviceType": "WallSwitch", "LocalZones": [{"href": "/zone/2"}], "Parent": {"href": "/project"}, "href": "/device/5", "ModelNumber": "PD-8ANS-XX", "SerialNumber": 26438022, "Name": "Entry Lights"}]}, "CommuniqueType": "ReadResponse", "Header": {"StatusCode": "200 OK", "Url": "/device", "MessageBodyType": "MultipleDeviceDefinition"}}'
    #bridge._load_devices(device_str)




