import math
import colorsys
from pywizlight import PilotBuilder


def _panel_mode(panel):
    # Effects must use the live lamp state, not preview-only UI controls.
    return getattr(panel, "last_mode", "colour")


def _is_white_panel(panel):
    return _panel_mode(panel) == "white"


def _safe_effect_brightness(value):
    try:
        value = int(value)
    except Exception:
        return 8
    return max(8, min(255, value))


def _normalize_wiz_colortemp(value):
    try:
        value = float(value)
    except Exception:
        value = 128.0
    if value > 1000:
        return int(max(2200, min(6500, value)))
    value = max(0.0, min(255.0, value))
    return int(2200 + (value / 255.0) * (6500 - 2200))


def _send_panel_brightness(send_lamp_color, send_lamp_white, ip, panel, brightness):
    brightness = _safe_effect_brightness(brightness)

    if _is_white_panel(panel):
        temp = getattr(panel, "last_temp", 4000)
        if send_lamp_white is not None:
            send_lamp_white(ip, brightness, temp)
        else:
            send_lamp_color(ip, 0, 0, brightness)
    else:
        h = getattr(panel, "last_hue", 0)
        s = getattr(panel, "last_sat", 1)
        send_lamp_color(ip, h, s, brightness)

    panel.last_brillo = brightness


def _pilot_for_panel(panel, brightness):
    brightness = _safe_effect_brightness(brightness)
    if _is_white_panel(panel):
        temp = _normalize_wiz_colortemp(getattr(panel, "last_temp", 4000))
        return PilotBuilder(brightness=brightness, colortemp=temp)

    h = getattr(panel, "last_hue", 0)
    s = getattr(panel, "last_sat", 1)
    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, 1)
    return PilotBuilder(
        rgb=(int(r * 255), int(g * 255), int(b * 255)),
        brightness=brightness
    )


def efecto_golpe_tambor(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    root
):
    """
    Golpe de tambor: flash blanco seguido de apagado inmediato.
    Duración total: ~250 ms.
    """

    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]

    # 1) Flash fuerte (blanco)
    for ip in activos:
        send_lamp_color(ip, 0, 0, 255)   # HSL blanco = brillo 255

    # 2) Apagado rápido (después de 120ms)
    def apagado():
        for ip in activos:
            send_lamp_color(ip, 0, 0, 0)
    root.after(120, apagado)


def efecto_golpe_tambor_(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    root
):
    """
    Golpe de tambor: flash blanco seguido de apagado inmediato.
    Duración total: ~250 ms.
    """

    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]

    # 1) Flash fuerte (blanco)
    for ip in activos:
        send_lamp_color(ip, 0, 0, 255)   # HSL blanco = brillo 255

    # 2) Apagado rápido (después de 120ms)
    def apagado():
        for ip in activos:
            send_lamp_color(ip, 0, 0, 0)
    root.after(120, apagado)


def efecto_respiracion(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    lamp_status,
    brillo_min,
    brillo_max,
    vel_up,
    vel_down,
    respirando_var,
    root,
    send_lamp_white=None,
    fase=[0.0]
):
    """
    Respiración REAL:
    - Movimiento senoidal del brillo.
    - Se detiene inmediatamente al apagar el check.
    - Transiciones suaves.
    - Sin saturar la red.
    - Sin threads.
    """

    # SI APAGASTE EL CHECK → DETENER
    if not respirando_var.get():
        return

    # avanzar fase muy lento → respiración suave
    fase[0] += 0.03  # bajar este número = respiración más lenta

    # onda normalizada 0–1
    onda = (math.sin(fase[0]) + 1) / 2

    # brillo suave generado por la onda
    brillo = int(brillo_min + (brillo_max - brillo_min) * onda)

    # lámparas activas y online
    activos = [
        ip for ip in LAMP_IPS
        if selected_devices[ip].get() and lamp_status.get(ip, False)
    ]

    for ip in activos:
        try:
            _send_panel_brightness(send_lamp_color, send_lamp_white, ip, panels[ip], brillo)
        except Exception as e:
            print(f"[respiración] Error en {ip}: {e}")

    # programar siguiente paso sin saturación
    root.after(40, efecto_respiracion,
               send_lamp_color, LAMP_IPS, panels,
               selected_devices, lamp_status,
               brillo_min, brillo_max,
               vel_up, vel_down,
               respirando_var, root, send_lamp_white, fase)


