import math

#oscar
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
            h = getattr(panels[ip], "last_hue", 0)
            s = getattr(panels[ip], "last_sat", 1)
            send_lamp_color(ip, h, s, brillo)
            panels[ip].last_brillo = brillo
        except Exception as e:
            print(f"[respiración] Error en {ip}: {e}")

    # programar siguiente paso sin saturación
    root.after(40, efecto_respiracion,
               send_lamp_color, LAMP_IPS, panels,
               selected_devices, lamp_status,
               brillo_min, brillo_max,
               vel_up, vel_down,
               respirando_var, root, fase)




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
    root
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
        h_on = getattr(panels[ip_on], "last_hue", 0)
        s_on = getattr(panels[ip_on], "last_sat", 1)

        # Apagar todos menos la activa
        for ip in activos:
            if ip != ip_on:
                apagar_lampara(ip)

        # Encender la lámpara actual
        send_lamp_color(ip_on, h_on, s_on, brillo_on)

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
        h = estado.get("h", 0)
        s = estado.get("s", 1)
        brillo_on = int(estado.get("brillo", 1))
        brillo_on = max(1, brillo_on)

        # actualizar UI local
        selected_devices[ip_on].set(True)
        panels[ip_on].last_mode = "colour"
        panels[ip_on].last_hue = h
        panels[ip_on].last_sat = s
        panels[ip_on].last_brillo = brillo_on

        threading.Thread(
            target=send_lamp_color,
            args=(ip_on, h, s, brillo_on),
            daemon=True
        ).start()

        # siguiente lámpara
        root.after(tiempo_on_ms, ciclo, idx + 1)

    ciclo(0)




#EFECTO SECUENCIA_OFF
import threading
from tablero.helpers_wiz import apagar_lampara

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
    pasos_fade
):
    """
    Apaga, una por una, las lámparas online, con una transición de brillo.
    Sin threads alrededor de pywizlight para evitar 'Event loop is closed'.
    """
    # lámparas online
    activos = [ip for ip in LAMP_IPS if lamp_status.get(ip, False)]
    if not activos:
        return

    # las apagamos al revés
    activos = list(reversed(activos))

    def ciclo(idx):
        if not secuencia_off_var.get():
            return

        if idx >= len(activos):
            return

        ip_off = activos[idx]

        # estado actual del panel
        brillo_inicial = getattr(panels[ip_off], "last_brillo", 255)
        h = getattr(panels[ip_off], "last_hue", 0)
        s = getattr(panels[ip_off], "last_sat", 1)

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
                return

            factor = 1 - (step / pasos_fade)
            brillo_actual = max(1, int(brillo_inicial * factor))

            # mandar color/brillo SIN thread
            send_lamp_color(ip_off, h, s, brillo_actual)
            panels[ip_off].last_brillo = brillo_actual

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
                    h = getattr(panels[ip], "last_hue", 0)
                    s = getattr(panels[ip], "last_sat", 1)
                    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, 1)
                    r, g, b = int(r * 255), int(g * 255), int(b * 255)
                    panels[ip].last_brillo = brillo_on
                    tasks_on.append(
                        luz.turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo_on))
                    )
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
                        h = getattr(panels[ip], "last_hue", 0)
                        s = getattr(panels[ip], "last_sat", 1)
                        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, 1)
                        r, g, b = int(r * 255), int(g * 255), int(b * 255)
                        panels[ip].last_brillo = brillo_off
                        tasks_off.append(
                            luz.turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo_off))
                        )
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
    off_ms           # tiempo apagada
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
            # PRENDER TODAS
            # primero leo colores de una
            colores = {
                ip: (
                    getattr(panels[ip], "last_hue", 0),
                    getattr(panels[ip], "last_sat", 1)
                )
                for ip in activos
            }
            for ip in activos:
                h, s = colores[ip]
                t = threading.Thread(
                    target=send_lamp_color,
                    args=(ip, h, s, brillo_on)
                )
                t.start()
                threads.append(t)
        else:
            # APAGAR / BAJAR TODAS
            for ip in activos:
                if brillo_off <= 0:
                    t = threading.Thread(target=send_off, args=(ip,))
                else:
                    h = getattr(panels[ip], "last_hue", 0)
                    s = getattr(panels[ip], "last_sat", 1)
                    t = threading.Thread(
                        target=send_lamp_color,
                        args=(ip, h, s, brillo_off)
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


