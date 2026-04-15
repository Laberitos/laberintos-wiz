import rtmidi
import tkinter as tk
from tkinter import messagebox
import json
import colorsys
import asyncio
import os
import subprocess
from pywizlight import wizlight, PilotBuilder
from tablero.real_colorwheel import RealColorWheel
from tablero.config import LAMP_IPS  # Lista de IPs
import time
import threading
import uuid
import screeninfo
from tablero.midi_listener import (
    start_midi_thread,
    inicializar_leds,
    midi_led,
    led_activo,
    led_inactivo,
)

bulb_states = {}
midi_out = None

# ============================================================
# SISTEMA ROBUSTO DE DETECCIÓN ONLINE/OFFLINE PARA LÁMPARAS WIZ
# ============================================================

# Historial para filtrar falsos offline (histeresis)
estado_historial = {}  # ip -> [True, False, True]


def _actualizar_historial(ip, estado):
    """
    Agrega una lectura al historial y devuelve el estado filtrado.
    Solo cambia si al menos 2 de las últimas 3 lecturas concuerdan.
    """
    lst = estado_historial.get(ip, [])
    lst.append(estado)

    if len(lst) > 3:
        lst.pop(0)

    estado_historial[ip] = lst

    # mayorías de 3 lecturas
    if lst.count(True) >= 2:
        return True
    if lst.count(False) >= 2:
        return False

    # si hay empate → devolver última lectura
    return estado




lamp_state = {}
escena_en_ejecucion = False
ultima_idx_escena = None   # índice de la escena ejecutada con ENTER

# ===== CONTROLADORES WIZ PERSISTENTES =====
WIZ = {}

def get_wiz(ip):
    if ip not in WIZ:
        WIZ[ip] = wizlight(ip)
    return WIZ[ip]


fade_token = [None]
semaforo_fades = asyncio.Semaphore(10)  # Solo 5 fades simultáneos, puedes ajustar el número



root = tk.Tk()
root.title("🎛️ Control de Luces Proyecto Laberintos 2025 © Pallakí")
root.configure(bg="#181b1e")

def ajustar_a_pantalla(root):
    from screeninfo import get_monitors
    monitor = get_monitors()[0]
    ancho = min(1580, monitor.width - 40)
    alto = min(950, monitor.height - 60)
    root.geometry(f"{ancho}x{alto}")

# Al inicio:
ajustar_a_pantalla(root)

# Haz que la ventana sea del tamaño de la pantalla
try:
    root.state('zoomed')
except:
    root.attributes('-zoomed', True)

selected_devices = {ip: tk.BooleanVar(value=False) for ip in LAMP_IPS}
panels = {}



# ---------------------------------------------------------
# SISTEMA DE EJECUCIÓN ASÍNCRONA ÚNICO Y ESTABLE
# ---------------------------------------------------------
import asyncio
import threading

_asyncio_loop = None
_asyncio_thread = None

# ======================================================
# INICIALIZACIÓN DEL EVENT LOOP GLOBAL (AL ARRANCAR)
# ======================================================
_asyncio_loop = asyncio.new_event_loop()

def _asyncio_loop_runner():
    asyncio.set_event_loop(_asyncio_loop)
    _asyncio_loop.run_forever()

_asyncio_thread = threading.Thread(
    target=_asyncio_loop_runner,
    daemon=True
)
_asyncio_thread.start()




def ejecutar_asyncio(coro):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
    except Exception as e:
        print("[ERROR asyncio]", e)
    finally:
        try:
            loop.close()
        except:
            pass


# ======================================================
# EVENT LOOP ÚNICO Y GLOBAL — *EL LOOP OFICIAL*
# ======================================================
def get_or_create_event_loop():
    global _asyncio_loop
    return _asyncio_loop



from pywizlight import wizlight


async def _get_lamp_info_async(ip: str):
    try:
        bulb = get_wiz(ip)
        pilot = await bulb.updateState()    # <-- YA NO DEVUELVE get_pilot()

        if pilot is None:
            return None

        return {
            "brightness": getattr(pilot, "dimming", 0),
            "mode": getattr(pilot, "colormode", "white"),
            "hue": getattr(pilot, "hue", 0),
            "sat": getattr(pilot, "sat", 0),
            "temp": getattr(pilot, "ct", 4000)
        }

    except Exception as e:
        print(f"[ERROR] get_lamp_info({ip}): {e}")
        return None


def get_lamp_info(ip: str):
    """Wrapper sync seguro para Tkinter"""
    async def _do():
        return await _get_lamp_info_async(ip)

    loop = get_or_create_event_loop()
    try:
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_do(), loop)
            return future.result(timeout=2)
        else:
            return loop.run_until_complete(_do())
    except Exception as e:
        print(f"[ERROR] get_lamp_info({ip}): {e}")
        return None




# -- Estado de lámparas online/offline + ESTADO REAL --
lamp_status = {}
lamp_state = {}

def refresh_lamp_status():
    """
    REFRESCO ROBUSTO:
    - Solo cambia estado UI si la lámpara cambió realmente entre online/offline.
    - Usa histeresis (3 lecturas) para evitar falsos "offline".
    - Actualiza información real (hue, sat, temp, brillo) SOLO si está online.
    """

    # 1) obtener lecturas reales
    online_raw = get_online_ips()

    for ip, panel in panels.items():

        # Estado leído del sistema
        ahora_online = ip in online_raw

        # Aplicar filtro anti-falsos-offline
        ahora_filtrado = _actualizar_historial(ip, ahora_online)

        # Estado anterior
        before = lamp_status.get(ip, None)

        # Si NO hubo cambio → NO tocar UI, NO refrescar.
        if before is not None and before == ahora_filtrado:
            continue

        # Actualizar estado
        lamp_status[ip] = ahora_filtrado

        # ---------------------------------------
        # UI: LÁMPARA ONLINE (verde)
        # ---------------------------------------
        if ahora_filtrado:
            panel.config(bg="#172d1f")  # verde
            try:
                info = get_lamp_info(ip)
            except:
                info = None

            if info:
                lamp_state[ip] = {
                    "brightness": info.get("brightness", 0),
                    "mode": info.get("mode", "colour"),
                    "hue": info.get("hue", 0),
                    "sat": info.get("sat", 1),
                    "temp": info.get("temp", 4000)
                }

            # borde verde
            panel.config(
                highlightbackground="#03A125",
                highlightcolor="#03A125"
            )

        # ---------------------------------------
        # UI: LÁMPARA OFFLINE (rojo)
        # ---------------------------------------
        else:
            panel.config(bg="#321c1c")   # rojo apagado
            lamp_state[ip] = {
                "brightness": 0,
                "mode": "colour",
                "hue": 0,
                "sat": 1,
                "temp": 4000
            }
            panel.config(
                highlightbackground="#252e36",
                highlightcolor="#252e36"
            )



#__________Evnvio de color a las lamparas___________________

def send_color_to_lamps(ips, h, s, brillo):
    brillo = safe_brightness(brillo)

    if brillo == 0:
        return

    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, 1)
    r, g, b = int(r*255), int(g*255), int(b*255)

    loop = get_or_create_event_loop()

    for ip in ips:
        bulb = get_wiz(ip)
        pilot = PilotBuilder(rgb=(r, g, b), brightness=brillo)

        try:
            asyncio.run_coroutine_threadsafe(bulb.turn_on(pilot), loop)
        except Exception as e:
            print(f"[WARN] No se pudo enviar color a {ip}: {e}")

            
            
def send_white_to_lamps(ips, brillo, temp):
    brillo = safe_brightness(brillo)
    if brillo == 0:
        return

    loop = get_or_create_event_loop()

    for ip in ips:
        bulb = get_wiz(ip)
        pilot = PilotBuilder(brightness=brillo, colortemp=temp)

        try:
            asyncio.run_coroutine_threadsafe(bulb.turn_on(pilot), loop)
        except Exception as e:
            print(f"[WARN] No se pudo enviar blanco a {ip}: {e}")

            


def map_slider_to_wiz_temp(value):
    """
    Convierte el valor del slider (0–100) a la temperatura en Kelvin (2200–6255 K)
    que entiende la bombilla Wiz.
    """
    try:
        value = float(value)
    except Exception:
        value = 50.0
    # 0 → 2200 K, 100 → 6500 K
    return int(2200 + (value / 100.0) * (6500 - 2200))


def send_lamp_white(ip, brillo_slider, temp_slider):
    if not lamp_status.get(ip, True):
        return

    brillo = map_slider_to_wiz_brightness(brillo_slider)
    temp = map_slider_to_wiz_temp(temp_slider)

    # brillo mínimo seguro
    brillo = max(8, min(255, int(brillo)))

    async def _do():
        try:
            pilot = PilotBuilder(
                brightness=int(brillo),
                colortemp=int(temp)
            )
            await get_wiz(ip).turn_on(pilot)
        except Exception as e:
            print(f"[send_lamp_white] error {ip}: {e}")

    loop = get_or_create_event_loop()
    if loop.is_running():
        asyncio.ensure_future(_do(), loop=loop)
    else:
        loop.run_until_complete(_do())
        

import asyncio
from pywizlight.exceptions import WizLightConnectionError

def get_or_create_event_loop():
    global _asyncio_loop
    return _asyncio_loop


def send_off(ip):
    if not lamp_status.get(ip, True):
        return

    async def _do():
        try:
            await get_wiz(ip).turn_off()
        except Exception:
            pass

    loop = get_or_create_event_loop()
    asyncio.run_coroutine_threadsafe(_do(), loop)


def update_name(ip, entry):
    lamp_names[ip] = entry.get()
    save_lamp_names(lamp_names)


def safe_brightness(val):
    try:
        return max(0, min(255, int(val)))
    except:
        return 0


def map_slider_to_wiz_brightness(slider_value):
    val = round(10 + (int(slider_value) - 1) * (255 - 10) / (255 - 1))
    return safe_brightness(val)

def map_slider_to_wiz_temperature(slider_value):
    # Slider a la izquierda = cálido, derecha = frío (más intuitivo)
    return int(2200 + ((int(slider_value)) * (6500 - 2200) / 255))

# === Estado de conexión de las lámparas ===
def ip_online(ip):
    try:
        result = subprocess.run(["ping", "-n", "1", "-w", "100", ip], capture_output=True)
        return result.returncode == 0
    except Exception:
        return False

async def _check_online_async(ip):
    """
    Usa directamente updateState() de pywizlight.
    Si responde → está online. Si no → offline real.
    """
    try:
        bulb = get_wiz(ip)
        await bulb.updateState()
        return True
    except:
        return False


def get_online_ips():
    """
    Llama a updateState() desde el loop global para TODAS las lámparas.
    Retorna SOLO aquellas que respondieron correctamente.
    """
    loop = get_or_create_event_loop()
    futures = [
        asyncio.run_coroutine_threadsafe(_check_online_async(ip), loop)
        for ip in LAMP_IPS
    ]

    online = []
    for ip, fut in zip(LAMP_IPS, futures):
        try:
            if fut.result(timeout=1.2):
                online.append(ip)
        except:
            pass
    return online


