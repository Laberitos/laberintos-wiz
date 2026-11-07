import unittest
import sys
import types

pywizlight_stub = types.ModuleType("pywizlight")
pywizlight_stub.wizlight = object
pywizlight_stub.PilotBuilder = object
sys.modules.setdefault("pywizlight", pywizlight_stub)

from tablero.helpers_wiz import safe_brightness


class SafeBrightnessTests(unittest.TestCase):
    def test_zero_remains_off(self):
        self.assertEqual(safe_brightness(0), 0)
        self.assertEqual(safe_brightness(-1), 0)

    def test_positive_values_use_wiz_safe_minimum(self):
        self.assertEqual(safe_brightness(1), 8)
        self.assertEqual(safe_brightness(8), 8)
        self.assertEqual(safe_brightness(255), 255)
        self.assertEqual(safe_brightness(300), 255)


if __name__ == "__main__":
    unittest.main()
