"""An API to communicate with the Lutron Caseta Smart Bridge."""

_LEAP_DEVICE_TYPES = {'light': ['WallDimmer', 'PlugInDimmer'],
                      'switch': ['WallSwitch'],
                      'fan': ['CasetaFanSpeedController'],
                      'cover': ['SerenaHoneycombShade', 'SerenaRollerShade',
                                'TriathlonHoneycombShade',
                                'TriathlonRollerShade', 'QsWirelessShade'],
                      'sensor': ['Pico1Button', 'Pico2Button',
                                 'Pico2ButtonRaiseLower', 'Pico3Button',
                                 'Pico3ButtonRaiseLower', 'Pico4Button',
                                 'Pico4ButtonScene', 'Pico4ButtonZone',
                                 'Pico4Button2Group', 'FourGroupRemote']}

FAN_OFF = 'Off'
FAN_LOW = 'Low'
FAN_MEDIUM = 'Medium'
FAN_MEDIUM_HIGH = 'MediumHigh'
FAN_HIGH = 'High'

OCCUPANCY_GROUP_OCCUPIED = "Occupied"
OCCUPANCY_GROUP_UNOCCUPIED = "Unoccupied"
OCCUPANCY_GROUP_UNKNOWN = "Unknown"
