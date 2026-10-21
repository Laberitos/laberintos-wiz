import threading
import time

import rtmidi

midi_in = None
midi_inputs = []
midi_input_sources = {}
midi_out = None
running = False
midi_thread = None
midi_generation = 0
connection_callback = None
preferred_input_port_name = None
preferred_output_port_name = None
last_port_inventory = ((), ())
reconnect_requested = threading.Event()
midi_port_lock = threading.RLock()

MIDI_PORT_SCAN_INTERVAL_SECONDS = 1.5
MIDI_RECONNECT_INTERVAL_SECONDS = 2.0

midi_status = {
    "input_port": None,
    "output_port": None,
    "input_ports": [],
    "output_ports": [],
    "running": False,
    "connected": False,
    "apc_connected": False,
    "reconnecting": False,
    "reconnect_count": 0,
    "last_error": "",
}


LED_APAGADO = 0
LED_ROJO = 5
LED_VERDE = 21
LED_AMARILLO = 13
LED_AZUL = 45
LED_MAGENTA = 53
LED_CYAN = 37
LED_BLANCO = 3
LED_AMARILLO_INTENSO = 63


def _find_port_index(ports, include_text="APC", exclude_text=None):
    include_text = include_text.lower()
    exclude_text = exclude_text.lower() if exclude_text else None
    for index, port_name in enumerate(ports):
        name = port_name.lower()
        if include_text in name and (exclude_text is None or exclude_text not in name):
            return index
    return None


def get_available_ports():
    try:
        midi_in_probe = rtmidi.MidiIn()
        midi_out_probe = rtmidi.MidiOut()
        return {
            "inputs": midi_in_probe.get_ports(),
            "outputs": midi_out_probe.get_ports(),
        }
    except Exception as exc:
        return {"inputs": [], "outputs": [], "error": str(exc)}


def get_midi_status():
    midi_status["running"] = bool(running)
    return dict(midi_status)


def _port_inventory(ports=None):
    ports = ports or get_available_ports()
    return (
        tuple(ports.get("inputs", [])),
        tuple(ports.get("outputs", [])),
    )


def _close_midi_ports():
    global midi_in, midi_inputs, midi_input_sources, midi_out

    with midi_port_lock:
        inputs = list(midi_inputs)
        if midi_in is not None and midi_in not in inputs:
            inputs.append(midi_in)

        for midi_input in inputs:
            try:
                midi_input.close_port()
            except Exception:
                pass

        try:
            if midi_out is not None:
                midi_out.close_port()
        except Exception:
            pass

        midi_in = None
        midi_inputs = []
        midi_input_sources = {}
        midi_out = None


def _notify_connection(event):
    callback = connection_callback
    if not callable(callback):
        return
    try:
        callback(event, get_midi_status())
    except Exception as exc:
        print(f"[MIDI ERROR] Avisando cambio de conexion: {exc}")


def request_midi_reconnect(error=None):
    if error:
        midi_status["last_error"] = str(error)
    midi_status["reconnecting"] = True
    reconnect_requested.set()


