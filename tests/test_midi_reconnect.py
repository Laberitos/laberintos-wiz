import unittest
from unittest.mock import patch

from tablero import midi_listener


class FakeMidiIn:
    ports = []

    def __init__(self):
        self.opened_index = None
        self.closed = False

    def get_ports(self):
        return list(self.ports)

    def open_port(self, index):
        self.opened_index = index

    def close_port(self):
        self.closed = True

    def get_message(self):
        return None


class FakeMidiOut(FakeMidiIn):
    sent_messages = []

    def send_message(self, message):
        self.sent_messages.append(list(message))


class MidiReconnectTests(unittest.TestCase):
    def setUp(self):
        midi_listener.stop_midi()
        midi_listener.midi_status.update(
            {
                "input_port": None,
                "output_port": None,
                "input_ports": [],
                "output_ports": [],
                "connected": False,
                "apc_connected": False,
                "reconnecting": False,
                "reconnect_count": 0,
                "last_error": "",
            }
        )
        midi_listener.last_port_inventory = ((), ())
        FakeMidiIn.ports = []
        FakeMidiOut.ports = []
        FakeMidiOut.sent_messages = []

    def tearDown(self):
        midi_listener.stop_midi()

    def test_init_reopens_apc_after_ports_return(self):
        with patch.object(midi_listener.rtmidi, "MidiIn", FakeMidiIn), patch.object(
            midi_listener.rtmidi,
            "MidiOut",
            FakeMidiOut,
        ):
            self.assertFalse(
                midi_listener.init_midi("Laberintos MIDI", "APC mini mk2")
            )

            FakeMidiIn.ports = ["Laberintos MIDI 1", "APC mini mk2 0"]
            FakeMidiOut.ports = ["APC mini mk2 1"]

            self.assertTrue(
                midi_listener.init_midi("Laberintos MIDI", "APC mini mk2")
            )

        status = midi_listener.get_midi_status()
        self.assertTrue(status["connected"])
        self.assertTrue(status["apc_connected"])
        self.assertIn("Laberintos MIDI 1", status["input_port"])
        self.assertEqual(status["output_port"], "APC mini mk2 1")

    def test_supervisor_connects_when_apc_appears(self):
        events = []
        midi_listener.running = True
        midi_listener.midi_generation += 1
        generation = midi_listener.midi_generation
        midi_listener.connection_callback = lambda event, _status: events.append(event)
        midi_listener.preferred_input_port_name = "Laberintos MIDI"
        midi_listener.preferred_output_port_name = "APC mini mk2"

        port_snapshots = [
            {"inputs": [], "outputs": []},
            {
                "inputs": ["Laberintos MIDI 1", "APC mini mk2 0"],
                "outputs": ["APC mini mk2 1"],
            },
        ]
        monotonic_values = iter((0.0, 2.0))
        init_calls = []

        def fake_init(input_port_name=None, output_port_name=None):
            init_calls.append((input_port_name, output_port_name))
            if len(init_calls) == 1:
                midi_listener.midi_status["connected"] = False
                return False
            midi_listener.midi_status["connected"] = True
            midi_listener.midi_status["apc_connected"] = True
            midi_listener.midi_status["output_port"] = "APC mini mk2 1"
            midi_listener.last_port_inventory = (
                tuple(port_snapshots[-1]["inputs"]),
                tuple(port_snapshots[-1]["outputs"]),
            )
            return True

        sleep_calls = 0

        def fake_sleep(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                midi_listener.running = False

        with patch.object(
            midi_listener,
            "get_available_ports",
            side_effect=port_snapshots,
        ), patch.object(midi_listener, "init_midi", side_effect=fake_init), patch.object(
            midi_listener.time,
            "monotonic",
            side_effect=monotonic_values,
        ), patch.object(midi_listener.time, "sleep", side_effect=fake_sleep):
            midi_listener.midi_loop(lambda _event: None, generation)

        self.assertEqual(len(init_calls), 2)
        self.assertIn("connected", events)
        self.assertTrue(midi_listener.midi_status["apc_connected"])

    def test_led_error_requests_reconnect(self):
        class BrokenMidiOut:
            def send_message(self, _message):
                raise RuntimeError("puerto desconectado")

            def close_port(self):
                return None

        midi_listener.midi_out = BrokenMidiOut()
        midi_listener.reconnect_requested.clear()

        midi_listener.midi_led(12, 21)

        self.assertTrue(midi_listener.reconnect_requested.is_set())
        self.assertTrue(midi_listener.midi_status["reconnecting"])

    def test_events_include_their_input_source(self):
        class OneMessageInput:
            def __init__(self):
                self.pending = [([0x90, 57, 127], 0.0)]

            def get_message(self):
                return self.pending.pop(0) if self.pending else None

            def close_port(self):
                return None

        midi_input = OneMessageInput()
        received = []
        midi_listener.running = True
        midi_listener.midi_generation += 1
        generation = midi_listener.midi_generation
        midi_listener.midi_inputs = [midi_input]
        midi_listener.midi_in = midi_input
        midi_listener.midi_input_sources = {
            id(midi_input): {
                "port": "APC mini mk2 1",
                "role": "apc",
            }
        }
        midi_listener.midi_status["connected"] = True
        midi_listener.last_port_inventory = (
            ("APC mini mk2 1",),
            ("APC mini mk2 2",),
        )

        def stop_after_iteration(_seconds):
            midi_listener.running = False

        with patch.object(
            midi_listener,
            "get_available_ports",
            return_value={
                "inputs": ["APC mini mk2 1"],
                "outputs": ["APC mini mk2 2"],
            },
        ), patch.object(midi_listener.time, "monotonic", return_value=0.0), patch.object(
            midi_listener.time,
            "sleep",
            side_effect=stop_after_iteration,
        ):
            midi_listener.midi_loop(received.append, generation)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["source_role"], "apc")
        self.assertEqual(received[0]["source_port"], "APC mini mk2 1")


if __name__ == "__main__":
    unittest.main()
