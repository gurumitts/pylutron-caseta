#!/bin/bash

devices="1409 851 1512 1626 1660 1592"

for device in $devices; do
	mkdir -p $device
	leap -v 192.168.5.81/device/$device/buttongroup/expanded | jq > $device/buttongroup.json
	leap -v 192.168.5.81/device/$device | jq > $device/device.json
done