NAMES_FILE = "lamp_names.json"
def load_lamp_names():
    try:
        with open(NAMES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {ip: f"Lámpara {i+1}" for i, ip in enumerate(LAMP_IPS)}

def save_lamp_names(names):
    with open(NAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=2)

lamp_names = load_lamp_names()


# 0 ------ FRAME PRINCIPAL
frame_main = tk.Frame(root, bg="#181b1e")
frame_main.pack(fill="both", expand=False)

# ----- 1. FRAME IZQUIERDO (vertical, maestro + efectos) -----
frame_left = tk.Frame(frame_main, bg="#181b1e")
frame_left.pack(side="left", fill="y", padx=(15, 8), pady=15)


# ---- CONTROL MAESTRO ----
frame_maestro = tk.LabelFrame(
    frame_left, text="Control Maestro", bg="#181b1e", fg="#20bdec",
    font=("Segoe UI", 16, "bold"), padx=5, pady=5, width=200, height=350
)
frame_maestro.pack(side="top", fill="x", expand=False, pady=(0, 16))

# ---- PANEL DE EFECTOS ----
frame_efectos = tk.LabelFrame(
    frame_left, text="Efectos", bg="#232b32", fg="#20bdec",
    font=("Segoe UI", 15, "bold"), padx=14, pady=14, width=200, height=700
)
frame_efectos.pack(side="top", fill="x", expand=False)
frame_efectos.pack_propagate(False)

# --- CONTROLES DE EFECTOS DENTRO DE frame_efectos ---

tk.Label(
    frame_efectos, text="Respiración",
    bg="#232b32", fg="#20bdec", font=("Segoe UI", 14, "bold")
).pack(pady=(0, 8))


#_______________________FUNCIONES SEGURAS_______________________________

from pywizlight.exceptions import WizLightConnectionError, WizLightTimeOutError

async def _send_color_async(ip, h, s, b):
    """
    Enviar color en modo RGB (compatible con tu versión de pywizlight).
    Evita fallback rojo y garantiza el color correcto en los fades.
    """
    try:
        # HSV → RGB (valor basado en brillo)
        # v = 1 porque el brillo lo controla el piloto
        r, g_val, b_val = colorsys.hsv_to_rgb(h / 360.0, s, 1)

        r = int(r * 255)
        g_val = int(g_val * 255)
        b_val = int(b_val * 255)

        # brillo mínimo seguro (Wiz hace fallback rojo < 8)
        brillo = max(8, min(255, int(b)))

        light = get_wiz(ip)
        pilot = PilotBuilder(
            rgb=(r, g_val, b_val),
            brightness=brillo
        )

        await light.turn_on(pilot)

    except Exception as e:
        print(f"[send_color_async] Error en {ip}: {e}")



def send_lamp_color_safe(ip, h, s, b):

    if not lamp_status.get(ip, False):
        return

    loop = get_or_create_event_loop()

    try:
        asyncio.run_coroutine_threadsafe(
            _send_color_async(ip, h, s, b),
            loop
        )
            # *** REGISTRAR EL ESTADO ***
        bulb_states[ip] = (h, s, b)    
        
    except Exception as e:
        print(f"[send_lamp_color_safe] Error en {ip}: {e}")




def send_off_safe(ip):
    try:
        send_off(ip)
    except (WizLightConnectionError, WizLightTimeOutError, OSError) as e:
        # print(f"[WARN] off {ip}: {e}")
        pass

########################################################################
# --- CONTROLES DE EFECTOS DENTRO DE frame_efectos ---
########################################################################
# GUI
import tkinter as tk
from tkinter import ttk

# tus acciones
from acciones.acciones import (
    efecto_respiracion,
    efecto_secuencia,
    secuencia_on,
    secuencia_off,
    parpadeo,
    efecto_estrobo,
    estrobo_udp,
    # los que agregamos nuevos:
    efecto_fuego_wiz,
    efecto_mar_wiz,
    efecto_arcoiris_wiz,
    efecto_vela_wiz,
    efecto_atardecer_wiz,
    efecto_desfasado_wiz,
    efecto_latido_wiz,
)

# ======================================================================
#                      PANEL DE EFECTOS (AGRUPADO)
# ======================================================================

def make_section(parent, title):
    frame = tk.LabelFrame(
        parent,
        text=title,
        bg="#232b32",
        fg="#20bdec",
        font=("Segoe UI", 12, "bold"),
        bd=0,
        padx=4,
        pady=4
    )
    frame.pack(fill="x", pady=(0, 6))
    # 2 columnas
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_columnconfigure(1, weight=1)
    return frame

# secciones
frame_suaves     = make_section(frame_efectos, "Suaves / Ambiente")
frame_secuencias = make_section(frame_efectos, "Secuencias")
frame_fx         = make_section(frame_efectos, "FX / Rápidos")
frame_tecnicos   = make_section(frame_efectos, "Técnicos / UDP")
frame_wiz        = make_section(frame_efectos, "Estilos Wiz")


# ======================== SUAVES / AMBIENTE ==========================
respirando = tk.BooleanVar(value=False)

def toggle_respiracion():
    if respirando.get():
        btn_respiracion.config(text="Detener", bg="#ef5350")
        efecto_respiracion(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,   # ← PASAMOS lamp_status
            1,    # brillo_min
            255,  # brillo_max
            0.1,  # vel subida
            0.1,  # vel bajada
            respirando,
            root
        )
    else:
        btn_respiracion.config(text="Respiración", bg="#20bdec")
        marcar_escena_terminada()


btn_respiracion = tk.Checkbutton(
    frame_suaves,
    text="Respiración",
    variable=respirando,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_respiracion
)
btn_respiracion.grid(row=0, column=0, padx=2, pady=2, sticky="ew")


# =========================== SECUENCIAS ==============================
secuencia_var = tk.BooleanVar(value=False)

def toggle_secuencia():
    if secuencia_var.get():
        btn_secuencia.config(text="Detener", bg="#ef5350")
        efecto_secuencia(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            1000,   # ms
            255,
            secuencia_var,
            root
        )
    else:
        btn_secuencia.config(text="Secuencia", bg="#20bdec")

btn_secuencia = tk.Checkbutton(
    frame_secuencias,
    text="Secuencia",
    variable=secuencia_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_secuencia
)
btn_secuencia.grid(row=0, column=0, padx=3, pady=3, sticky="ew")


secuencia_on_var = tk.BooleanVar(value=False)


def toggle_secuencia_on():
    if secuencia_on_var.get():
        btn_secuencia_on.config(text="Detener", bg="#ef5350")

        # cargar escena seleccionada
        escena = escena_seleccionada_en_listbox()
        escenas = load_escenas()
        datos = escenas["datos"].get(escena, {})

        # preparar dict destino
        valores_destino = {}
        for ip in LAMP_IPS:
            if ip in datos:
                estado = datos[ip]
                valores_destino[ip] = {
                        "h": estado.get("h", 0),
                        "s": estado.get("s", 1),
                        "brillo": estado.get("brillo", 1)
                    }

        # llamar a la secuencia usando valores reales de la escena
        secuencia_on(
            send_lamp_color=send_lamp_color_safe,
            LAMP_IPS=LAMP_IPS,
            panels=panels,
            selected_devices=selected_devices,
            lamp_status=lamp_status,
            valores_destino=valores_destino,
            tiempo_on_ms=4000,
            secuencia_var=secuencia_on_var,
            root=root,
            nombre_escena=escena,
            btn_secuencia_on=btn_secuencia_on,   # ← AÑADIR ESTA LÍNEA
            on_finish_cb=escena_finalizada_callback    # ← NUEVO
        )


    else:
        btn_secuencia_on.config(text="Secuencia_ON", bg="#20bdec")


btn_secuencia_on = tk.Checkbutton(
    frame_secuencias,
    text="Secuencia_ON",
    variable=secuencia_on_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_secuencia_on
)
btn_secuencia_on.grid(row=0, column=1, padx=3, pady=3, sticky="ew")


secuencia_off_var = tk.BooleanVar(value=False)

def toggle_secuencia_off():
    if secuencia_off_var.get():
        btn_secuencia_off.config(text="Detener", bg="#ef5350")
        secuencia_off(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            20000,               # tiempo entre apagados
            secuencia_off_var,
            root,
            fade_ms=20000,
            pasos_fade=20
        )
    else:
        btn_secuencia_off.config(text="Secuencia_OFF", bg="#20bdec")

btn_secuencia_off = tk.Checkbutton(
    frame_secuencias,
    text="Secuencia_OFF",
    variable=secuencia_off_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_secuencia_off
)
# segunda fila
btn_secuencia_off.grid(row=1, column=0, padx=3, pady=3, sticky="ew")


# =========================== FX / RÁPIDOS ============================
parpadeo_var = tk.BooleanVar(value=False)

def toggle_parpadeo():
    if parpadeo_var.get():
        btn_parpadeo.config(text="Detener", bg="#ef5350")
        parpadeo(
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            parpadeo_var,
            brillo_on=230,
            brillo_off=0,
            tiempo_on_ms=20,
            tiempo_off_ms=20,
            
        )
    else:
        btn_parpadeo.config(text="Parpadeo", bg="#20bdec")

btn_parpadeo = tk.Checkbutton(
    frame_fx,
    text="Parpadeo",
    variable=parpadeo_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_parpadeo
)
btn_parpadeo.grid(row=0, column=0, padx=3, pady=3, sticky="ew")


estrobo_var = tk.BooleanVar(value=False)

def toggle_estrobo():
    if estrobo_var.get():
        btn_estrobo.config(text="Detener", bg="#ef5350")
        efecto_estrobo(
            send_lamp_color_safe,
            send_off,
            LAMP_IPS,
            panels,
            selected_devices,
            estrobo_var,
            root,
            brillo_on=255,
            brillo_off=0,
            on_ms=70,
            off_ms=70
            
        )
    else:
        btn_estrobo.config(text="Estrobo", bg="#20bdec")

btn_estrobo = tk.Checkbutton(
    frame_fx,
    text="Estrobo",
    variable=estrobo_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_estrobo
)
btn_estrobo.grid(row=0, column=1, padx=3, pady=3, sticky="ew")


# ========================== TÉCNICOS / UDP ===========================
estrobo_udp_var = tk.BooleanVar(value=False)

def toggle_estrobo_udp():
    if estrobo_udp_var.get():
        estrobo_udp(
            LAMP_IPS,
            selected_devices,
            lamp_status,
            estrobo_udp_var,
            root,
            on_ms=50,
            off_ms=50,
            solo_seleccionadas=False
        )
    else:
        # al poner False, la función deja de re-ejecutarse
        pass

chk_estrobo_udp = tk.Checkbutton(
    frame_tecnicos,
    text="Estrobo (UDP rápido)",
    variable=estrobo_udp_var,
    font=("Segoe UI", 11, "bold"),
    bg="#232b32", fg="#fff", selectcolor="#232b32",
    command=toggle_estrobo_udp,
    anchor="w"
)
chk_estrobo_udp.grid(row=0, column=0, columnspan=2, sticky="w", pady=3)


# ============================ WIZ STYLE ==============================
fuego_var = tk.BooleanVar(value=False)

def toggle_fuego():
    if fuego_var.get():
        btn_fuego.config(text="Detener", bg="#ef5350")
        efecto_fuego_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            fuego_var,
            root
        )
    else:
        btn_fuego.config(text="Fuego", bg="#20bdec")