# EFECTO SECUENCIA (CHASE) – SIN THREADS
def efecto_secuencia(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    lamp_status,           # ← NUEVO
    brillo_on,
    tiempo_on_ms,
    chase_var,
    root,
    send_lamp_white=None
):
    def ciclo(idx):
        # Si apagaste el efecto, apagamos todo y salimos
        if not chase_var.get():
            activos = [
                ip for ip in LAMP_IPS
                if selected_devices[ip].get() and lamp_status.get(ip, False)
            ]
            for ip in activos:
                apagar_lampara(ip)   # ← sin threads
            return

        # Filtrar lámparas válidas
        activos = [
            ip for ip in LAMP_IPS
            if selected_devices[ip].get() and lamp_status.get(ip, False)
        ]

        if not activos:
            root.after(100, ciclo, idx)
            return

        if idx >= len(activos):
            idx = 0

        ip_on = activos[idx]

        # Apagar todos menos la activa
        for ip in activos:
            if ip != ip_on:
                apagar_lampara(ip)

        # Encender la lámpara actual
        _send_panel_brightness(send_lamp_color, send_lamp_white, ip_on, panels[ip_on], brillo_on)

        # Programar apagado y siguiente paso
        def apagar_y_seguir():
            apagar_lampara(ip_on)
            root.after(10, ciclo, idx + 1)

        root.after(tiempo_on_ms, apagar_y_seguir)

    ciclo(0)


import threading

#EFECTO SECUENCIA_ON
def secuencia_on(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    lamp_status,
    valores_destino,
    tiempo_on_ms,
    secuencia_var,
    root,
    nombre_escena=None,
    btn_secuencia_on=None,     # ← AÑADIDO
    on_finish_cb=None    # ← NUEVO

):
    """
    Secuencia ON optimizada:
    - enciende lámparas una por una usando valores de escena
    - finaliza automáticamente al terminar
    """

    activos = [
        ip for ip in LAMP_IPS
        if lamp_status.get(ip, False) and ip in valores_destino
    ]
    if not activos:
        print("[SECUENCIA ON] No hay lámparas activas.")
        return

    total = len(activos)

    def ciclo(idx):
        # si usuario apagó el check, detener
        if not secuencia_var.get():
            print("[SECUENCIA ON] Interrumpida por el usuario.")
            return

        # si ya se encendieron todas
        if idx >= total:
            print("[SECUENCIA ON] Finalizada correctamente.")

            # 1) Apagar el Checkbutton
            secuencia_var.set(False)

            # 2) Actualizar UI del botón
            if btn_secuencia_on:
                try:
                    btn_secuencia_on.config(text="Secuencia_ON", bg="#20bdec")
                except:
                    pass

            # 3) Liberar escena
            global escena_en_ejecucion
            escena_en_ejecucion = False

            # 4) Llamar callback externo (UI del main)
            if on_finish_cb:
                try:
                    on_finish_cb(nombre_escena)
                except:
                    pass

            return


        ip_on = activos[idx]

        # valores de escena
        estado = valores_destino[ip_on]
        modo = estado.get("modo", "colour")
        brillo_on = int(estado.get("brillo", 1))
        brillo_on = max(1, brillo_on)

        # actualizar UI local
        selected_devices[ip_on].set(True)
        panels[ip_on].last_mode = modo
        panels[ip_on].last_brillo = brillo_on

        if modo == "white":
            temp = estado.get("temp", getattr(panels[ip_on], "last_temp", 4000))
            panels[ip_on].last_temp = temp
            target = helper_send_lamp_white
            args = (ip_on, brillo_on, _normalize_wiz_colortemp(temp))
        else:
            h = estado.get("h", getattr(panels[ip_on], "last_hue", 0))
            s = estado.get("s", getattr(panels[ip_on], "last_sat", 1))
            panels[ip_on].last_hue = h
            panels[ip_on].last_sat = s
            target = send_lamp_color
            args = (ip_on, h, s, brillo_on)

        threading.Thread(target=target, args=args, daemon=True).start()

        # siguiente lámpara
        root.after(tiempo_on_ms, ciclo, idx + 1)

    ciclo(0)




