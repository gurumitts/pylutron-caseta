# protocol which defines a method that returns a dictionary of the leap command given a zone string
from abc import ABC, abstractmethod
import colorsys
from typing import Optional


class ColorMode(ABC):
    """
    A protocol for setting the color property of a support light.
   """

    @abstractmethod
    def get_spectrum_tuning_level_parameters(self) -> dict:
        """
        Gets the relevant parameter dictionary for the spectrum tuning level of the child class.

        :return: spectrum tuning level parameter dictionary
        """
        pass

    def get_white_tuning_level_parameters(self) -> dict:
        """
        Gets the relevant parameter dictionary for the white tuning level of the child class.

        :return: white tuning level parameter dictionary
        """
        pass


    @staticmethod
    def get_color_from_leap(zone_status: dict) -> Optional["ColorMode"]:
        """
        Gets the color value from the leap command.

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
            return FullColorValue(HueSaturationColorParameter(hue, saturation))

        return None


class FullColorParameter(ABC):
    @abstractmethod
    def get_hs(self) -> (int, int):
        pass


class RGBColorParameter(FullColorParameter):
    def __init__(self, r: int, g: int, b: int):
        self.r = r
        self.g = g
        self.b = b

    def get_hs(self) -> (int, int):
        # convert rgb to hsv, then from 0-1 into 0-360 and 0-100
        h, s, _ = colorsys.rgb_to_hsv(float(self.r) / 255.0, float(self.g) / 255.0, float(self.b) / 255.0)
        return int(h * 360), int(s * 100)


class HueSaturationColorParameter(FullColorParameter):
    def __init__(self, hue: int, saturation: int):
        self.hue = hue
        self.saturation = saturation

    def get_hs(self) -> (int, int):
        return self.hue, self.saturation


class FullColorValue(ColorMode):
    def __init__(self, color: FullColorParameter):
        """
        Full Color spectrum value

        :param color: color parameter for the bulb defined by either RGB or Hue/Saturation
        """
        self.hue, self.saturation = color.get_hs()

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

    def get_rgb(self) -> (int, int, int):
        # convert hsv to rgb, then from 0-1 into 0-255
        r, g, b = colorsys.hsv_to_rgb(float(self.hue) / 360.0, float(self.saturation) / 100.0, 1.0)
        return int(r * 255), int(g * 255), int(b * 255)


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