btn_fuego = tk.Checkbutton(
    frame_wiz,
    text="Fuego",
    variable=fuego_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_fuego
)
btn_fuego.grid(row=0, column=0, padx=3, pady=3, sticky="ew")


mar_var = tk.BooleanVar(value=False)

def toggle_mar():
    if mar_var.get():
        btn_mar.config(text="Detener", bg="#ef5350")
        efecto_mar_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            mar_var,
            root
        )
    else:
        btn_mar.config(text="Mar / Oceánico", bg="#20bdec")

btn_mar = tk.Checkbutton(
    frame_wiz,
    text="Mar / Oceánico",
    variable=mar_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_mar
)
btn_mar.grid(row=0, column=1, padx=3, pady=3, sticky="ew")


arcoiris_var = tk.BooleanVar(value=False)

def toggle_arcoiris():
    if arcoiris_var.get():
        btn_arcoiris.config(text="Detener", bg="#ef5350")
        efecto_arcoiris_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            arcoiris_var,
            root
        )
    else:
        btn_arcoiris.config(text="Arcoíris", bg="#20bdec")

btn_arcoiris = tk.Checkbutton(
    frame_wiz,
    text="Arcoíris",
    variable=arcoiris_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_arcoiris
)
btn_arcoiris.grid(row=1, column=0, padx=3, pady=3, sticky="ew")


vela_var = tk.BooleanVar(value=False)

def toggle_vela():
    if vela_var.get():
        btn_vela.config(text="Detener", bg="#ef5350")
        efecto_vela_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            vela_var,
            root
        )
    else:
        btn_vela.config(text="Vela", bg="#20bdec")

btn_vela = tk.Checkbutton(
    frame_wiz,
    text="Vela",
    variable=vela_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_vela
)
btn_vela.grid(row=1, column=1, padx=3, pady=3, sticky="ew")


atardecer_var = tk.BooleanVar(value=False)

def toggle_atardecer():
    if atardecer_var.get():
        btn_atardecer.config(text="Detener", bg="#ef5350")
        efecto_atardecer_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            atardecer_var,
            root
        )
    else:
        btn_atardecer.config(text="Atardecer", bg="#20bdec")

btn_atardecer = tk.Checkbutton(
    frame_wiz,
    text="Atardecer",
    variable=atardecer_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_atardecer
)
# tercera fila para que no quede tan apretado
btn_atardecer.grid(row=2, column=0, padx=3, pady=3, sticky="ew")

desfase_var = tk.BooleanVar(value=False)

def toggle_desfase():
    if desfase_var.get():
        btn_desfase.config(text="Detener", bg="#ef5350")
        efecto_desfasado_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            desfase_var,
            root
        )
    else:
        btn_desfase.config(text="Desfase", bg="#20bdec")

btn_desfase = tk.Checkbutton(
    frame_wiz,
    text="Desfase",
    variable=desfase_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_desfase
)
btn_desfase.grid(row=2, column=1, padx=3, pady=3, sticky="ew")


latido_var = tk.BooleanVar(value=False)

def toggle_latido():
    if latido_var.get():
        btn_latido.config(text="Detener", bg="#ef5350")
        efecto_latido_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            latido_var,
            root
        )
    else:
        btn_latido.config(text="Latido", bg="#20bdec")

btn_latido = tk.Checkbutton(
    frame_wiz,
    text="Latido",
    variable=latido_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_latido
)
btn_latido.grid(row=3, column=0, padx=3, pady=3, sticky="ew")

#################_DEFINICIONES DE EFECTOS_##############################

effect_vars = {
    "respiracion": respirando,
    "secuencia": secuencia_var,
    "secuencia_on": secuencia_on_var,
    "secuencia_off": secuencia_off_var,
    "parpadeo": parpadeo_var,
    "estrobo": estrobo_var,
    "estrobo_udp": estrobo_udp_var,
    "fuego": fuego_var,
    "mar": mar_var,
    "arcoiris": arcoiris_var,
    "vela": vela_var,
    "atardecer": atardecer_var,
    "desfase": desfase_var,
    "latido": latido_var,
}

effect_toggles = {
    "respiracion": toggle_respiracion,
    "secuencia": toggle_secuencia,
    "secuencia_on": toggle_secuencia_on,
    "secuencia_off": toggle_secuencia_off,
    "parpadeo": toggle_parpadeo,
    "estrobo": toggle_estrobo,
    "estrobo_udp": toggle_estrobo_udp,
    "fuego": toggle_fuego,
    "mar": toggle_mar,
    "arcoiris": toggle_arcoiris,
    "vela": toggle_vela,
    "atardecer": toggle_atardecer,
    "desfase": toggle_desfase,
    "latido": toggle_latido,
}


#__________________________________________________FIN EFECTOS_____________________________________


maestro_hsv = {"h": 0, "s": 1}
maestro_brillo = tk.IntVar(value=1)
maestro_temp = tk.IntVar(value=1)
maestro_mode = tk.StringVar(value="colour")

def maestro_on_color(h, s, v):
    maestro_hsv["h"] = h
    maestro_hsv["s"] = s
    if maestro_mode.get() == "colour":
        h = maestro_hsv["h"]
        s = maestro_hsv["s"]
        brillo = maestro_brillo.get()
        selected_ips = [ip for ip in LAMP_IPS if selected_devices[ip].get() and lamp_status.get(ip, True)]

        # Actualizar UI
        for ip in selected_ips:
            panels[ip].mode_var.set("colour")
            panels[ip].last_mode = "colour"
            panels[ip].last_hue = h
            panels[ip].last_sat = s
            panels[ip].last_brillo = brillo

        if selected_ips:
            try:
                # ejecutar en loop global sin usar async
                loop = get_or_create_event_loop()
                loop.call_soon_threadsafe(
                    send_color_to_lamps,
                    selected_ips, h, s, brillo
                )

            except Exception as e:
                print(f"[WARN] Maestro color: {e}")


def maestro_on_temp(value):
    if maestro_mode.get() == "white":
        brillo = maestro_brillo.get()
        temp = maestro_temp.get()
        selected_ips = [ip for ip in LAMP_IPS if selected_devices[ip].get() and lamp_status.get(ip, True)]

        for ip in selected_ips:
            panels[ip].mode_var.set("white")
            panels[ip].last_mode = "white"
            panels[ip].last_brillo = brillo
            panels[ip].last_temp = temp

        if selected_ips:
            try:
                loop = get_or_create_event_loop()
                coro = send_white_to_lamps(selected_ips, brillo, map_slider_to_wiz_temperature(temp))
                if loop.is_running():
                    asyncio.ensure_future(coro, loop=loop)
                else:
                    loop.run_until_complete(coro)
            except Exception as e:
                print(f"[WARN] Maestro blanco: {e}")

                
def maestro_on_brillo(value):
    import asyncio

    # Tkinter la manda como string → la pasamos a int
    brillo = int(float(value))

    modo = maestro_mode.get()
    h = maestro_hsv["h"]
    s = maestro_hsv["s"]
    temp = maestro_temp.get()

    # lámparas que realmente queremos tocar
    selected_ips = [
        ip for ip in LAMP_IPS
        if selected_devices[ip].get() and lamp_status.get(ip, True)
    ]

    # si el brillo es 0 → apagamos y listo
    if brillo == 0:
        for ip in selected_ips:
            try:
                # usá send_off_safe si la tenés
                send_off(ip)
                panels[ip].last_brillo = 0
                panels[ip].last_mode = modo
            except Exception as e:
                print(f"[WARN] Maestro brillo (off) {ip}: {e}")
        return

    # si el brillo > 0 → actualizamos panel y mandamos como antes
    for ip in selected_ips:
        panels[ip].last_brillo = brillo
        panels[ip].mode_var.set(modo)
        panels[ip].last_mode = modo

    if selected_ips:
        try:
            loop = get_or_create_event_loop()

            # Ejecutar de forma segura en el loop global (funciones NO async)
            if modo == "colour":
                loop.call_soon_threadsafe(
                    send_color_to_lamps,
                    selected_ips, h, s, brillo
                )
            else:
                loop.call_soon_threadsafe(
                    send_white_to_lamps,
                    selected_ips, brillo, temp
                )

        except Exception as e:
            print(f"[WARN] Maestro brillo: {e}")



def aplicar_maestro():
    modo = maestro_mode.get()
    h = maestro_hsv["h"]
    s = maestro_hsv["s"]
    brillo = maestro_brillo.get()
    temp = maestro_temp.get()
    selected_ips = [ip for ip in LAMP_IPS if selected_devices[ip].get() and lamp_status.get(ip, True)]

    # Actualizar UI
    for ip in selected_ips:
        panels[ip].mode_var.set(modo)
        panels[ip].last_mode = modo
        if modo == "colour":
            panels[ip].last_hue = h
            panels[ip].last_sat = s
            panels[ip].last_brillo = brillo
        else:
            panels[ip].last_brillo = brillo
            panels[ip].last_temp = temp

    if selected_ips:
        try:
            loop = get_or_create_event_loop()
            if modo == "colour":
                coro = send_color_to_lamps(selected_ips, h, s, brillo)
            else:
                coro = send_white_to_lamps(selected_ips, brillo, temp)

            if loop.is_running():
                asyncio.ensure_future(coro, loop=loop)
            else:
                loop.run_until_complete(coro)
        except Exception as e:
            print(f"[WARN] Maestro aplicar: {e}")


colorwheel_maestro = RealColorWheel(frame_maestro, radius=90, callback=maestro_on_color, bg="#181b1e", bd=0, highlightthickness=0)
colorwheel_maestro.pack(side="left", padx=16)

controls_maestro = tk.Frame(frame_maestro, bg="#181b1e")
controls_maestro.pack(side="left", padx=18)

tk.Label(controls_maestro, text="Brillo", bg="#181b1e", fg="#fff").pack()
tk.Scale(controls_maestro, from_=0, to=255, orient="horizontal", variable=maestro_brillo,
         length=260, bg="#181b1e", fg="#20bdec", command=maestro_on_brillo).pack()

tk.Label(controls_maestro, text="Temp (Blanco cálido–frío)", bg="#181b1e", fg="#f1c40f").pack()
tk.Scale(controls_maestro, from_=0, to=255, orient="horizontal", variable=maestro_temp,
         length=240, bg="#181b1e", fg="#f1c40f",
         command=lambda v: maestro_on_temp(v)).pack()

# --- Subframe horizontal para los Radiobuttons ---
frame_modos_maestro = tk.Frame(controls_maestro, bg="#181b1e")
frame_modos_maestro.pack(pady=(8, 4))

tk.Radiobutton(
    frame_modos_maestro, text="Color",
    variable=maestro_mode, value="colour",
    bg="#181b1e", fg="#20bdec", selectcolor="#181b1e",
    font=("Segoe UI", 12, "bold")
).pack(side="left", padx=6)

