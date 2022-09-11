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
    "sensor": [  # Legacy button device support
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
    "keypad": [  # New control station support
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
BUTTON_TYPE_LOWER = "Lower"
BUTTON_TYPE_RAISE = "Raise"
BUTTON_TYPE_TOP_LOWER = "Lower (Top)"
BUTTON_TYPE_TOP_RAISE = "Raise (Top)"
BUTTON_TYPE_BOTTOM_LOWER = "Lower (Bottom)"
BUTTON_TYPE_BOTTOM_RAISE = "Raise (Bottom)"
BUTTON_TYPE_LEFT_LOWER = "Lower (Left)"
BUTTON_TYPE_LEFT_RAISE = "Raise (Left)"
BUTTON_TYPE_CENTER_LOWER = "Lower (Center)"
BUTTON_TYPE_CENTER_RAISE = "Raise (Center)"
BUTTON_TYPE_RIGHT_LOWER = "Lower (Right)"
BUTTON_TYPE_RIGHT_RAISE = "Raise (Right)"

# Identifies special buttons on keypads that aren't user-programmable
# such as raise and lower buttons
_KEYPAD_SPECIAL_BUTTON_MAP = {
    "Custom Keypad": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQR-T5CRL-XX": {
        20: BUTTON_TYPE_LOWER,
        21: BUTTON_TYPE_RAISE,
    },
    "HQR-T5RL": {
        24: BUTTON_TYPE_LOWER,
        25: BUTTON_TYPE_RAISE,
    },
    "HQR-T10CRL-XX": {
        20: BUTTON_TYPE_RIGHT_LOWER,
        21: BUTTON_TYPE_RIGHT_RAISE,
        22: BUTTON_TYPE_LEFT_LOWER,
        23: BUTTON_TYPE_LEFT_RAISE,
    },
    "HQR-T10RL": {
        24: BUTTON_TYPE_LOWER,
        25: BUTTON_TYPE_RAISE,
    },
    "HQR-T15CRL-XX": {
        20: BUTTON_TYPE_RIGHT_LOWER,
        21: BUTTON_TYPE_RIGHT_RAISE,
        22: BUTTON_TYPE_CENTER_LOWER,
        23: BUTTON_TYPE_CENTER_RAISE,
        24: BUTTON_TYPE_LEFT_LOWER,
        25: BUTTON_TYPE_LEFT_RAISE,
    },
    "HQRD-H1RLD": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-H2RLD": {
        16: BUTTON_TYPE_TOP_LOWER,
        17: BUTTON_TYPE_TOP_RAISE,
        18: BUTTON_TYPE_BOTTOM_LOWER,
        19: BUTTON_TYPE_BOTTOM_RAISE,
    },
    "HQRD-H3S": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-H3BSRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-H4S": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-H5BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-H6BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-HN1RLD": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-HN2RLD": {
        16: BUTTON_TYPE_TOP_LOWER,
        17: BUTTON_TYPE_TOP_RAISE,
        18: BUTTON_TYPE_BOTTOM_LOWER,
        19: BUTTON_TYPE_BOTTOM_RAISE,
    },
    "HQRD-HN3BSRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-HN3S": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-HN4S": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-HN5BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-HN6BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-W1RLD": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-W2RLD": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-W3BSRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-W5BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQRD-W6BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQWD-W1RLD": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQWD-W2RLD": {
        16: BUTTON_TYPE_TOP_LOWER,
        17: BUTTON_TYPE_TOP_RAISE,
        18: BUTTON_TYPE_BOTTOM_LOWER,
        19: BUTTON_TYPE_BOTTOM_RAISE,
    },
    "HQWD-W3BSRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQWD-W3S": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQWD-W4S": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQWD-W5BIR": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQWD-W5BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQWD-W6BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HQWT-U-PRW": {
        16: BUTTON_TYPE_LOWER,
        17: BUTTON_TYPE_RAISE,
    },
    "HWIS-5BIR-I": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HWIS-5BRL-I": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HWIS-6BRL-I": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HWIS-7BRL-I": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HWIS-8BIR-I": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HWIS-8BRL-I": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "HWIS-10BRL-I": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "LFS-W1RLD": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "LFS-W2RLD": {
        16: BUTTON_TYPE_TOP_LOWER,
        17: BUTTON_TYPE_TOP_RAISE,
        18: BUTTON_TYPE_BOTTOM_LOWER,
        19: BUTTON_TYPE_BOTTOM_RAISE,
    },
    "LFS-W3S": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "LFS-W3BSRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "LFS-W5BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "LFS-W6BRL": {
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "RRST-W3RL-XX": {  # RA3 Sunnata 3-button w/ raise/lower
        18: BUTTON_TYPE_LOWER,
        19: BUTTON_TYPE_RAISE,
    },
    "3RL": {  # HomeWorks Sunnata 3-button w/ raise/lower
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