def init_midi(input_port_name=None, output_port_name=None):
    global midi_in, midi_inputs, midi_input_sources, midi_out, last_port_inventory

    _close_midi_ports()
    midi_status["input_port"] = None
    midi_status["output_port"] = None
    midi_status["connected"] = False
    midi_status["apc_connected"] = False
    midi_status["reconnecting"] = True
    try:
        midi_status["last_error"] = ""

        input_probe = rtmidi.MidiIn()
        input_ports = input_probe.get_ports()
        midi_status["input_ports"] = input_ports
        output_probe = rtmidi.MidiOut()
        output_ports = output_probe.get_ports()
        midi_status["output_ports"] = output_ports
        last_port_inventory = (tuple(input_ports), tuple(output_ports))

        input_specs = []
        if input_port_name:
            preferred_index = _find_port_index(input_ports, input_port_name)
            if preferred_index is not None:
                preferred_name = input_ports[preferred_index]
                preferred_role = "apc" if "apc" in preferred_name.lower() else "ableton"
                input_specs.append((preferred_index, preferred_role))

        apc_index = _find_port_index(input_ports, "APC")
        if apc_index is not None and all(index != apc_index for index, _role in input_specs):
            input_specs.append((apc_index, "apc"))

        if not input_specs:
            midi_status["last_error"] = "No se encontro entrada MIDI compatible."
            print("[MIDI] No se encontro entrada MIDI compatible.")
            return False

        midi_inputs = []
        midi_input_sources = {}
        for input_port_index, source_role in input_specs:
            midi_input = rtmidi.MidiIn()
            midi_input.open_port(input_port_index)
            midi_inputs.append(midi_input)
            midi_input_sources[id(midi_input)] = {
                "port": input_ports[input_port_index],
                "role": source_role,
            }

        midi_in = midi_inputs[0] if midi_inputs else None
        midi_status["input_port"] = " + ".join(
            input_ports[index]
            for index, _role in input_specs
        )
        print("[MIDI] Entrada MIDI conectada:", midi_status["input_port"])

        midi_out = rtmidi.MidiOut()
        if output_port_name and "microsoft gs wavetable" in output_port_name.lower():
            output_port_name = None

        output_port_index = None
        if output_port_name:
            output_port_index = _find_port_index(output_ports, output_port_name)
        if output_port_index is None:
            output_port_index = _find_port_index(output_ports, "APC mini mk2", "MIDIOUT2")
        if output_port_index is None:
            output_port_index = _find_port_index(output_ports, "APC")

        print("[MIDI DEBUG] Puerto OUT seleccionado:", output_port_index)

        if output_port_index is None:
            midi_status["output_port"] = None
            print("[MIDI] No se encontro APC Mini como salida.")
        else:
            midi_out.open_port(output_port_index)
            midi_status["output_port"] = output_ports[output_port_index]
            print("[MIDI] Salida MIDI conectada:", output_ports[output_port_index])

        connected_names = input_ports + output_ports
        midi_status["connected"] = bool(midi_inputs)
        midi_status["apc_connected"] = any("apc" in name.lower() for name in connected_names)
        midi_status["reconnecting"] = False
        return True

    except Exception as exc:
        _close_midi_ports()
        midi_status["input_port"] = None
        midi_status["output_port"] = None
        midi_status["connected"] = False
        midi_status["apc_connected"] = False
        midi_status["reconnecting"] = True
        midi_status["last_error"] = str(exc)
        print(f"[MIDI ERROR] No se pudo inicializar MIDI: {exc}")
        return False


def midi_led(note, velocity):
    if not midi_out or note is None:
        return
    try:
        with midi_port_lock:
            if midi_out is not None:
                midi_out.send_message([144, note, velocity])
    except Exception as exc:
        midi_status["last_error"] = str(exc)
        print(f"[MIDI ERROR] LED note={note}: {exc}")
        request_midi_reconnect(exc)


def led_activo(note):
    midi_led(note, LED_VERDE)


def led_inactivo(note):
    midi_led(note, LED_ROJO)


def clear_all_leds():
    if not midi_out:
        return
    for note in range(128):
        midi_led(note, LED_APAGADO)


def procesar_mensaje_crudo(msg):
    try:
        raw, timestamp = msg
        status = raw[0]
        note = raw[1]
        velocity = raw[2]

        message_type = status & 0xF0
        is_note_on = message_type == 0x90 and velocity > 0
        is_note_off = message_type == 0x80 or (message_type == 0x90 and velocity == 0)

        return {
            "status": status,
            "note": note,
            "velocity": velocity,
            "timestamp": timestamp,
            "note_on": is_note_on,
            "note_off": is_note_off,
        }

    except Exception as exc:
        midi_status["last_error"] = str(exc)
        print(f"[MIDI ERROR] Error procesando mensaje: {exc}")
        return None