tk.Radiobutton(
    frame_modos_maestro, text="Blanco",
    variable=maestro_mode, value="white",
    bg="#181b1e", fg="#f1c40f", selectcolor="#181b1e",
    font=("Segoe UI", 12, "bold")
).pack(side="left", padx=6)

tk.Button(controls_maestro, text="Aplicar Maestro",
    command=aplicar_maestro,
    font=("Segoe UI", 13, "bold"), fg="#fff", bg="#20bdec", relief="raised", width=18
).pack(pady=8)

tk.Button(controls_maestro, text="Refrescar Estado Lámparas", command=refresh_lamp_status,
    font=("Segoe UI", 10), fg="#fff", bg="#27ae60", relief="raised", width=22
).pack(pady=6)


# --- Botones de apagar/encender todo ---
frame_bottom = tk.Frame(frame_left, bg="#181b1e")
frame_bottom.pack(fill="x", pady=18)

def apagar_todo():
    ips = [ip for ip in LAMP_IPS if lamp_status.get(ip, True)]
    async def apagar_lamps():
        tasks = [get_wiz(ip).turn_off() for ip in ips]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for ip, result in zip(ips, results):
            if isinstance(result, Exception):
                print(f"[WARN] No se pudo apagar la lámpara {ip}: {result}")
    for ip in LAMP_IPS:
        selected_devices[ip].set(False)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(apagar_lamps())
        else:
            loop.run_until_complete(apagar_lamps())
    except Exception as e:
        print(f"[WARN] Apagar todo: {e}")


############################## BOTONES ENCENDER Y APAGAR ##########################################

def encender_todo():
    modo = maestro_mode.get()
    h = maestro_hsv["h"]
    s = maestro_hsv["s"]
    brillo = maestro_brillo.get()
    temp = maestro_temp.get()

    # lámparas online
    ips = [ip for ip in LAMP_IPS if lamp_status.get(ip, True)]

    # marcar todo como seleccionado
    for ip in LAMP_IPS:
        selected_devices[ip].set(True)
        panel = panels[ip]

        if modo == "colour":
            panel.last_mode = "colour"
            panel.last_hue = h
            panel.last_sat = s
            panel.last_brillo = brillo
        else:
            panel.last_mode = "white"
            panel.last_brillo = brillo
            panel.last_temp = temp

    # función normal (NO async)
    def encender_lamps():
        if modo == "colour":
            send_color_to_lamps(ips, h, s, brillo)
        else:
            send_white_to_lamps(ips, brillo, temp)

    # Ejecutarlo en el loop global
    try:
        loop = get_or_create_event_loop()
        loop.call_soon_threadsafe(encender_lamps)
    except Exception as e:
        print(f"[WARN] Encender todo: {e}")

        

tk.Button(frame_maestro, text="On ⏼", command=encender_todo,
          bg="#20bdec", fg="#fff", font=("Segoe UI", 10, "bold")).pack(side="top", padx=13)
tk.Button(frame_maestro, text="Off ⏻", command=apagar_todo,
          bg="#807D7D", fg="#fff", font=("Segoe UI", 10, "bold")).pack(side="top", padx=13)     


#_____________________________________CIERRE MAESTRO Y EFECTOS__________________________________________________________________________________________

# ----- 2. FRAME CENTRAL (lámparas) -------------------------------------------------------------------------------
frame_center = tk.Frame(frame_main, bg="#181b1e")
frame_center.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=15)


# --------------------------------------
# NUEVO: CONTENEDOR SCROLLEABLE
# --------------------------------------
# Canvas que contendrá los paneles de lámparas
canvas_lamps = tk.Canvas(
    frame_center,
    bg="#181b1e",
    highlightthickness=0,
    bd=0
)
canvas_lamps.pack(side="left", fill="both", expand=True)

# Scrollbar vertical
scroll_lamps = tk.Scrollbar(
    frame_center,
    orient="vertical",
    command=canvas_lamps.yview
)
scroll_lamps.pack(side="right", fill="y")

canvas_lamps.configure(yscrollcommand=scroll_lamps.set)

# Frame real donde van las lámparas
frame_lamps = tk.Frame(canvas_lamps, bg="#212529")
canvas_lamps.create_window((0, 0), window=frame_lamps, anchor="nw")


# Auto-ajustar el scroll cuando se agregan lámparas
def actualizar_scroll(event):
    canvas_lamps.configure(scrollregion=canvas_lamps.bbox("all"))

frame_lamps.bind("<Configure>", actualizar_scroll)

for idx, ip in enumerate(LAMP_IPS):
    panel = tk.LabelFrame(
        frame_lamps,
        text=lamp_names.get(ip, f"Lámpara {ip}"),
        bg="#22292f",
        fg="#20bdec",
        font=("Segoe UI", 12, "bold"),
        padx=5,
        pady=5,
        labelanchor="n",
        bd=3,               # <--- grosor del borde
        highlightthickness=3,  # <--- grosor del "highlight"
        highlightbackground="#252e36",  # <--- color por defecto (gris)
        highlightcolor="#252e36"      # <--- igual al anterior
        
    )
    panel.grid(row=idx//5, column=idx%5, padx=10, pady=16, sticky="nsew")

    entry = tk.Entry(panel, font=("Segoe UI", 11), width=18, bg="#111519", fg="#b9e3f7")
    entry.insert(0, lamp_names.get(ip, f"Lámpara {ip}"))
    entry.pack(pady=4)
    entry.bind("<FocusOut>", lambda e, ip=ip, entry=entry: update_name(ip, entry))

    modo_var = tk.StringVar(value="colour")
    panel.mode_var = modo_var
    panel.last_mode = "colour"

    tk.Checkbutton(
        panel,
        text="Encender",
        variable=selected_devices[ip],
        command=lambda ip=ip: (
            send_lamp_color_safe(ip, getattr(panels[ip], "last_hue", 0), getattr(panels[ip], "last_sat", 1), getattr(panels[ip], "last_brillo", 255))
            if panels[ip].last_mode == "colour" and selected_devices[ip].get()
            else send_lamp_white(ip, getattr(panels[ip], "last_brillo", 255), getattr(panels[ip], "last_temp", 255))
            if panels[ip].last_mode == "white" and selected_devices[ip].get()
            else send_off(ip)
        ),
        fg="#20bdec",
        bg="#161a1d",
        selectcolor="#212529",
        font=("Segoe UI", 11, "bold")
    ).pack()

    brillo_var = tk.IntVar(value=255)
    temp_var = tk.IntVar(value=255)
    
    panel.brillo_var = brillo_var
    panel.temp_var = temp_var

    def on_color(h, s, v, ip=ip, brillo_var=brillo_var, panel=panel):
        panel.last_hue = h
        panel.last_sat = s
        panel.last_brillo = brillo_var.get()
        panel.mode_var.set("colour")
        panel.last_mode = "colour"
        if selected_devices[ip].get():
            send_lamp_color_safe(ip, h, s, brillo_var.get())

    colorwheel_lamp = RealColorWheel(panel, radius=70, callback=on_color, bg="#181b1e",bd=0, highlightthickness=0)
    colorwheel_lamp.pack(pady=8)
    panel.colorwheel_lamp = colorwheel_lamp
    panel.last_hue = 0
    panel.last_sat = 1
    panel.last_brillo = brillo_var.get()
    panel.last_temp = temp_var.get()

    tk.Label(panel, text="Brillo", bg="#22292f", fg="#20bdec").pack()
    
    def on_brillo_change(v, ip=ip, panel=panel):
        panel.last_brillo = int(v)
        if selected_devices[ip].get():
            modo = panel.mode_var.get()
            if modo == "colour":
                send_lamp_color_safe(ip, getattr(panel, "last_hue", 0), getattr(panel, "last_sat", 1), panel.last_brillo)
            elif modo == "white":
                send_lamp_white(ip, panel.last_brillo, getattr(panel, "last_temp", 255))

    tk.Scale(panel, from_=0, to=255, orient="horizontal", variable=brillo_var,
            command=lambda v, ip=ip, panel=panel: on_brillo_change(v, ip, panel),
            bg="#161a1d", fg="#20bdec", length=120).pack()

    tk.Label(panel, text="Temp (Blanco cálido–frío)", bg="#22292f", fg="#f1c40f").pack()

    def on_temp_panel(value, ip=ip, panel=panel):
        panel.last_temp = int(value)
        if panel.mode_var.get() == "white" and selected_devices[ip].get():
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)

    tk.Scale(panel, from_=0, to=255, orient="horizontal", variable=temp_var,
             command=lambda v, ip=ip, panel=panel: on_temp_panel(v, ip, panel),
             bg="#161a1d", fg="#f1c40f", length=120).pack()

    # --- Subframe horizontal para radiobuttons Color/Blanco ---
    frame_modos = tk.Frame(panel, bg="#22292f")
    frame_modos.pack(pady=(6, 2))
    
    panel.brillo_var = brillo_var
    panel.temp_var = temp_var

    tk.Radiobutton(
        frame_modos,
        text="Color", variable=modo_var, value="colour",
        command=lambda ip=ip, panel=panel: (
            setattr(panel, "last_mode", "colour"),
            send_lamp_color_safe(ip, getattr(panel, "last_hue", 0), getattr(panel, "last_sat", 1), getattr(panel, "last_brillo", 255))
            if selected_devices[ip].get() else None
        ),
        bg="#22292f", fg="#20bdec", selectcolor="#161a1d", font=("Segoe UI", 11)
    ).pack(side="left", padx=2)

    tk.Radiobutton(
        frame_modos,
        text="Blanco", variable=modo_var, value="white",
        command=lambda ip=ip, panel=panel: (
            setattr(panel, "last_mode", "white"),
            send_lamp_white(ip, getattr(panel, "last_brillo", 255), getattr(panel, "last_temp", 255))
            if selected_devices[ip].get() else None
        ),
        bg="#22292f", fg="#f1c40f", selectcolor="#161a1d", font=("Segoe UI", 11)
    ).pack(side="left", padx=2)

    send_off(ip)
    panels[ip] = panel
#___________________________________________________________________________________

# ----- 3. FRAME DERECHO (escenas) -----
frame_right = tk.Frame(frame_main, bg="#202428",width=280)
frame_right.pack(side="right", fill="y", padx=(10), pady=10)
frame_right.pack_propagate(False)
# Panel de Escenas (tu panel de siempre, a la derecha del de efectos)
frame_lateral = tk.Frame(frame_main, bg="#181b1e", width=280)


# -------- PANEL DE ESCENAS EN LA DERECHA ---------

from .escenas_proyectos import (
    load_escenas, save_escenas,
    get_effects_state, apply_effects_state,
    guardar_escena, actualizar_escena_completa,
    load_proyectos,
    guardar_proyecto, obtener_escenas_de_proyecto,
    exportar_proyecto_a_archivo, importar_obra_desde_archivo,
    borrar_proyecto, borrar_todos_los_proyectos,  # 👈 agrega esto
)

