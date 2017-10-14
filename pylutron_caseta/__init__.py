"""An API to communicate with the Lutron Caseta Smart Bridge."""

_LEAP_DEVICE_TYPES = {'light': ['WallDimmer', 'PlugInDimmer'],
                      'switch': ['WallSwitch'],
                      'cover': ['SerenaHoneycombShade', 'SerenaRollerShade',
                                'TriathlonHoneycombShade',
                                'TriathlonRollerShade', 'QsWirelessShade'],
                      'sensor': ['Pico1Button', 'Pico2Button',
                                 'Pico2ButtonRaiseLower', 'Pico3Button',
                                 'Pico3ButtonRaiseLower', 'Pico4Button',
                                 'Pico4ButtonScene', 'Pico4ButtonZone',
                                 'Pico4Button2Group', 'FourGroupRemote']}
