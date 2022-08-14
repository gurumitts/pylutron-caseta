#!/bin/bash

areas="3 32 804 1008 1020 1032 1578"

for area in $areas; do
	mkdir -p $area
	leap -v 192.168.5.81/area/$area/associatedcontrolstation | jq > $area/controlstation.json
	leap -v 192.168.5.81/area/$area/associatedzone | jq > $area/associatedzone.json
done
