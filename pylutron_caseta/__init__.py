"""An API to communicate with the Lutron Caseta Smart Bridge."""

from typing import Optional

from .messages import Response, ResponseStatus

_LEAP_DEVICE_TYPES = {
    "light": [
        "WallDimmer",
        "PlugInDimmer",
        "InLineDimmer",
        "SunnataDimmer",
        "TempInWallPaddleDimmer",
        "WallDimmerWithPreset",
        "Dimmed",
        "SpectrumTune",  # Ketra lamps
    ],
    "switch": [
        "WallSwitch",
        "OutdoorPlugInSwitch",
        "PlugInSwitch",
        "InLineSwitch",
        "PowPakSwitch",
        "SunnataSwitch",
        "TempInWallPaddleSwitch",
        "Switched",
        "KeypadLED",
    ],
    "fan": [
        "CasetaFanSpeedController",
        "MaestroFanSpeedController",
        "FanSpeed",
    ],
    "cover": [
        "SerenaHoneycombShade",
        "SerenaRollerShade",
        "TriathlonHoneycombShade",
        "TriathlonRollerShade",
        "QsWirelessShade",
        "QsWirelessHorizontalSheerBlind",
        "QsWirelessWoodBlind",
        "RightDrawDrape",
        "Shade",
        "SerenaTiltOnlyWoodBlind",
    ],
    "sensor": [ # Legacy button device support
        "Pico1Button",
        "Pico2Button",
        "Pico2ButtonRaiseLower",
        "Pico3Button",
        "Pico3ButtonRaiseLower",
        "Pico4Button",
        "Pico4ButtonScene",
        "Pico4ButtonZone",
        "Pico4Button2Group",
        "FourGroupRemote",
    ],
    "keypad": [ # New control station support
        "SeeTouchTabletopKeypad",
        "SunnataKeypad",
        "SeeTouchHybridKeypad",
        "SeeTouchInternational",
        "SeeTouchKeypad",
        "HomeownerKeypad",
        "GrafikTHybridKeypad",
        "AlisseKeypad",
        "PalladiomKeypad",
    ],
}

KEYPAD_LED_STATE_UNKNOWN = -1
KEYPAD_LED_STATE_ON = 100
KEYPAD_LED_STATE_OFF = 0

# Special button types that can't be labeled by the user
BUTTON_TYPE_RAISE = "Raise"
BUTTON_TYPE_LOWER = "Lower"

# Identifies special buttons on keypads that aren't user-programmable
# such as raise and lower buttons
_KEYPAD_SPECIAL_BUTTON_MAP = {
    "HQWT-U-PRW": {
        16: BUTTON_TYPE_RAISE,
        17: BUTTON_TYPE_LOWER,
    },
    "RRST-W3RL-XX": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
}

FAN_OFF = "Off"
FAN_LOW = "Low"
FAN_MEDIUM = "Medium"
FAN_MEDIUM_HIGH = "MediumHigh"
FAN_HIGH = "High"

OCCUPANCY_GROUP_OCCUPIED = "Occupied"
OCCUPANCY_GROUP_UNOCCUPIED = "Unoccupied"
OCCUPANCY_GROUP_UNKNOWN = "Unknown"

RA3_OCCUPANCY_SENSOR_DEVICE_TYPES = [
    "RPSOccupancySensor",
    "RPSCeilingMountedOccupancySensor",
]

BUTTON_STATUS_PRESSED = "Press"
BUTTON_STATUS_RELEASED = "Release"


class BridgeDisconnectedError(Exception):
    """Raised when the connection is lost while waiting for a response."""


class BridgeResponseError(Exception):
    """Raised when the bridge sends an error response."""

    def __init__(self, response: Response):
        """Create a BridgeResponseError."""
        super().__init__(str(response.Header.StatusCode))
        self.response = response

    @property
    def code(self) -> Optional[ResponseStatus]:
        """Get the status code returned by the server."""
        return self.response.Header.StatusCode