def on_guardar_escena():
    # 1) Nombre de la escena
    nombre = entry_escena.get().strip()
    if not nombre:
        messagebox.showwarning("Nombre requerido", "Escribe un nombre para la escena.")
        return

    # 2) Ver si ya existe
    escenas = load_escenas()
    if nombre in escenas["orden"]:
        messagebox.showerror("Duplicado", f"Ya existe la escena '{nombre}'.")
        return

    # 3) Fades desde tus widgets (sliders, spinbox, etc.)
    fade_in_val = fade_in_var.get()
    fade_out_val = fade_out_var.get()

    # 4) Estado de efectos (respiración, estrobo, fuego, etc.)
    effects_state = get_effects_state(effect_vars)

    # 5) Llamar al módulo para que arme y guarde todo
    ok = guardar_escena(
        nombre,
        fade_in_val,
        fade_out_val,
        LAMP_IPS,
        panels,
        selected_devices,
        effects_state,
    )

    if ok:
        # 6) Actualizar la lista de escenas en la UI
        actualizar_lista_escenas()
        entry_escena.delete(0, tk.END)


def get_lamp_state(ip):
    panel = panels[ip]
    if panel.last_mode == "colour":
        return {
            "modo": "colour",
            "h": panel.last_hue,
            "s": panel.last_sat,
            "brillo": panel.last_brillo
        }
    else:
        return {
            "modo": "white",
            "brillo": panel.last_brillo,
            "temp": panel.last_temp
        }
        
        
def estado_lampara_actual(ip):
    """
    Devuelve el estado actual de la lámpara según el panel y el check.
    - Si el check NO está tildado → la tomamos como APAGADA (brillo 0).
    - Si está tildado → usamos los valores del panel.
    """
    panel = panels[ip]

    # Solo consideramos "encendida" si el check está en True
    on_real = bool(selected_devices[ip].get())

    state = {"on": on_real}

    if on_real:
        if getattr(panel, "last_mode", "colour") == "colour":
            state.update({
                "modo": "colour",
                "h": getattr(panel, "last_hue", 0),
                "s": getattr(panel, "last_sat", 1),
                "brillo": getattr(panel, "last_brillo", 255),
            })
        else:
            state.update({
                "modo": "white",
                "brillo": getattr(panel, "last_brillo", 255),
                "temp": getattr(panel, "last_temp", 4000),
            })
    else:
        # Encendido falso → los valores de brillo los tratamos como 0
        state.update({
            "modo": getattr(panel, "last_mode", "colour"),
            "brillo": 0,
            "h": getattr(panel, "last_hue", 0),
            "s": getattr(panel, "last_sat", 1),
            "temp": getattr(panel, "last_temp", 4000),
        })

    return state


def estados_son_iguales(actual, destino):
    """
    Compara estado actual vs destino para evitar fades innecesarios.
    """

    # Ambos apagados
    if actual.get("brillo", 0) == 0 and destino.get("brillo", 0) == 0:
        return True

    # Uno apagado y otro no
    if (actual.get("brillo", 0) == 0) != (destino.get("brillo", 0) == 0):
        return False

    # Modo distinto
    if actual.get("modo") != destino.get("modo"):
        return False

    # Brillo distinto
    if int(actual.get("brillo", 0)) != int(destino.get("brillo", 0)):
        return False

    # Color
    if actual.get("modo") == "colour":
        return (
            int(actual.get("h")) == int(destino.get("h")) and
            float(actual.get("s")) == float(destino.get("s"))
        )

    # Blanco
    if actual.get("modo") == "white":
        return int(actual.get("temp")) == int(destino.get("temp"))

    return False

        

# --- FADE IN/OUT ---
import asyncio
import math

def ease_in_out_sine(x):
    return -(math.cos(math.pi * x) - 1) / 2


def mostrar_estado_escena_en_paneles(nombre_escena):
    """
    Muestra un PREVIEW de la escena en los paneles,
    pero SIN modificar el estado real last_* de las lámparas.
    """
    escenas = load_escenas()
    datos = escenas.get("datos", {})

    if nombre_escena not in datos:
        return

    escena = datos[nombre_escena]

    for ip in LAMP_IPS:
        estado = escena.get(ip, {})
        panel = panels.get(ip)
        if panel is None:
            continue

        # ----- PREVIEW DEL MODO -----
        modo = estado.get("modo", "colour")
        panel.mode_var.set(modo)

        # ----- PREVIEW DEL BRILLO (solo UI) -----
        if hasattr(panel, "brillo_var"):
            panel.brillo_var.set(safe_brightness(estado.get("brillo", 0)))

        # ----- PREVIEW DE SELECCIÓN ON/OFF -----
        if estado.get("state", "off") == "on":
            selected_devices[ip].set(True)
        else:
            selected_devices[ip].set(False)

        # ----- PREVIEW DE COLOR / TEMP -----
        if modo == "colour":
            h = estado.get("h", getattr(panel, "last_hue", 0))
            s = estado.get("s", getattr(panel, "last_sat", 1))

            # NO tocamos last_hue / last_sat, solo el wheel
            if hasattr(panel, "colorwheel_lamp"):
                v = estado.get("brillo", 255) / 255.0
                panel.colorwheel_lamp.set_color(h, s, v)
        else:
            temp = estado.get("temp", getattr(panel, "last_temp", 4000))
            if hasattr(panel, "temp_var"):
                panel.temp_var.set(temp)

        # ----- PREVIEW DE BORDE (solo visual) -----
        color_borde = "#03A125" if estado.get("state", "off") == "on" else "#252e36"
        panel.config(highlightbackground=color_borde, highlightcolor=color_borde)


 
 # ----------- PROYECTOS EN LA UI -----------

lista_proyectos = tk.StringVar(value=[])

# ================== PROYECTOS / OBRAS ==================

def on_guardar_proyecto():
    nombre = entry_proyecto.get().strip()
    if not nombre:
        messagebox.showwarning("Nombre requerido", "Debes ingresar un nombre para el proyecto/obra.")
        return

    escenas = load_escenas()
    if not escenas["orden"]:
        messagebox.showwarning("Sin escenas", "No hay escenas para guardar en el proyecto.")
        return

    # Guarda o actualiza el proyecto con el orden actual de escenas
    guardar_proyecto(nombre, escenas["orden"])
    actualizar_lista_proyectos()
    messagebox.showinfo("Proyecto guardado", f"Proyecto/obra '{nombre}' guardado.")
    # no borro el entry para facilitar sobreescritura


def on_cargar_proyecto():
    sel = listbox_proyectos.curselection()
    if not sel:
        messagebox.showwarning("Selecciona un proyecto", "Debes seleccionar un proyecto/obra.")
        return

    nombre = listbox_proyectos.get(sel)
    try:
        escenas_proyecto = obtener_escenas_de_proyecto(nombre)
    except KeyError:
        messagebox.showerror("Proyecto no encontrado", f"No existe el proyecto '{nombre}'.")
        return

    escenas = load_escenas()
    # Filtrar solo escenas que todavía existan
    nuevas = [e for e in escenas_proyecto if e in escenas["datos"]]
    if not nuevas:
        messagebox.showwarning("Proyecto vacío", f"El proyecto '{nombre}' no tiene escenas válidas.")
        return

    escenas["orden"] = nuevas
    save_escenas(escenas)
    actualizar_lista_escenas()
    messagebox.showinfo("Proyecto cargado", f"Escenas reordenadas según el proyecto '{nombre}'.")
    


def on_exportar_obra():
    sel = listbox_proyectos.curselection()
    if not sel:
        messagebox.showwarning("Selecciona un proyecto", "Debes seleccionar un proyecto/obra para exportar.")
        return

    nombre = listbox_proyectos.get(sel)

    filename = filedialog.asksaveasfilename(
        defaultextension=".json",
        filetypes=[("Obra de luces", "*.json"), ("JSON", "*.json")],
        title="Guardar obra como..."
    )
    if not filename:
        return

    try:
        exportar_proyecto_a_archivo(nombre, filename)
        messagebox.showinfo("Obra exportada", f"Obra '{nombre}' guardada en:\n{filename}")
    except Exception as e:
        messagebox.showerror("Error al exportar", str(e))
        
def on_importar_obra():
    filename = filedialog.askopenfilename(
        filetypes=[("Obra de luces", "*.json"), ("JSON", "*.json")],
        title="Cargar obra..."
    )
    if not filename:
        return

    try:
        nombre_creado = importar_obra_desde_archivo(filename)
        messagebox.showinfo("Obra importada",
                            f"Se importó la obra como proyecto '{nombre_creado}'.")
        actualizar_lista_escenas()
        actualizar_lista_proyectos()
    except Exception as e:
        messagebox.showerror("Error al importar", str(e))
        

def on_borrar_proyecto():
    sel = listbox_proyectos.curselection()
    if not sel:
        messagebox.showwarning("Selecciona un proyecto", "Debes seleccionar un proyecto para borrarlo.")
        return

    nombre = listbox_proyectos.get(sel)

    if not messagebox.askyesno(
        "Confirmar borrado",
        f"¿Seguro que quieres borrar el proyecto/obra '{nombre}'?"
    ):
        return

    if borrar_proyecto(nombre):
        actualizar_lista_proyectos()
        messagebox.showinfo("Proyecto borrado", f"Se borró el proyecto '{nombre}'.")
    else:
        messagebox.showerror("Error", f"No se pudo borrar el proyecto '{nombre}'.")
            

tk.Label(
    frame_right,
    text="PROYECTOS / OBRAS",
    bg="#202428", fg="#20bdec",
    font=("Segoe UI", 14, "bold")
).pack(anchor="w", pady=(10, 4))

# --- BARRA DE BOTONES PEQUEÑOS EN UNA FILA ---

frame_proy_bar = tk.Frame(frame_right, bg="#202428")
frame_proy_bar.pack(fill="x", pady=(0, 4))


################## TOOLTIP PARA BOTONES ######################
class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        widget.bind("<Enter>", self.show_tooltip)
        widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window is not None:
            return

        # Crear ventana del tooltip inicialmente fuera de pantalla
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry("+0+0")

        # Contenido del tooltip
        label = tk.Label(
            tw, text=self.text,
            bg="#333", fg="white",
            padx=6, pady=3,
            relief="solid", borderwidth=1,
            font=("Segoe UI", 11)
        )
        label.pack()

        tw.update_idletasks()  # Necesario para medir tamaño real del tooltip

        # Tamaño del tooltip
        tooltip_width = tw.winfo_width()
        tooltip_height = tw.winfo_height()

        # Coordenadas iniciales (abajo a la derecha del widget)
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        # Tamaño de pantalla
        screen_width = tw.winfo_screenwidth()
        screen_height = tw.winfo_screenheight()

        # Corrección horizontal (si se sale por la derecha)
        if x + tooltip_width > screen_width:
            x = self.widget.winfo_rootx() - tooltip_width - 20  # mostrar a la izquierda

        # Corrección vertical (si se sale por abajo)
        if y + tooltip_height > screen_height:
            y = self.widget.winfo_rooty() - tooltip_height - 5  # mostrar arriba

        tw.wm_geometry(f"+{x}+{y}")

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None



########## CARGAR PROYECTO #################

