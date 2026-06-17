import threading
import time

import rtmidi

midi_in = None
midi_out = None
running = False
midi_thread = None

midi_status = {
    "input_port": None,
    "output_port": None,
    "input_ports": [],
    "output_ports": [],
    "running": False,
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


def init_midi():
    global midi_in, midi_out

    try:
        midi_status["last_error"] = ""

        midi_in = rtmidi.MidiIn()
        input_ports = midi_in.get_ports()
        midi_status["input_ports"] = input_ports
        input_port_index = _find_port_index(input_ports, "APC")

        if input_port_index is None:
            midi_status["last_error"] = "No se encontro APC Mini como entrada."
            print("[MIDI] No se encontro APC Mini como entrada.")
            return False

        midi_in.open_port(input_port_index)
        midi_status["input_port"] = input_ports[input_port_index]
        print("[MIDI] Entrada MIDI conectada:", input_ports[input_port_index])

        midi_out = rtmidi.MidiOut()
        output_ports = midi_out.get_ports()
        midi_status["output_ports"] = output_ports
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

        return True

    except Exception as exc:
        midi_status["last_error"] = str(exc)
        print(f"[MIDI ERROR] No se pudo inicializar MIDI: {exc}")
        return False


def midi_led(note, velocity):
    if not midi_out or note is None:
        return
    try:
        midi_out.send_message([144, note, velocity])
    except Exception as exc:
        midi_status["last_error"] = str(exc)
        print(f"[MIDI ERROR] LED note={note}: {exc}")


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


def midi_loop(handle_event_callback):
    global midi_in, running

    while running:
        try:
            msg = midi_in.get_message()
        except Exception as exc:
            midi_status["last_error"] = str(exc)
            print(f"[MIDI ERROR] Leyendo mensaje: {exc}")
            time.sleep(0.1)
            continue

        if msg:
            event = procesar_mensaje_crudo(msg)
            if event:
                handle_event_callback(event)

        time.sleep(0.003)


def start_midi_thread(handle_event_callback):
    global running, midi_thread

    if running:
        return True

    ok = init_midi()
    if not ok:
        print("[MIDI] No se iniciara el hilo MIDI.")
        running = False
        midi_status["running"] = False
        return False

    running = True
    midi_status["running"] = True

    midi_thread = threading.Thread(
        target=midi_loop,
        args=(handle_event_callback,),
        daemon=True,
    )
    midi_thread.start()

    print("[MIDI] Thread MIDI iniciado.")
    return True


def stop_midi():
    global running, midi_in, midi_out
    running = False
    midi_status["running"] = False
    try:
        if midi_in:
            midi_in.close_port()
    except Exception:
        pass
    try:
        if midi_out:
            midi_out.close_port()
    except Exception:
        pass


def inicializar_leds(mapeo_notas):
    if not midi_out:
        print("[MIDI] No se pueden encender LEDs: no hay salida MIDI.")
        return

    try:
        clear_all_leds()
        midi_out.send_message([0x90, 0, 1])
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
