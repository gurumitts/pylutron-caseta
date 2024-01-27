"""Types for specifying colors."""

from abc import ABC, abstractmethod
from typing import Optional


class ColorMode(ABC):
    """A color for spectrum tune or white tune lights."""

    @abstractmethod
    def get_spectrum_tuning_level_parameters(self) -> dict:
        """
        Get the relevant parameter dictionary for the spectrum tuning level.

        :return: spectrum tuning level parameter dictionary
        """

    @abstractmethod
    def get_white_tuning_level_parameters(self) -> dict:
        """
        Get the relevant parameter dictionary for the white tuning level.

        :return: white tuning level parameter dictionary
        """

    @staticmethod
    def get_color_from_leap(zone_status: dict) -> Optional["ColorMode"]:
        """
        Get the color value from the zone status.

        Returns None if no color is set.

        :param zone_status: leap zone status dictionary
        :return: color value
        """
        if zone_status is None:
            return None

        color_status = zone_status.get("ColorTuningStatus")
        if color_status is None:
            return None

        if "WhiteTuningLevel" in color_status:
            kelvin = color_status["WhiteTuningLevel"]["Kelvin"]
            return WarmCoolColorValue(kelvin)

        if "HSVTuningLevel" in color_status:
            hue = color_status["HSVTuningLevel"]["Hue"]
            saturation = color_status["HSVTuningLevel"]["Saturation"]
            return FullColorValue(hue, saturation)

        return None


class FullColorValue(ColorMode):
    """A color specified as hue+saturation."""

    def __init__(self, hue: int, saturation: int):
        """
        Create a Full Color value.

        :param hue: Hue of the bulb
        :param saturation: Saturation of the bulb
        """
        self.hue = hue
        self.saturation = saturation

    def get_spectrum_tuning_level_parameters(self) -> dict:
        return {"ColorTuningStatus": self.get_white_tuning_level_parameters()}

    def get_white_tuning_level_parameters(self) -> dict:
        return {"HSVTuningLevel": {"Hue": self.hue, "Saturation": self.saturation}}


class WarmCoolColorValue(ColorMode):
    """A color temperature."""

    def __init__(self, kelvin: int):
        """
        Create a Warm Cool color value.

        :param kelvin: kelvin value of the bulb
        """
        self.kelvin = kelvin

    def get_spectrum_tuning_level_parameters(self) -> dict:
        return {"ColorTuningStatus": self.get_white_tuning_level_parameters()}

    def get_white_tuning_level_parameters(self) -> dict:
        return {"WhiteTuningLevel": {"Kelvin": self.kelvin}}


class WarmDimmingColorValue:
    """
    A Warm Dimming value.

    :param enabled: enable warm dimming
    """

    def __init__(self, enabled: bool, additional_params: Optional[dict] = None):
        """Create a Warm Dimming value."""
        self.enabled = enabled
        self.additional_params = additional_params or {}

    @staticmethod
    def get_warm_dim_from_leap(zone_status: dict) -> Optional["bool"]:
        """
        Check whether warm dimming is active for a zone status.

        Returns None if the zone status does not contain warm dimming information.
        """
        if zone_status is None:
            return None

        color_status = zone_status.get("ColorTuningStatus")
        if color_status is None:
            return None

        curve_dimming = color_status.get("CurveDimming")
        if curve_dimming is None:
            return None

        return "Curve" in curve_dimming

    def get_leap_parameters(self) -> dict:
        """Get the leap parameters for applying warm dimming."""
        if self.enabled:
            curve_dimming = {"Curve": {"href": "/curve/1"}}
        else:
            curve_dimming = None

        return {"CurveDimming": curve_dimming}

    def get_spectrum_tuning_level_parameters(self) -> dict:
        """
        Get the relevant parameter dictionary for the spectrum tuning level.

        :return: spectrum tuning level parameter dictionary
        """
        params = {"ColorTuningStatus": self.get_leap_parameters()}
        params.update(self.additional_params)
        return {
            "CommandType": "GoToSpectrumTuningLevel",
            "SpectrumTuningLevelParameters": params,
        }

    def get_white_tuning_level_parameters(self) -> dict:
        """
        Get the relevant parameter dictionary for the white tuning level.

        :return: white tuning level parameter dictionary
        """
        params = self.get_leap_parameters()
        params.update(self.additional_params)

        return {"CommandType": "GoToWarmDim", "WarmDimParameters": params}