btn_cargar_proyecto = tk.Button(
    frame_proy_bar,
    text="▶",           # Cargar / aplicar orden
    command=on_cargar_proyecto,
    width=3,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold"),
    relief="raised",
    
)
btn_cargar_proyecto.grid(row=0, column=0, padx=2)

Tooltip(btn_cargar_proyecto, "Cargar y aplicar el proyecto seleccionado")


########## CARGAR GUARDAR #################

# Botones con iconos (emoji) y pequeños
btn_guardar_proyecto = tk.Button(
    frame_proy_bar,
    text="💾",           # Guardar proyecto
    command=on_guardar_proyecto,
    width=3,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold"),
    relief="raised"
)
btn_guardar_proyecto.grid(row=0, column=1, padx=2)

Tooltip(btn_guardar_proyecto, "Guardar el proyecto actual")

########## EXPORTAR #################

btn_exportar_obra = tk.Button(
    frame_proy_bar,
    text="📥",           # Exportar a archivo
    command=on_exportar_obra,
    width=3,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold"),
    relief="raised"
)
btn_exportar_obra.grid(row=0, column=2, padx=2)

Tooltip(btn_exportar_obra, "Exportar la obra a archivo para respaldarla")


########## IMPORTAR PROYECTO #################

btn_importar_obra = tk.Button(
    frame_proy_bar,
    text="📤",           # Importar desde archivo
    command=on_importar_obra,
    width=3,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold"),
    relief="raised"
)
btn_importar_obra.grid(row=0, column=3, padx=2)

Tooltip(btn_importar_obra, "Importar una obra desde un archivo")


########## BORRAR PROYECTO #################

btn_borrar_proyecto = tk.Button(
    frame_proy_bar,
    text="🗑",           # Borrar proyecto seleccionado
    command=on_borrar_proyecto,
    width=3,
    bg="#f65f5f", fg="#fff",
    font=("Segoe UI", 10, "bold"),
    relief="raised"
)
btn_borrar_proyecto.grid(row=0, column=4, padx=2)

Tooltip(btn_borrar_proyecto, "Eliminar el proyecto seleccionado")


frame_proy_top = tk.Frame(frame_right, bg="#202428")
frame_proy_top.pack(fill="x", pady=(0, 4))


label_nombre = tk.Label(
    frame_proy_top,
    text="Nombre proyecto / obra:",
    bg="#202428", fg="#b9e3f7",
    font=("Segoe UI", 10),
    anchor="center"
)
label_nombre.grid(row=0, column=0, pady=(2, 2))
frame_proy_top.grid_columnconfigure(0, weight=1)


entry_proyecto = tk.Entry(
    frame_proy_top,
    font=("Segoe UI", 12),
    width=22,
    bg="#181b1e", fg="#b9e3f7",
    justify="center"
)
entry_proyecto.grid(row=1, column=0, pady=(0, 4))
frame_proy_top.grid_columnconfigure(0, weight=1)

entry_proyecto.config(insertbackground="#20bdec")  # ¡Color del cursor!

# Lista de proyectos guardados
lista_proyectos = tk.StringVar(value=[])

listbox_proyectos = tk.Listbox(
    frame_right,
    listvariable=lista_proyectos,
    width=12, height=3,
    font=("Segoe UI", 11),
    bg="#17191c", fg="#fff",
    selectbackground="#20bdec",
    activestyle="dotbox"
)
listbox_proyectos.pack(fill="x", pady=(4, 4))


def actualizar_lista_proyectos():
    proyectos = load_proyectos()
    lista_proyectos.set(proyectos["orden"])



# def on_borrar_todos_los_proyectos():
#     if not messagebox.askyesno(
#         "Confirmar borrado",
#         "¿Seguro que quieres borrar TODOS los proyectos/obras?\nEsta acción no se puede deshacer."
#     ):
#         return

#     borrar_todos_los_proyectos()
#     actualizar_lista_proyectos()
#     messagebox.showinfo("Proyectos borrados", "Se borraron todos los proyectos/obras.")

# btn_borrar_todos = tk.Button(
#     frame_right,
#     text="Borrar TODOS los proyectos",
#     command=on_borrar_todos_los_proyectos,
#     bg="#b71c1c", fg="#fff",
#     font=("Segoe UI", 10, "bold")
# )
# btn_borrar_todos.pack(fill="x", pady=(0, 4))



# Inicializamos lista de proyectos al arrancar
actualizar_lista_proyectos()

#----------------------FIN OBRAS PROYECTOS --------------------------------------------




def fade_to(ip, tiempo, from_brillo, to_brillo, modo, h=0, s=1, temp=4000, token=None):

    if token is None:
        token = fade_token[0]

    panel = panels.get(ip)

    # Normalizar
    from_b = int(max(0, min(255, from_brillo)))
    to_b   = int(max(0, min(255, to_brillo)))

    # ==========================================
    #  SIN FADE
    # ==========================================
    if tiempo <= 0:
        if to_b <= 0:
            send_off(ip)
        else:
            if modo == "colour":
                send_lamp_color_safe(ip, h, s, to_b)
            else:
                send_lamp_white(ip, to_b, temp)

        # Actualiza estado
        if panel:
            panel.last_brillo = to_b
            panel.last_mode = modo
            if modo == "colour":
                panel.last_hue = h
                panel.last_sat = s
            else:
                panel.last_temp = temp
        return

    # ==========================================
    #  FADE REAL
    # ==========================================
    apagando = (to_b == 0)
    fps = 30
    steps = max(1, int(tiempo * fps))
    dt = tiempo / steps

    # Estado REAL al inicio
    info = lamp_state.get(ip, {})
    h_real = info.get("hue", panel.last_hue if panel else 0)
    s_real = info.get("sat", panel.last_sat if panel else 1)
    temp_real = info.get("temp", panel.last_temp if panel else 4000)

    for i in range(1, steps + 1):

        if fade_token[0] != token:
            return

        t = i / steps
        curva = -(math.cos(math.pi * t) - 1) / 2
        brillo = int(from_b + (to_b - from_b) * curva)

        # caso de apagado
        if apagando:
            if brillo <= 7:
                send_off(ip)
                break

            if modo == "colour":
                send_lamp_color_safe(ip, h_real, s_real, brillo)
            else:
                send_lamp_white(ip, brillo, temp_real)

        else:
            # caso de encendido/cambio color
            if modo == "colour":
                send_lamp_color_safe(ip, h, s, brillo)
            else:
                send_lamp_white(ip, brillo, temp)

        time.sleep(dt)

    # ESTADO FINAL EXACTO
    if to_b <= 0:
        send_off(ip)
    else:
        if modo == "colour":
            send_lamp_color_safe(ip, h, s, to_b)
        else:
            send_lamp_white(ip, to_b, temp)

    # guardar estado final
    if panel:
        panel.last_brillo = to_b
        panel.last_mode = modo
        if modo == "colour":
            panel.last_hue = h
            panel.last_sat = s
        else:
            panel.last_temp = temp

    # ★★★ Actualizar estado REAL ★★★
    update_lamp_state(ip, modo, h, s, temp, to_b)


def finalizar_escena(token, nombre):
    global escena_en_ejecucion, ultima_idx_escena

    # Si se lanzó otra escena después, no hacemos nada
    if fade_token[0] != token:
        return

    escena_en_ejecucion = False

    # Reactivar controles
    try:
        btn_cargar.config(state="normal")
    except:
        pass
    try:
        listbox_escenas.config(state="normal")
    except:
        pass
    
    # Mensaje de estado
    try:
        set_estado_escena(f"Escena '{nombre}' terminada", "#28a745")
    except:
        pass

    # ⬇⬇⬇ AQUÍ HACEMOS EL "SALTO DE LÍNEA" ⬇⬇⬇
    if ultima_idx_escena is not None:
        try:
            next_idx = ultima_idx_escena + 1

            listbox_escenas.selection_clear(0, tk.END)

            if next_idx < listbox_escenas.size():
                listbox_escenas.selection_set(next_idx)
                listbox_escenas.activate(next_idx)
                listbox_escenas.see(next_idx)

            # ya usamos el índice, lo limpiamos
            ultima_idx_escena = None
        except Exception as e:
            print(f"[WARN] No se pudo avanzar en la lista de escenas: {e}")


def escena_finalizada_callback(nombre):
    try:
        set_estado_escena(f"Escena '{nombre}' finalizada", "#8dfa9f")
    except:
        pass

from tkinter import filedialog
import uuid
import threading
from tablero.helpers_wiz import safe_brightness

def update_lamp_state(ip, modo, h, s, temp, brillo):
    lamp_state[ip] = {
        "mode": modo,
        "hue": h,
        "sat": s,
        "temp": temp,
        "brightness": brillo
    }


