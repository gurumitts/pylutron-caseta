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
        "DivaSmartDimmer",
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
        "DivaSmartSwitch",
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
    "sensor": [
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
        "SunnataKeypad_2Button",
        "SunnataKeypad_3ButtonRaiseLower",
        "SunnataKeypad_4Button",
        "SeeTouchHybridKeypad",
        "SeeTouchInternational",
        "SeeTouchKeypad",
        "HomeownerKeypad",
        "GrafikTHybridKeypad",
        "AlisseKeypad",
        "PalladiomKeypad",
    ],
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
