from abc import ABC, abstractmethod
from typing import Optional


class ColorMode(ABC):
    """
    A protocol for getting leap commands to send color to supported spectrum tune and white tune lights .
   """

    @abstractmethod
    def get_spectrum_tuning_level_parameters(self) -> dict:
        """
        Gets the relevant parameter dictionary for the spectrum tuning level of the child class.

        :return: spectrum tuning level parameter dictionary
        """
        pass

    @abstractmethod
    def get_white_tuning_level_parameters(self) -> dict:
        """
        Gets the relevant parameter dictionary for the white tuning level of the child class.

        :return: white tuning level parameter dictionary
        """
        pass

    @staticmethod
    def get_color_from_leap(zone_status: dict) -> Optional["ColorMode"]:
        """
        Gets the color value from the zone status. Returns None if no color is set.

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
        elif "HSVTuningLevel" in color_status:
            hue = color_status["HSVTuningLevel"]["Hue"]
            saturation = color_status["HSVTuningLevel"]["Saturation"]
            return FullColorValue(hue, saturation)

        return None


class FullColorValue(ColorMode):
    def __init__(self, hue: int, saturation: int):
        """
        Full Color value

        :param hue: Hue of the bulb
        :param saturation: Saturation of the bulb
        """
        self.hue = hue
        self.saturation = saturation

    def get_spectrum_tuning_level_parameters(self) -> dict:
        return {
            "ColorTuningStatus": self.get_white_tuning_level_parameters()
        }

    def get_white_tuning_level_parameters(self) -> dict:
        return {
            "HSVTuningLevel":
                {
                    "Hue": self.hue,
                    "Saturation": self.saturation
                }
        }


class WarmCoolColorValue(ColorMode):
    def __init__(self, kelvin: int):
        """
        Warm Cool color value

        :param kelvin: kelvin value between 1400 and 7000
        """
        self.kelvin = kelvin

    def get_spectrum_tuning_level_parameters(self) -> dict:
        return {
            "ColorTuningStatus": self.get_white_tuning_level_parameters()
        }

    def get_white_tuning_level_parameters(self) -> dict:
        return {
            "WhiteTuningLevel": {
                "Kelvin": self.kelvin
            }
        }


class WarmDimmingColorValue:
    """
    Warm Dimming value

    :param enabled: enable warm dimming
    """

    def __init__(self, enabled: bool, additional_params: dict = {}):
        self.enabled = enabled
        self.additional_params = additional_params

    @staticmethod
    def get_warm_dim_from_leap(zone_status: dict) -> Optional["bool"]:
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
        if self.enabled:
            curve_dimming = {
                "Curve":
                    {
                        "href": "/curve/1"
                    }
            }
        else:
            curve_dimming = None

        return {
            "CurveDimming": curve_dimming
        }

    def get_spectrum_tuning_level_parameters(self) -> dict:
        params = {
            "ColorTuningStatus": self.get_leap_parameters()
        }
        params.update(self.additional_params)
        return {
            "CommandType": "GoToSpectrumTuningLevel",
            "SpectrumTuningLevelParameters": params
        }

    def get_white_tuning_level_parameters(self) -> dict:
        params = self.get_leap_parameters()
        params.update(self.additional_params)

        return {
            "CommandType": "GoToWarmDim",
            "WarmDimParameters": params
        }