def aplicar_escena(nombre_escena):
    global escena_en_ejecucion

    escenas = load_escenas()
    datos = escenas.get("datos", {})

    if nombre_escena not in datos:
        print(f"[ESCENA] No existe: {nombre_escena}")
        return

    # Candado de ejecución
    if escena_en_ejecucion:
        print("[INFO] No se puede ejecutar otra escena aún.")
        return
    escena_en_ejecucion = True

    # Deshabilitar UI
    try: btn_cargar.config(state="disabled")
    except: pass
    try: listbox_escenas.config(state="disabled")
    except: pass

    escena = datos[nombre_escena]

    fade_in_val = float(escena.get("fade_in", 0.0) or 0.0)
    fade_out_val = float(escena.get("fade_out", 0.0) or 0.0)

    online_ips = [
        ip for ip in LAMP_IPS
        if lamp_status.get(ip, True) and ip in escena
    ]

    nuevo_token = str(uuid.uuid4())
    fade_token[0] = nuevo_token

    try:
        set_estado_escena(f"Ejecutando escena: {nombre_escena}…", "#ff4d4d")
    except:
        pass

    # -----------------------------------------------------
    # 🚨 DETECCIÓN DE ACCIONES DINÁMICAS
    # -----------------------------------------------------
    effects = escena.get("effects", {})

    acciones_dinamicas = [
        "secuencia_on", "secuencia_off", "secuencia",
        "respiracion", "fuego", "mar", "arcoiris",
        "vela", "atardecer", "latido", "parpadeo",
        "estrobo", "estrobo_udp", "desfase"
    ]

    if any(effects.get(acc, False) for acc in acciones_dinamicas):
        print(f"[ESCENA] {nombre_escena}: acción dinámica detectada → NO ejecutar fades.")

        # Marcar la escena como finalizada (FIX agregado)
        marcar_escena_terminada()

        # Cargar estado visual en el panel (no afecta lámparas)
        for ip in online_ips:
            estado = escena[ip]
            panel = panels[ip]
            panel.last_mode = estado.get("modo", "colour")
            panel.last_hue = estado.get("h", 0)
            panel.last_sat = estado.get("s", 1)
            panel.last_brillo = estado.get("brillo", 1)

        # Aplicar efectos
        root.after(
            10,
            lambda c=effects: apply_effects_state(c, effect_vars, effect_toggles)
        )

        # Rehabilitar UI y desbloquear escena
        escena_en_ejecucion = False
        try: btn_cargar.config(state="normal")
        except: pass
        try: listbox_escenas.config(state="normal")
        except: pass

        return

    # -----------------------------------------------------
    # 🟩 SI NO ES DINÁMICA → FADES NORMALES
    # -----------------------------------------------------
    def worker():
        threads = []

        for ip in online_ips:
            estado_destino = escena[ip]

            info = lamp_state.get(ip, {})
            from_brillo = safe_brightness(info.get("brightness", 0))
            from_h = info.get("hue", 0)
            from_s = info.get("sat", 1)
            from_temp = info.get("temp", 4000)
            from_mode = info.get("mode", "colour")

            to_brillo = safe_brightness(estado_destino.get("brillo", 0))
            to_mode = estado_destino.get("modo", from_mode)
            to_h = estado_destino.get("h", from_h)
            to_s = estado_destino.get("s", from_s)
            to_temp = estado_destino.get("temp", from_temp)

            destino_on = (estado_destino.get("state", "off") == "on" and to_brillo > 0)

            if from_brillo == to_brillo and from_mode == to_mode and from_h == to_h and from_s == to_s:
                print(f"[SKIP] {ip}: sin cambios reales")
                continue

            if destino_on:
                tiempo = fade_in_val
                start_b = from_brillo
                end_b = to_brillo
                modo = to_mode
                h = to_h
                s = to_s
                temp = to_temp
            else:
                if from_brillo <= 0:
                    print(f"[SKIP] {ip}: ya apagada")
                    continue

                tiempo = fade_out_val
                start_b = from_brillo
                end_b = 0
                modo = from_mode
                h = from_h
                s = from_s
                temp = from_temp

            print(f"[DEBUG ESCENA] {nombre_escena} ip={ip} t={tiempo}s {start_b}→{end_b} modo={modo}")

            t = threading.Thread(
                target=fade_to,
                args=(ip, tiempo, start_b, end_b, modo, h, s, temp, nuevo_token),
                daemon=True
            )
            t.start()
            threads.append(t)

    threading.Thread(target=worker, daemon=True).start()

    tiempo_total = max(fade_in_val, fade_out_val)

    root.after(
        int(tiempo_total * 1200),
        lambda: finalizar_escena(nuevo_token, nombre_escena)
    )

    if "effects" in escena:
        root.after(
            0,
            lambda c=escena["effects"]: apply_effects_state(c, effect_vars, effect_toggles)
        )


    # -------------------------------
    # FINALIZAR EN TIEMPO (con leve margen)
    # -------------------------------
    tiempo_total = max(fade_in_val, fade_out_val)

    root.after(
        int(tiempo_total * 1200),  # 20% de margen para desfases de red/threads
        lambda: finalizar_escena(nuevo_token, nombre_escena)
    )

    # Efectos (respiración, estrobo, etc.)
    try:
        cfg = datos[nombre_escena]
        effects_cfg = cfg.get("effects", None)
    except:
        effects_cfg = None

    if effects_cfg:
        root.after(
            0,
            lambda c=effects_cfg: apply_effects_state(c, effect_vars, effect_toggles)
        )


def marcar_escena_terminada():
    global escena_en_ejecucion
    escena_en_ejecucion = False

    # Cambiar mensaje en la UI (si existe)
    try:
        lbl_estado_escena.config(
            text="ESCENA FINALIZADA",
            fg="#03fc7f"   # verde
        )
    except:
        pass


def borrar():
    sel = listbox_escenas.curselection()
    if sel:
        escena = listbox_escenas.get(sel)
        if messagebox.askyesno("Eliminar escena", f"¿Estás seguro que quieres eliminar la escena '{escena}'?"):
            escenas = load_escenas()
            if escena in escenas["datos"]:
                del escenas["datos"][escena]
            if escena in escenas["orden"]:
                escenas["orden"].remove(escena)
            save_escenas(escenas)
            actualizar_lista_escenas()



def actualizar_lista_escenas():
    escenas = load_escenas()
    lista_escenas.set(escenas["orden"])


def guardar():
    nombre = entry_escena.get().strip()
    if not nombre:
        messagebox.showwarning("Nombre requerido", "Debes ingresar un nombre para la escena.")
        return

    escenas = load_escenas()
    if nombre in escenas["orden"]:
        messagebox.showerror(
            "Nombre duplicado",
            f"Ya existe una escena llamada '{nombre}'.\nPor favor elige otro nombre."
        )
        entry_escena.focus_set()
        entry_escena.selection_range(0, tk.END)
        return

    # Leer fades
    try:
        fade_in_val = float(fade_in_var.get())
    except Exception:
        fade_in_val = 0.0
    try:
        fade_out_val = float(fade_out_var.get())
    except Exception:
        fade_out_val = 0.0

    if fade_in_val <= 0:
        fade_in_val = 0.0
    if fade_out_val <= 0:
        fade_out_val = 0.0

    # 👉 NUEVO: leer estado de efectos (respiración, estrobo, etc.)
    effects_state = get_effects_state(effect_vars)

    # 👉 NUEVO: delegar en escenas_proyectos.guardar_escena(...)
    exito = guardar_escena(
        nombre,
        fade_in_val,
        fade_out_val,
        LAMP_IPS,
        panels,
        selected_devices,
        effects_state,
    )

    if exito:
        actualizar_lista_escenas()
        entry_escena.delete(0, tk.END)

        
def on_actualizar_escena():
    escena = escena_seleccionada_en_listbox()  # tu lógica
    if not escena:
        messagebox.showwarning("Selecciona una escena", "Elige una escena a actualizar.")
        return

    fade_in_val = fade_in_var.get()
    fade_out_val = fade_out_var.get()
    effects_state = get_effects_state(effect_vars)

    if actualizar_escena_completa(
        escena,
        fade_in_val,
        fade_out_val,
        LAMP_IPS,
        panels,
        selected_devices,
        effects_state,
    ):
        messagebox.showinfo("Escena actualizada", f"'{escena}' guardada.")
        


def mostrar_fades_de_escena(event=None):
    sel = listbox_escenas.curselection()
    if sel:
        escena = listbox_escenas.get(sel)
        escenas = load_escenas()
        datos = escenas["datos"].get(escena, {})
        fade_in_var.set(datos.get("fade_in", 0.0))
        fade_out_var.set(datos.get("fade_out", 0.0))
        mostrar_estado_escena_en_paneles(escena) 
               
def cargar():
    sel = listbox_escenas.curselection()
    if sel:
        escena = listbox_escenas.get(sel)
        aplicar_escena(escena)
        

def on_listbox_enter(event):
    global escena_en_ejecucion, ultima_idx_escena

    # Si ya hay una escena corriendo, NO hacer nada
    if escena_en_ejecucion:
        return "break"

    sel = listbox_escenas.curselection()
    if not sel:
        return "break"

    idx = sel[0]
    escena = listbox_escenas.get(idx)

    # Guardamos qué índice se ejecutó
    ultima_idx_escena = idx

    # Mostramos y ejecutamos la escena
    mostrar_estado_escena_en_paneles(escena)
    aplicar_escena(escena)

    # IMPORTANTE: devolvemos "break" para que Tkinter
    # no cambie la selección todavía. El salto lo haremos
    # recién al terminar la escena, en finalizar_escena.
    return "break"



         

def mover_arriba():
    sel = listbox_escenas.curselection()
    if sel:
        idx = sel[0]
        escenas = load_escenas()
        orden = escenas["orden"]
        if idx > 0:
            orden[idx], orden[idx-1] = orden[idx-1], orden[idx]
            save_escenas(escenas)
            actualizar_lista_escenas()
            listbox_escenas.selection_clear(0, tk.END)
            listbox_escenas.selection_set(idx-1)
            listbox_escenas.activate(idx-1)
            
            
def mover_abajo():
    sel = listbox_escenas.curselection()
    if sel:
        idx = sel[0]
        escenas = load_escenas()
        orden = escenas["orden"]
        if idx < len(orden)-1:
            orden[idx], orden[idx+1] = orden[idx+1], orden[idx]
            save_escenas(escenas)
            actualizar_lista_escenas()
            listbox_escenas.selection_clear(0, tk.END)
            listbox_escenas.selection_set(idx+1)
            listbox_escenas.activate(idx+1)
            
def on_fade_scroll(event, var):
    delta = 0.1 if event.delta > 0 else -0.1
    value = var.get()
    try:
        newval = round(max(0.0, float(value) + delta), 2)
    except Exception:
        newval = 0.1
    var.set(newval)
    
# ==== UI ====
tk.Label(frame_right, text="ESCENAS", bg="#202428", fg="#20bdec",
         font=("Segoe UI", 16, "bold")).pack(pady=(6, 12))

tk.Label(frame_right, text="Nombre:", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 11)).pack(anchor="n")
entry_escena = tk.Entry(frame_right, font=("Segoe UI", 12), width=30, bg="#181b1e", fg="#b9e3f7")
entry_escena.pack(pady=(0,6))
entry_escena.config(insertbackground="#20bdec")  # ¡Color del cursor!

from tkinter import ttk


estado_escena_var = tk.StringVar(value="Sin escenas en ejecución")
lbl_estado_escena = tk.Label(
    frame_right,
    textvariable=estado_escena_var,
    bg="#202428",
    fg="#b9e3f7",
    font=("Segoe UI", 10, "italic")
)
lbl_estado_escena.pack(pady=(0, 6))

def actualizar_escena():
    escena = escena_seleccionada_en_listbox()
    if not escena:
        messagebox.showwarning("Selecciona una escena", "Debes elegir una escena para actualizar.")
        return

    # Obtener fades
    try:
        fade_in_val = float(fade_in_var.get())
    except:
        fade_in_val = 0.0

    try:
        fade_out_val = float(fade_out_var.get())
    except:
        fade_out_val = 0.0

    if fade_in_val <= 0:
        fade_in_val = 0.0
    if fade_out_val <= 0:
        fade_out_val = 0.0

    # Obtener efectos
    effects_state = get_effects_state(effect_vars)

    # Llamar al módulo escenas_proyectos
    ok = actualizar_escena_completa(
        escena,
        fade_in_val,
        fade_out_val,
        LAMP_IPS,
        panels,
        selected_devices,
        effects_state,
    )

    if ok:
        messagebox.showinfo("Escena actualizada", f"La escena '{escena}' ha sido actualizada.")
        actualizar_lista_escenas()

def set_estado_escena(texto, color):
    estado_escena_var.set(texto)
    lbl_estado_escena.config(fg=color)

# Evento opcional para enganchar lógica al final de una escena
def on_escena_terminada(event):
    print("[INFO] Escena finalizada.")  # aquí puedes reproducir un sonido, loguear, etc.
root.bind("<<EscenaTerminada>>", on_escena_terminada)

# --- Sliders/entries de fade
frame_fades = tk.Frame(frame_right, bg="#202428")
frame_fades.pack(pady=(0,8))
tk.Label(frame_fades, text="Fade In (seg):", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="e")
fade_in_var = tk.DoubleVar(value=0.0)
tk.Label(frame_fades, text="Fade Out (seg):", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="e")
fade_out_var = tk.DoubleVar(value=0.0)    