#EFECTO SECUENCIA_OFF
import threading
from tablero.helpers_wiz import apagar_lampara, send_lamp_white as helper_send_lamp_white

def secuencia_off(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    lamp_status,
    tiempo_off_ms,
    secuencia_off_var,
    root,
    fade_ms,
    pasos_fade,
    send_lamp_white=None,
    on_finish_cb=None
):
    """
    Apaga, una por una, las lámparas online, con una transición de brillo.
    Sin threads alrededor de pywizlight para evitar 'Event loop is closed'.
    """
    # lámparas online
    activos = [
        ip for ip in LAMP_IPS
        if selected_devices[ip].get() and lamp_status.get(ip, False)
    ]
    if not activos:
        secuencia_off_var.set(False)
        if on_finish_cb:
            on_finish_cb()
        return

    # las apagamos al revés
    activos = list(reversed(activos))

    def finish():
        secuencia_off_var.set(False)
        if on_finish_cb:
            on_finish_cb()

    def ciclo(idx):
        if not secuencia_off_var.get():
            return

        if idx >= len(activos):
            return

        ip_off = activos[idx]

        # estado actual del panel
        brillo_inicial = getattr(panels[ip_off], "last_brillo", 255)

        # mini-fade
        def fade_step(step):
            if not secuencia_off_var.get():
                return

            # último paso: apagar
            if step >= pasos_fade:
                # apagar directo SIN thread
                apagar_lampara(ip_off)
                if ip_off in selected_devices:
                    selected_devices[ip_off].set(False)
                panels[ip_off].last_brillo = 0
                if idx == len(activos) - 1:
                    finish()
                return

            factor = 1 - (step / pasos_fade)
            brillo_actual = max(1, int(brillo_inicial * factor))

            # mandar color/brillo SIN thread
            _send_panel_brightness(send_lamp_color, send_lamp_white, ip_off, panels[ip_off], brillo_actual)

            # siguiente pasito del fade
            intervalo = int(fade_ms / pasos_fade) if pasos_fade else fade_ms
            root.after(intervalo, fade_step, step + 1)

        # arrancamos el fade de esta lámpara
        fade_step(0)

        # y programamos la siguiente lámpara
        root.after(tiempo_off_ms, ciclo, idx + 1)

    ciclo(0)


import asyncio
import threading
import colorsys
from pywizlight import wizlight, PilotBuilder

def parpadeo(
    LAMP_IPS,
    panels,
    selected_devices,   # 👈 lo agregamos
    lamp_status,
    parpadeo_var,
    brillo_on=230,
    brillo_off=0,
    tiempo_on_ms=70,
    tiempo_off_ms=70,
):
    """
    Estrobo real SOLO para las lámparas seleccionadas:
    - corre en un hilo aparte
    - dentro de ese hilo hay UN event loop solo para el estrobo
    - en cada ciclo hace un gather(...) con las lámparas seleccionadas
    """

    # filtramos las que estén online Y seleccionadas
    activos = [
        ip for ip in LAMP_IPS
        if lamp_status.get(ip, False) and selected_devices[ip].get()
    ]
    if not activos:
        return

    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        luces = [wizlight(ip) for ip in activos]

        async def run_strobe():
            on_sec = tiempo_on_ms / 1000.0
            off_sec = tiempo_off_ms / 1000.0

            while parpadeo_var.get():
                # ON: todas juntas
                tasks_on = []
                for luz, ip in zip(luces, activos):
                    panels[ip].last_brillo = brillo_on
                    tasks_on.append(luz.turn_on(_pilot_for_panel(panels[ip], brillo_on)))
                if tasks_on:
                    await asyncio.gather(*tasks_on, return_exceptions=True)

                await asyncio.sleep(on_sec)

                # OFF: todas juntas
                tasks_off = []
                for luz, ip in zip(luces, activos):
                    if brillo_off <= 0:
                        panels[ip].last_brillo = 0
                        tasks_off.append(luz.turn_off())
                    else:
                        panels[ip].last_brillo = brillo_off
                        tasks_off.append(luz.turn_on(_pilot_for_panel(panels[ip], brillo_off)))
                if tasks_off:
                    await asyncio.gather(*tasks_off, return_exceptions=True)

                await asyncio.sleep(off_sec)

        try:
            loop.run_until_complete(run_strobe())
        finally:
            loop.close()

    threading.Thread(target=worker, daemon=True).start()



