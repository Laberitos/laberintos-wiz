import rtmidi
import time
import threading

midi_in = None
midi_out = None
running = False


# ===========================================================
# INICIALIZACIÓN DE MIDI (IN + OUT)
# ===========================================================
def init_midi():
    global midi_in, midi_out

    try:
        midi_in = rtmidi.MidiIn()
        ports = midi_in.get_ports()

        # -------------------------------------------
        # ENTRADA MIDI (APC MINI MK2)
        # -------------------------------------------
        in_port = None
        for i, p in enumerate(ports):
            if "APC" in p or "apc" in p.lower():
                in_port = i
                break

        if in_port is None:
            print("[MIDI] No se encontró APC Mini como entrada.")
            return False

        midi_in.open_port(in_port)
        print("[MIDI] Entrada MIDI conectada:", ports[in_port])

        # -------------------------------------------
        # SALIDA MIDI (APC MINI MK2 LEDS)
        # -------------------------------------------
        midi_out = rtmidi.MidiOut()
        out_ports = midi_out.get_ports()

        # Buscar explícitamente el puerto RGB real
        # Elegir siempre el puerto correcto (RGB)
        out_port = None
        for i, p in enumerate(out_ports):
            if "APC mini mk2" in p and "MIDIOUT2" not in p:
                out_port = i
                break

        # Si por algún motivo no lo encontró, forzar puerto 1
        if out_port is None:
            out_port = 1
         
        print("[MIDI DEBUG] Puerto OUT seleccionado:", out_port)
 
         
        if out_port is None:
            print("[MIDI] No se encontró APC Mini como salida.")
        else:
            midi_out.open_port(out_port)
            print("[MIDI] Salida MIDI conectada:", out_ports[out_port])

        return True

    except Exception as e:
        print(f"[MIDI ERROR] No se pudo inicializar MIDI: {e}")
        return False



# ===========================================================
# FUNCIONES DE LED PARA APC MINI MK2
# ===========================================================
# ====================== COLORES REALES APC MINI MK2 ======================

# Colores intensos reales (probados)
LED_APAGADO = 0
LED_ROJO = 5          # Rojo brillante bien visible
LED_VERDE = 21        # Verde brillante
LED_AMARILLO = 13     # Amarillo fuerte
LED_AZUL = 45         # Azul intenso
LED_MAGENTA = 53      # Magenta fuerte
LED_CYAN = 37         # Cyan brillante
LED_BLANCO = 3        # Blanco tenue pero visible
LED_AMARILLO_INTENSO = 63 # amarillo para boton inferior

def midi_led(note, velocity):
    """Enciende el LED con un color intenso real."""
    if midi_out:
        midi_out.send_message([144, note, velocity])

def led_activo(note):
    """Efecto ACTIVO → verde brillante"""
    midi_led(note, LED_VERDE)

def led_inactivo(note):
    """Efecto disponible pero apagado → rojo brillante"""
    midi_led(note, LED_ROJO)




# ===========================================================
# PROCESAMIENTO DEL MENSAJE MIDI
# ===========================================================
def procesar_mensaje_crudo(msg):
    try:
        raw, timestamp = msg
        status = raw[0]
        note = raw[1]
        vel = raw[2]

        is_note_on = (status & 0xF0) == 0x90 and vel > 0
        is_note_off = (status & 0xF0) == 0x80 or ((status & 0xF0) == 0x90 and vel == 0)

        return {
            "status": status,
            "note": note,
            "velocity": vel,
            "timestamp": timestamp,
            "note_on": is_note_on,
            "note_off": is_note_off
        }

    except Exception as e:
        print(f"[MIDI ERROR] Error procesando mensaje: {e}")
        return None


# ===========================================================
# LOOP MIDI
# ===========================================================
def midi_loop(handle_event_callback):
    global midi_in, running

    while running:
        msg = midi_in.get_message()

        if msg:
            event = procesar_mensaje_crudo(msg)
            if event:
                handle_event_callback(event)

        time.sleep(0.001)



# ===========================================================
# INICIO DEL THREAD MIDI
# ===========================================================
def start_midi_thread(handle_event_callback):
    global running

    ok = init_midi()
    if not ok:
        print("[MIDI] No se iniciará el hilo MIDI.")
        running = False
        return False

    running = True

    t = threading.Thread(
        target=midi_loop,
        args=(handle_event_callback,),
        daemon=True
    )
    t.start()

    print("[MIDI] Thread MIDI iniciado.")
    return True



# ===========================================================
# DETENER
# ===========================================================
def stop_midi():
    global running
    running = False


def inicializar_leds(mapeo_notas):
    global midi_out
    if not midi_out:
        print("[MIDI] No se pueden encender LEDs: no hay salida MIDI.")
        return

    try:
        # Desbloquear modo RGB de pads
        midi_out.send_message([0x90, 0, 1])
        time.sleep(0.05)

        efectos_validos = {16, 24, 32, 40, 48, 56}

        for note in mapeo_notas:

            # --- Refresh (botón 8) ---
            if note == 0:
                midi_led(note, LED_MAGENTA)
                continue
            
            if note == 2:
                midi_led(2, 47)  # flash rojo
              #  root.after(80, lambda: midi_led(2, 12))  # vuelve a azul tenue

            # --- Encender Todo (7) ---
            if note == 7:
                midi_led(note, 12 )  # azul tenue al iniciar
                continue
 
            # --- Apagar Todo (6) ---
            if note == 6:
                midi_led(note, 12)  # azul tenue al iniciar
                continue
            
                        # --- Apagar Todo (6) ---
            if note == 58:
                midi_led(note, 45)  # azul tenue al iniciar
                continue

            # --- Efectos válidos (RGB pads) ---
            if note in efectos_validos:
                midi_led(note, LED_ROJO)
                continue

        print("[MIDI] LEDs iniciales encendidos correctamente.")

    except Exception as e:
        print("[MIDI ERROR] inicializando LEDs:", e)





