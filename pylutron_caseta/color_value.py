# protocol which defines a method that returns a dictionary of the leap command given a zone string
from abc import ABC, abstractmethod
import colorsys


# Protocol for color supported lights
class ColorValue(ABC):
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


class FullColorValue(ColorValue):
    def __init__(self, r: int, g: int, b: int):
        """
        Full Color spectrum value

        :param r: red value between 0 and 255
        :param g: green value between 0 and 255
        :param b: blue value between 0 and 255
        """
        # convert rgb to hsv, then from 0-1 into 0-360 and 0-100
        h, s, _ = colorsys.rgb_to_hsv(float(r) / 255.0, float(g) / 255.0, float(b) / 255.0)
        self.hue = int(h * 360)
        self.saturation = int(s * 100)

    def get_spectrum_tuning_level_parameters(self) -> dict:
        return {
            "ColorTuningStatus": {
                "HSVTuningLevel":
                    {
                        "Hue": self.hue,
                        "Saturation": self.saturation
                    }
            }
        }


class WarmCoolColorValue(ColorValue):
    def __init__(self, kelvin: int):
        """
        Warm Cool color value

        :param kelvin: kelvin value between 1400 and 7000
        """
        self.kelvin = kelvin

    def get_spectrum_tuning_level_parameters(self) -> dict:
        return {
            "ColorTuningStatus": {
                "WhiteTuningLevel":
                    {
                        "Kelvin": self.kelvin
                    }
            }
        }


class WarmDimmingColorValue(ColorValue):
    """
    Warm Dimming value

    :param enabled: enable warm dimming
    """

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def get_spectrum_tuning_level_parameters(self) -> dict:

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
            "ColorTuningStatus":
                {
                    "CurveDimming": curve_dimming
                }
        }


class VibrancyColorValue(ColorValue):
    def __init__(self, vibrancy: int):
        """
        set the vibrancy value

        :param vibrancy: vibrancy value between 0 and 100
        """
        self.vibrancy = vibrancy

    def get_spectrum_tuning_level_parameters(self) -> dict:
        return {
            "Vibrancy": self.vibrancy
        }