#EFECTO ESTROBO
# EFECTO ESTROBO
def efecto_estrobo(
    send_lamp_color,
    send_off,
    LAMP_IPS,
    panels,
    selected_devices,
    estrobo_var,
    root,
    brillo_on,     # igual que usás en respiración
    brillo_off,       # 0 = apagado total, poné 80 si querés que no se note tanto el lag
    on_ms,           # tiempo encendida
    off_ms,          # tiempo apagada
    send_lamp_white=None
):
    import threading

    def ciclo(encendida: bool):
        # si apagaste el check → salir
        if not estrobo_var.get():
            return

        # usamos la MISMA lógica que respiración: solo las seleccionadas
        activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]

        threads = []
        if encendida:
            for ip in activos:
                t = threading.Thread(
                    target=_send_panel_brightness,
                    args=(send_lamp_color, send_lamp_white, ip, panels[ip], brillo_on)
                )
                t.start()
                threads.append(t)
        else:
            # APAGAR / BAJAR TODAS
            for ip in activos:
                if brillo_off <= 0:
                    t = threading.Thread(target=send_off, args=(ip,))
                else:
                    t = threading.Thread(
                        target=_send_panel_brightness,
                        args=(send_lamp_color, send_lamp_white, ip, panels[ip], brillo_off)
                    )
                t.start()
                threads.append(t)

        # igual que en respiración: esperar un poquito a que terminen
        for t in threads:
            t.join(timeout=0.05)

        # programar el siguiente tick
        if encendida:
            root.after(on_ms, ciclo, False)
        else:
            root.after(off_ms, ciclo, True)

    # arrancamos prendiendo
    ciclo(True)


import socket
import json
import threading