def midi_loop(handle_event_callback, generation):
    global midi_in, midi_inputs, running, last_port_inventory

    next_port_scan = 0.0
    next_reconnect_attempt = 0.0
    connection_announced = bool(midi_status.get("connected"))

    while running and generation == midi_generation:
        now = time.monotonic()
        if now >= next_port_scan:
            available = get_available_ports()
            inventory = _port_inventory(available)
            inventory_changed = inventory != last_port_inventory
            should_reconnect = (
                reconnect_requested.is_set()
                or inventory_changed
                or not midi_status.get("connected", False)
            )

            if should_reconnect and now >= next_reconnect_attempt:
                if not running or generation != midi_generation:
                    break
                was_connected = bool(midi_status.get("connected"))
                was_apc_connected = bool(midi_status.get("apc_connected"))
                midi_status["reconnecting"] = True
                if was_connected and (inventory_changed or reconnect_requested.is_set()):
                    midi_status["connected"] = False
                    midi_status["apc_connected"] = False
                    _notify_connection("disconnected")

                ok = init_midi(
                    input_port_name=preferred_input_port_name,
                    output_port_name=preferred_output_port_name,
                )
                reconnect_requested.clear()
                next_reconnect_attempt = now + MIDI_RECONNECT_INTERVAL_SECONDS

                if ok:
                    reconnected = connection_announced or was_connected or was_apc_connected
                    if reconnected:
                        midi_status["reconnect_count"] += 1
                    connection_announced = True
                    _notify_connection("reconnected" if reconnected else "connected")
                    print("[MIDI] Conexion restablecida automaticamente.")

            next_port_scan = now + MIDI_PORT_SCAN_INTERVAL_SECONDS

        if not running or generation != midi_generation:
            break

        with midi_port_lock:
            active_inputs = [
                (
                    midi_input,
                    dict(
                        midi_input_sources.get(
                            id(midi_input),
                            {"port": "", "role": "unknown"},
                        )
                    ),
                )
                for midi_input in (midi_inputs or ([midi_in] if midi_in else []))
            ]
        for midi_input, source in active_inputs:
            try:
                with midi_port_lock:
                    msg = midi_input.get_message()
            except Exception as exc:
                midi_status["last_error"] = str(exc)
                print(f"[MIDI ERROR] Leyendo mensaje: {exc}")
                if running and generation == midi_generation:
                    request_midi_reconnect(exc)
                break

            if msg:
                event = procesar_mensaje_crudo(msg)
                if event:
                    event["source_port"] = source.get("port", "")
                    event["source_role"] = source.get("role", "unknown")
                    handle_event_callback(event)

        time.sleep(0.003)


def start_midi_thread(
    handle_event_callback,
    input_port_name=None,
    output_port_name=None,
    on_connection_change=None,
):
    global running, midi_thread, connection_callback, midi_generation
    global preferred_input_port_name, preferred_output_port_name

    preferred_input_port_name = input_port_name
    preferred_output_port_name = output_port_name
    connection_callback = on_connection_change

    if running:
        request_midi_reconnect()
        return True

    ok = init_midi(input_port_name=input_port_name, output_port_name=output_port_name)
    if not ok:
        print("[MIDI] Puertos no disponibles; se intentara reconectar automaticamente.")

    running = True
    midi_generation += 1
    generation = midi_generation
    midi_status["running"] = True

    midi_thread = threading.Thread(
        target=midi_loop,
        args=(handle_event_callback, generation),
        daemon=True,
    )
    midi_thread.start()

    if ok:
        _notify_connection("connected")
    else:
        request_midi_reconnect()
    print("[MIDI] Thread MIDI iniciado con supervision de puertos.")
    return True


def stop_midi():
    global running, midi_generation
    running = False
    midi_generation += 1
    midi_status["running"] = False
    midi_status["connected"] = False
    midi_status["apc_connected"] = False
    midi_status["reconnecting"] = False
    reconnect_requested.clear()
    _close_midi_ports()


def inicializar_leds(mapeo_notas):
    if not midi_out:
        print("[MIDI] No se pueden encender LEDs: no hay salida MIDI.")
        return

    try:
        clear_all_leds()
        midi_led(0, 1)
        time.sleep(0.05)

        efectos_validos = {16, 24, 32, 40, 48, 56}

        for note in mapeo_notas:
            if note == 0:
                midi_led(note, LED_MAGENTA)
            elif note == 2:
                midi_led(note, 47)
            elif note in (1, 4):
                midi_led(note, LED_CYAN)
            elif note == 3:
                midi_led(note, LED_AMARILLO)
            elif note == 5:
                midi_led(note, LED_ROJO)
            elif note in (6, 7):
                midi_led(note, 12)
            elif note == 58:
                midi_led(note, LED_AZUL)
            elif note in efectos_validos:
                midi_led(note, LED_ROJO)

        print("[MIDI] LEDs iniciales encendidos correctamente.")

    except Exception as exc:
        midi_status["last_error"] = str(exc)
        print("[MIDI ERROR] inicializando LEDs:", exc)