# Para Windows (tkinter usa event.delta), para otros sistemas puede ser diferente.
fade_in_entry = tk.Entry(frame_fades, textvariable=fade_in_var, width=6, font=("Segoe UI", 11), bg="#1e2224", fg="#e6e6e6")
fade_in_entry.grid(row=0, column=1)
fade_in_entry.bind("<MouseWheel>", lambda e: on_fade_scroll(e, fade_in_var))

fade_out_entry = tk.Entry(frame_fades, textvariable=fade_out_var, width=6, font=("Segoe UI", 11), bg="#1e2224", fg="#e6e6e6")
fade_out_entry.grid(row=1, column=1)
fade_out_entry.bind("<MouseWheel>", lambda e: on_fade_scroll(e, fade_out_var))
            
# ---- UI Panel derecho ----
frame_escenas_bar = tk.Frame(frame_right, bg="#202428")
frame_escenas_bar.pack(fill="x", pady=(4, 8))

############ EJECUTAR ESCENA ###############

tk.Label(frame_right, text="listado Escenas guardadas:", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 11)).pack(anchor="w", pady=(8,2))
lista_escenas = tk.StringVar(value=[])

btn_cargar = tk.Button(
    frame_escenas_bar,
    text="▶",
    command=cargar,
    width=3,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold"),
)
btn_cargar.grid(row=0, column=0, padx=3)

Tooltip(btn_cargar, "Ejecutar escena seleccionada")

############ GUARDAR ESCENA ###############

btn_guardar_escena = tk.Button(
    frame_escenas_bar,
    text="💾",
    command=guardar,
    width=3,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold"),
)
btn_guardar_escena.grid(row=0, column=1, padx=3)

Tooltip(btn_guardar_escena, "Guardar escena")

############ ACTUALIZAR ESCENA ###############

btn_actualizar_escena = tk.Button(
    frame_escenas_bar,
    text="🔃",
    command=on_actualizar_escena,
    width=3,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold"),
)
btn_actualizar_escena.grid(row=0, column=2, padx=3)

Tooltip(btn_actualizar_escena, "Actualizar escena seleccionada")

############ BORRAR ESCENA ###############
btn_borrar = tk.Button(
    frame_escenas_bar,
    text="🗑",
    command=borrar,
    width=3,
    bg="#e53935", fg="#fff",
    font=("Segoe UI", 10, "bold"),
)
btn_borrar.grid(row=0, column=3, padx=3)

Tooltip(btn_borrar, "Borrar escena seleccionada")


########## LISTBOX ESCENAS ###################

# --- LISTA DE ESCENAS CON SCROLLBAR ---

# --- LISTA DE ESCENAS + SCROLLBAR + BOTONES ↑ ↓ EN LA MISMA FILA ---

frame_lista_escenas = tk.Frame(frame_right, bg="#202428")
frame_lista_escenas.pack(fill="both", pady=(4, 8))

# Listbox + scrollbar en un sub-frame
frame_listbox = tk.Frame(frame_lista_escenas, bg="#202428")
frame_listbox.grid(row=0, column=0, sticky="nsw")

scroll_esc = tk.Scrollbar(frame_listbox, orient="vertical")
scroll_esc.pack(side="right", fill="y")


from tablero.helpers_wiz import bloquear_enter
listbox_escenas = tk.Listbox(
    frame_listbox,
    listvariable=lista_escenas,
    width=25, height=10,
    font=("Segoe UI", 11),
    bg="#17191c", fg="#fff",
    selectbackground="#20bdec",
    activestyle="dotbox",
    yscrollcommand=scroll_esc.set
)
listbox_escenas.pack(side="left", fill="both")

listbox_escenas.bind("<Return>", bloquear_enter)
scroll_esc.config(command=listbox_escenas.yview)

# Botonera UP/DOWN al lado derecho del listbox
frame_updown = tk.Frame(frame_lista_escenas, bg="#202428")
frame_updown.grid(row=0, column=1, padx=6, sticky="ns")

btn_up = tk.Button(
    frame_updown, text="🔼",
    command=mover_arriba,
    width=4,
    bg="#81d4fa", fg="#000",
    font=("Segoe UI", 10, "bold")
)
btn_up.pack(pady=4)
Tooltip(btn_up, "Subir escena seleccionada")

btn_down = tk.Button(
    frame_updown, text="🔽",
    command=mover_abajo,
    width=4,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold")
)
btn_down.pack(pady=4)
Tooltip(btn_down, "Bajar escena seleccionada")


def on_enter_escena(event):
    global escena_en_ejecucion

    # Si una escena está corriendo → BLOQUEAR ENTER
    if escena_en_ejecucion:
        return "break"

    # Si NO hay escena ejecutándose → permitir ejecución normal
    try:
        on_listbox_enter(event)
    except:
        pass
    

actualizar_lista_escenas()
listbox_escenas.bind("<<ListboxSelect>>", mostrar_fades_de_escena)
listbox_escenas.bind("<Return>", on_listbox_enter)




def escena_seleccionada_en_listbox():
    """
    Devuelve el nombre de la escena seleccionada en el listbox de escenas,
    o None si no hay nada seleccionado.
    """
    sel = listbox_escenas.curselection()
    if not sel:
        return None
    return listbox_escenas.get(sel)

#____________________________inicio_MIDI______________________________________________________________

from tablero.midi_listener import start_midi_thread


def handle_midi_event(event):
    note = event.get("note")
    vel = event.get("velocity")
    status = event.get("status")

    # ----------------------------
    # NOTE ON → ejecutar acción
    # ----------------------------
    if event.get("note_on"):

        # Primero: ejecutar la acción asignada
        if note in note_map:
            try:
                note_map[note]()
            except Exception as e:
                print("[MIDI ERROR] en ejecución de note_map:", e)

        # -----------------------------------------
        # FEEDBACK ESPECIAL PARA 6 (APAGAR) y 7 (ENCENDER)
        # -----------------------------------------
        COLOR_ACTIVO_ENCENDER = 13     # amarillo intenso
        COLOR_INACTIVO_ENCENDER = 3   # azul tenue

        COLOR_ACTIVO_APAGAR = 5       # rojo fuerte
        COLOR_INACTIVO_APAGAR = 3     # azul tenue

        if note == 7:   # ENCENDER TODO
            midi_led(7, COLOR_ACTIVO_ENCENDER)
            midi_led(6, COLOR_INACTIVO_APAGAR)
            return  # luego de LED no procesamos efectos

        if note == 6:   # APAGAR TODO
            midi_led(6, COLOR_ACTIVO_APAGAR)
            midi_led(7, COLOR_INACTIVO_ENCENDER)
            return

        # -----------------------------------------
        # FEEDBACK PARA EFECTOS
        # -----------------------------------------
        efectos_validos = {16, 24, 32, 40, 48, 56}
        botones_especiales = {6, 7, 0}

        # Si es efecto: LED verde (activo)
        if note in efectos_validos:
            led_activo(note)
            return

        # Si es botón especial (refresh): no tocar LED
        if note in botones_especiales:
            return

        # Otros → no hacen nada visual
        return


    # ----------------------------
    # CC (control change → fader)
    # ----------------------------
    if (status & 0xF0) == 0xB0:   # CC
        cc = note
        value = vel
        if cc in cc_map:
            try:
                cc_map[cc](value)
            except Exception as e:
                print("[MIDI ERROR] en ejecución de cc_map:", e)


#funcion general para asignacion de los botones
def toggle_efecto(var, start_fn, nombre):
    if var.get():
        var.set(False)
        globals()[f"btn_{nombre}"].config(text=f"Iniciar {nombre}", bg="#20bdec")
        # el efecto se corta solo porque el ciclo lee la var
    else:
        var.set(True)
        start_fn()


def set_maestro_brillo_from_midi(v):
    # v viene 0-127 → lo mapeamos al rango del slider (0-1000)
    brillo = int((v / 127) * 255)
    maestro_brillo.set(brillo)
    maestro_on_brillo(brillo)



from tablero.midi_listener import led_activo, led_inactivo
from tablero.helpers_wiz import restore_lamp_state
from tablero.efectos_wiz import efecto_golpe_de_tambor

midi_estado_efectos = {
    56: respirando,
    48: secuencia_var,
    40: secuencia_on_var,
    32: secuencia_off_var,
    24: parpadeo_var,
    16: estrobo_var,
    58: atardecer_var,
}

def actualizar_led_efecto(note):
    BOTONES_ESPECIALES = {0, 6, 7}

    # Nunca tocar LEDs especiales
    if note in BOTONES_ESPECIALES:
        return

    var = midi_estado_efectos.get(note)

    # Si no es efecto, no modificar LED
    if var is None:
        return

    # Efecto -> verde si activo, rojo si apagado
    if var.get():
        led_activo(note)
    else:
        led_inactivo(note)


# --- diccionario de mapeo MIDI ---
note_map = {

    # en el diccionario MIDI:
    56: lambda: root.after(0, lambda: (toggle_efecto(respirando, toggle_respiracion, "respiracion"), actualizar_led_efecto(56))),
    48: lambda: root.after(0, lambda: (toggle_efecto(secuencia_var, toggle_secuencia, "secuencia"), actualizar_led_efecto(48))),
    40: lambda: root.after(0, lambda: (toggle_efecto(secuencia_on_var, toggle_secuencia_on, "secuencia_on"), actualizar_led_efecto(40))),
    32: lambda: root.after(0, lambda: (toggle_efecto(secuencia_off_var, toggle_secuencia_off, "secuencia_off"), actualizar_led_efecto(32))),
    24: lambda: root.after(0, lambda: (toggle_efecto(parpadeo_var, toggle_parpadeo, "parpadeo"), actualizar_led_efecto(24))),
    16: lambda: root.after(0, lambda: (toggle_efecto(estrobo_var, toggle_estrobo, "estrobo"), actualizar_led_efecto(16))),

    # Maestro
    7: lambda: root.after(0, encender_todo),
    6: lambda: root.after(0, apagar_todo),   # ← FIX
    0: lambda: root.after(0, refresh_lamp_status),
    58: lambda: root.after(0, lambda: (toggle_efecto(atardecer_var, toggle_atardecer, "atardecer"), actualizar_led_efecto(10))),
    


}
    
note_map[2] = lambda: efecto_golpe_de_tambor(
    send_lamp_color_safe,
    get_lamp_state,
    restore_lamp_state,
    LAMP_IPS,
    selected_devices,
    root
)   
   
cc_map = {
     48: set_maestro_brillo_from_midi,  # fader 1
}

# --- activar el listener MIDI ---
# 1) Iniciar MIDI
if start_midi_thread(handle_midi_event):
    # 2) Una vez que MIDI está listo, esperar un poco
    #    y luego encender LEDs de acciones
    root.after(1200, lambda: inicializar_leds(note_map.keys()))
else:
    print("[MIDI] No se pudo iniciar MIDI.")



#______________________________FIN MIDI_________________________________________________



# CIERRE PANEL ESCENAS_________________________________________________________________________________________________________

# refresco inteligente cada 1.2 s
# def refresco_periodico():
#     refresh_lamp_status()
#     root.after(1200, refresco_periodico)
# root.after(1200, refresco_periodico)
root.after(800, refresh_lamp_status)

root.mainloop()