def _wiz_send_udp(ip: str, payload: dict):
    """Envia un comando Wiz por UDP sin pasar por pywizlight."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.05)             # no nos quedamos colgados
        sock.sendto(json.dumps(payload).encode("utf-8"), (ip, 38899))
    except OSError as e:
        # si una lámpara no responde, no rompemos el efecto
        # print(f"[WARN] UDP {ip}: {e}")
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass


def estrobo_udp(
    LAMP_IPS,
    selected_devices,
    lamp_status,
    estrobo_var,
    root,
    on_ms=60,
    off_ms=60,
    solo_seleccionadas=True,
):
    """
    Estrobo rápido y simultáneo usando UDP directo a las lámparas Wiz.
    - SIN transiciones
    - SIN pywizlight
    - paralelo (un hilo por lámpara por tick)
    """

    payload_on = {"method": "setPilot", "params": {"state": True}}
    payload_off = {"method": "setPilot", "params": {"state": False}}

    def get_activos():
        if solo_seleccionadas:
            return [
                ip for ip in LAMP_IPS
                if lamp_status.get(ip, False) and selected_devices[ip].get()
            ]
        else:
            return [ip for ip in LAMP_IPS if lamp_status.get(ip, False)]

    def tick(encender: bool):
        if not estrobo_var.get():
            return

        activos = get_activos()
        threads = []

        if encender:
            for ip in activos:
                t = threading.Thread(target=_wiz_send_udp, args=(ip, payload_on))
                t.start()
                threads.append(t)
            # no esperamos a que terminen para no acumular delay
            root.after(on_ms, tick, False)
        else:
            for ip in activos:
                t = threading.Thread(target=_wiz_send_udp, args=(ip, payload_off))
                t.start()
                threads.append(t)
            root.after(off_ms, tick, True)

    # arrancamos prendiendo
    tick(True)


# ================== EFECTOS WIZ INSPIRADOS EN LA APP ==================
import random

def efecto_fuego_wiz(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    efecto_var,
    root,
    brillo_min=140,
    brillo_max=255,
):
    """
    Flicker orgánico en tonos rosa pálido.
    Ideal para nacimiento / fluidos / carne / latido.
    """
    if not efecto_var.get():
        return

    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]

    for ip in activos:
        # ---- ROSA PÁLIDO ----
        h = random.uniform(330, 350)      # rosa / magenta suave
        s = random.uniform(0.25, 0.45)    # baja saturación (pálido)
        brillo = random.randint(brillo_min, brillo_max)

        send_lamp_color(ip, h, s, brillo)

    # ritmo tipo fuego pero más orgánico
    root.after(
        random.randint(140, 260),
        efecto_fuego_wiz,
        send_lamp_color,
        LAMP_IPS,
        panels,
        selected_devices,
        efecto_var,
        root,
        brillo_min,
        brillo_max
    )

def efecto_mar_wiz(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    efecto_var,
    root,
    _t=[0.0],
):
    """
    Azules/verdosos suaves tipo “Ocean”.
    """
    if not efecto_var.get():
        return

    t = _t[0]
    # movemos el tono entre 180° y 210°
    h = 195 + (15 * (random.random() * 2 - 1))  # un poco de variación
    s = 0.6
    brillo = 200

    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    for ip in activos:
        send_lamp_color(ip, h, s, brillo)

    _t[0] = t + 0.12
    root.after(250, efecto_mar_wiz,
               send_lamp_color, LAMP_IPS, panels, selected_devices,
               efecto_var, root, _t)


def efecto_arcoiris_wiz(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    efecto_var,
    root,
    _h=[0],
):
    """
    Recorre todo el círculo de color.
    """
    if not efecto_var.get():
        return

    h = _h[0]
    s = 1
    brillo = 220
    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    for ip in activos:
        send_lamp_color(ip, h, s, brillo)

    _h[0] = (h + 8) % 360
    root.after(180, efecto_arcoiris_wiz,
               send_lamp_color, LAMP_IPS, panels, selected_devices,
               efecto_var, root, _h)


def efecto_vela_wiz(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    efecto_var,
    root,
    brillo_base=120,
):
    """
    Vela cálida, pequeñas variaciones.
    """
    if not efecto_var.get():
        return

    h = 28   # cálido
    s = 1
    # variación pequeñita
    brillo = brillo_base + random.randint(-25, 40)
    brillo = max(40, min(200, brillo))

    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    for ip in activos:
        send_lamp_color(ip, h, s, brillo)

    root.after(random.randint(250, 600), efecto_vela_wiz,
               send_lamp_color, LAMP_IPS, panels, selected_devices,
               efecto_var, root, brillo_base)


def efecto_atardecer_wiz_(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    efecto_var,
    root,
    _i=[0],
):
    """
    Cicla por una pequeña paleta cálida, lento.
    """
    if not efecto_var.get():
        return

    paleta = [
        (50, 1, 240),
        (40, 1, 220),
        (35, 1, 210),   # amarillito
        (25, 1, 200),   # naranja
        (15, 1, 180),   # más rojizo
        (8,  1, 170),
        (4,  1, 120)
  
    ]
    i = _i[0]
    h, s, brillo = paleta[i]
    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    for ip in activos:
        send_lamp_color(ip, h, s, brillo)

    _i[0] = (i + 1) % len(paleta)
    root.after(4000, efecto_atardecer_wiz, #modificar el tiempo entre cambios 
               send_lamp_color, LAMP_IPS, panels, selected_devices,
               efecto_var, root, _i)


def efecto_desfasado_wiz(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    efecto_var,
    root,
    h=35,
    s=1,
):
    if not efecto_var.get():
        return

    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    for ip in activos:
        # cada una elige si prende o baja un poco
        if random.random() < 0.55:
            brillo = random.randint(150, 240)
        else:
            brillo = random.randint(30, 120)
        send_lamp_color(ip, h, s, brillo)

    # ritmo irregular global
    root.after(random.randint(140, 320),
               efecto_desfasado_wiz,
               send_lamp_color, LAMP_IPS, panels,
               selected_devices, efecto_var, root, h, s)
    
    
    
    
def efecto_latido_wiz(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    efecto_var,
    root,
    h=5,
    s=1,
    paso=40,
    fase=0,
):
    """
    Efecto "latido": dos pulsos rápidos y una pausa.
    """
    if not efecto_var.get():
        return

    # patrón: fuerte → medio → pausa
    if fase == 0:
        brillo = 240
        delay = 120
    elif fase == 1:
        brillo = 150
        delay = 180
    else:  # pausa
        brillo = 30
        delay = 350

    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    for ip in activos:
        send_lamp_color(ip, h, s, brillo)

    # siguiente fase
    fase = (fase + 1) % 3

    root.after(
        delay,
        efecto_latido_wiz,
        send_lamp_color,
        LAMP_IPS,
        panels,
        selected_devices,
        efecto_var,
        root,
        h,
        s,
        paso,
        fase,
    )








def  efecto_atardecer_wiz(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    efecto_var,
    root,
    _i=[0],
):
    """
    Atardecer azul ultra suave:
    Transición de azul claro a azul profundo y vuelta.
    240 pasos → 2 minutos totales.
    100% imperceptible.
    """

    if not efecto_var.get():
        return

    # =============================
    # CONFIGURACIÓN DE TRANSICIÓN
    # =============================
    pasos = 300                    # más pasos = más suave
    duracion_total_ms = 250_000    # 2 minutos
    delay = duracion_total_ms // pasos  # ~500 ms (0.5 segundos por paso)

    # Rango cromático azul (Hue)
    hue_min = 205   # azul claro
    hue_max = 250   # azul profundo

    # Brillo también se va degradando para simular profundidad
    brillo_min = 120
    brillo_max = 255

    # Crear lista dinámica de pasos suave ida y vuelta
    paleta = []

    # Subida azul claro → azul profundo
    for n in range(pasos // 2):
        t = n / (pasos // 2 - 1)
        h = int(hue_min + (hue_max - hue_min) * t)
        b = int(brillo_max - (brillo_max - brillo_min) * t)
        paleta.append((h, 1, b))

    # Bajada azul profundo → azul claro (espejo)
    paleta += list(reversed(paleta))

    # Obtener paso actual
    i = _i[0]
    h, s, brillo = paleta[i]

    # Aplicar a lámparas activas
    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    for ip in activos:
        send_lamp_color(ip, h, s, brillo)

    # Avanzar
    _i[0] = (i + 1) % len(paleta)

    # Repetir
    root.after(
        delay,
        efecto_atardecer_wiz,
        send_lamp_color, LAMP_IPS, panels, selected_devices,
        efecto_var, root, _i
    )


def efecto_intercambio_colores(
    send_lamp_color,
    LAMP_IPS,
    panels,
    selected_devices,
    lamp_status,
    efecto_var,
    root,
    color_a=(0, 1),        # rojo: h=0, s=1
    color_b=(220, 1),      # azul: h=220, s=1
    brillo=220,
    duracion_ms=8000,
    pasos=80,
):
    """
    Mitad de lámparas arranca en color A y mitad en color B.
    Gradualmente intercambian sus colores.
    """

    activos = [
        ip for ip in LAMP_IPS
        if selected_devices[ip].get() and lamp_status.get(ip, False)
    ]

    if len(activos) < 2:
        return

    mitad = len(activos) // 2
    grupo_a = activos[:mitad]
    grupo_b = activos[mitad:]

    h_a, s_a = color_a
    h_b, s_b = color_b

    intervalo = max(1, int(duracion_ms / pasos))

    def interpolar(v1, v2, t):
        return v1 + (v2 - v1) * t

    def paso(i):
        if not efecto_var.get():
            return

        t = i / pasos

        # grupo A: color A → color B
        h1 = interpolar(h_a, h_b, t)
        s1 = interpolar(s_a, s_b, t)

        # grupo B: color B → color A
        h2 = interpolar(h_b, h_a, t)
        s2 = interpolar(s_b, s_a, t)

        for ip in grupo_a:
            panels[ip].last_hue = h1
            panels[ip].last_sat = s1
            panels[ip].last_brillo = brillo
            panels[ip].last_mode = "colour"
            send_lamp_color(ip, h1, s1, brillo)

        for ip in grupo_b:
            panels[ip].last_hue = h2
            panels[ip].last_sat = s2
            panels[ip].last_brillo = brillo
            panels[ip].last_mode = "colour"
            send_lamp_color(ip, h2, s2, brillo)

        if i < pasos:
            root.after(intervalo, paso, i + 1)
        else:
            efecto_var.set(False)

    paso(0)
