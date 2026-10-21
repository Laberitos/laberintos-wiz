import json
import unittest
from unittest.mock import patch

from tablero.lamp_network import pilot_result_to_info, probe_known_lamps


class LampNetworkTests(unittest.TestCase):
    def test_parses_colour_state(self):
        info = pilot_result_to_info(
            {
                "state": True,
                "dimming": 100,
                "r": 255,
                "g": 0,
                "b": 0,
                "mac": "AA:BB:CC:DD:EE:FF",
            }
        )

        self.assertTrue(info["is_on"])
        self.assertEqual(info["brightness"], 255)
        self.assertEqual(info["mode"], "colour")
        self.assertAlmostEqual(info["hue"], 0.0)
        self.assertAlmostEqual(info["sat"], 1.0)

    def test_parses_warm_white_while_off(self):
        info = pilot_result_to_info(
            {
                "state": False,
                "dimming": 8,
                "temp": 2200,
            }
        )

        self.assertFalse(info["is_on"])
        self.assertEqual(info["brightness"], 20)
        self.assertEqual(info["mode"], "white")
        self.assertEqual(info["temp"], 2200)

    def test_probe_recognizes_udp_response(self):
        class FakeSocket:
            def __init__(self):
                self.responses = []

            def setblocking(self, _enabled):
                return None

            def sendto(self, _request, address):
                if not self.responses:
                    response = {
                        "method": "getPilot",
                        "result": {
                            "state": True,
                            "dimming": 50,
                            "temp": 3000,
                        },
                    }
                    self.responses.append(
                        (json.dumps(response).encode("utf-8"), (address[0], address[1]))
                    )

            def recvfrom(self, _size):
                if not self.responses:
                    raise BlockingIOError
                return self.responses.pop(0)

            def close(self):
                return None

        fake_socket = FakeSocket()

        def fake_select(_read, _write, _errors, _timeout):
            return ([fake_socket], [], []) if fake_socket.responses else ([], [], [])

        with patch("tablero.lamp_network.socket.socket", return_value=fake_socket), patch(
            "tablero.lamp_network.select.select",
            side_effect=fake_select,
        ):
            results = probe_known_lamps(
                ["127.0.0.1"],
                timeout=0.8,
                retry_offsets=(0.0,),
                port=38899,
            )

        self.assertTrue(results["127.0.0.1"]["online"])
        self.assertEqual(results["127.0.0.1"]["info"]["brightness"], 128)


if __name__ == "__main__":
    unittest.main()
