import rtmidi
import tkinter as tk
from tkinter import messagebox
import json
import colorsys
import asyncio
import os
import subprocess
from pywizlight import wizlight, PilotBuilder
from tablero.real_colorwheel import RealColorWheel, WhiteTempWheel
from tablero.config import (
    LAMP_IPS,
    LAMPS_CONFIG,
    lamp_names as CONFIG_LAMP_NAMES,
    load_lamps_config,
    save_lamps_config,
)  # Lista de IPs
import time
import threading
import uuid
import random
import screeninfo
from concurrent.futures import wait
from tablero.midi_listener import (
    start_midi_thread,
    stop_midi,
    inicializar_leds,
    midi_led,
    led_activo,
    led_inactivo,
    get_available_ports,
    get_midi_status,
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
active_scene_runtime = {
    "name": None,
    "data": None,
    "target_ips": set(),
    "effects": set(),
}
espacio_midi_effect_ips = set()

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


def mostrar_ventana_inicio():
    try:
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.after(500, lambda: root.attributes("-topmost", False))
        root.focus_force()
    except Exception as exc:
        print(f"[WARN] No se pudo traer la ventana al frente: {exc}")


root.after(100, mostrar_ventana_inicio)


def bind_mousewheel_scroll(scroll_target, *hover_widgets, horizontal=False, skip_form_controls=True):
    hover_widgets = hover_widgets or (scroll_target,)

    def pointer_inside(widget):
        try:
            x = widget.winfo_pointerx()
            y = widget.winfo_pointery()
            left = widget.winfo_rootx()
            top = widget.winfo_rooty()
            right = left + widget.winfo_width()
            bottom = top + widget.winfo_height()
            return left <= x <= right and top <= y <= bottom
        except Exception:
            return False

    def pointer_inside_any():
        return any(pointer_inside(widget) for widget in hover_widgets)

    def should_skip(event):
        if not pointer_inside_any():
            return True
        if not skip_form_controls:
            return False
        try:
            widget_class = event.widget.winfo_class()
        except Exception:
            return False
        return widget_class in {"Scale", "TScale", "Spinbox", "TSpinbox", "Entry", "TEntry", "Combobox", "TCombobox"}

    def scroll_units(delta):
        if delta == 0:
            return 0
        return -1 if delta > 0 else 1

    def on_mousewheel(event):
        if should_skip(event):
            return None
        units = scroll_units(getattr(event, "delta", 0))
        if units:
            try:
                if horizontal:
                    scroll_target.xview_scroll(units, "units")
                else:
                    scroll_target.yview_scroll(units, "units")
                return "break"
            except Exception:
                return None
        return None

    def on_button4(event):
        if should_skip(event):
            return None
        try:
            if horizontal:
                scroll_target.xview_scroll(-1, "units")
            else:
                scroll_target.yview_scroll(-1, "units")
            return "break"
        except Exception:
            return None

    def on_button5(event):
        if should_skip(event):
            return None
        try:
            if horizontal:
                scroll_target.xview_scroll(1, "units")
            else:
                scroll_target.yview_scroll(1, "units")
            return "break"
        except Exception:
            return None

    try:
        root.bind_all("<MouseWheel>", on_mousewheel, add="+")
        root.bind_all("<Button-4>", on_button4, add="+")
        root.bind_all("<Button-5>", on_button5, add="+")
    except Exception:
        pass


selected_devices = {ip: tk.BooleanVar(value=False) for ip in LAMP_IPS}
panels = {}


def get_lamp_config(ip):
    if not LAMPS_CONFIG:
        return {}
    for lamp in LAMPS_CONFIG.get("lamparas", []):
        if lamp.get("ip") == ip:
            return lamp
    return {}


def get_lamp_group(ip):
    return get_lamp_config(ip).get("grupo_default", "sin_grupo")


def get_lamp_id(ip):
    return get_lamp_config(ip).get("id_escenico", ip)


def get_lamp_numeric_id(ip):
    text = str(get_lamp_id(ip))
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return int(digits)
    return 999999


def get_sequence_ordered_lamp_ips():
    return sorted(
        LAMP_IPS,
        key=lambda ip: (get_lamp_numeric_id(ip), str(get_lamp_id(ip)), ip)
    )


ESPACIO_LABERINTOS_FILE = "espacio_laberintos.json"
ESPACIO_DEFAULT_ROWS = 4
ESPACIO_DEFAULT_COLS = 6
ESPACIO_MAX_ROWS = 4
ESPACIO_MAX_COLS = 6
APC_ESPACIO_ROWS = (
    tuple(range(57, 63)),
    tuple(range(49, 55)),
    tuple(range(41, 47)),
    tuple(range(33, 39)),
)
APC_ESPACIO_NOTES = {note for row in APC_ESPACIO_ROWS for note in row}
APC_ESPACIO_LED_CONNECTED = 21
APC_ESPACIO_LED_DISCONNECTED = 5
APC_ESPACIO_LED_EMPTY = 0


def load_espacio_laberintos():
    default_data = {
        "version": 1,
        "rows": ESPACIO_DEFAULT_ROWS,
        "cols": ESPACIO_DEFAULT_COLS,
        "placements": {},
    }
    if not os.path.exists(ESPACIO_LABERINTOS_FILE):
        return default_data
    try:
        with open(ESPACIO_LABERINTOS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = int(data.get("rows", ESPACIO_DEFAULT_ROWS))
        cols = int(data.get("cols", ESPACIO_DEFAULT_COLS))
        placements = data.get("placements", {})
        if not isinstance(placements, dict):
            placements = {}
        return {
            "version": 1,
            "rows": max(1, min(ESPACIO_MAX_ROWS, rows)),
            "cols": max(1, min(ESPACIO_MAX_COLS, cols)),
            "placements": placements,
        }
    except Exception as e:
        print(f"No se pudo cargar ESPACIO LABERINTOS: {e}")
        return default_data


def save_espacio_laberintos(data):
    try:
        with open(ESPACIO_LABERINTOS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        messagebox.showerror("ESPACIO LABERINTOS", f"No se pudo guardar el espacio:\n{e}")
        return False


def get_lamp_ip_by_id(lamp_id):
    lamp_id = str(lamp_id)
    for ip in LAMP_IPS:
        if str(get_lamp_id(ip)) == lamp_id:
            return ip
    return None


def get_apc_espacio_note(row, col):
    try:
        row = int(row)
        col = int(col)
    except Exception:
        return None
    if row < 0 or col < 0 or row >= len(APC_ESPACIO_ROWS) or col >= len(APC_ESPACIO_ROWS[row]):
        return None
    return APC_ESPACIO_ROWS[row][col]


def is_apc_espacio_note(note):
    try:
        return int(note) in APC_ESPACIO_NOTES
    except Exception:
        return False



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

        # ---------------------------------------
        # UI: LÁMPARA OFFLINE (rojo)
        # ---------------------------------------
        else:
            lamp_state[ip] = {
                "brightness": 0,
                "mode": "colour",
                "hue": 0,
                "sat": 1,
                "temp": 4000
            }

        apply_visual = globals().get("apply_lamp_visual_state")
        if callable(apply_visual):
            apply_visual(panel)

    refresh_espacio = globals().get("refresh_espacio_laberintos_visual")
    if callable(refresh_espacio):
        refresh_espacio()



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
    Convierte el valor del control (0-255) a Kelvin (2200-6500 K).
    """
    try:
        value = max(0.0, min(255.0, float(value)))
    except Exception:
        value = 128.0
    return int(2200 + (value / 255.0) * (6500 - 2200))


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
        asyncio.run_coroutine_threadsafe(_do(), loop)
    else:
        loop.run_until_complete(_do())
        

def normalize_scene_colortemp(value):
    try:
        value = float(value)
    except Exception:
        value = 128.0
    if value > 1000:
        return int(max(2200, min(6500, value)))
    return map_slider_to_wiz_temp(value)


def send_lamp_white_scene(ip, brillo, temp):
    if not lamp_status.get(ip, True):
        return

    brillo = safe_brightness(brillo)
    if brillo <= 0:
        send_off(ip)
        return

    colortemp = normalize_scene_colortemp(temp)

    async def _do():
        try:
            pilot = PilotBuilder(
                brightness=int(brillo),
                colortemp=int(colortemp)
            )
            await get_wiz(ip).turn_on(pilot)
        except Exception as e:
            print(f"[send_lamp_white_scene] error {ip}: {e}")

    loop = get_or_create_event_loop()
    if loop.is_running():
        asyncio.run_coroutine_threadsafe(_do(), loop)
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
    return map_slider_to_wiz_temp(slider_value)

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
    future_by_ip = {
        asyncio.run_coroutine_threadsafe(_check_online_async(ip), loop): ip
        for ip in LAMP_IPS
    }

    done, pending = wait(future_by_ip, timeout=1.2)
    for fut in pending:
        fut.cancel()

    online = []
    for fut in done:
        try:
            if fut.result():
                ip = future_by_ip[fut]
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
lamp_names.update(CONFIG_LAMP_NAMES)


# 0 ------ FRAME PRINCIPAL
frame_main = tk.Frame(root, bg="#181b1e")
frame_main.pack(fill="both", expand=True)

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

scene_effect_enabled_var = tk.BooleanVar(value=False)
scene_effect_category_var = tk.StringVar(value="Escena / color configurable")
scene_effect_display_var = tk.StringVar(value="")
scene_effect_name_var = tk.StringVar(value="")
scene_effect_target_var = tk.StringVar(value="seleccion")
scene_effect_status_var = tk.StringVar(value="Sin efecto asociado")
scene_effect_combo = None


def scene_effect_options_for_category(category):
    return [
        effect_name
        for effect_name in effect_categories.get(category, [])
        if effect_name in effect_vars
    ]


def update_scene_effect_options(selected_effect=None):
    global scene_effect_combo
    options = scene_effect_options_for_category(scene_effect_category_var.get())
    display_values = [effect_display_names.get(name, name) for name in options]
    if scene_effect_combo is not None:
        scene_effect_combo.configure(values=display_values)

    if selected_effect in options:
        scene_effect_name_var.set(selected_effect)
    elif options:
        scene_effect_name_var.set(options[0])
    else:
        scene_effect_name_var.set("")

    sync_scene_effect_display()
    update_scene_effect_status()


def on_scene_effect_display_selected(event=None):
    options = scene_effect_options_for_category(scene_effect_category_var.get())
    display_value = scene_effect_display_var.get()
    for effect_name in options:
        if effect_display_names.get(effect_name, effect_name) == display_value:
            scene_effect_name_var.set(effect_name)
            break
    update_scene_effect_status()


def sync_scene_effect_display():
    effect_name = scene_effect_name_var.get()
    scene_effect_display_var.set(effect_display_names.get(effect_name, effect_name) if effect_name else "")


def update_scene_effect_status(*_):
    if not scene_effect_enabled_var.get():
        scene_effect_status_var.set("Sin efecto asociado")
        return

    effect_name = scene_effect_name_var.get()
    if not effect_name:
        scene_effect_status_var.set("Elige un efecto")
        return

    category = effect_to_category.get(effect_name, scene_effect_category_var.get())
    label = effect_display_names.get(effect_name, effect_name)
    scene_effect_status_var.set(f"{label} - {category}")


def on_scene_effect_category_changed(event=None):
    update_scene_effect_options()


def load_scene_effect_controls(scene_data):
    layers = scene_data.get("effects_layers") or []
    effect_name = None
    target_mode = "seleccion"

    if layers:
        first_layer = layers[0]
        effect_name = first_layer.get("name")
        target = first_layer.get("target", {})
        if target.get("mode") == "group":
            target_mode = target.get("group", "seleccion")
        elif target.get("mode") == "all":
            target_mode = "todas"
        else:
            target_mode = "seleccion"
    else:
        effect_name = get_first_enabled_effect(scene_data.get("effects", {}))

    if effect_name and effect_name in effect_vars:
        scene_effect_enabled_var.set(True)
        scene_effect_category_var.set(effect_to_category.get(effect_name, "Escena / color configurable"))
        update_scene_effect_options(effect_name)
        scene_effect_target_var.set(target_mode)
    else:
        scene_effect_enabled_var.set(False)

    sync_scene_effect_display()
    update_scene_effect_status()

# tus acciones
from acciones.acciones import (
    efecto_respiracion,
    efecto_secuencia,
    secuencia_on,
    secuencia_on_overlay,
    secuencia_off,
    secuencia_off_overlay,
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
    efecto_intercambio_colores,
    efecto_transicion_color,
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

effect_param_vars = {
    "respiracion": {
        "brillo_min": tk.IntVar(value=1),
        "brillo_max": tk.IntVar(value=255),
    },
    "transicion_color": {
        "hue_destino": tk.IntVar(value=280),
        "sat_destino_pct": tk.IntVar(value=100),
        "duracion_ms": tk.IntVar(value=180000),
        "pasos": tk.IntVar(value=240),
    },
    "secuencia": {
        "brillo_on": tk.IntVar(value=255),
        "tiempo_on_ms": tk.IntVar(value=70),
        "cambio_ms": tk.IntVar(value=0),
        "cola_lamparas": tk.IntVar(value=1),
        "brillo_cola_pct": tk.IntVar(value=18),
        "brillo_fondo_pct": tk.IntVar(value=0),
    },
    "secuencia_on": {
        "tiempo_on_ms": tk.IntVar(value=4000),
    },
    "secuencia_on_overlay": {
        "tiempo_on_ms": tk.IntVar(value=4000),
    },
    "secuencia_off": {
        "tiempo_off_ms": tk.IntVar(value=20000),
        "fade_ms": tk.IntVar(value=20000),
        "pasos_fade": tk.IntVar(value=20),
    },
    "secuencia_off_overlay": {
        "tiempo_off_ms": tk.IntVar(value=20000),
        "fade_ms": tk.IntVar(value=20000),
        "pasos_fade": tk.IntVar(value=20),
    },
    "parpadeo": {
        "brillo_on": tk.IntVar(value=230),
        "brillo_off": tk.IntVar(value=0),
        "tiempo_on_ms": tk.IntVar(value=20),
        "tiempo_off_ms": tk.IntVar(value=20),
    },
    "estrobo": {
        "brillo_on": tk.IntVar(value=255),
        "brillo_off": tk.IntVar(value=0),
        "on_ms": tk.IntVar(value=70),
        "off_ms": tk.IntVar(value=70),
    },
    "estrobo_udp": {
        "on_ms": tk.IntVar(value=50),
        "off_ms": tk.IntVar(value=50),
    },
    "fuego": {
        "brillo_min": tk.IntVar(value=140),
        "brillo_max": tk.IntVar(value=255),
    },
    "vela": {
        "brillo_base": tk.IntVar(value=120),
    },
    "Intercambio": {
        "hue_a": tk.IntVar(value=0),
        "sat_a_pct": tk.IntVar(value=100),
        "hue_b": tk.IntVar(value=220),
        "sat_b_pct": tk.IntVar(value=100),
        "brillo_min": tk.IntVar(value=20),
        "brillo": tk.IntVar(value=220),
        "duracion_ms": tk.IntVar(value=10000),
        "pasos": tk.IntVar(value=100),
    },
}


def clamp_int(value, min_value, max_value):
    try:
        value = int(float(value))
    except Exception:
        value = min_value
    return max(min_value, min(max_value, value))


def apply_effect_target_selection(target):
    for ip in LAMP_IPS:
        group = get_lamp_group(ip)
        should_select = (
            target == "seleccion"
            and selected_devices[ip].get()
        ) or (
            target == "todas"
        ) or (
            target == "efectos"
            and group == "efectos"
        ) or (
            target == "atmosfera"
            and group == "atmosfera"
        )

        if target != "seleccion":
            selected_devices[ip].set(bool(should_select))

def toggle_respiracion():
    if respirando.get():
        params = effect_param_vars["respiracion"]
        btn_respiracion.config(text="Detener", bg="#ef5350")
        efecto_respiracion(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,   # ← PASAMOS lamp_status
            clamp_int(params["brillo_min"].get(), 1, 255),
            clamp_int(params["brillo_max"].get(), 1, 255),
            0.1,
            0.1,
            respirando,
            root,
            send_lamp_white=send_lamp_white
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


transicion_color_var = tk.BooleanVar(value=False)
transicion_color_runtime = {"on_finish": None}


def toggle_transicion_color():
    if transicion_color_var.get():
        params = effect_param_vars["transicion_color"]
        finish_cb = transicion_color_runtime.get("on_finish")
        transicion_color_runtime["on_finish"] = None
        btn_transicion_color.config(text="Detener", bg="#ef5350")

        def finish_transition():
            btn_transicion_color.config(text="Transicion color", bg="#20bdec")
            if finish_cb:
                finish_cb()
            else:
                effects_panel_status_var.set("Transicion a color finalizada")

        efecto_transicion_color(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            transicion_color_var,
            root,
            hue_destino=clamp_int(params["hue_destino"].get(), 0, 359),
            sat_destino=clamp_int(params["sat_destino_pct"].get(), 0, 100) / 100.0,
            duracion_ms=clamp_int(params["duracion_ms"].get(), 100, 600000),
            pasos=clamp_int(params["pasos"].get(), 1, 2000),
            on_step_cb=lambda ip: update_panel_visual(panels[ip]) if ip in panels else None,
            on_finish_cb=finish_transition,
        )
    else:
        transicion_color_runtime["on_finish"] = None
        btn_transicion_color.config(text="Transicion color", bg="#20bdec")


btn_transicion_color = tk.Checkbutton(
    frame_suaves,
    text="Transicion color",
    variable=transicion_color_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_transicion_color
)
btn_transicion_color.grid(row=0, column=1, padx=2, pady=2, sticky="ew")


# =========================== SECUENCIAS ==============================
secuencia_var = tk.BooleanVar(value=False)

def toggle_secuencia():
    if secuencia_var.get():
        params = effect_param_vars["secuencia"]
        btn_secuencia.config(text="Detener", bg="#ef5350")
        efecto_secuencia(
            send_lamp_color_safe,
            get_sequence_ordered_lamp_ips(),
            panels,
            selected_devices,
            lamp_status,
            clamp_int(params["brillo_on"].get(), 1, 255),
            clamp_int(params["tiempo_on_ms"].get(), 20, 60000),
            secuencia_var,
            root,
            send_lamp_white=send_lamp_white,
            cambio_ms=clamp_int(params["cambio_ms"].get(), 0, 60000),
            cola_lamparas=clamp_int(params["cola_lamparas"].get(), 0, 50),
            brillo_cola_pct=clamp_int(params["brillo_cola_pct"].get(), 0, 100),
            brillo_fondo_pct=clamp_int(params["brillo_fondo_pct"].get(), 0, 100),
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
secuencia_on_runtime = {"ips": None, "scene_data": None, "on_finish": None}


def build_sequence_destination_values(scene_data):
    valores_destino = {}
    for ip in LAMP_IPS:
        if ip not in scene_data:
            continue

        estado = scene_data[ip]
        panel = panels.get(ip)
        valores_destino[ip] = {
            "h": estado.get("h", getattr(panel, "last_hue", 0) if panel else 0),
            "s": estado.get("s", getattr(panel, "last_sat", 1) if panel else 1),
            "brillo": estado.get("brillo", getattr(panel, "last_brillo", 1) if panel else 1),
            "modo": estado.get("modo", getattr(panel, "last_mode", "colour") if panel else "colour"),
            "temp": estado.get("temp", getattr(panel, "last_temp", 4000) if panel else 4000),
            "state": estado.get("state", "on"),
        }
    return valores_destino


def toggle_secuencia_on():
    if secuencia_on_var.get():
        btn_secuencia_on.config(text="Detener", bg="#ef5350")

        runtime_scene_data = secuencia_on_runtime.get("scene_data")
        target_ips = secuencia_on_runtime.get("ips")
        finish_cb = secuencia_on_runtime.get("on_finish") or escena_finalizada_callback
        secuencia_on_runtime["scene_data"] = None
        secuencia_on_runtime["ips"] = None
        secuencia_on_runtime["on_finish"] = None

        if runtime_scene_data is not None:
            escena = None
            datos = runtime_scene_data
        else:
            escena = escena_seleccionada_en_listbox()
            escenas = load_escenas()
            datos = escenas["datos"].get(escena, {})

        valores_destino = build_sequence_destination_values(datos)

        secuencia_on(
            send_lamp_color=send_lamp_color_safe,
            LAMP_IPS=LAMP_IPS,
            panels=panels,
            selected_devices=selected_devices,
            lamp_status=lamp_status,
            valores_destino=valores_destino,
            tiempo_on_ms=clamp_int(effect_param_vars["secuencia_on"]["tiempo_on_ms"].get(), 20, 60000),
            secuencia_var=secuencia_on_var,
            root=root,
            nombre_escena=escena,
            btn_secuencia_on=btn_secuencia_on,
            on_finish_cb=finish_cb,
            target_ips=target_ips,
        )

    else:
        secuencia_on_runtime["scene_data"] = None
        secuencia_on_runtime["ips"] = None
        secuencia_on_runtime["on_finish"] = None
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


secuencia_on_overlay_var = tk.BooleanVar(value=False)
secuencia_on_overlay_target_override = {"ips": None, "scene_data": None, "on_finish": None}


def add_lamp_to_atardecer(ip):
    effect_retired_ips["atardecer"].discard(ip)
    panel = panels.get(ip)
    if panel is None:
        return

    reference = None
    for ref_ip in LAMP_IPS:
        if ref_ip == ip:
            continue
        if selected_devices[ref_ip].get() and ref_ip not in effect_retired_ips["atardecer"]:
            reference = panels.get(ref_ip)
            break

    if reference is not None:
        panel.last_mode = getattr(reference, "last_mode", "colour")
        panel.last_hue = getattr(reference, "last_hue", getattr(panel, "last_hue", 0))
        panel.last_sat = getattr(reference, "last_sat", getattr(panel, "last_sat", 1))
        panel.last_brillo = max(80, safe_brightness(getattr(reference, "last_brillo", 180)))
        if panel.last_mode == "colour":
            send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, panel.last_brillo)
        else:
            panel.last_temp = getattr(reference, "last_temp", getattr(panel, "last_temp", 4000))
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)
    else:
        panel.last_brillo = max(80, safe_brightness(getattr(panel, "last_brillo", 180)))
        if panel.last_mode == "colour":
            send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, panel.last_brillo)
        else:
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)
    update_panel_visual(panel)


def toggle_secuencia_on_overlay():
    if secuencia_on_overlay_var.get():
        params = effect_param_vars["secuencia_on_overlay"]
        target_ips = secuencia_on_overlay_target_override.get("ips")
        runtime_scene_data = secuencia_on_overlay_target_override.get("scene_data")
        finish_cb = secuencia_on_overlay_target_override.get("on_finish")
        secuencia_on_overlay_target_override["ips"] = None
        secuencia_on_overlay_target_override["scene_data"] = None
        secuencia_on_overlay_target_override["on_finish"] = None
        btn_secuencia_on_overlay.config(text="Detener", bg="#ef5350")

        if runtime_scene_data is not None:
            datos = runtime_scene_data
        else:
            escena = escena_seleccionada_en_listbox()
            escenas = load_escenas()
            datos = escenas["datos"].get(escena, {})

        valores_destino = build_sequence_destination_values(datos)

        def finish_overlay():
            btn_secuencia_on_overlay.config(text="Secuencia_ON FX", bg="#20bdec")
            if finish_cb:
                finish_cb()

        secuencia_on_overlay(
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            clamp_int(params["tiempo_on_ms"].get(), 20, 60000),
            secuencia_on_overlay_var,
            root,
            target_ips=target_ips,
            valores_destino=valores_destino,
            send_lamp_color=send_lamp_color_safe,
            send_lamp_white=send_lamp_white_scene,
            on_lamp_on_cb=lambda ip: update_panel_visual(panels[ip]) if ip in panels else None,
            on_finish_cb=finish_overlay,
        )
    else:
        secuencia_on_overlay_target_override["ips"] = None
        secuencia_on_overlay_target_override["scene_data"] = None
        secuencia_on_overlay_target_override["on_finish"] = None
        btn_secuencia_on_overlay.config(text="Secuencia_ON FX", bg="#20bdec")


btn_secuencia_on_overlay = tk.Checkbutton(
    frame_secuencias,
    text="Secuencia_ON FX",
    variable=secuencia_on_overlay_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_secuencia_on_overlay
)
btn_secuencia_on_overlay.grid(row=2, column=1, padx=3, pady=3, sticky="ew")


secuencia_off_var = tk.BooleanVar(value=False)

def toggle_secuencia_off():
    if secuencia_off_var.get():
        params = effect_param_vars["secuencia_off"]
        btn_secuencia_off.config(text="Detener", bg="#ef5350")
        secuencia_off(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            clamp_int(params["tiempo_off_ms"].get(), 20, 60000),
            secuencia_off_var,
            root,
            fade_ms=clamp_int(params["fade_ms"].get(), 20, 60000),
            pasos_fade=clamp_int(params["pasos_fade"].get(), 1, 200),
            send_lamp_white=send_lamp_white,
            on_finish_cb=lambda: btn_secuencia_off.config(text="Secuencia_OFF", bg="#20bdec")
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


secuencia_off_overlay_var = tk.BooleanVar(value=False)
secuencia_off_overlay_target_override = {"ips": None, "on_finish": None}


def toggle_secuencia_off_overlay():
    if secuencia_off_overlay_var.get():
        params = effect_param_vars["secuencia_off_overlay"]
        target_ips = secuencia_off_overlay_target_override.get("ips")
        finish_cb = secuencia_off_overlay_target_override.get("on_finish")
        secuencia_off_overlay_target_override["ips"] = None
        secuencia_off_overlay_target_override["on_finish"] = None
        btn_secuencia_off_overlay.config(text="Detener", bg="#ef5350")

        def finish_overlay():
            btn_secuencia_off_overlay.config(text="Secuencia_OFF FX", bg="#20bdec")
            if target_ips:
                for finished_ip in target_ips:
                    panel = panels.get(finished_ip)
                    if panel is not None:
                        selected_devices[finished_ip].set(False)
                        panel.last_brillo = 0
                        try:
                            panel.brillo_var.set(0)
                        except Exception:
                            pass
                        try:
                            update_lamp_state(
                                finished_ip,
                                getattr(panel, "last_mode", "colour"),
                                getattr(panel, "last_hue", 0),
                                getattr(panel, "last_sat", 1),
                                getattr(panel, "last_temp", 4000),
                                0,
                            )
                        except Exception:
                            pass
                        update_panel_visual(panel)
            stop_all_active_effects("fin Secuencia OFF FX")
            if finish_cb:
                finish_cb()

        secuencia_off_overlay(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            clamp_int(params["tiempo_off_ms"].get(), 20, 60000),
            secuencia_off_overlay_var,
            root,
            fade_ms=clamp_int(params["fade_ms"].get(), 20, 60000),
            pasos_fade=clamp_int(params["pasos_fade"].get(), 1, 200),
            send_lamp_white=send_lamp_white,
            on_finish_cb=finish_overlay,
            target_ips=target_ips,
            on_lamp_off_cb=retire_lamp_from_atardecer,
        )
    else:
        secuencia_off_overlay_target_override["ips"] = None
        secuencia_off_overlay_target_override["on_finish"] = None
        btn_secuencia_off_overlay.config(text="Secuencia_OFF FX", bg="#20bdec")


btn_secuencia_off_overlay = tk.Checkbutton(
    frame_secuencias,
    text="Secuencia_OFF FX",
    variable=secuencia_off_overlay_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_secuencia_off_overlay
)
btn_secuencia_off_overlay.grid(row=1, column=1, padx=3, pady=3, sticky="ew")


# =========================== FX / RÁPIDOS ============================
parpadeo_var = tk.BooleanVar(value=False)

def toggle_parpadeo():
    if parpadeo_var.get():
        params = effect_param_vars["parpadeo"]
        btn_parpadeo.config(text="Detener", bg="#ef5350")
        parpadeo(
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            parpadeo_var,
            brillo_on=clamp_int(params["brillo_on"].get(), 1, 255),
            brillo_off=clamp_int(params["brillo_off"].get(), 0, 255),
            tiempo_on_ms=clamp_int(params["tiempo_on_ms"].get(), 10, 60000),
            tiempo_off_ms=clamp_int(params["tiempo_off_ms"].get(), 10, 60000),
            
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
        params = effect_param_vars["estrobo"]
        btn_estrobo.config(text="Detener", bg="#ef5350")
        efecto_estrobo(
            send_lamp_color_safe,
            send_off,
            LAMP_IPS,
            panels,
            selected_devices,
            estrobo_var,
            root,
            brillo_on=clamp_int(params["brillo_on"].get(), 1, 255),
            brillo_off=clamp_int(params["brillo_off"].get(), 0, 255),
            on_ms=clamp_int(params["on_ms"].get(), 10, 60000),
            off_ms=clamp_int(params["off_ms"].get(), 10, 60000),
            send_lamp_white=send_lamp_white
            
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
        params = effect_param_vars["estrobo_udp"]
        estrobo_udp(
            LAMP_IPS,
            selected_devices,
            lamp_status,
            estrobo_udp_var,
            root,
            on_ms=clamp_int(params["on_ms"].get(), 10, 60000),
            off_ms=clamp_int(params["off_ms"].get(), 10, 60000),
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
        params = effect_param_vars["fuego"]
        btn_fuego.config(text="Detener", bg="#ef5350")
        efecto_fuego_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            fuego_var,
            root,
            brillo_min=clamp_int(params["brillo_min"].get(), 1, 255),
            brillo_max=clamp_int(params["brillo_max"].get(), 1, 255),
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
        params = effect_param_vars["vela"]
        btn_vela.config(text="Detener", bg="#ef5350")
        efecto_vela_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            vela_var,
            root,
            brillo_base=clamp_int(params["brillo_base"].get(), 1, 255),
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
effect_retired_ips = {"atardecer": set()}


def claim_lamps_for_manual_control(ips):
    if isinstance(ips, str):
        ips = [ips]

    claimed_ips = [ip for ip in ips if ip in panels]
    if not claimed_ips:
        return

    active_effects = [
        name for name, var in globals().get("effect_vars", {}).items()
        if getattr(var, "get", lambda: False)()
    ]
    if active_effects and "stop_all_active_effects" in globals():
        stop_all_active_effects("control manual")

    effect_retired_ips["atardecer"].clear()
    for ip in claimed_ips:
        panel = panels.get(ip)
        if panel is not None:
            panel.scene_involved = False
            apply_visual = globals().get("apply_lamp_visual_state")
            if callable(apply_visual):
                apply_visual(panel)


def retire_lamp_from_atardecer(ip):
    effect_retired_ips["atardecer"].add(ip)
    panel = panels.get(ip)
    if panel is None:
        return
    try:
        panel.last_brillo = max(80, safe_brightness(panel.brillo_var.get()))
    except Exception:
        panel.last_brillo = 180
    selected_devices[ip].set(False)
    update_panel_visual(panel)


def toggle_atardecer():
    if atardecer_var.get():
        effect_retired_ips["atardecer"].clear()
        btn_atardecer.config(text="Detener", bg="#ef5350")
        efecto_atardecer_wiz(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            atardecer_var,
            root,
            effect_retired_ips["atardecer"],
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





intercambio_var = tk.BooleanVar(value=False)
intercambio_runtime = {"on_finish": None}

def toggle_intercambio():
    if intercambio_var.get():
        params = effect_param_vars["Intercambio"]
        finish_cb = intercambio_runtime.get("on_finish")
        intercambio_runtime["on_finish"] = None
        btn_intercambio.config(text="Detener", bg="#ef5350")

        def finish_intercambio():
            btn_intercambio.config(text="Intercambio", bg="#20bdec")
            if finish_cb:
                finish_cb()

        efecto_intercambio_colores(
            send_lamp_color_safe,
            LAMP_IPS,
            panels,
            selected_devices,
            lamp_status,
            intercambio_var,
            root,
            color_a=(
                clamp_int(params["hue_a"].get(), 0, 359),
                clamp_int(params["sat_a_pct"].get(), 0, 100) / 100.0,
            ),
            color_b=(
                clamp_int(params["hue_b"].get(), 0, 359),
                clamp_int(params["sat_b_pct"].get(), 0, 100) / 100.0,
            ),
            brillo_min=clamp_int(params["brillo_min"].get(), 0, 255),
            brillo=clamp_int(params["brillo"].get(), 1, 255),
            duracion_ms=clamp_int(params["duracion_ms"].get(), 100, 120000),
            pasos=clamp_int(params["pasos"].get(), 2, 500),
            on_finish_cb=finish_intercambio,
        )
    else:
        intercambio_runtime["on_finish"] = None
        btn_intercambio.config(text="Intercambio", bg="#20bdec")

btn_intercambio = tk.Checkbutton(
    frame_fx,
    text="Intercambio",
    variable=intercambio_var,
    font=("Segoe UI", 12, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    command=toggle_intercambio
)
btn_intercambio.grid(row=1, column=0, padx=3, pady=3, sticky="ew")

#################_DEFINICIONES DE EFECTOS_##############################

effect_vars = {
    "respiracion": respirando,
    "transicion_color": transicion_color_var,
    "secuencia": secuencia_var,
    "secuencia_on": secuencia_on_var,
    "secuencia_on_overlay": secuencia_on_overlay_var,
    "secuencia_off": secuencia_off_var,
    "secuencia_off_overlay": secuencia_off_overlay_var,
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
    "Intercambio":intercambio_var
}

effect_toggles = {
    "respiracion": toggle_respiracion,
    "transicion_color": toggle_transicion_color,
    "secuencia": toggle_secuencia,
    "secuencia_on": toggle_secuencia_on,
    "secuencia_on_overlay": toggle_secuencia_on_overlay,
    "secuencia_off": toggle_secuencia_off,
    "secuencia_off_overlay": toggle_secuencia_off_overlay,
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
    "Intercambio":toggle_intercambio
}

effect_display_names = {
    "respiracion": "Respiracion",
    "transicion_color": "Transicion a color",
    "secuencia": "Secuencia",
    "secuencia_on": "Secuencia ON",
    "secuencia_on_overlay": "Secuencia ON FX",
    "secuencia_off": "Secuencia OFF",
    "secuencia_off_overlay": "Secuencia OFF FX",
    "parpadeo": "Parpadeo",
    "estrobo": "Estrobo",
    "estrobo_udp": "Estrobo UDP",
    "fuego": "Fuego",
    "mar": "Mar / Oceanico",
    "arcoiris": "Arcoiris",
    "vela": "Vela",
    "atardecer": "Atardecer",
    "desfase": "Desfase",
    "latido": "Latido",
    "Intercambio": "Intercambio",
}

effect_descriptions = {
    "respiracion": "Pulso suave de brillo sobre las lamparas seleccionadas. Mantiene el color actual y genera una atmosfera viva.",
    "transicion_color": "Mueve las lamparas desde su color actual hacia un color destino de forma gradual.",
    "secuencia": "Recorre las lamparas una a una como una persecucion luminica, con opcion de cola y fondo.",
    "secuencia_on": "Enciende las lamparas una por una hasta llegar al estado de color configurado para la escena.",
    "secuencia_on_overlay": "Prueba o ejecuta un encendido progresivo sobre una escena o grupo, ideal para revelar una atmosfera por capas.",
    "secuencia_off": "Apaga las lamparas una por una usando el estado seleccionado como punto de salida.",
    "secuencia_off_overlay": "Retira lamparas de un efecto activo una por una, conservando la imagen viva hasta apagarlas.",
    "parpadeo": "Alterna brillo alto y bajo rapidamente para generar pulso ritmico o alerta visual.",
    "estrobo": "Flash rapido de alta intensidad para impactos cortos y momentos de tension.",
    "estrobo_udp": "Version tecnica de estrobo con envio UDP rapido para pruebas de respuesta.",
    "fuego": "Variacion calida e irregular de brillo y color, pensada para sensacion de llama.",
    "mar": "Movimiento frio y ondulante de azules y cianes para atmosfera acuosa.",
    "arcoiris": "Recorrido continuo por distintos tonos de color.",
    "vela": "Parpadeo sutil y calido, similar a una vela o luz fragil.",
    "atardecer": "Transicion atmosferica hacia tonos calidos, suave y envolvente.",
    "desfase": "Variacion entre lamparas con tiempos desplazados para dar profundidad y movimiento.",
    "latido": "Pulso marcado de brillo, pensado como golpe organico o tension escenica.",
    "Intercambio": "Divide las lamparas en dos grupos: bajan al brillo minimo, cambian al color opuesto y vuelven a subir.",
}

effect_categories = {
    "Escena / color configurable": [
        "respiracion",
        "transicion_color",
        "secuencia",
        "secuencia_on",
        "secuencia_on_overlay",
        "secuencia_off",
        "secuencia_off_overlay",
        "Intercambio",
    ],
    "Predefinidos atmosfericos": [
        "fuego",
        "mar",
        "arcoiris",
        "vela",
        "atardecer",
        "desfase",
        "latido",
    ],
    "Ritmo / impacto": [
        "parpadeo",
        "estrobo",
        "estrobo_udp",
    ],
}

effect_category_descriptions = {
    "Escena / color configurable": "Usan la seleccion de lamparas y pueden acompañar una escena con colores configurados.",
    "Predefinidos atmosfericos": "Tienen una identidad visual propia; el color principal viene dado por el efecto.",
    "Ritmo / impacto": "Efectos de pulso, golpe o corte rapido para momentos puntuales.",
}

effect_category_types = {
    "Escena / color configurable": "uses_scene_color",
    "Predefinidos atmosfericos": "predefined",
    "Ritmo / impacto": "impact",
}

effect_to_category = {
    effect_name: category
    for category, names in effect_categories.items()
    for effect_name in names
}


effect_param_labels = {
    "brillo_min": "Brillo minimo",
    "brillo_max": "Brillo maximo",
    "brillo_on": "Brillo encendido",
    "brillo_off": "Brillo apagado",
    "brillo": "Brillo",
    "brillo_base": "Brillo base",
    "tiempo_on_ms": "Tiempo encendido (ms)",
    "tiempo_off_ms": "Tiempo apagado (ms)",
    "cambio_ms": "Cambio entre lamparas (ms)",
    "cola_lamparas": "Cola (lamparas)",
    "brillo_cola_pct": "Brillo cola (%)",
    "brillo_fondo_pct": "Brillo fondo (%)",
    "fade_ms": "Fade (ms)",
    "pasos_fade": "Pasos fade",
    "on_ms": "On (ms)",
    "off_ms": "Off (ms)",
    "hue_destino": "Color destino Hue",
    "sat_destino_pct": "Saturacion destino (%)",
    "hue_a": "Color A Hue",
    "sat_a_pct": "Saturacion A (%)",
    "hue_b": "Color B Hue",
    "sat_b_pct": "Saturacion B (%)",
    "duracion_ms": "Duracion (ms)",
    "pasos": "Pasos",
}

effect_target_var = tk.StringVar(value="seleccion")
effects_panel_window = None
lamp_config_window = None
effects_panel_status_var = tk.StringVar(value="Selecciona un efecto")
effects_panel_countdown_var = tk.StringVar(value="Sin prueba activa")
effects_panel_test_state = {"effect": None, "after_id": None}


def cancel_effect_test_timer():
    after_id = effects_panel_test_state.get("after_id")
    if after_id:
        try:
            root.after_cancel(after_id)
        except Exception:
            pass
    effects_panel_test_state["after_id"] = None


def finish_effect_test(effect_name=None, message=None):
    cancel_effect_test_timer()
    effects_panel_test_state["effect"] = None
    effects_panel_countdown_var.set("Sin prueba activa")
    if message:
        effects_panel_status_var.set(message)
    elif effect_name:
        effects_panel_status_var.set(f"Prueba finalizada: {effect_display_names.get(effect_name, effect_name)}")


def start_effect_test_timer(effect_name, seconds):
    cancel_effect_test_timer()
    effect_label = effect_display_names.get(effect_name, effect_name)
    if seconds is None or seconds <= 0:
        effects_panel_countdown_var.set(f"{effect_label}\nPrueba sin tiempo fijo")
        return

    end_time = time.time() + float(seconds)

    def tick():
        remaining = max(0, int(round(end_time - time.time())))
        minutes = remaining // 60
        secs = remaining % 60
        effects_panel_countdown_var.set(f"{effect_label}\nTiempo de prueba: {minutes:02d}:{secs:02d}")
        if remaining <= 0:
            effects_panel_test_state["after_id"] = None
            effects_panel_test_state["effect"] = None
            effects_panel_countdown_var.set(f"{effect_label}\nPrueba finalizada")
            effects_panel_status_var.set(f"Prueba finalizada: {effect_label}")
            return
        effects_panel_test_state["after_id"] = root.after(250, tick)

    tick()


def selected_effect_target_ips():
    target = effect_target_var.get()
    if target == "todas":
        return [ip for ip in LAMP_IPS]
    if target in ("efectos", "atmosfera"):
        return [ip for ip in LAMP_IPS if get_lamp_group(ip) == target]
    return [ip for ip in LAMP_IPS if selected_devices[ip].get()]


def panel_state_for_sequence_test(ip):
    panel = panels.get(ip)
    if panel is None:
        return {"state": "off"}

    try:
        brillo = safe_brightness(getattr(panel, "last_brillo", 0))
    except Exception:
        brillo = 0
    if brillo <= 0:
        try:
            brillo = safe_brightness(panel.brillo_var.get())
        except Exception:
            brillo = 0
    if brillo <= 0:
        brillo = 180

    estado = {
        "state": "on",
        "initial_state": "off",
        "modo": getattr(panel, "last_mode", "colour"),
        "brillo": brillo,
    }
    if estado["modo"] == "white":
        estado["temp"] = getattr(panel, "last_temp", 4000)
    else:
        estado["h"] = getattr(panel, "last_hue", 0)
        estado["s"] = getattr(panel, "last_sat", 1)
    return estado


def build_panel_sequence_test_scene_data(effect_name, target_ips):
    effects = {
        name: False
        for name in effect_vars
    }
    effects["_params"] = {
        name: {
            param: var.get()
            for param, var in params.items()
        }
        for name, params in effect_param_vars.items()
    }
    for name in effect_vars:
        effects[name] = False
    effects[effect_name] = True

    data = {
        "effects": effects,
        "effects_layers": [{
            "name": effect_name,
            "display_name": effect_display_names.get(effect_name, effect_name),
            "enabled": True,
            "category": effect_to_category.get(effect_name, "Sin categoria"),
            "type": effect_category_types.get(effect_to_category.get(effect_name, ""), "custom"),
            "target": build_effect_target_snapshot(effect_target_var.get()),
            "params": effects.get("_params", {}).get(effect_name, {}),
        }],
    }
    target_set = set(target_ips or [])
    for ip in LAMP_IPS:
        data[ip] = panel_state_for_sequence_test(ip) if ip in target_set else {"state": "off"}
    return data


def estimate_effect_test_seconds(effect_name, target_ips):
    count = max(1, sum(1 for ip in target_ips if lamp_status.get(ip, True)))
    params = effect_param_vars.get(effect_name, {})
    if effect_name in ("secuencia_on", "secuencia_on_overlay"):
        tiempo = clamp_int(params["tiempo_on_ms"].get(), 20, 60000)
        return max(0.5, count * tiempo / 1000.0)
    if effect_name == "secuencia_off":
        tiempo = clamp_int(params["tiempo_off_ms"].get(), 20, 60000)
        return max(0.5, count * tiempo / 1000.0)
    if effect_name == "secuencia_off_overlay":
        tiempo = clamp_int(params["tiempo_off_ms"].get(), 20, 60000)
        fade = clamp_int(params["fade_ms"].get(), 20, 60000)
        return max(0.5, (((count - 1) * tiempo) + fade) / 1000.0)
    if effect_name == "transicion_color":
        return max(0.5, clamp_int(params["duracion_ms"].get(), 100, 600000) / 1000.0)
    if effect_name == "Intercambio":
        return max(0.5, clamp_int(params["duracion_ms"].get(), 100, 120000) / 1000.0)
    return None


def start_effect_from_panel(effect_name):
    if not effect_name:
        effects_panel_status_var.set("Selecciona un efecto para probar")
        return

    finish_effect_test()
    stop_all_active_effects("nueva prueba")

    target = effect_target_var.get()
    apply_effect_target_selection(target)
    target_ips = selected_effect_target_ips()
    if not target_ips:
        effects_panel_status_var.set("No hay lamparas seleccionadas para la prueba")
        return

    var = effect_vars.get(effect_name)
    toggle = effect_toggles.get(effect_name)
    if var is None or toggle is None:
        return

    test_duration = estimate_effect_test_seconds(effect_name, target_ips)
    finish_cb = lambda name=effect_name: finish_effect_test(
        name,
        f"Prueba finalizada: {effect_display_names.get(name, name)}"
    )

    if effect_name == "secuencia_on":
        scene_data = build_panel_sequence_test_scene_data(effect_name, target_ips)
        secuencia_on_runtime["ips"] = set(target_ips)
        secuencia_on_runtime["scene_data"] = scene_data
        secuencia_on_runtime["on_finish"] = lambda _name=None: finish_cb()
    elif effect_name == "secuencia_on_overlay":
        scene_data = build_panel_sequence_test_scene_data(effect_name, target_ips)
        secuencia_on_overlay_target_override["ips"] = set(target_ips)
        secuencia_on_overlay_target_override["scene_data"] = scene_data
        secuencia_on_overlay_target_override["on_finish"] = finish_cb
    elif effect_name == "secuencia_off_overlay":
        secuencia_off_overlay_target_override["ips"] = set(target_ips)
        secuencia_off_overlay_target_override["on_finish"] = finish_cb
    elif effect_name == "transicion_color":
        transicion_color_runtime["on_finish"] = finish_cb
    elif effect_name == "Intercambio":
        intercambio_runtime["on_finish"] = finish_cb

    var.set(True)
    toggle()
    effects_panel_test_state["effect"] = effect_name
    start_effect_test_timer(effect_name, test_duration)
    effects_panel_status_var.set(f"Probando: {effect_display_names.get(effect_name, effect_name)}")


def stop_effect_from_panel(effect_name):
    if not effect_name:
        return
    var = effect_vars.get(effect_name)
    toggle = effect_toggles.get(effect_name)
    if var is None or toggle is None:
        return
    if var.get():
        var.set(False)
        toggle()
    finish_effect_test(effect_name, f"Prueba finalizada: {effect_display_names.get(effect_name, effect_name)}")


def stop_all_active_effects(reason=""):
    stopped = []
    for effect_name, var in effect_vars.items():
        if not var.get():
            continue

        toggle = effect_toggles.get(effect_name)
        var.set(False)
        if toggle is not None:
            try:
                toggle()
            except Exception as exc:
                print(f"[WARN] No se pudo detener efecto {effect_name}: {exc}")
        stopped.append(effect_display_names.get(effect_name, effect_name))

    if stopped:
        label = ", ".join(stopped[:3])
        if len(stopped) > 3:
            label += "..."
        suffix = f" ({reason})" if reason else ""
        effects_panel_status_var.set(f"Efectos detenidos: {label}{suffix}")


def build_effect_target_snapshot(target_mode):
    if target_mode == "efectos":
        return {"mode": "group", "group": "efectos"}
    if target_mode == "atmosfera":
        return {"mode": "group", "group": "atmosfera"}
    if target_mode == "todas":
        return {"mode": "all"}

    selected_lamps = [
        get_lamp_id(ip)
        for ip in LAMP_IPS
        if selected_devices[ip].get()
    ]
    return {"mode": "lamps", "lamps": selected_lamps}


def build_scene_effect_layers(effects_state, target_mode=None):
    params_state = effects_state.get("_params", {})
    target_mode = target_mode or effect_target_var.get()
    layers = []

    for effect_name, enabled in effects_state.items():
        if effect_name == "_params" or not enabled:
            continue

        category = effect_to_category.get(effect_name, "Sin categoria")
        layers.append({
            "name": effect_name,
            "display_name": effect_display_names.get(effect_name, effect_name),
            "enabled": True,
            "category": category,
            "type": effect_category_types.get(category, "custom"),
            "target": build_effect_target_snapshot(target_mode),
            "params": params_state.get(effect_name, {}),
        })

    return layers


def build_scene_save_effects_state():
    state = get_effects_state(effect_vars, effect_param_vars)
    for effect_name in effect_vars:
        state[effect_name] = False

    if not scene_effect_enabled_var.get():
        return state

    selected_effect = scene_effect_name_var.get()
    if selected_effect in effect_vars:
        state[selected_effect] = True
    return state


def get_scene_save_effect_target():
    try:
        return scene_effect_target_var.get()
    except Exception:
        return effect_target_var.get()


class BoolSnapshot:
    def __init__(self, value):
        self.value = bool(value)

    def get(self):
        return self.value


def build_scene_save_selected_devices():
    if not scene_effect_enabled_var.get():
        return selected_devices

    target = get_scene_save_effect_target()
    if target == "seleccion":
        return selected_devices

    def in_save_scope(ip):
        group = get_lamp_group(ip)
        if target == "todas":
            return True
        if target == "efectos":
            return group == "efectos"
        if target == "atmosfera":
            return group == "atmosfera"
        return selected_devices[ip].get()

    return {
        ip: BoolSnapshot(in_save_scope(ip))
        for ip in LAMP_IPS
    }


def get_first_enabled_effect(effects_state):
    for effect_name, enabled in effects_state.items():
        if effect_name != "_params" and enabled:
            return effect_name
    return None


def apply_scene_effect_target(scene_data):
    layers = scene_data.get("effects_layers") or []
    if not layers:
        return

    target = layers[0].get("target", {})
    mode = target.get("mode")

    if mode == "group":
        apply_effect_target_selection(target.get("group", "seleccion"))
    elif mode == "all":
        apply_effect_target_selection("todas")
    elif mode == "lamps":
        lamp_ids = set(target.get("lamps", []))
        for ip in LAMP_IPS:
            selected_devices[ip].set(get_lamp_id(ip) in lamp_ids)


def estimate_sequence_effect_seconds(scene_data, effect_name, target_ips):
    params = scene_data.get("effects", {}).get("_params", {}).get(effect_name, {})
    if target_ips is None:
        ips = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    else:
        ips = list(target_ips)
    count = sum(1 for ip in ips if lamp_status.get(ip, True))

    if effect_name == "secuencia_off_overlay":
        tiempo = clamp_int(params.get("tiempo_off_ms", effect_param_vars[effect_name]["tiempo_off_ms"].get()), 20, 60000)
        fade = clamp_int(params.get("fade_ms", effect_param_vars[effect_name]["fade_ms"].get()), 20, 60000)
        return max(0.5, (((max(1, count) - 1) * tiempo) + fade) / 1000.0)

    if effect_name == "secuencia_on":
        tiempo = clamp_int(params.get("tiempo_on_ms", effect_param_vars[effect_name]["tiempo_on_ms"].get()), 20, 60000)
        return max(0.5, max(1, count) * tiempo / 1000.0)

    if effect_name == "secuencia_on_overlay":
        tiempo = clamp_int(params.get("tiempo_on_ms", effect_param_vars[effect_name]["tiempo_on_ms"].get()), 20, 60000)
        return max(0.5, max(1, count) * tiempo / 1000.0)

    return 0.5


def finish_scene_sequence_execution(scene_token, scene_name):
    if scene_token and scene_name:
        finalizar_escena(scene_token, scene_name)
    else:
        marcar_escena_terminada()


def apply_scene_effects_for_execution(scene_data, scene_token=None, scene_name=None):
    effects = scene_data.get("effects", {})
    if effects.get("secuencia_off_overlay"):
        params_state = effects.get("_params", {}).get("secuencia_off_overlay", {})
        for param, value in params_state.items():
            var = effect_param_vars.get("secuencia_off_overlay", {}).get(param)
            if var is not None:
                var.set(value)

        if secuencia_off_overlay_var.get():
            secuencia_off_overlay_var.set(False)
            toggle_secuencia_off_overlay()

        secuencia_off_overlay_target_override["ips"] = resolve_scene_effect_target_ips(scene_data)
        secuencia_off_overlay_target_override["on_finish"] = (
            lambda token=scene_token, name=scene_name: finish_scene_sequence_execution(token, name)
        )
        secuencia_off_overlay_var.set(True)
        toggle_secuencia_off_overlay()
        return

    if effects.get("secuencia_on_overlay"):
        params_state = effects.get("_params", {}).get("secuencia_on_overlay", {})
        for param, value in params_state.items():
            var = effect_param_vars.get("secuencia_on_overlay", {}).get(param)
            if var is not None:
                var.set(value)

        if secuencia_on_overlay_var.get():
            secuencia_on_overlay_var.set(False)
            toggle_secuencia_on_overlay()

        secuencia_on_overlay_target_override["ips"] = resolve_scene_effect_target_ips(scene_data)
        secuencia_on_overlay_target_override["scene_data"] = scene_data
        secuencia_on_overlay_target_override["on_finish"] = (
            lambda token=scene_token, name=scene_name: finish_scene_sequence_execution(token, name)
        )
        secuencia_on_overlay_var.set(True)
        toggle_secuencia_on_overlay()
        return

    effect_retired_ips["atardecer"].clear()

    if effects.get("secuencia_on"):
        params_state = effects.get("_params", {}).get("secuencia_on", {})
        for param, value in params_state.items():
            var = effect_param_vars.get("secuencia_on", {}).get(param)
            if var is not None:
                var.set(value)

        if secuencia_on_var.get():
            secuencia_on_var.set(False)
            toggle_secuencia_on()

        secuencia_on_runtime["ips"] = resolve_scene_effect_target_ips(scene_data)
        secuencia_on_runtime["scene_data"] = scene_data
        secuencia_on_runtime["on_finish"] = (
            lambda _name=None, token=scene_token, name=scene_name: finish_scene_sequence_execution(token, name)
        )
        secuencia_on_var.set(True)
        toggle_secuencia_on()
        return

    if effects.get("transicion_color"):
        params_state = effects.get("_params", {}).get("transicion_color", {})
        for param, value in params_state.items():
            var = effect_param_vars.get("transicion_color", {}).get(param)
            if var is not None:
                var.set(value)

        if transicion_color_var.get():
            transicion_color_var.set(False)
            toggle_transicion_color()

        apply_scene_effect_target(scene_data)

        duration_ms = clamp_int(
            effect_param_vars["transicion_color"]["duracion_ms"].get(),
            100,
            600000,
        )
        if scene_token:
            try:
                start_scene_progress(scene_token, max(0.5, duration_ms / 1000.0))
            except Exception:
                pass

        transicion_color_runtime["on_finish"] = (
            lambda token=scene_token, name=scene_name: finish_scene_sequence_execution(token, name)
        )
        transicion_color_var.set(True)
        toggle_transicion_color()
        return

    apply_scene_effect_target(scene_data)
    apply_effects_state(
        effects,
        effect_vars,
        effect_toggles,
        effect_param_vars,
    )


def open_lamp_config_panel():
    global lamp_config_window

    if lamp_config_window and lamp_config_window.winfo_exists():
        lamp_config_window.lift()
        lamp_config_window.focus_force()
        return

    win = tk.Toplevel(root)
    lamp_config_window = win
    win.title("Configuracion de lamparas")
    win.configure(bg="#181b1e")
    win.geometry("820x520")
    win.minsize(720, 420)

    def on_close():
        global lamp_config_window
        lamp_config_window = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    config = load_lamps_config() or {"version": 1, "lamparas": []}

    frame = tk.Frame(win, bg="#181b1e")
    frame.pack(fill="both", expand=True, padx=10, pady=10)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(1, weight=1)

    header = tk.Frame(frame, bg="#181b1e")
    header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    header.grid_columnconfigure(0, weight=1)

    tk.Label(header, text="Lamparas y grupos", bg="#181b1e", fg="#20bdec",
             font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")

    status_var = tk.StringVar(value="Edita una fila o agrega una lampara nueva")
    tk.Label(header, textvariable=status_var, bg="#181b1e", fg="#b9e3f7",
             font=("Segoe UI", 9)).grid(row=0, column=1, sticky="e")

    columns = ("id", "alias", "ip", "grupo", "orden", "activa")
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
    headings = {"id": "ID", "alias": "Nombre", "ip": "IP", "grupo": "Grupo", "orden": "Orden", "activa": "Activa"}
    widths = {"id": 80, "alias": 120, "ip": 130, "grupo": 110, "orden": 70, "activa": 70}
    for col in columns:
        tree.heading(col, text=headings[col])
        tree.column(col, width=widths[col], anchor="w")
    tree.grid(row=1, column=0, sticky="nsew")
    scroll = tk.Scrollbar(frame, orient="vertical", command=tree.yview)
    scroll.grid(row=1, column=1, sticky="ns")
    tree.configure(yscrollcommand=scroll.set)
    bind_mousewheel_scroll(tree, tree, skip_form_controls=False)

    def sorted_lamps():
        return sorted(config.get("lamparas", []), key=lambda item: int(item.get("orden", 9999)))

    def group_key_to_label(group):
        if group == "efectos":
            return "bichos"
        return group

    def group_label_to_key(label):
        if label == "bichos":
            return "efectos"
        return label

    def refresh_tree():
        tree.delete(*tree.get_children())
        for lamp in sorted_lamps():
            tree.insert("", "end", values=(
                lamp.get("id_escenico", ""),
                lamp.get("alias", lamp.get("id_escenico", "")),
                lamp.get("ip", ""),
                group_key_to_label(lamp.get("grupo_default", "sin_grupo")),
                lamp.get("orden", 0),
                "si" if lamp.get("activa", True) else "no",
            ))

    form = tk.LabelFrame(frame, text="Edicion", bg="#181b1e", fg="#20bdec",
                         font=("Segoe UI", 10, "bold"), padx=8, pady=8)
    form.grid(row=2, column=0, sticky="ew", pady=(10, 0))

    id_var = tk.StringVar()
    alias_var = tk.StringVar()
    ip_var = tk.StringVar()
    group_var = tk.StringVar(value="bichos")
    order_var = tk.IntVar(value=1)
    active_var = tk.BooleanVar(value=True)

    for label, var, row, col, width in (
        ("ID", id_var, 0, 0, 10),
        ("Nombre", alias_var, 0, 2, 14),
        ("IP", ip_var, 0, 4, 15),
    ):
        tk.Label(form, text=label, bg="#181b1e", fg="#b9e3f7").grid(row=row, column=col, sticky="w", padx=(0, 4))
        tk.Entry(form, textvariable=var, width=width, bg="#111519", fg="#fff").grid(row=row, column=col + 1, sticky="w", padx=(0, 10))

    tk.Label(form, text="Grupo", bg="#181b1e", fg="#b9e3f7").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(8, 0))
    ttk.Combobox(form, textvariable=group_var, values=("bichos", "atmosfera", "sin_grupo"),
                 width=12, state="readonly").grid(row=1, column=1, sticky="w", padx=(0, 10), pady=(8, 0))

    tk.Label(form, text="Orden", bg="#181b1e", fg="#b9e3f7").grid(row=1, column=2, sticky="w", padx=(0, 4), pady=(8, 0))
    tk.Spinbox(form, from_=1, to=200, textvariable=order_var, width=6, bg="#111519", fg="#fff").grid(row=1, column=3, sticky="w", padx=(0, 10), pady=(8, 0))

    tk.Checkbutton(form, text="Activa", variable=active_var, bg="#181b1e", fg="#b9e3f7",
                   selectcolor="#212529").grid(row=1, column=4, sticky="w", pady=(8, 0))

    def next_lamp_id():
        used = []
        for lamp in config.get("lamparas", []):
            scenic_id = str(lamp.get("id_escenico", ""))
            if scenic_id.upper().startswith("L") and scenic_id[1:].isdigit():
                used.append(int(scenic_id[1:]))
        return f"L{(max(used) + 1) if used else 1}"

    def next_order():
        values = []
        for lamp in config.get("lamparas", []):
            try:
                values.append(int(lamp.get("orden", 0)))
            except Exception:
                pass
        return (max(values) + 1) if values else 1

    def load_selected(event=None):
        selected = tree.selection()
        if not selected:
            return
        values = tree.item(selected[0], "values")
        id_var.set(values[0])
        alias_var.set(values[1])
        ip_var.set(values[2])
        group_var.set(values[3])
        order_var.set(int(values[4]))
        active_var.set(values[5] == "si")

    tree.bind("<<TreeviewSelect>>", load_selected)

    def clear_form():
        id_var.set(next_lamp_id())
        alias_var.set(id_var.get())
        ip_var.set("")
        group_var.set("sin_grupo")
        order_var.set(next_order())
        active_var.set(True)
        tree.selection_remove(tree.selection())

    def upsert_from_form():
        scenic_id = id_var.get().strip()
        alias = alias_var.get().strip() or scenic_id
        ip = ip_var.get().strip()
        group = group_label_to_key(group_var.get().strip() or "sin_grupo")
        if not scenic_id or not ip:
            messagebox.showwarning("Datos incompletos", "ID e IP son obligatorios.")
            return False
        for lamp in config.get("lamparas", []):
            if lamp.get("id_escenico") != scenic_id and lamp.get("ip") == ip:
                messagebox.showerror("IP duplicada", f"La IP {ip} ya esta asignada.")
                return False

        found = None
        for lamp in config.get("lamparas", []):
            if lamp.get("id_escenico") == scenic_id:
                found = lamp
                break
        if found is None:
            found = {}
            config.setdefault("lamparas", []).append(found)
        found.update({
            "id_escenico": scenic_id,
            "alias": alias,
            "ip": ip,
            "grupo_default": group,
            "activa": bool(active_var.get()),
            "orden": clamp_int(order_var.get(), 1, 200),
        })
        refresh_tree()
        status_var.set(f"Fila lista: {scenic_id}")
        return True

    def delete_selected():
        selected = tree.selection()
        if not selected:
            return
        scenic_id = tree.item(selected[0], "values")[0]
        if not messagebox.askyesno("Eliminar lampara", f"Quitar {scenic_id} de la configuracion?"):
            return
        config["lamparas"] = [lamp for lamp in config.get("lamparas", []) if lamp.get("id_escenico") != scenic_id]
        refresh_tree()
        clear_form()

    def save_config_from_panel():
        if ip_var.get().strip() and not upsert_from_form():
            return
        save_lamps_config({"version": config.get("version", 1), "lamparas": sorted_lamps()})
        status_var.set("Configuracion guardada")
        messagebox.showinfo(
            "Configuracion guardada",
            "Se guardo lamps_config.json.\nReinicia la aplicacion para reconstruir los paneles con los nuevos grupos.",
        )

    def add_discovered_ip(ip):
        if not ip:
            return False
        for lamp in config.get("lamparas", []):
            if lamp.get("ip") == ip:
                return False
        scenic_id = next_lamp_id()
        config.setdefault("lamparas", []).append({
            "id_escenico": scenic_id,
            "alias": scenic_id,
            "ip": ip,
            "grupo_default": "sin_grupo",
            "activa": True,
            "orden": next_order(),
        })
        return True

    def discover_lamps():
        status_var.set("Buscando lamparas en red...")

        def worker():
            found_ips = []
            try:
                from pywizlight.discovery import discover_lights
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                bulbs = loop.run_until_complete(discover_lights(broadcast_space="192.168.0.255", wait_time=4.0))
                loop.close()
                for bulb in bulbs:
                    ip = str(getattr(bulb, "ip", "") or getattr(bulb, "_ip", "") or getattr(bulb, "ip_address", "")).strip()
                    if ip:
                        found_ips.append(ip)
            except Exception as exc:
                root.after(0, lambda: messagebox.showerror("Busqueda fallida", str(exc)))
                root.after(0, lambda: status_var.set("No se pudo completar la busqueda"))
                return

            def finish():
                added = 0
                for ip in sorted(set(found_ips)):
                    if add_discovered_ip(ip):
                        added += 1
                refresh_tree()
                status_var.set(f"Detectadas: {len(set(found_ips))}. Nuevas: {added}.")

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    buttons = tk.Frame(frame, bg="#181b1e")
    buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    tk.Button(buttons, text="Nueva", command=clear_form, bg="#2b343b", fg="#fff", width=10).pack(side="left", padx=(0, 6))
    tk.Button(buttons, text="Agregar / actualizar", command=upsert_from_form, bg="#20bdec", fg="#fff", width=16).pack(side="left", padx=(0, 6))
    tk.Button(buttons, text="Buscar en red", command=discover_lamps, bg="#27ae60", fg="#fff", width=12).pack(side="left", padx=(0, 6))
    tk.Button(buttons, text="Eliminar", command=delete_selected, bg="#ef5350", fg="#fff", width=10).pack(side="left", padx=(0, 6))
    tk.Button(buttons, text="Guardar", command=save_config_from_panel, bg="#4fc3f7", fg="#000", width=10).pack(side="right")

    refresh_tree()
    clear_form()


def open_effects_config_panel():
    global effects_panel_window

    if effects_panel_window and effects_panel_window.winfo_exists():
        effects_panel_window.lift()
        effects_panel_window.focus_force()
        return

    win = tk.Toplevel(root)
    effects_panel_window = win
    win.title("Panel de efectos")
    win.configure(bg="#181b1e")
    win.transient(root)
    win.geometry("720x680")
    win.minsize(620, 560)

    def dock_to_workspace(event=None):
        try:
            root.update_idletasks()
            available_width = max(620, frame_right.winfo_rootx() - frame_center.winfo_rootx() - 34)
            width = min(760, available_width)
            height = min(720, max(560, root.winfo_height() - 80))
            x = max(frame_center.winfo_rootx() + 10, frame_right.winfo_rootx() - width - 14)
            y = root.winfo_rooty() + 44
            win.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")
        except Exception:
            pass

    def on_close():
        global effects_panel_window
        try:
            root.unbind("<Configure>", dock_bind_id)
        except Exception:
            pass
        effects_panel_window = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)
    dock_bind_id = root.bind("<Configure>", dock_to_workspace, add="+")
    win.after(80, dock_to_workspace)

    header = tk.Frame(win, bg="#181b1e")
    header.pack(fill="x", padx=12, pady=(10, 6))
    tk.Label(
        header,
        text="Efectos configurables",
        bg="#181b1e",
        fg="#20bdec",
        font=("Segoe UI", 15, "bold")
    ).pack(side="left")

    main = tk.Frame(win, bg="#181b1e")
    main.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    main.grid_columnconfigure(1, weight=1)
    main.grid_rowconfigure(0, weight=1)

    left = tk.Frame(main, bg="#181b1e", width=230)
    left.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
    left.grid_propagate(False)

    tk.Label(left, text="Categoria", bg="#181b1e", fg="#b9e3f7",
             font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
    category_var = tk.StringVar(value="Escena / color configurable")
    category_combo = ttk.Combobox(
        left,
        textvariable=category_var,
        values=list(effect_categories.keys()),
        state="readonly",
        width=24
    )
    category_combo.pack(fill="x", pady=(0, 6))

    category_desc_var = tk.StringVar(value=effect_category_descriptions.get(category_var.get(), ""))
    tk.Label(
        left,
        textvariable=category_desc_var,
        bg="#181b1e",
        fg="#8fb8c9",
        font=("Segoe UI", 8),
        wraplength=205,
        justify="left"
    ).pack(fill="x", pady=(0, 8))

    tk.Label(left, text="Lista de efectos", bg="#181b1e", fg="#b9e3f7",
             font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
    list_frame = tk.Frame(left, bg="#181b1e")
    list_frame.pack(fill="both", expand=True)
    effect_list = tk.Listbox(
        list_frame,
        bg="#111519",
        fg="#fff",
        selectbackground="#20bdec",
        activestyle="dotbox",
        font=("Segoe UI", 10),
        height=15,
        exportselection=False
    )
    effect_scroll = tk.Scrollbar(list_frame, orient="vertical", command=effect_list.yview)
    effect_list.configure(yscrollcommand=effect_scroll.set)
    bind_mousewheel_scroll(effect_list, effect_list, skip_form_controls=False)
    effect_scroll.pack(side="right", fill="y")
    effect_list.pack(side="left", fill="both", expand=True)

    visible_effects = []

    def load_category():
        visible_effects.clear()
        effect_list.delete(0, tk.END)
        category = category_var.get()
        category_desc_var.set(effect_category_descriptions.get(category, ""))
        for name in effect_categories.get(category, []):
            if name in effect_vars:
                visible_effects.append(name)
                effect_list.insert(tk.END, effect_display_names.get(name, name))
        if visible_effects:
            effect_list.selection_set(0)
            render_params(visible_effects[0])

    right = tk.Frame(main, bg="#202428")
    right.grid(row=0, column=1, sticky="nsew")
    right.grid_columnconfigure(0, weight=1)

    selected_effect_var = tk.StringVar(value="")
    title_var = tk.StringVar(value="Selecciona un efecto")
    effect_help_var = tk.StringVar(value="")

    tk.Label(right, textvariable=title_var, bg="#202428", fg="#20bdec",
             font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))

    help_box = tk.Frame(right, bg="#182024", padx=8, pady=6)
    help_box.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
    tk.Label(
        help_box,
        textvariable=effect_help_var,
        bg="#182024",
        fg="#d9f3ff",
        font=("Segoe UI", 9),
        wraplength=260,
        justify="left",
        anchor="w"
    ).pack(fill="x")

    scope = tk.LabelFrame(right, text="Aplicar a", bg="#202428", fg="#20bdec",
                          font=("Segoe UI", 10, "bold"), padx=8, pady=6)
    scope.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
    for label, value in (
        ("Seleccion actual", "seleccion"),
        ("Bichos", "efectos"),
        ("Atmosfera", "atmosfera"),
        ("Todas", "todas"),
    ):
        tk.Radiobutton(scope, text=label, variable=effect_target_var, value=value,
                       bg="#202428", fg="#d9f3ff", selectcolor="#202428",
                       activebackground="#202428", activeforeground="#20bdec",
                       font=("Segoe UI", 9)).pack(side="left", padx=(0, 10))

    params_frame = tk.LabelFrame(right, text="Parametros", bg="#202428", fg="#20bdec",
                                 font=("Segoe UI", 10, "bold"), padx=8, pady=8)
    params_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 8))
    params_frame.grid_columnconfigure(0, weight=1)
    params_frame.grid_rowconfigure(0, weight=1)
    params_canvas = tk.Canvas(params_frame, bg="#202428", highlightthickness=0, bd=0)
    params_scroll = tk.Scrollbar(params_frame, orient="vertical", command=params_canvas.yview)
    params_body = tk.Frame(params_canvas, bg="#202428")
    params_window = params_canvas.create_window((0, 0), window=params_body, anchor="nw")
    params_body.bind("<Configure>", lambda event: params_canvas.configure(scrollregion=params_canvas.bbox("all")))
    params_canvas.bind("<Configure>", lambda event: params_canvas.itemconfigure(params_window, width=event.width))
    params_canvas.configure(yscrollcommand=params_scroll.set)

    bind_mousewheel_scroll(params_canvas, params_canvas, params_body)
    params_canvas.grid(row=0, column=0, sticky="nsew")
    params_scroll.grid(row=0, column=1, sticky="ns")
    params_body.grid_columnconfigure(1, weight=1)
    right.grid_rowconfigure(3, weight=1)

    actions = tk.Frame(right, bg="#202428")
    actions.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 8))
    actions.grid_columnconfigure(0, weight=1)
    actions.grid_columnconfigure(1, weight=1)

    countdown_box = tk.Frame(
        right,
        bg="#111519",
        highlightthickness=1,
        highlightbackground="#20bdec",
        padx=8,
        pady=6
    )
    countdown_box.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 8))
    tk.Label(
        countdown_box,
        textvariable=effects_panel_countdown_var,
        bg="#111519",
        fg="#d9f3ff",
        font=("Segoe UI", 12, "bold"),
        anchor="center"
    ).pack(fill="x")

    def current_effect():
        return selected_effect_var.get()

    def render_params(effect_name):
        for child in params_body.winfo_children():
            child.destroy()

        selected_effect_var.set(effect_name)
        title_var.set(effect_display_names.get(effect_name, effect_name))
        effect_help_var.set(effect_descriptions.get(effect_name, "Sin descripcion disponible."))
        params = effect_param_vars.get(effect_name, {})
        if not params:
            tk.Label(params_body, text="Este efecto no tiene parametros configurables.",
                     bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w")
            return

        if effect_name == "transicion_color":
            color_box = tk.Frame(params_body, bg="#202428")
            color_box.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
            color_box.grid_columnconfigure(1, weight=1)

            hue_var = params["hue_destino"]
            sat_var = params["sat_destino_pct"]

            def preview_hex():
                h = clamp_int(hue_var.get(), 0, 359)
                s = clamp_int(sat_var.get(), 0, 100) / 100.0
                r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, 1.0)
                return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

            preview = tk.Frame(
                color_box,
                bg=preview_hex(),
                width=52,
                height=52,
                highlightthickness=1,
                highlightbackground="#d9f3ff"
            )
            preview.grid(row=0, column=1, sticky="nw", padx=(12, 0), pady=(10, 2))
            preview.grid_propagate(False)

            color_label = tk.StringVar()

            def sync_color_widgets():
                h = clamp_int(hue_var.get(), 0, 359)
                s_pct = clamp_int(sat_var.get(), 0, 100)
                hue_var.set(h)
                sat_var.set(s_pct)
                preview.config(bg=preview_hex())
                color_label.set(f"Hue {h} / Sat {s_pct}%")
                try:
                    wheel.set_color(h, s_pct / 100.0, 1.0)
                except Exception:
                    pass

            def on_color_pick(h, s, _v):
                hue_var.set(int(round(h)) % 360)
                sat_var.set(int(round(max(0.0, min(1.0, s)) * 100)))
                sync_color_widgets()

            wheel = RealColorWheel(
                color_box,
                radius=62,
                callback=on_color_pick,
                bg="#202428",
                bd=0,
                highlightthickness=0
            )
            wheel.grid(row=0, column=0, rowspan=2, sticky="w")

            tk.Label(
                color_box,
                textvariable=color_label,
                bg="#202428",
                fg="#b9e3f7",
                font=("Segoe UI", 9, "bold")
            ).grid(row=1, column=1, sticky="nw", padx=(12, 0))

            sync_color_widgets()

            row = 1
            for param, var in params.items():
                tk.Label(params_body, text=effect_param_labels.get(param, param),
                         bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=4)
                spin = tk.Spinbox(params_body, from_=0, to=600000, increment=1, textvariable=var,
                                  width=10, bg="#111519", fg="#e6e6e6",
                                  buttonbackground="#30363d", relief="flat",
                                  font=("Segoe UI", 10), command=sync_color_widgets)
                spin.grid(row=row, column=1, sticky="e", pady=4)
                if param in ("hue_destino", "sat_destino_pct"):
                    spin.bind("<KeyRelease>", lambda _event: sync_color_widgets())
                    spin.bind("<FocusOut>", lambda _event: sync_color_widgets())
                row += 1
            return

        if effect_name == "Intercambio":
            timing_box = tk.LabelFrame(
                params_body,
                text="Tiempo y brillo",
                bg="#202428",
                fg="#20bdec",
                font=("Segoe UI", 9, "bold"),
                padx=8,
                pady=6
            )
            timing_box.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
            timing_box.grid_columnconfigure(1, weight=1)
            timing_params = ("duracion_ms", "brillo_min", "brillo", "pasos")
            timing_labels = {
                "duracion_ms": "Duracion total (ms)",
                "brillo_min": "Brillo minimo",
                "brillo": "Brillo maximo",
                "pasos": "Suavidad / pasos",
            }
            for row_index, param in enumerate(timing_params):
                tk.Label(
                    timing_box,
                    text=timing_labels.get(param, effect_param_labels.get(param, param)),
                    bg="#202428",
                    fg="#b9e3f7",
                    font=("Segoe UI", 10)
                ).grid(row=row_index, column=0, sticky="w", pady=3)
                spin_to = 120000 if param == "duracion_ms" else 500 if param == "pasos" else 255
                spin_from = 100 if param == "duracion_ms" else 2 if param == "pasos" else 0
                tk.Spinbox(
                    timing_box,
                    from_=spin_from,
                    to=spin_to,
                    increment=1,
                    textvariable=params[param],
                    width=10,
                    bg="#111519",
                    fg="#e6e6e6",
                    buttonbackground="#30363d",
                    relief="flat",
                    font=("Segoe UI", 10)
                ).grid(row=row_index, column=1, sticky="e", pady=3)

            color_box = tk.Frame(params_body, bg="#202428")
            color_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
            color_box.grid_columnconfigure(0, weight=1)
            color_box.grid_columnconfigure(1, weight=1)

            def make_intercambio_color_picker(parent, col, title, hue_var, sat_var):
                holder = tk.Frame(parent, bg="#202428")
                holder.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))
                label_var = tk.StringVar()
                preview = tk.Frame(
                    holder,
                    width=46,
                    height=24,
                    highlightthickness=1,
                    highlightbackground="#d9f3ff"
                )

                def preview_hex():
                    h = clamp_int(hue_var.get(), 0, 359)
                    s = clamp_int(sat_var.get(), 0, 100) / 100.0
                    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, 1.0)
                    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

                def sync_widgets():
                    h = clamp_int(hue_var.get(), 0, 359)
                    s_pct = clamp_int(sat_var.get(), 0, 100)
                    hue_var.set(h)
                    sat_var.set(s_pct)
                    preview.config(bg=preview_hex())
                    label_var.set(f"{title}: H {h} / S {s_pct}%")
                    try:
                        wheel.set_color(h, s_pct / 100.0, 1.0)
                    except Exception:
                        pass

                def on_pick(h, s, _v):
                    hue_var.set(int(round(h)) % 360)
                    sat_var.set(int(round(max(0.0, min(1.0, s)) * 100)))
                    sync_widgets()

                tk.Label(holder, text=title, bg="#202428", fg="#b9e3f7",
                         font=("Segoe UI", 9, "bold")).pack(anchor="w")
                wheel = RealColorWheel(
                    holder,
                    radius=44,
                    callback=on_pick,
                    bg="#202428",
                    bd=0,
                    highlightthickness=0
                )
                wheel.pack(anchor="w", pady=(2, 4))
                preview.pack(anchor="w", pady=(0, 3))
                tk.Label(holder, textvariable=label_var, bg="#202428", fg="#8fb8c9",
                         font=("Segoe UI", 8)).pack(anchor="w")
                sync_widgets()
                return sync_widgets

            sync_a = make_intercambio_color_picker(
                color_box,
                0,
                "Color A",
                params["hue_a"],
                params["sat_a_pct"],
            )
            sync_b = make_intercambio_color_picker(
                color_box,
                1,
                "Color B",
                params["hue_b"],
                params["sat_b_pct"],
            )

            return

        for row, (param, var) in enumerate(params.items()):
            tk.Label(params_body, text=effect_param_labels.get(param, param),
                     bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=4)
            tk.Spinbox(params_body, from_=0, to=120000, increment=1, textvariable=var,
                       width=10, bg="#111519", fg="#e6e6e6",
                       buttonbackground="#30363d", relief="flat",
                       font=("Segoe UI", 10)).grid(row=row, column=1, sticky="e", pady=4)

    def on_select(event=None):
        sel = effect_list.curselection()
        if not sel:
            return
        render_params(visible_effects[sel[0]])

    effect_list.bind("<<ListboxSelect>>", on_select)
    category_combo.bind("<<ComboboxSelected>>", lambda event: load_category())

    tk.Button(actions, text="Probar", command=lambda: start_effect_from_panel(current_effect()),
              bg="#20bdec", fg="#001018", relief="flat",
              font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="ew", padx=(0, 5))
    tk.Button(actions, text="Finalizar prueba", command=lambda: stop_effect_from_panel(
        effects_panel_test_state.get("effect") or current_effect()
    ),
              bg="#ef5350", fg="#fff", relief="flat",
              font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="ew", padx=(5, 0))

    load_category()

    tk.Label(
        win,
        textvariable=effects_panel_status_var,
        bg="#181b1e",
        fg="#8dfa9f",
        font=("Segoe UI", 10, "italic")
    ).pack(fill="x", padx=12, pady=(0, 8))


frame_efectos.pack_forget()


midi_config_window = None
MIDI_CONFIG_FILE = "midi_config.json"

MIDI_ACTION_LABELS = {
    "scene_prev": "Escena anterior",
    "scene_go": "GO escena seleccionada",
    "scene_next": "Escena siguiente",
    "show_stop": "Stop show",
    "drum_hit": "Golpe de tambor",
    "refresh": "Refrescar lamparas",
    "all_on": "Encender todo",
    "all_off": "Apagar todo",
    "effect_strobe": "Estrobo",
    "effect_blink": "Parpadeo",
    "effect_sequence_off": "Secuencia OFF",
    "effect_sequence_on": "Secuencia ON",
    "effect_sequence": "Secuencia",
    "effect_breathe": "Respiracion",
    "effect_sunset": "Atardecer",
    "trigger_white_impact": "Disparador - Destello de portal",
    "trigger_warm_hit": "Disparador - Pulso de antorcha",
    "trigger_fast_chase": "Disparador - Cometa ascendente",
    "trigger_reverse_chase": "Disparador - Cometa descendente",
    "trigger_blackout_snap": "Disparador - Sombra instantanea",
    "trigger_red_pulse": "Disparador - Latido rojo",
    "trigger_blue_wave": "Disparador - Ola fria",
    "trigger_short_strobe": "Disparador - Relampago corto",
    "trigger_magenta_heartbeat": "Disparador - Latido magenta",
    "trigger_center_open": "Disparador - Apertura solar",
    "trigger_star_twinkle": "Disparador - Rocio de estrellas",
    "trigger_firefly_field": "Disparador - Luciernagas",
    "trigger_ghost_breath": "Disparador - Respiracion fantasma",
    "trigger_curtain_close": "Disparador - Cierre de telon",
    "trigger_northern_glow": "Disparador - Aurora lateral",
    "trigger_scene_crescendo": "Disparador escena - Crescendo",
    "trigger_scene_echo": "Disparador escena - Eco de color",
    "trigger_scene_water_echo": "Disparador escena - Eco de agua",
    "trigger_scene_wave": "Disparador escena - Marea de escena",
    "trigger_scene_constellation": "Disparador escena - Constelacion viva",
    "trigger_scene_suspense": "Disparador escena - Suspenso tenue",
    "trigger_scene_floor": "Disparador escena - Piso de escena",
    "trigger_scene_full": "Disparador escena - Pleno de escena",
    "trigger_slow_blackout": "Disparador escena - Blackout lento",
    "trigger_hold_scene_rise": "Disparador presion - Crecer escena",
    "trigger_hold_scene_shadow": "Disparador presion - Sombra sostenida",
    "trigger_hold_scene_shimmer": "Disparador presion - Titileo sostenido",
}

MIDI_ACTION_DEFAULT_NOTES = {
    "scene_prev": 1,
    "scene_go": 3,
    "scene_next": 4,
    "show_stop": 5,
    "drum_hit": 2,
    "refresh": 0,
    "all_on": 7,
    "all_off": 6,
    "effect_strobe": 16,
    "effect_blink": 24,
    "effect_sequence_off": 32,
    "effect_sequence_on": 40,
    "effect_sequence": 48,
    "effect_breathe": 56,
    "effect_sunset": 58,
    "trigger_white_impact": 8,
    "trigger_warm_hit": 9,
    "trigger_fast_chase": 10,
    "trigger_reverse_chase": 11,
    "trigger_blackout_snap": 12,
    "trigger_red_pulse": 13,
    "trigger_blue_wave": 14,
    "trigger_short_strobe": 15,
    "trigger_magenta_heartbeat": 17,
    "trigger_center_open": 18,
    "trigger_star_twinkle": 19,
    "trigger_firefly_field": 20,
    "trigger_ghost_breath": 21,
    "trigger_curtain_close": 22,
    "trigger_northern_glow": 23,
    "trigger_scene_crescendo": 25,
    "trigger_scene_echo": 26,
    "trigger_scene_wave": 27,
    "trigger_scene_constellation": 28,
    "trigger_scene_suspense": 29,
    "trigger_scene_floor": 30,
    "trigger_scene_full": 31,
    "trigger_scene_water_echo": 36,
    "trigger_slow_blackout": None,
    "trigger_hold_scene_rise": 33,
    "trigger_hold_scene_shadow": 34,
    "trigger_hold_scene_shimmer": 35,
}

MIDI_LED_COLOR_OPTIONS = {
    "Apagado": 0,
    "Azul suave": 3,
    "Rojo": 5,
    "Azul tenue": 12,
    "Amarillo": 13,
    "Verde": 21,
    "Cian": 37,
    "Azul": 45,
    "Rojo flash": 47,
    "Magenta": 53,
    "Amarillo intenso": 63,
}

MIDI_ACTION_DEFAULT_LED_COLORS = {
    "scene_prev": 37,
    "scene_go": 13,
    "scene_next": 37,
    "show_stop": 5,
    "drum_hit": 47,
    "refresh": 53,
    "all_on": 12,
    "all_off": 12,
    "effect_strobe": 5,
    "effect_blink": 5,
    "effect_sequence_off": 5,
    "effect_sequence_on": 5,
    "effect_sequence": 5,
    "effect_breathe": 5,
    "effect_sunset": 45,
    "trigger_white_impact": 63,
    "trigger_warm_hit": 13,
    "trigger_fast_chase": 37,
    "trigger_reverse_chase": 37,
    "trigger_blackout_snap": 5,
    "trigger_red_pulse": 47,
    "trigger_blue_wave": 45,
    "trigger_short_strobe": 63,
    "trigger_magenta_heartbeat": 53,
    "trigger_center_open": 21,
    "trigger_star_twinkle": 63,
    "trigger_firefly_field": 21,
    "trigger_ghost_breath": 3,
    "trigger_curtain_close": 5,
    "trigger_northern_glow": 37,
    "trigger_scene_crescendo": 63,
    "trigger_scene_echo": 13,
    "trigger_scene_water_echo": 45,
    "trigger_scene_wave": 37,
    "trigger_scene_constellation": 53,
    "trigger_scene_suspense": 3,
    "trigger_scene_floor": 3,
    "trigger_scene_full": 63,
    "trigger_slow_blackout": 5,
    "trigger_hold_scene_rise": 63,
    "trigger_hold_scene_shadow": 3,
    "trigger_hold_scene_shimmer": 53,
}

MIDI_LED_COLOR_NAMES = {
    value: name
    for name, value in MIDI_LED_COLOR_OPTIONS.items()
}
midi_action_notes = {}
midi_action_led_colors = {}
midi_learn_target = {"var": None, "status_var": None, "label": ""}


def set_midi_learn_target(var, status_var=None, label=""):
    midi_learn_target["var"] = var
    midi_learn_target["status_var"] = status_var
    midi_learn_target["label"] = label
    if status_var is not None:
        status_var.set(f"Escuchando MIDI para: {label}. Presiona un boton de la APC.")


def capture_midi_learn_note(note):
    if midi_learn_target.get("var") is None:
        return False

    def apply_note():
        var = midi_learn_target.get("var")
        if var is None:
            return
        var.set(str(note))
        status_var = midi_learn_target.get("status_var")
        label = midi_learn_target.get("label") or "accion"
        if status_var is not None:
            status_var.set(f"Nota {note} capturada para {label}. Guarda el mapa para confirmar.")

    root.after(0, apply_note)
    return True


def sanitize_midi_action_notes(notes):
    sanitized = dict(notes)
    for action, note in list(sanitized.items()):
        if is_apc_espacio_note(note):
            sanitized[action] = None
    return sanitized


def update_midi_scene_indicator(widget):
    if widget is None:
        return
    running = escena_en_ejecucion
    widget.config(
        text="ESCENA EN EJECUCION" if running else "ESCENA LIBRE",
        bg="#ef5350" if running else "#27ae60",
        fg="#ffffff",
        activebackground="#ef5350" if running else "#27ae60",
        activeforeground="#ffffff",
    )


def update_midi_scene_execution_led():
    try:
        note = get_midi_note("scene_go")
        if note is None:
            return
        midi_led(note, 5 if escena_en_ejecucion else 21)
    except Exception:
        pass


def load_midi_config():
    actions = {}
    colors = {}
    if os.path.exists(MIDI_CONFIG_FILE):
        try:
            with open(MIDI_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                actions = data.get("actions", {})
                colors = data.get("colors", {})
        except Exception as exc:
            print(f"[MIDI CONFIG] No se pudo leer {MIDI_CONFIG_FILE}: {exc}")

    notes = dict(MIDI_ACTION_DEFAULT_NOTES)
    for action, value in actions.items():
        if action in MIDI_ACTION_DEFAULT_NOTES:
            try:
                if value in ("", None):
                    notes[action] = None
                else:
                    note = int(value)
                    notes[action] = note if 0 <= note <= 127 else None
            except Exception:
                notes[action] = None

    led_colors = dict(MIDI_ACTION_DEFAULT_LED_COLORS)
    valid_colors = set(MIDI_LED_COLOR_OPTIONS.values())
    for action, value in colors.items():
        if action in MIDI_ACTION_DEFAULT_LED_COLORS:
            try:
                color = int(value)
                led_colors[action] = color if color in valid_colors else MIDI_ACTION_DEFAULT_LED_COLORS[action]
            except Exception:
                led_colors[action] = MIDI_ACTION_DEFAULT_LED_COLORS[action]

    return sanitize_midi_action_notes(notes), led_colors


def save_midi_action_notes():
    with open(MIDI_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "version": 1,
                "actions": midi_action_notes,
                "colors": midi_action_led_colors,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def get_midi_note(action):
    value = midi_action_notes.get(action, MIDI_ACTION_DEFAULT_NOTES[action])
    if value in ("", None):
        return None
    try:
        note = int(value)
    except Exception:
        return None
    return note if 0 <= note <= 127 else None


def get_midi_led_color(action):
    value = midi_action_led_colors.get(action, MIDI_ACTION_DEFAULT_LED_COLORS[action])
    try:
        color = int(value)
    except Exception:
        return MIDI_ACTION_DEFAULT_LED_COLORS[action]
    return color if color in MIDI_LED_COLOR_OPTIONS.values() else MIDI_ACTION_DEFAULT_LED_COLORS[action]


def get_midi_led_color_name(action):
    return MIDI_LED_COLOR_NAMES.get(get_midi_led_color(action), "Rojo")


midi_action_notes, midi_action_led_colors = load_midi_config()


def describe_midi_action(note):
    for action, action_note in midi_action_notes.items():
        if action_note is not None and int(action_note) == int(note):
            return MIDI_ACTION_LABELS.get(action, action)
    return "Accion MIDI"


def get_midi_action_for_note(note):
    if note is None:
        return None
    for action, action_note in midi_action_notes.items():
        try:
            if action_note is not None and int(action_note) == int(note):
                return action
        except Exception:
            continue
    return None


def save_single_midi_mapping(action, raw_note, color_name=None):
    if action not in MIDI_ACTION_DEFAULT_NOTES:
        messagebox.showwarning("Accion invalida", "No se encontro la accion MIDI.")
        return False

    raw = str(raw_note).strip()
    if raw == "":
        next_note = None
    else:
        try:
            next_note = int(raw)
        except Exception:
            messagebox.showwarning("Nota invalida", f"'{raw}' no es una nota MIDI valida.")
            return False

        if next_note < 0 or next_note > 127:
            messagebox.showwarning("Nota invalida", "Las notas MIDI deben estar entre 0 y 127.")
            return False

        if is_apc_espacio_note(next_note):
            messagebox.showwarning(
                "Nota reservada",
                "Esa nota APC esta reservada para ESPACIO LABERINTOS."
            )
            return False

        for other_action, other_note in midi_action_notes.items():
            if other_action == action or other_note is None:
                continue
            try:
                if int(other_note) == next_note:
                    messagebox.showwarning(
                        "Nota ocupada",
                        f"La nota {next_note} ya esta asignada a {MIDI_ACTION_LABELS.get(other_action, other_action)}."
                    )
                    return False
            except Exception:
                continue

    midi_action_notes[action] = next_note

    if color_name is not None:
        if color_name not in MIDI_LED_COLOR_OPTIONS:
            messagebox.showwarning("Color invalido", f"'{color_name}' no es un color LED valido.")
            return False
        midi_action_led_colors[action] = MIDI_LED_COLOR_OPTIONS[color_name]

    save_midi_action_notes()
    rebuild_midi_mappings()
    try:
        inicializar_leds_midi()
    except Exception:
        pass
    return True


def open_midi_config_panel():
    global midi_config_window

    if midi_config_window and midi_config_window.winfo_exists():
        midi_config_window.lift()
        midi_config_window.focus_force()
        return

    win = tk.Toplevel(root)
    midi_config_window = win
    win.title("Configuracion MIDI")
    win.configure(bg="#181b1e")
    win.geometry("780x620")
    win.minsize(680, 500)

    def on_close():
        global midi_config_window
        midi_config_window = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    frame = tk.Frame(win, bg="#181b1e")
    frame.pack(fill="both", expand=True, padx=12, pady=12)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(2, weight=1)

    tk.Label(frame, text="MIDI / APC Mini", bg="#181b1e", fg="#20bdec",
             font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")

    status_var = tk.StringVar(value="")

    status_box = tk.LabelFrame(frame, text="Estado", bg="#181b1e", fg="#20bdec",
                               font=("Segoe UI", 10, "bold"), padx=8, pady=8)
    status_box.grid(row=1, column=0, sticky="ew", pady=(10, 8))
    scene_indicator_btn = tk.Button(
        status_box,
        text="ESCENA LIBRE",
        bg="#27ae60",
        fg="#ffffff",
        relief="flat",
        takefocus=0,
        font=("Segoe UI", 10, "bold"),
    )
    scene_indicator_btn.pack(fill="x", pady=(0, 8))
    tk.Label(status_box, textvariable=status_var, bg="#181b1e", fg="#d9f3ff",
             font=("Segoe UI", 9), justify="left", anchor="w").pack(fill="x")

    map_box = tk.LabelFrame(frame, text="Asignaciones MIDI", bg="#181b1e", fg="#20bdec",
                            font=("Segoe UI", 10, "bold"), padx=8, pady=8)
    map_box.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
    map_box.grid_rowconfigure(0, weight=1)
    map_box.grid_columnconfigure(0, weight=1)

    table_canvas = tk.Canvas(map_box, bg="#181b1e", highlightthickness=0)
    table_scroll = tk.Scrollbar(map_box, orient="vertical", command=table_canvas.yview)
    table_inner = tk.Frame(table_canvas, bg="#181b1e")
    table_inner.bind(
        "<Configure>",
        lambda event: table_canvas.configure(scrollregion=table_canvas.bbox("all"))
    )
    table_window = table_canvas.create_window((0, 0), window=table_inner, anchor="nw")
    table_canvas.bind(
        "<Configure>",
        lambda event: table_canvas.itemconfigure(table_window, width=event.width)
    )
    table_canvas.configure(yscrollcommand=table_scroll.set)
    table_canvas.grid(row=0, column=0, sticky="nsew")
    table_scroll.grid(row=0, column=1, sticky="ns")
    table_inner.grid_columnconfigure(0, weight=1)
    bind_mousewheel_scroll(table_canvas, table_canvas, table_inner)

    action_note_vars = {}
    action_color_vars = {}
    midi_row_frames = {}
    midi_row_hover = set()
    midi_row_focus = set()

    header_row = tk.Frame(table_inner, bg="#202832", padx=8, pady=5)
    header_row.grid(row=0, column=0, sticky="ew", pady=(0, 5))
    header_row.grid_columnconfigure(0, minsize=42)
    header_row.grid_columnconfigure(1, weight=1)
    header_row.grid_columnconfigure(2, minsize=100)
    header_row.grid_columnconfigure(3, minsize=190)
    tk.Label(header_row, text="Fila", bg="#202832", fg="#8fb8c9",
             font=("Segoe UI", 9, "bold"), anchor="center").grid(row=0, column=0, sticky="ew", padx=(0, 10))
    tk.Label(header_row, text="Accion", bg="#202832", fg="#8fb8c9",
             font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(0, 12))
    tk.Label(header_row, text="Nota APC", bg="#202832", fg="#8fb8c9",
             font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w", padx=(0, 12))
    tk.Label(header_row, text="Color LED", bg="#202832", fg="#8fb8c9",
             font=("Segoe UI", 9, "bold")).grid(row=0, column=3, sticky="w")

    def set_midi_row_highlight(action):
        row_frame = midi_row_frames.get(action)
        if row_frame is None:
            return
        active = action in midi_row_hover or action in midi_row_focus
        normal_bg = getattr(row_frame, "normal_bg", "#181b1e")
        bg = "#123544" if active else normal_bg
        row_frame.config(bg=bg, highlightbackground="#20bdec" if active else "#2a343d")
        for child in row_frame.winfo_children():
            if isinstance(child, tk.Label):
                child.config(bg=bg)

    def set_midi_row_hover(action, active=True):
        if active:
            midi_row_hover.add(action)
        else:
            midi_row_hover.discard(action)
        set_midi_row_highlight(action)

    def set_midi_row_focus(action, active=True):
        if active:
            midi_row_focus.add(action)
        else:
            midi_row_focus.discard(action)
        set_midi_row_highlight(action)

    def leave_midi_row(action, row_frame):
        x = row_frame.winfo_pointerx()
        y = row_frame.winfo_pointery()
        left = row_frame.winfo_rootx()
        top = row_frame.winfo_rooty()
        right = left + row_frame.winfo_width()
        bottom = top + row_frame.winfo_height()
        if left <= x <= right and top <= y <= bottom:
            return
        set_midi_row_hover(action, False)

    def midi_config_category(action):
        if action.startswith("scene_") or action == "show_stop":
            return "ESCENAS / SHOW"
        if action in ("all_on", "all_off", "refresh", "drum_hit"):
            return "CONTROL GENERAL"
        if action.startswith("effect_"):
            return "EFECTOS"
        if action.startswith("trigger_hold"):
            return "DISPARADORES - PRESION"
        if action.startswith("trigger_scene") or action == "trigger_slow_blackout":
            return "DISPARADORES - SOBRE ESCENA"
        if action.startswith("trigger_"):
            return "DISPARADORES - COLOR / MOVIMIENTO"
        return "OTROS"

    category_order = (
        "ESCENAS / SHOW",
        "CONTROL GENERAL",
        "EFECTOS",
        "DISPARADORES - SOBRE ESCENA",
        "DISPARADORES - PRESION",
        "DISPARADORES - COLOR / MOVIMIENTO",
        "OTROS",
    )
    actions_by_category = {category: [] for category in category_order}
    for action in MIDI_ACTION_DEFAULT_NOTES:
        actions_by_category.setdefault(midi_config_category(action), []).append(action)

    table_row = 1
    display_row = 1
    for category in category_order:
        actions_in_category = actions_by_category.get(category, [])
        if not actions_in_category:
            continue
        actions_in_category = sorted(
            actions_in_category,
            key=lambda action: (
                0 if get_midi_note(action) is not None else 1,
                MIDI_ACTION_LABELS.get(action, action),
            ),
        )

        assigned_count = sum(1 for action in actions_in_category if get_midi_note(action) is not None)
        category_row = tk.Frame(table_inner, bg="#111519", padx=8, pady=4)
        category_row.grid(row=table_row, column=0, sticky="ew", pady=(8, 2))
        category_row.grid_columnconfigure(0, weight=1)
        tk.Label(
            category_row,
            text=f"{category}  |  {assigned_count}/{len(actions_in_category)} asignadas",
            bg="#111519",
            fg="#20bdec",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        table_row += 1

        for action in actions_in_category:
            row = table_row
            row_number_value = display_row
            table_row += 1
            display_row += 1
            note = get_midi_note(action)
            note_var = tk.StringVar(value="" if note is None else str(note))
            color_var = tk.StringVar(value=get_midi_led_color_name(action))
            action_note_vars[action] = note_var
            action_color_vars[action] = color_var

            row_bg = "#181f25" if row_number_value % 2 else "#151a1f"
            row_frame = tk.Frame(
                table_inner,
                bg=row_bg,
                padx=8,
                pady=4,
                highlightthickness=1,
                highlightbackground=row_bg,
            )
            row_frame.normal_bg = row_bg
            row_frame.grid(row=row, column=0, sticky="ew", pady=1)
            row_frame.grid_columnconfigure(0, minsize=42)
            row_frame.grid_columnconfigure(1, weight=1)
            row_frame.grid_columnconfigure(2, minsize=100)
            row_frame.grid_columnconfigure(3, minsize=190)
            midi_row_frames[action] = row_frame

            row_number = tk.Label(row_frame, text=str(row_number_value), bg=row_bg, fg="#8fb8c9",
                                  font=("Segoe UI", 9, "bold"), anchor="center")
            row_number.grid(row=0, column=0, sticky="ew", padx=(0, 10))
            action_label = tk.Label(row_frame, text=MIDI_ACTION_LABELS[action], bg=row_bg, fg="#d9f3ff",
                                    font=("Segoe UI", 10), anchor="w")
            action_label.grid(row=0, column=1, sticky="ew", padx=(0, 12))
            note_entry = tk.Entry(row_frame, textvariable=note_var, width=8, bg="#111519", fg="#e6e6e6",
                                  insertbackground="#20bdec", relief="flat",
                                  font=("Segoe UI", 10))
            note_entry.grid(row=0, column=2, sticky="w", padx=(0, 12))
            note_entry.bind(
                "<FocusIn>",
                lambda _e, v=note_var, a=action: set_midi_learn_target(
                    v,
                    status_var,
                    MIDI_ACTION_LABELS.get(a, a),
                ),
                add="+",
            )
            color_combo = ttk.Combobox(
                row_frame,
                textvariable=color_var,
                values=list(MIDI_LED_COLOR_OPTIONS.keys()),
                state="readonly",
                width=18,
                font=("Segoe UI", 9),
            )
            color_combo.grid(row=0, column=3, sticky="w")

            for widget in (row_frame, row_number, action_label, note_entry, color_combo):
                widget.bind("<FocusIn>", lambda _e, a=action: set_midi_row_focus(a, True), add="+")
                widget.bind("<FocusOut>", lambda _e, a=action: root.after(120, lambda: set_midi_row_focus(a, False)))
                widget.bind("<Enter>", lambda _e, a=action: set_midi_row_hover(a, True))
                widget.bind("<Leave>", lambda _e, a=action, rf=row_frame: root.after(20, lambda: leave_midi_row(a, rf)))

    actions = tk.Frame(frame, bg="#181b1e")
    actions.grid(row=3, column=0, sticky="ew")
    for col in range(4):
        actions.grid_columnconfigure(col, weight=1)

    def refresh_midi_panel():
        status = get_midi_status()
        ports = get_available_ports()
        input_count = len(ports.get("inputs", []))
        output_count = len(ports.get("outputs", []))
        update_midi_scene_indicator(scene_indicator_btn)
        status_var.set(
            "Estado: {estado}\nEntrada: {entrada}\nSalida: {salida}\nPuertos disponibles: {inputs} entrada(s), {outputs} salida(s)\nUltimo error: {error}".format(
                estado="conectado" if status.get("running") else "detenido",
                entrada=status.get("input_port") or "sin entrada",
                salida=status.get("output_port") or "sin salida",
                inputs=input_count,
                outputs=output_count,
                error=status.get("last_error") or "sin errores",
            )
        )

        for action, var in action_note_vars.items():
            note = get_midi_note(action)
            var.set("" if note is None else str(note))
        for action, var in action_color_vars.items():
            var.set(get_midi_led_color_name(action))

    def refresh_scene_indicator_loop():
        if not win.winfo_exists():
            return
        update_midi_scene_indicator(scene_indicator_btn)
        win.after(250, refresh_scene_indicator_loop)

    def save_all_mappings():
        next_notes = {}
        next_colors = {}
        used_notes = {}

        for action, var in action_note_vars.items():
            raw = var.get().strip()
            if raw == "":
                next_notes[action] = None
                continue

            try:
                note = int(raw)
            except Exception:
                messagebox.showwarning("Nota invalida", f"'{raw}' no es una nota MIDI valida.")
                return

            if note < 0 or note > 127:
                messagebox.showwarning("Nota invalida", "Las notas MIDI deben estar entre 0 y 127.")
                return

            if is_apc_espacio_note(note):
                messagebox.showwarning(
                    "Nota reservada",
                    f"La nota {note} esta reservada para ESPACIO LABERINTOS."
                )
                return

            used_notes.setdefault(note, []).append(action)
            next_notes[action] = note

        for action, var in action_color_vars.items():
            color_name = var.get().strip()
            if color_name not in MIDI_LED_COLOR_OPTIONS:
                messagebox.showwarning("Color invalido", f"'{color_name}' no es un color LED valido.")
                return
            next_colors[action] = MIDI_LED_COLOR_OPTIONS[color_name]

        duplicates = {
            note: actions
            for note, actions in used_notes.items()
            if len(actions) > 1
        }
        if duplicates:
            detalle = "\n".join(
                f"Nota {note}: " + ", ".join(MIDI_ACTION_LABELS[action] for action in actions)
                for note, actions in duplicates.items()
            )
            messagebox.showwarning(
                "Notas duplicadas",
                "Cada boton APC debe quedar asignado a una sola accion.\n\n" + detalle
            )
            return

        midi_action_notes.clear()
        midi_action_notes.update(next_notes)
        midi_action_led_colors.clear()
        midi_action_led_colors.update(next_colors)
        save_midi_action_notes()
        rebuild_midi_mappings()
        inicializar_leds_midi()
        refresh_midi_panel()

    def reset_default_mapping():
        if not messagebox.askyesno("Restaurar MIDI", "¿Restaurar el mapa MIDI por defecto?"):
            return
        midi_action_notes.clear()
        midi_action_notes.update(sanitize_midi_action_notes(MIDI_ACTION_DEFAULT_NOTES))
        midi_action_led_colors.clear()
        midi_action_led_colors.update(MIDI_ACTION_DEFAULT_LED_COLORS)
        save_midi_action_notes()
        rebuild_midi_mappings()
        inicializar_leds_midi()
        refresh_midi_panel()

    def refresh_leds_from_panel():
        inicializar_leds_midi()
        refresh_midi_panel()

    tk.Button(actions, text="Actualizar", command=refresh_midi_panel,
              bg="#20bdec", fg="#001018", relief="flat",
              font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="ew", padx=(0, 5))
    tk.Button(actions, text="Guardar mapa", command=save_all_mappings,
              bg="#27ae60", fg="#fff", relief="flat",
              font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="ew", padx=5)
    tk.Button(actions, text="Reiniciar LEDs", command=refresh_leds_from_panel,
              bg="#2b343b", fg="#d9f3ff", relief="flat",
              font=("Segoe UI", 10, "bold")).grid(row=0, column=2, sticky="ew", padx=5)
    tk.Button(actions, text="Defaults", command=reset_default_mapping,
              bg="#5c6a73", fg="#fff", relief="flat",
              font=("Segoe UI", 10, "bold")).grid(row=0, column=3, sticky="ew", padx=(5, 0))

    refresh_midi_panel()
    refresh_scene_indicator_loop()


app_menu = tk.Menu(root)
file_menu = tk.Menu(app_menu, tearoff=0)
file_menu.add_command(label="Salir", command=lambda: on_app_close())
app_menu.add_cascade(label="Archivo", menu=file_menu)

config_menu = tk.Menu(app_menu, tearoff=0)
config_menu.add_command(label="Lamparas y grupos", command=open_lamp_config_panel)
config_menu.add_command(label="Refrescar estado de lamparas", command=refresh_lamp_status)
app_menu.add_cascade(label="Configuracion", menu=config_menu)

effects_menu = tk.Menu(app_menu, tearoff=0)
effects_menu.add_command(label="Panel de efectos", command=open_effects_config_panel)
app_menu.add_cascade(label="Efectos", menu=effects_menu)

midi_menu = tk.Menu(app_menu, tearoff=0)
midi_menu.add_command(label="Configuracion MIDI", command=open_midi_config_panel)
app_menu.add_cascade(label="MIDI", menu=midi_menu)
root.config(menu=app_menu)

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
        if is_preview_update_suspended():
            return
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
        if is_preview_update_suspended():
            return
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
        if is_preview_update_suspended():
            return
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

    # No apagamos lamparas al construir la interfaz.
    panels[ip] = panel
#___________________________________________________________________________________

# ================== INTEGRACION UI: MAESTRO + GRUPOS ==================
try:
    frame_maestro.destroy()
except Exception:
    pass
try:
    frame_center.destroy()
except Exception:
    pass

panels.clear()

frame_maestro = tk.LabelFrame(
    frame_left,
    text="Control Maestro",
    bg="#181b1e",
    fg="#20bdec",
    font=("Segoe UI", 14, "bold"),
    padx=4,
    pady=4,
    width=185,
    height=330
)
frame_maestro.pack(side="top", fill="x", expand=False, pady=(0, 12))
frame_maestro.pack_propagate(False)

maestro_hsv = {"h": 0, "s": 1}
maestro_brillo = tk.IntVar(value=180)
maestro_temp = tk.IntVar(value=128)
maestro_mode = tk.StringVar(value="colour")
maestro_scope_effects = tk.BooleanVar(value=True)
maestro_scope_atmos = tk.BooleanVar(value=True)


def get_ips_by_scope(include_offline=False):
    ips = []
    for ip in LAMP_IPS:
        group = get_lamp_group(ip)
        in_scope = (
            (group == "efectos" and maestro_scope_effects.get()) or
            (group == "atmosfera" and maestro_scope_atmos.get()) or
            (group not in ("efectos", "atmosfera") and maestro_scope_effects.get() and maestro_scope_atmos.get())
        )
        if in_scope and (include_offline or lamp_status.get(ip, True)):
            ips.append(ip)
    return ips


def _mix_rgb(a, b, ratio):
    ratio = max(0.0, min(1.0, float(ratio)))
    return tuple(int(a[i] + (b[i] - a[i]) * ratio) for i in range(3))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _white_preview_hex(temp):
    try:
        temp = float(temp)
    except Exception:
        temp = 128.0
    if temp > 1000:
        ratio = (temp - 2200) / (6500 - 2200)
    else:
        ratio = temp / 255.0
    return _rgb_to_hex(_mix_rgb((255, 190, 105), (242, 248, 255), ratio))


def _colour_preview_hex(h, s):
    try:
        h = float(h) % 360
        s = max(0.0, min(1.0, float(s)))
    except Exception:
        h, s = 0.0, 1.0
    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, 1.0)
    return _rgb_to_hex((int(r * 255), int(g * 255), int(b * 255)))


def set_panel_preview_swatch(panel, mode=None, h=None, s=None, temp=None, is_on=None):
    swatch = getattr(panel, "preview_swatch", None)
    if swatch is None:
        return

    if is_on is None:
        try:
            is_on = selected_devices[panel.ip].get() and safe_brightness(getattr(panel, "last_brillo", 0)) > 0
        except Exception:
            is_on = True

    if not is_on:
        swatch.config(bg="#15191d", highlightbackground="#2b343b")
        return

    mode = mode or getattr(panel, "last_mode", "colour")
    if mode == "white":
        color = _white_preview_hex(temp if temp is not None else getattr(panel, "last_temp", 128))
    else:
        color = _colour_preview_hex(
            h if h is not None else getattr(panel, "last_hue", 0),
            s if s is not None else getattr(panel, "last_sat", 1),
        )

    swatch.config(bg=color, highlightbackground="#d9f3ff" if mode == "white" else "#111519")


def get_panel_assignment_state(ip):
    try:
        placements = globals().get("espacio_laberintos_data", {}).get("placements", {})
        return str(get_lamp_id(ip)) in placements
    except Exception:
        return False


def get_panel_connection_state(ip):
    return lamp_status.get(ip, None)


def apply_lamp_visual_state(panel, update_swatch=True):
    ip = getattr(panel, "ip", None)
    if not ip:
        return

    connected = get_panel_connection_state(ip)
    powered = bool(selected_devices[ip].get()) if ip in selected_devices else False
    if connected is True:
        base_bg = "#17291c"
        strip_bg = "#18a957"
    elif connected is False:
        base_bg = "#2b171a"
        strip_bg = "#b9363f"
    else:
        base_bg = "#202428"
        strip_bg = "#68737d"

    scene_involved = bool(getattr(panel, "scene_involved", False))
    border = "#252e36"
    panel.config(bg=base_bg, highlightbackground=border, highlightcolor=border)

    for widget_name in (
        "top_frame",
        "mode_row",
        "body_frame",
        "sliders_frame",
        "wheel_slot",
        "on_check",
        "mode_colour_radio",
        "mode_white_radio",
    ):
        widget = getattr(panel, widget_name, None)
        if widget is not None:
            try:
                widget.config(bg=base_bg, activebackground=base_bg)
            except Exception:
                try:
                    widget.config(bg=base_bg)
                except Exception:
                    pass

    strip = getattr(panel, "connection_strip", None)
    if strip is not None:
        strip.config(bg=strip_bg)

    power_dot = getattr(panel, "power_dot", None)
    if power_dot is not None:
        power_dot.config(bg="#23d160" if powered else "#3b444c")

    scene_dot = getattr(panel, "scene_dot", None)
    if scene_dot is not None:
        if scene_involved:
            scene_dot.config(text="E", bg="#f1c40f", fg="#111519", highlightbackground="#fff3a6")
        else:
            scene_dot.config(text="", bg=base_bg, fg=base_bg, highlightbackground=base_bg)

    group_badge = getattr(panel, "group_badge", None)
    if group_badge is not None:
        group_badge.config(bg="#111519")

    if update_swatch:
        set_panel_preview_swatch(panel, is_on=powered)


def update_panel_visual(panel):
    try:
        apply_lamp_visual_state(panel)
        refresh_espacio = globals().get("refresh_espacio_laberintos_visual")
        if callable(refresh_espacio):
            refresh_espacio()
    except Exception:
        pass


def sync_espacio_laberintos_current_state(ips=None):
    if ips is None:
        target_panels = list(panels.values())
    else:
        if isinstance(ips, str):
            ips = [ips]
        target_panels = [panels[ip] for ip in ips if ip in panels]

    for panel in target_panels:
        try:
            panel.scene_involved = False
            apply_lamp_visual_state(panel)
        except Exception:
            pass

    refresh_espacio = globals().get("refresh_espacio_laberintos_visual")
    if callable(refresh_espacio):
        refresh_espacio()


def set_panel_mode(panel, mode, send=True):
    if send and not is_preview_update_suspended():
        claim_lamps_for_manual_control(panel.ip)
    panel.mode_var.set(mode)
    panel.last_mode = mode
    if mode == "colour":
        panel.whitewheel_lamp.pack_forget()
        panel.colorwheel_lamp.pack()
        if send and selected_devices[panel.ip].get():
            send_lamp_color_safe(panel.ip, panel.last_hue, panel.last_sat, panel.last_brillo)
    else:
        panel.colorwheel_lamp.pack_forget()
        panel.whitewheel_lamp.pack()
        if send and selected_devices[panel.ip].get():
            send_lamp_white(panel.ip, panel.last_brillo, panel.last_temp)
    update_panel_visual(panel)


def set_panel_mode_preview(panel, mode):
    try:
        panel.mode_var.set(mode)
        if mode == "white":
            panel.colorwheel_lamp.pack_forget()
            panel.whitewheel_lamp.pack()
        else:
            panel.whitewheel_lamp.pack_forget()
            panel.colorwheel_lamp.pack()
        set_panel_preview_swatch(panel, mode)
    except Exception:
        pass


def apply_master_to_ips(ips, force_on=False):
    modo = maestro_mode.get()
    h = maestro_hsv["h"]
    s = maestro_hsv["s"]
    brillo = safe_brightness(maestro_brillo.get())
    temp = int(maestro_temp.get())

    claim_lamps_for_manual_control(ips)
    live_ips = []

    for ip in ips:
        panel = panels.get(ip)
        if panel is None:
            continue
        was_on = bool(selected_devices[ip].get())
        should_send = force_on or was_on
        if should_send and lamp_status.get(ip, True):
            live_ips.append(ip)
        panel.last_brillo = brillo
        panel.brillo_var.set(brillo)
        panel.last_mode = modo
        panel.mode_var.set(modo)
        if modo == "colour":
            panel.last_hue = h
            panel.last_sat = s
            panel.colorwheel_lamp.set_color(h, s, max(0.01, brillo / 255))
        else:
            panel.last_temp = temp
            panel.temp_var.set(temp)
            panel.whitewheel_lamp.set_temp_value(temp)
        if should_send and brillo <= 0:
            selected_devices[ip].set(False)
        elif should_send:
            selected_devices[ip].set(True)
        set_panel_mode(panel, modo, send=False)
        update_panel_visual(panel)

    sync_espacio_laberintos_current_state(ips)

    if not live_ips:
        return
    if brillo <= 0:
        for ip in live_ips:
            send_off(ip)
        return
    if modo == "colour":
        send_color_to_lamps(live_ips, h, s, brillo)
    else:
        send_white_to_lamps(live_ips, brillo, map_slider_to_wiz_temperature(temp))


def maestro_on_color(h, s, v):
    maestro_hsv["h"] = h
    maestro_hsv["s"] = s
    set_master_mode("colour")


def maestro_on_temp(value):
    maestro_temp.set(int(float(value)))
    set_master_mode("white")


def maestro_on_brillo(value):
    maestro_brillo.set(safe_brightness(value))


def set_master_mode(mode):
    maestro_mode.set(mode)
    try:
        colorwheel_maestro.pack_forget()
        whitewheel_maestro.pack_forget()
        if mode == "white":
            whitewheel_maestro.pack()
        else:
            colorwheel_maestro.pack()
    except Exception:
        pass


def aplicar_maestro():
    apply_master_to_ips(get_ips_by_scope())


def apagar_todo():
    ips = get_ips_by_scope()
    claim_lamps_for_manual_control(ips)
    for ip in ips:
        selected_devices[ip].set(False)
        if ip in panels:
            panels[ip].last_brillo = 0
            panels[ip].brillo_var.set(0)
            update_panel_visual(panels[ip])
        send_off(ip)
    sync_espacio_laberintos_current_state(ips)


def encender_todo():
    if safe_brightness(maestro_brillo.get()) <= 0:
        maestro_brillo.set(180)
    apply_master_to_ips(get_ips_by_scope(), force_on=True)


maestro_top = tk.Frame(frame_maestro, bg="#181b1e")
maestro_top.pack(fill="x", pady=(0, 3))
tk.Radiobutton(maestro_top, text="C", variable=maestro_mode, value="colour",
               command=lambda: set_master_mode("colour"),
               bg="#181b1e", fg="#20bdec", selectcolor="#181b1e",
               font=("Segoe UI", 8, "bold")).pack(side="left", padx=(22, 2))
tk.Radiobutton(maestro_top, text="B", variable=maestro_mode, value="white",
               command=lambda: set_master_mode("white"),
               bg="#181b1e", fg="#f1c40f", selectcolor="#181b1e",
               font=("Segoe UI", 8, "bold")).pack(side="left", padx=2)

scope_row = tk.Frame(frame_maestro, bg="#181b1e")
scope_row.pack(fill="x", pady=(0, 3))
tk.Checkbutton(scope_row, text="Bichos", variable=maestro_scope_effects,
               bg="#181b1e", fg="#20bdec", selectcolor="#181b1e",
               font=("Segoe UI", 8)).pack(side="left", padx=(12, 2))
tk.Checkbutton(scope_row, text="Atmos.", variable=maestro_scope_atmos,
               bg="#181b1e", fg="#f1c40f", selectcolor="#181b1e",
               font=("Segoe UI", 8)).pack(side="left", padx=2)

maestro_body = tk.Frame(frame_maestro, bg="#181b1e")
maestro_body.pack(fill="x")
maestro_wheel_slot = tk.Frame(maestro_body, bg="#181b1e", width=136, height=136)
maestro_wheel_slot.pack(side="left", padx=(6, 4))
maestro_wheel_slot.pack_propagate(False)
colorwheel_maestro = RealColorWheel(maestro_wheel_slot, radius=63, callback=maestro_on_color, bg="#181b1e", bd=0, highlightthickness=0)
whitewheel_maestro = WhiteTempWheel(maestro_wheel_slot, radius=63, callback=maestro_on_temp, bg="#181b1e", bd=0, highlightthickness=0)
colorwheel_maestro.pack()

maestro_sliders = tk.Frame(maestro_body, bg="#181b1e")
maestro_sliders.pack(side="left")
tk.Label(maestro_sliders, text="I", bg="#181b1e", fg="#20bdec", font=("Segoe UI", 8, "bold")).grid(row=0, column=0)
tk.Label(maestro_sliders, text="T", bg="#181b1e", fg="#f1c40f", font=("Segoe UI", 8, "bold")).grid(row=0, column=1)
tk.Scale(maestro_sliders, from_=255, to=0, orient="vertical", variable=maestro_brillo,
         length=92, width=4, sliderlength=10, showvalue=False, bg="#181b1e", fg="#20bdec",
         highlightthickness=0, command=maestro_on_brillo).grid(row=1, column=0, padx=1)
tk.Scale(maestro_sliders, from_=255, to=0, orient="vertical", variable=maestro_temp,
         length=92, width=4, sliderlength=10, showvalue=False, bg="#181b1e", fg="#f1c40f",
         highlightthickness=0, command=maestro_on_temp).grid(row=1, column=1, padx=1)

master_actions = tk.Frame(frame_maestro, bg="#181b1e")
master_actions.pack(fill="x", pady=(7, 0), padx=6)
for col in range(2):
    master_actions.grid_columnconfigure(col, weight=1)
tk.Button(master_actions, text="Aplicar", command=aplicar_maestro,
          bg="#20bdec", fg="#fff", relief="flat",
          font=("Segoe UI", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
tk.Button(master_actions, text="On", command=encender_todo,
          bg="#20bdec", fg="#fff", relief="flat",
          font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="ew", padx=(0, 3))
tk.Button(master_actions, text="Off", command=apagar_todo,
          bg="#807D7D", fg="#fff", relief="flat",
          font=("Segoe UI", 9, "bold")).grid(row=1, column=1, sticky="ew", padx=(3, 0))
tk.Button(master_actions, text="Refrescar", command=refresh_lamp_status,
          bg="#27ae60", fg="#fff", relief="flat",
          font=("Segoe UI", 8)).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))


frame_center = tk.Frame(frame_main, bg="#181b1e")
frame_center.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=15)
canvas_lamps = tk.Canvas(frame_center, bg="#181b1e", highlightthickness=0, bd=0)
canvas_lamps.grid(row=0, column=0, sticky="nsew")
scroll_lamps = tk.Scrollbar(frame_center, orient="vertical", command=canvas_lamps.yview)
scroll_lamps.grid(row=0, column=1, sticky="ns")
frame_center.grid_rowconfigure(0, weight=1)
frame_center.grid_columnconfigure(0, weight=1)
canvas_lamps.configure(yscrollcommand=scroll_lamps.set)

frame_lamps = tk.Frame(canvas_lamps, bg="#181b1e")
frame_lamps_window = canvas_lamps.create_window((0, 0), window=frame_lamps, anchor="nw")
frame_lamps.grid_columnconfigure(0, weight=1)
frame_lamps.bind("<Configure>", lambda event: canvas_lamps.configure(scrollregion=canvas_lamps.bbox("all")))
canvas_lamps.bind("<Configure>", lambda event: canvas_lamps.itemconfigure(frame_lamps_window, width=event.width))

espacio_laberintos_data = load_espacio_laberintos()
espacio_selected_lamp = {"id": None}
espacio_drag_lamp = {"id": None}
espacio_cells = {}
espacio_palette_items = {}
espacio_status_var = tk.StringVar(value="Elige una lampara y ubicala en la matriz.")
espacio_midi_action_var = tk.StringVar(value="toggle")
espacio_midi_trigger_var = tk.StringVar(value="Pulso color")
ESPACIO_MIDI_ACTIONS = {
    "toggle": "Alternar",
    "pulse": "Pulso",
    "hold": "Sostener",
    "solo": "Solo",
    "master": "Copiar maestro",
    "scene_mark": "Sumar escena",
    "freeze": "Congelar",
}
ESPACIO_MIDI_TRIGGERS = ("Pulso color", "Pulso blanco", "Flash rojo")
espacio_midi_hold_states = {}
espacio_midi_pulse_states = {}


def normalize_espacio_laberintos():
    rows = max(1, min(ESPACIO_MAX_ROWS, int(espacio_laberintos_data.get("rows", ESPACIO_DEFAULT_ROWS))))
    cols = max(1, min(ESPACIO_MAX_COLS, int(espacio_laberintos_data.get("cols", ESPACIO_DEFAULT_COLS))))
    valid_ids = {str(get_lamp_id(ip)) for ip in LAMP_IPS}
    occupied = set()
    clean = {}
    for lamp_id, pos in espacio_laberintos_data.get("placements", {}).items():
        lamp_id = str(lamp_id)
        if lamp_id not in valid_ids or not isinstance(pos, dict):
            continue
        try:
            row = int(pos.get("row", -1))
            col = int(pos.get("col", -1))
        except Exception:
            continue
        if row < 0 or col < 0 or row >= rows or col >= cols:
            continue
        if (row, col) in occupied:
            continue
        clean[lamp_id] = {"row": row, "col": col}
        occupied.add((row, col))
    espacio_laberintos_data["rows"] = rows
    espacio_laberintos_data["cols"] = cols
    espacio_laberintos_data["placements"] = clean


def get_espacio_lamp_at(row, col):
    for lamp_id, pos in espacio_laberintos_data.get("placements", {}).items():
        if int(pos.get("row", -1)) == row and int(pos.get("col", -1)) == col:
            return lamp_id
    return None


def get_espacio_cell_from_event(event):
    widget = root.winfo_containing(event.x_root, event.y_root)
    while widget is not None:
        cell = getattr(widget, "espacio_cell", None)
        if cell is not None:
            return cell
        widget = getattr(widget, "master", None)
    return None


def select_espacio_lamp(lamp_id):
    espacio_selected_lamp["id"] = lamp_id
    espacio_status_var.set(f"{lamp_id} lista para ubicar.")
    refresh_espacio_laberintos_visual()


def assign_espacio_lamp(lamp_id, row, col, save=False):
    if not lamp_id:
        return
    normalize_espacio_laberintos()
    current = get_espacio_lamp_at(row, col)
    if current and current != lamp_id:
        espacio_laberintos_data["placements"].pop(current, None)
    espacio_laberintos_data["placements"][lamp_id] = {"row": row, "col": col}
    espacio_status_var.set(f"{lamp_id} ubicada en fila {row + 1}, columna {col + 1}.")
    rebuild_layout = globals().get("rebuild_lamp_layout")
    if callable(rebuild_layout):
        rebuild_layout()
    else:
        refresh_espacio_laberintos_visual()
    if save:
        save_espacio_laberintos(espacio_laberintos_data)


def clear_espacio_cell(row, col):
    lamp_id = get_espacio_lamp_at(row, col)
    if lamp_id:
        espacio_laberintos_data["placements"].pop(lamp_id, None)
        espacio_status_var.set(f"{lamp_id} queda sin ubicacion.")
        rebuild_layout = globals().get("rebuild_lamp_layout")
        if callable(rebuild_layout):
            rebuild_layout()
        else:
            refresh_espacio_laberintos_visual()


def remove_espacio_lamp(lamp_id):
    lamp_id = str(lamp_id)
    if lamp_id not in espacio_laberintos_data.get("placements", {}):
        return
    espacio_laberintos_data["placements"].pop(lamp_id, None)
    espacio_status_var.set(f"{lamp_id} retirada de ESPACIO LABERINTOS.")
    rebuild_layout = globals().get("rebuild_lamp_layout")
    if callable(rebuild_layout):
        rebuild_layout()
    else:
        refresh_espacio_laberintos_visual()


def is_espacio_lamp_connected(ip):
    if not ip:
        return False
    return bool(lamp_status.get(ip, False))


def get_espacio_cell_for_apc_note(note):
    try:
        note = int(note)
    except Exception:
        return None
    for row, notes in enumerate(APC_ESPACIO_ROWS):
        for col, cell_note in enumerate(notes):
            if cell_note == note:
                return row, col
    return None


def refresh_espacio_midi_leds():
    for row in range(ESPACIO_MAX_ROWS):
        for col in range(ESPACIO_MAX_COLS):
            note = get_apc_espacio_note(row, col)
            if note is None:
                continue
            lamp_id = get_espacio_lamp_at(row, col)
            if not lamp_id:
                midi_led(note, APC_ESPACIO_LED_EMPTY)
                continue
            ip = get_lamp_ip_by_id(lamp_id)
            midi_led(
                note,
                APC_ESPACIO_LED_CONNECTED
                if is_espacio_lamp_connected(ip)
                else APC_ESPACIO_LED_DISCONNECTED,
            )


def set_active_scene_runtime(name=None, scene_data=None):
    active_scene_runtime["name"] = name
    active_scene_runtime["data"] = scene_data
    if scene_data:
        try:
            target_ips = resolve_scene_effect_target_ips(scene_data)
        except Exception:
            target_ips = None
        if target_ips is None:
            target_ips = {
                ip for ip in LAMP_IPS
                if ip in scene_data
                and scene_data[ip].get("state", "off") == "on"
                and safe_brightness(scene_data[ip].get("brillo", 0)) > 0
            }
        active_scene_runtime["target_ips"] = set(target_ips or [])
        try:
            active_scene_runtime["effects"] = set(active_scene_effect_names(scene_data))
        except Exception:
            active_scene_runtime["effects"] = set()
    else:
        active_scene_runtime["target_ips"] = set()
        active_scene_runtime["effects"] = set()
        espacio_midi_effect_ips.clear()


def is_ip_in_active_scene_effect(ip):
    active_effects = {
        name for name, var in globals().get("effect_vars", {}).items()
        if getattr(var, "get", lambda: False)()
    }
    if not active_effects:
        return False

    target_ips = active_scene_runtime.get("target_ips", set())
    if target_ips:
        return ip in target_ips

    return (
        ip in espacio_midi_effect_ips
        or bool(selected_devices.get(ip) is not None and selected_devices[ip].get())
    )


def restore_ip_to_active_scene_effect(ip):
    scene_data = active_scene_runtime.get("data")
    if ip not in panels:
        return
    if not scene_data:
        effect_retired_ips.setdefault("atardecer", set()).discard(ip)
        espacio_midi_effect_ips.add(ip)
        selected_devices[ip].set(True)
        panel = panels[ip]
        if safe_brightness(getattr(panel, "last_brillo", 0)) <= 0:
            panel.last_brillo = 180
            try:
                panel.brillo_var.set(180)
            except Exception:
                pass
        update_panel_visual(panel)
        sync_espacio_laberintos_current_state(ip)
        return
    effect_retired_ips.setdefault("atardecer", set()).discard(ip)
    espacio_midi_effect_ips.add(ip)
    selected_devices[ip].set(True)
    try:
        apply_scene_mode_to_effect_target(
            scene_data,
            {ip},
            preserve_brightness=False,
            send_to_lamps=False,
        )
    except Exception:
        update_panel_visual(panels[ip])


def remove_ip_from_active_scene_effect(ip, turn_off=True):
    panel = panels.get(ip)
    if panel is None:
        return
    effect_retired_ips.setdefault("atardecer", set()).add(ip)
    espacio_midi_effect_ips.add(ip)
    selected_devices[ip].set(False)
    panel.scene_involved = True
    if turn_off:
        panel.last_brillo = 0
        try:
            panel.brillo_var.set(0)
        except Exception:
            pass
        send_off(ip)
    update_panel_visual(panel)
    sync_espacio_laberintos_current_state(ip)


def espacio_midi_set_lamp_power(ip, powered):
    panel = panels.get(ip)
    if panel is None:
        return
    if is_ip_in_active_scene_effect(ip):
        if powered:
            restore_ip_to_active_scene_effect(ip)
        else:
            remove_ip_from_active_scene_effect(ip, turn_off=True)
        refresh_espacio_midi_leds()
        return

    claim_lamps_for_manual_control(ip)
    selected_devices[ip].set(bool(powered))
    if powered:
        if safe_brightness(getattr(panel, "last_brillo", 0)) <= 0:
            panel.last_brillo = 180
            try:
                panel.brillo_var.set(panel.last_brillo)
            except Exception:
                pass
        if getattr(panel, "last_mode", "colour") == "white":
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)
        else:
            send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, panel.last_brillo)
    else:
        send_off(ip)
    update_panel_visual(panel)
    sync_espacio_laberintos_current_state(ip)


def espacio_midi_restore_lamp(ip, snapshot):
    panel = panels.get(ip)
    if panel is None or not snapshot:
        return
    selected_devices[ip].set(bool(snapshot.get("selected", False)))
    panel.last_mode = snapshot.get("mode", getattr(panel, "last_mode", "colour"))
    panel.last_hue = snapshot.get("h", getattr(panel, "last_hue", 0))
    panel.last_sat = snapshot.get("s", getattr(panel, "last_sat", 1))
    panel.last_brillo = snapshot.get("brillo", getattr(panel, "last_brillo", 0))
    panel.last_temp = snapshot.get("temp", getattr(panel, "last_temp", 128))
    try:
        panel.brillo_var.set(panel.last_brillo)
        panel.temp_var.set(panel.last_temp)
    except Exception:
        pass
    set_panel_mode(panel, panel.last_mode, send=False)
    if selected_devices[ip].get() and panel.last_brillo > 0:
        if panel.last_mode == "white":
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)
        else:
            send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, panel.last_brillo)
    else:
        send_off(ip)
    update_panel_visual(panel)
    sync_espacio_laberintos_current_state(ip)


def espacio_midi_snapshot_lamp(ip):
    panel = panels.get(ip)
    if panel is None or ip not in selected_devices:
        return None
    return {
        "selected": selected_devices[ip].get(),
        "mode": getattr(panel, "last_mode", "colour"),
        "h": getattr(panel, "last_hue", 0),
        "s": getattr(panel, "last_sat", 1),
        "brillo": getattr(panel, "last_brillo", 0),
        "temp": getattr(panel, "last_temp", 128),
    }


def espacio_midi_trigger_lamp(ip, restore_after_ms=320, snapshot=None):
    panel = panels.get(ip)
    if panel is None:
        return None
    if not is_ip_in_active_scene_effect(ip):
        claim_lamps_for_manual_control(ip)
    if snapshot is None:
        snapshot = espacio_midi_snapshot_lamp(ip)
    if snapshot is None:
        return None
    selected_devices[ip].set(True)
    trigger = espacio_midi_trigger_var.get()
    if trigger == "Pulso blanco":
        panel.last_mode = "white"
        panel.last_brillo = 255
        panel.last_temp = 170
        try:
            panel.brillo_var.set(255)
            panel.temp_var.set(170)
        except Exception:
            pass
        set_panel_mode(panel, "white", send=False)
        send_lamp_white(ip, 255, 170)
    elif trigger == "Flash rojo":
        panel.last_mode = "colour"
        panel.last_hue = 0
        panel.last_sat = 1
        panel.last_brillo = 255
        try:
            panel.brillo_var.set(255)
        except Exception:
            pass
        set_panel_mode(panel, "colour", send=False)
        send_lamp_color_safe(ip, 0, 1, 255)
    else:
        panel.last_brillo = 255
        try:
            panel.brillo_var.set(255)
        except Exception:
            pass
        if getattr(panel, "last_mode", "colour") == "white":
            send_lamp_white(ip, 255, panel.last_temp)
        else:
            send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, 255)
    update_panel_visual(panel)
    if restore_after_ms is not None:
        root.after(
            max(60, int(restore_after_ms)),
            lambda target_ip=ip, state=snapshot: espacio_midi_restore_lamp(target_ip, state),
        )
    return snapshot


def espacio_midi_send_pulse_level(ip, level):
    panel = panels.get(ip)
    if panel is None:
        return
    selected_devices[ip].set(level > 0)
    panel.last_brillo = level
    try:
        panel.brillo_var.set(level)
    except Exception:
        pass
    trigger = espacio_midi_trigger_var.get()
    if level <= 0:
        send_off(ip)
    elif trigger == "Pulso blanco":
        panel.last_mode = "white"
        panel.last_temp = 170
        try:
            panel.temp_var.set(170)
        except Exception:
            pass
        set_panel_mode(panel, "white", send=False)
        send_lamp_white(ip, level, panel.last_temp)
    elif trigger == "Flash rojo":
        panel.last_mode = "colour"
        panel.last_hue = 0
        panel.last_sat = 1
        set_panel_mode(panel, "colour", send=False)
        send_lamp_color_safe(ip, 0, 1, level)
    else:
        if getattr(panel, "last_mode", "colour") == "white":
            send_lamp_white(ip, level, panel.last_temp)
        else:
            send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, level)
    update_panel_visual(panel)


def start_espacio_midi_pulse(note, ip):
    note = int(note)
    stop_espacio_midi_pulse(note, turn_off=False)
    if not is_ip_in_active_scene_effect(ip):
        claim_lamps_for_manual_control(ip)
    state = {
        "ip": ip,
        "active": True,
        "step": 0,
        "levels": (18, 70, 145, 235, 255, 180, 80, 18),
    }
    espacio_midi_pulse_states[note] = state
    midi_led(note, 63)

    def loop():
        current = espacio_midi_pulse_states.get(note)
        if not current or not current.get("active"):
            return
        levels = current["levels"]
        level = levels[current["step"] % len(levels)]
        current["step"] += 1
        espacio_midi_send_pulse_level(ip, level)
        root.after(115, loop)

    loop()


def stop_espacio_midi_pulse(note, turn_off=True):
    state = espacio_midi_pulse_states.pop(int(note), None)
    if not state:
        return False
    state["active"] = False
    ip = state.get("ip")
    if turn_off and ip in panels:
        panel = panels[ip]
        selected_devices[ip].set(False)
        panel.last_brillo = 0
        try:
            panel.brillo_var.set(0)
        except Exception:
            pass
        send_off(ip)
        update_panel_visual(panel)
        sync_espacio_laberintos_current_state(ip)
    refresh_espacio_midi_leds()
    return True


def espacio_midi_solo_lamp(ip):
    target_group = get_lamp_group(ip)
    group_ips = [
        candidate_ip
        for candidate_ip in LAMP_IPS
        if get_lamp_group(candidate_ip) == target_group and is_espacio_lamp_connected(candidate_ip)
    ]
    for candidate_ip in group_ips:
        espacio_midi_set_lamp_power(candidate_ip, candidate_ip == ip)


def espacio_midi_toggle_scene_mark(ip):
    panel = panels.get(ip)
    if panel is None:
        return False
    selected_devices[ip].set(not selected_devices[ip].get())
    update_panel_visual(panel)
    sync_espacio_laberintos_current_state(ip)
    return selected_devices[ip].get()


def espacio_midi_freeze_lamp(ip):
    panel = panels.get(ip)
    if panel is None:
        return
    effect_retired_ips.setdefault("atardecer", set()).add(ip)
    panel.scene_involved = False
    selected_devices[ip].set(False)
    update_panel_visual(panel)
    sync_espacio_laberintos_current_state(ip)


def espacio_midi_apply_master_to_scene_ip(ip):
    panel = panels.get(ip)
    if panel is None:
        return
    modo = maestro_mode.get()
    brillo = max(8, safe_brightness(maestro_brillo.get()))
    panel.last_mode = modo
    panel.mode_var.set(modo)
    panel.last_brillo = brillo
    try:
        panel.brillo_var.set(brillo)
    except Exception:
        pass
    if modo == "colour":
        panel.last_hue = maestro_hsv["h"]
        panel.last_sat = maestro_hsv["s"]
        try:
            panel.colorwheel_lamp.set_color(panel.last_hue, panel.last_sat, max(0.01, brillo / 255))
        except Exception:
            pass
    else:
        panel.last_temp = int(maestro_temp.get())
        try:
            panel.temp_var.set(panel.last_temp)
            panel.whitewheel_lamp.set_temp_value(panel.last_temp)
        except Exception:
            pass
    selected_devices[ip].set(True)
    effect_retired_ips.setdefault("atardecer", set()).discard(ip)
    set_panel_mode(panel, modo, send=False)
    update_panel_visual(panel)
    sync_espacio_laberintos_current_state(ip)


def handle_espacio_midi_note_off(note):
    if stop_espacio_midi_pulse(note, turn_off=True):
        return True
    state = espacio_midi_hold_states.pop(int(note), None)
    if not state:
        return False
    espacio_midi_restore_lamp(state.get("ip"), state.get("snapshot"))
    refresh_espacio_midi_leds()
    return True


def handle_espacio_midi_note(note):
    cell = get_espacio_cell_for_apc_note(note)
    if cell is None:
        return False
    row, col = cell
    lamp_id = get_espacio_lamp_at(row, col)
    if not lamp_id:
        espacio_status_var.set(f"Pad MIDI {note}: celda vacia.")
        refresh_espacio_midi_leds()
        return True
    ip = get_lamp_ip_by_id(lamp_id)
    if not ip:
        espacio_status_var.set(f"Pad MIDI {note}: {lamp_id} no encontrada.")
        refresh_espacio_midi_leds()
        return True
    if not is_espacio_lamp_connected(ip):
        espacio_status_var.set(f"{lamp_id} no esta conectada.")
        refresh_espacio_midi_leds()
        return True

    mode = espacio_midi_action_var.get()
    if mode == "pulse":
        start_espacio_midi_pulse(note, ip)
        espacio_status_var.set(f"{lamp_id}: pulso vivo hasta soltar.")
    elif mode == "hold":
        snapshot = espacio_midi_snapshot_lamp(ip)
        espacio_midi_trigger_lamp(ip, restore_after_ms=None, snapshot=snapshot)
        espacio_midi_hold_states[int(note)] = {"ip": ip, "snapshot": snapshot}
        espacio_status_var.set(f"{lamp_id}: sosteniendo {espacio_midi_trigger_var.get()}.")
    elif mode == "solo":
        espacio_midi_solo_lamp(ip)
        espacio_status_var.set(f"{lamp_id} en solo dentro de su grupo.")
    elif mode == "master":
        if is_ip_in_active_scene_effect(ip):
            espacio_midi_apply_master_to_scene_ip(ip)
        else:
            apply_master_to_ips([ip])
        espacio_status_var.set(f"{lamp_id} copio el control maestro.")
    elif mode == "scene_mark":
        marcado = espacio_midi_toggle_scene_mark(ip)
        espacio_status_var.set(f"{lamp_id} {'sumada a' if marcado else 'retirada de'} la seleccion de escena.")
    elif mode == "freeze":
        espacio_midi_freeze_lamp(ip)
        espacio_status_var.set(f"{lamp_id} congelada fuera de la seleccion viva.")
    else:
        espacio_midi_set_lamp_power(ip, not selected_devices[ip].get())
        estado = "encendida" if selected_devices[ip].get() else "apagada"
        espacio_status_var.set(f"{lamp_id} {estado} desde MIDI.")
    refresh_espacio_midi_leds()
    return True


def on_espacio_cell_click(row, col):
    selected = espacio_selected_lamp.get("id")
    current = get_espacio_lamp_at(row, col)
    if selected and selected != current:
        assign_espacio_lamp(selected, row, col)
    elif current:
        select_espacio_lamp(current)


def on_espacio_palette_press(lamp_id):
    espacio_drag_lamp["id"] = lamp_id
    select_espacio_lamp(lamp_id)


def on_espacio_palette_release(event):
    lamp_id = espacio_drag_lamp.get("id") or espacio_selected_lamp.get("id")
    cell = get_espacio_cell_from_event(event)
    if lamp_id and cell:
        assign_espacio_lamp(lamp_id, cell[0], cell[1])
    espacio_drag_lamp["id"] = None


def apply_espacio_matrix_size():
    try:
        rows = int(espacio_rows_var.get())
        cols = int(espacio_cols_var.get())
    except Exception:
        messagebox.showwarning("ESPACIO LABERINTOS", "Revisa filas y columnas.")
        return
    espacio_laberintos_data["rows"] = max(1, min(ESPACIO_MAX_ROWS, rows))
    espacio_laberintos_data["cols"] = max(1, min(ESPACIO_MAX_COLS, cols))
    normalize_espacio_laberintos()
    build_espacio_laberintos_grid()
    rebuild_layout = globals().get("rebuild_lamp_layout")
    if callable(rebuild_layout):
        rebuild_layout()


def save_espacio_from_ui():
    normalize_espacio_laberintos()
    if save_espacio_laberintos(espacio_laberintos_data):
        espacio_status_var.set("Espacio guardado.")
        messagebox.showinfo("ESPACIO LABERINTOS", "Mapa espacial guardado.")


def clear_espacio_all():
    if messagebox.askyesno("ESPACIO LABERINTOS", "Quitar todas las lamparas de la matriz?"):
        espacio_laberintos_data["placements"] = {}
        espacio_status_var.set("Matriz limpia.")
        rebuild_layout = globals().get("rebuild_lamp_layout")
        if callable(rebuild_layout):
            rebuild_layout()
        else:
            refresh_espacio_laberintos_visual()


def refresh_espacio_laberintos_visual():
    if not espacio_cells:
        refresh_espacio_midi_leds()
        return
    placements = espacio_laberintos_data.get("placements", {})
    selected = espacio_selected_lamp.get("id")
    placed_ids = set(placements.keys())
    for (row, col), cell in espacio_cells.items():
        lamp_id = get_espacio_lamp_at(row, col)
        if lamp_id:
            ip = get_lamp_ip_by_id(lamp_id)
            group = get_lamp_group(ip) if ip else "sin_grupo"
            is_connected = is_espacio_lamp_connected(ip)
            bg = "#14351d" if group == "efectos" else "#34311a" if group == "atmosfera" else "#24313a"
            outline = "#20bdec" if lamp_id == selected else "#03A125" if is_connected else "#58616a"
            cell.config(bg=bg, highlightbackground=outline, highlightcolor=outline)
        else:
            cell.config(bg="#111519", highlightbackground="#303840", highlightcolor="#303840")
    for lamp_id, widget in espacio_palette_items.items():
        ip = get_lamp_ip_by_id(lamp_id)
        is_connected = is_espacio_lamp_connected(ip)
        is_placed = lamp_id in placed_ids
        if is_connected:
            bg = "#198f41"
            fg = "#ffffff"
        else:
            bg = "#7b2028"
            fg = "#ffd9d9"

        if is_placed:
            border = "#f1c40f"
        else:
            border = "#212529"

        if lamp_id == selected:
            border = "#ffffff"
            fg = "#ffffff"
        border_frame = getattr(widget, "border_frame", None)
        if border_frame is not None:
            border_frame.config(bg=border)
        widget.config(bg=bg, fg=fg, highlightbackground=border, highlightcolor=border)
    refresh_espacio_midi_leds()


def build_espacio_empty_cell(cell, row, col):
    for child in cell.winfo_children():
        child.destroy()
    empty = tk.Label(
        cell,
        text="+",
        bg="#111519",
        fg="#303840",
        bd=0,
        font=("Segoe UI", 18, "bold"),
        cursor="hand2",
    )
    empty.pack(fill="both", expand=True)
    empty.bind("<Button-1>", lambda e, r=row, c=col: on_espacio_cell_click(r, c))
    empty.bind("<ButtonRelease-1>", lambda e, r=row, c=col: on_espacio_cell_click(r, c) if espacio_drag_lamp.get("id") else None)
    empty.bind("<Button-3>", lambda e, r=row, c=col: clear_espacio_cell(r, c))


def build_espacio_laberintos_grid():
    normalize_espacio_laberintos()
    for child in espacio_grid_frame.winfo_children():
        child.destroy()
    espacio_cells.clear()
    rows = espacio_laberintos_data["rows"]
    cols = espacio_laberintos_data["cols"]
    for r in range(rows):
        espacio_grid_frame.grid_rowconfigure(r, weight=1, minsize=178)
        for c in range(cols):
            espacio_grid_frame.grid_columnconfigure(c, weight=1, minsize=128)
            cell = tk.Frame(
                espacio_grid_frame,
                bg="#111519",
                bd=1,
                relief="flat",
                highlightthickness=2,
                highlightbackground="#303840",
            )
            cell.is_espacio_cell = True
            cell.espacio_cell = (r, c)
            cell.grid(row=r, column=c, sticky="nsew", padx=2, pady=2)
            cell.bind("<Button-1>", lambda e, row=r, col=c: on_espacio_cell_click(row, col))
            cell.bind("<ButtonRelease-1>", lambda e, row=r, col=c: on_espacio_cell_click(row, col) if espacio_drag_lamp.get("id") else None)
            cell.bind("<Button-3>", lambda e, row=r, col=c: clear_espacio_cell(row, col))
            espacio_cells[(r, c)] = cell
            build_espacio_empty_cell(cell, r, c)
    refresh_espacio_laberintos_visual()


frame_espacio = tk.LabelFrame(
    frame_lamps,
    text="ESPACIO LABERINTOS",
    bg="#212529",
    fg="#20bdec",
    font=("Segoe UI", 12, "bold"),
    padx=8,
    pady=8,
)
frame_espacio.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 10))

espacio_toolbar = tk.Frame(frame_espacio, bg="#212529")
espacio_toolbar.pack(fill="x", pady=(0, 6))
espacio_matrix_tools = tk.Frame(espacio_toolbar, bg="#212529")
espacio_matrix_tools.pack(side="left", anchor="w")
tk.Label(espacio_matrix_tools, text="Filas", bg="#212529", fg="#b9e3f7", font=("Segoe UI", 8)).pack(side="left")
espacio_rows_var = tk.IntVar(value=espacio_laberintos_data.get("rows", ESPACIO_DEFAULT_ROWS))
tk.Spinbox(espacio_matrix_tools, from_=1, to=ESPACIO_MAX_ROWS, width=4, textvariable=espacio_rows_var, bg="#111519", fg="#d8f6ff",
           relief="flat").pack(side="left", padx=(4, 8))
tk.Label(espacio_matrix_tools, text="Columnas", bg="#212529", fg="#b9e3f7", font=("Segoe UI", 8)).pack(side="left")
espacio_cols_var = tk.IntVar(value=espacio_laberintos_data.get("cols", ESPACIO_DEFAULT_COLS))
tk.Spinbox(espacio_matrix_tools, from_=1, to=ESPACIO_MAX_COLS, width=4, textvariable=espacio_cols_var, bg="#111519", fg="#d8f6ff",
           relief="flat").pack(side="left", padx=(4, 8))
tk.Button(espacio_matrix_tools, text="Aplicar matriz", command=apply_espacio_matrix_size,
          bg="#35bdf2", fg="#000", relief="flat", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 5))
tk.Button(espacio_matrix_tools, text="Guardar espacio", command=save_espacio_from_ui,
          bg="#27ae60", fg="#fff", relief="flat", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 5))
tk.Button(espacio_matrix_tools, text="Limpiar", command=clear_espacio_all,
          bg="#807D7D", fg="#fff", relief="flat", font=("Segoe UI", 8, "bold")).pack(side="left")
tk.Label(espacio_toolbar, textvariable=espacio_status_var, bg="#212529", fg="#9fe7ff",
         font=("Segoe UI", 8, "italic"), anchor="w").pack(side="left", fill="x", expand=True, padx=(12, 0))

espacio_midi_controls = tk.LabelFrame(
    frame_espacio,
    text="Control Buttons MIDI",
    bg="#212529",
    fg="#20bdec",
    font=("Segoe UI", 9, "bold"),
    padx=6,
    pady=4,
    bd=1,
    relief="solid",
)
espacio_midi_controls.pack(fill="x", pady=(0, 6))
espacio_midi_controls.grid_columnconfigure(0, weight=1)
espacio_midi_controls.grid_columnconfigure(1, weight=0)

espacio_midi_modes = tk.Frame(espacio_midi_controls, bg="#212529")
espacio_midi_modes.grid(row=0, column=0, sticky="ew")

for idx, (value, label) in enumerate(ESPACIO_MIDI_ACTIONS.items()):
    tk.Radiobutton(
        espacio_midi_modes,
        text=label,
        variable=espacio_midi_action_var,
        value=value,
        bg="#212529",
        fg="#d9f3ff",
        selectcolor="#111519",
        activebackground="#212529",
        activeforeground="#20bdec",
        font=("Segoe UI", 8, "bold"),
    ).grid(row=idx // 4, column=idx % 4, sticky="w", padx=(0, 8), pady=1)

espacio_midi_trigger_box = tk.Frame(espacio_midi_controls, bg="#212529")
espacio_midi_trigger_box.grid(row=0, column=1, sticky="e", padx=(12, 0))

tk.Label(
    espacio_midi_trigger_box,
    text="Tipo:",
    bg="#212529",
    fg="#8fb8c9",
    font=("Segoe UI", 8, "bold"),
).pack(side="left", padx=(0, 4))

ttk.Combobox(
    espacio_midi_trigger_box,
    textvariable=espacio_midi_trigger_var,
    values=list(ESPACIO_MIDI_TRIGGERS),
    state="readonly",
    width=13,
    font=("Segoe UI", 8),
).pack(side="left")

espacio_palette = tk.Frame(frame_espacio, bg="#212529")
espacio_palette.pack(fill="x", pady=(0, 6))


def build_espacio_palette_group(parent, title, group_key, accent):
    lamps = [ip for ip in get_sequence_ordered_lamp_ips() if get_lamp_group(ip) == group_key]
    if not lamps:
        return
    box = tk.LabelFrame(
        parent,
        text=title,
        bg="#212529",
        fg=accent,
        font=("Segoe UI", 9, "bold"),
        padx=6,
        pady=4,
        bd=1,
        relief="solid",
    )
    box.pack(side="left", fill="x", expand=False, padx=(0, 10))
    for ip in lamps:
        lamp_id = str(get_lamp_id(ip))
        item_border = tk.Frame(box, bg="#212529", padx=1, pady=1)
        item_border.pack(side="left", padx=2, pady=2)
        item = tk.Label(
            item_border,
            text=lamp_id,
            bg="#111519",
            fg=accent,
            width=4,
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#111519",
            font=("Segoe UI", 8, "bold"),
            cursor="hand2",
        )
        item.border_frame = item_border
        item.pack(side="left")
        item.bind("<ButtonPress-1>", lambda e, lid=lamp_id: on_espacio_palette_press(lid))
        item.bind("<ButtonRelease-1>", on_espacio_palette_release)
        item.bind("<Button-3>", lambda e, lid=lamp_id: remove_espacio_lamp(lid))
        item_border.bind("<ButtonPress-1>", lambda e, lid=lamp_id: on_espacio_palette_press(lid))
        item_border.bind("<ButtonRelease-1>", on_espacio_palette_release)
        item_border.bind("<Button-3>", lambda e, lid=lamp_id: remove_espacio_lamp(lid))
        espacio_palette_items[lamp_id] = item


build_espacio_palette_group(espacio_palette, "Bichos", "efectos", "#20bdec")
build_espacio_palette_group(espacio_palette, "Atmosfera", "atmosfera", "#f1c40f")
build_espacio_palette_group(espacio_palette, "Sin grupo", "sin_grupo", "#c9d8e3")

espacio_grid_frame = tk.Frame(frame_espacio, bg="#181b1e")
espacio_grid_frame.pack(fill="x")
build_espacio_laberintos_grid()

group_sections = {
    "efectos": {
        "frame": tk.LabelFrame(frame_lamps, text="Lamparas bichos", bg="#212529", fg="#20bdec",
                               font=("Segoe UI", 12, "bold"), padx=8, pady=8),
        "items": [],
    },
    "atmosfera": {
        "frame": tk.LabelFrame(frame_lamps, text="Lamparas de atmosfera", bg="#212529", fg="#20bdec",
                               font=("Segoe UI", 12, "bold"), padx=8, pady=8),
        "items": [],
    },
    "sin_grupo": {
        "frame": tk.LabelFrame(frame_lamps, text="Sin grupo", bg="#212529", fg="#20bdec",
                               font=("Segoe UI", 12, "bold"), padx=8, pady=8),
        "items": [],
    },
}

for ip in LAMP_IPS:
    group = get_lamp_group(ip)
    if group not in group_sections:
        group = "sin_grupo"
    group_sections[group]["items"].append(ip)

row_section = 1
for key in ("efectos", "atmosfera", "sin_grupo"):
    if not group_sections[key]["items"]:
        continue
    section = group_sections[key]["frame"]
    # Los grupos ahora se gestionan visualmente desde ESPACIO LABERINTOS.
    # Se conservan como contenedores internos para no romper referencias existentes.
    for col in range(5):
        section.grid_columnconfigure(col, weight=0, minsize=160)
    row_section += 1

frame_hidden_lamp_controls = tk.Frame(frame_lamps, bg="#181b1e")


def toggle_lamp_power(ip):
    panel = panels[ip]
    update_panel_visual(panel)
    if selected_devices[ip].get():
        claim_lamps_for_manual_control(ip)
        if ip in effect_retired_ips.get("atardecer", set()):
            panel.last_brillo = max(80, safe_brightness(getattr(panel, "last_brillo", 180)))
        if panel.last_mode == "colour":
            send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, panel.last_brillo)
        else:
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)
    else:
        send_off(ip)


def build_lamp_panel(parent, ip, idx):
    lamp_group = get_lamp_group(ip)
    group_badge = "BI" if lamp_group == "efectos" else "AT" if lamp_group == "atmosfera" else "SG"
    group_color = "#20bdec" if lamp_group == "efectos" else "#f1c40f" if lamp_group == "atmosfera" else "#c9d8e3"
    compact_space = bool(getattr(parent, "is_espacio_cell", False))
    wheel_radius = 44 if compact_space else 55
    wheel_size = 94 if compact_space else 118
    slider_length = 58 if compact_space else 72
    entry_width = 9 if compact_space else 15
    panel_padx = 3 if compact_space else 5
    panel_pady = 3 if compact_space else 4
    panel = tk.LabelFrame(
        parent,
        bg="#17291c",
        fg="#20bdec",
        font=("Segoe UI", 9, "bold"),
        padx=panel_padx,
        pady=panel_pady,
        bd=2,
        highlightthickness=2,
        highlightbackground="#03A125",
        highlightcolor="#03A125"
    )
    panel.ip = ip
    panel.grid(row=idx // 5, column=idx % 5, padx=5, pady=5, sticky="nw")
    panels[ip] = panel

    connection_strip = tk.Frame(panel, bg="#68737d", height=4)
    connection_strip.pack(fill="x", pady=(0, 3))
    panel.connection_strip = connection_strip

    top = tk.Frame(panel, bg="#17291c")
    panel.top_frame = top
    top.pack(fill="x")
    top.grid_columnconfigure(0, weight=1)
    entry = tk.Entry(top, font=("Segoe UI", 8), width=entry_width, bg="#111519", fg="#b9e3f7", relief="flat")
    entry.insert(0, lamp_names.get(ip, f"Lampara {ip}"))
    entry.grid(row=0, column=0, sticky="ew", padx=(0, 3))
    entry.bind("<FocusOut>", lambda e, ip=ip, entry=entry: update_name(ip, entry))

    group_badge_widget = tk.Label(
        top,
        text=group_badge,
        bg="#111519",
        fg=group_color,
        bd=1,
        relief="solid",
        font=("Segoe UI", 7, "bold"),
        width=3,
    )
    group_badge_widget.grid(row=0, column=1, sticky="e", padx=(0, 3))
    panel.group_badge = group_badge_widget

    if compact_space:
        remove_btn = tk.Button(
            top,
            text="X",
            command=lambda lid=str(get_lamp_id(ip)): remove_espacio_lamp(lid),
            bg="#5a1f24",
            fg="#ffffff",
            activebackground="#7b2028",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            width=1,
            font=("Segoe UI", 7, "bold"),
        )
        remove_btn.grid(row=0, column=5, sticky="ne")
        panel.remove_button = remove_btn

    scene_dot = tk.Label(
        top,
        text="",
        width=1,
        bg="#17291c",
        fg="#17291c",
        highlightthickness=1,
        highlightbackground="#17291c",
        font=("Segoe UI", 6, "bold"),
    )
    scene_dot.grid(row=0, column=2, sticky="e", padx=(0, 3))
    panel.scene_dot = scene_dot

    power_dot = tk.Frame(top, width=7, height=7, bg="#3b444c", highlightthickness=1, highlightbackground="#111519")
    power_dot.grid(row=0, column=3, sticky="e", padx=(0, 3))
    power_dot.pack_propagate(False)
    panel.power_dot = power_dot

    on_check = tk.Checkbutton(top, text="On", variable=selected_devices[ip],
                              command=lambda ip=ip: toggle_lamp_power(ip),
                              bg="#17291c", fg="#20bdec", selectcolor="#17291c",
                              activebackground="#17291c", activeforeground="#20bdec",
                              font=("Segoe UI", 8, "bold"))
    on_check.grid(row=0, column=4, sticky="e", padx=(0, 3))
    panel.on_check = on_check

    mode_row = tk.Frame(panel, bg="#17291c")
    panel.mode_row = mode_row
    mode_row.pack(fill="x", pady=(3, 2))
    modo_var = tk.StringVar(value="colour")
    panel.mode_var = modo_var
    panel.last_mode = "colour"

    preview_swatch = tk.Frame(
        mode_row,
        width=34,
        height=15,
        bg="#ff0000",
        bd=1,
        relief="sunken",
        highlightthickness=1,
        highlightbackground="#111519",
    )
    preview_swatch.pack(side="left", padx=(2, 6))
    preview_swatch.pack_propagate(False)
    panel.preview_swatch = preview_swatch

    mode_colour = tk.Radiobutton(mode_row, text="C", variable=modo_var, value="colour",
                                 command=lambda p=panel: set_panel_mode(p, "colour"),
                                 bg="#17291c", fg="#20bdec", selectcolor="#17291c",
                                 font=("Segoe UI", 8, "bold"))
    mode_colour.pack(side="left", padx=(0, 2))
    mode_white = tk.Radiobutton(mode_row, text="B", variable=modo_var, value="white",
                                command=lambda p=panel: set_panel_mode(p, "white"),
                                bg="#17291c", fg="#f1c40f", selectcolor="#17291c",
                                font=("Segoe UI", 8, "bold"))
    mode_white.pack(side="left", padx=2)
    panel.mode_colour_radio = mode_colour
    panel.mode_white_radio = mode_white

    body = tk.Frame(panel, bg="#17291c")
    panel.body_frame = body
    body.pack(fill="x")
    brillo_var = tk.IntVar(value=180)
    temp_var = tk.IntVar(value=128)
    panel.brillo_var = brillo_var
    panel.temp_var = temp_var
    panel.last_hue = 0
    panel.last_sat = 1
    panel.last_brillo = brillo_var.get()
    panel.last_temp = temp_var.get()

    def on_color(h, s, v, ip=ip, panel=panel):
        if is_preview_update_suspended():
            return
        claim_lamps_for_manual_control(ip)
        panel.last_hue = h
        panel.last_sat = s
        panel.last_brillo = max(80, safe_brightness(panel.brillo_var.get()))
        set_panel_mode(panel, "colour", send=False)
        if ip in effect_retired_ips.get("atardecer", set()) and not selected_devices[ip].get():
            selected_devices[ip].set(True)
            update_panel_visual(panel)
        if selected_devices[ip].get():
            send_lamp_color_safe(ip, h, s, panel.last_brillo)

    def on_white(value, ip=ip, panel=panel):
        if is_preview_update_suspended():
            return
        claim_lamps_for_manual_control(ip)
        panel.last_temp = int(value)
        panel.temp_var.set(panel.last_temp)
        set_panel_mode(panel, "white", send=False)
        if ip in effect_retired_ips.get("atardecer", set()) and not selected_devices[ip].get():
            selected_devices[ip].set(True)
            panel.last_brillo = max(80, safe_brightness(panel.brillo_var.get()))
            update_panel_visual(panel)
        if selected_devices[ip].get():
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)

    wheel_slot = tk.Frame(body, bg="#17291c", width=118, height=118)
    panel.wheel_slot = wheel_slot
    wheel_slot.pack(side="left", padx=(0, 5))
    wheel_slot.pack_propagate(False)

    wheel_slot.config(width=wheel_size, height=wheel_size)

    colorwheel = RealColorWheel(wheel_slot, radius=wheel_radius, callback=on_color, bg="#111519", bd=0, highlightthickness=0)
    whitewheel = WhiteTempWheel(wheel_slot, radius=wheel_radius, callback=on_white, bg="#111519", bd=0, highlightthickness=0)
    panel.colorwheel_lamp = colorwheel
    panel.whitewheel_lamp = whitewheel
    colorwheel.pack()

    sliders = tk.Frame(body, bg="#17291c")
    panel.sliders_frame = sliders
    sliders.pack(side="left")
    tk.Label(sliders, text="I", bg="#17291c", fg="#20bdec", font=("Segoe UI", 7, "bold")).grid(row=0, column=0)
    tk.Label(sliders, text="T", bg="#17291c", fg="#f1c40f", font=("Segoe UI", 7, "bold")).grid(row=0, column=1)

    def on_brillo_change(value, ip=ip, panel=panel):
        if is_preview_update_suspended():
            return
        claim_lamps_for_manual_control(ip)
        panel.last_brillo = safe_brightness(value)
        update_panel_visual(panel)
        if selected_devices[ip].get():
            if panel.last_brillo <= 0:
                send_off(ip)
            elif panel.last_mode == "colour":
                send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, panel.last_brillo)
            else:
                send_lamp_white(ip, panel.last_brillo, panel.last_temp)

    def on_temp_panel(value, ip=ip, panel=panel):
        if is_preview_update_suspended():
            return
        claim_lamps_for_manual_control(ip)
        panel.last_temp = int(float(value))
        update_panel_visual(panel)
        if panel.last_mode == "white" and selected_devices[ip].get():
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)

    tk.Scale(sliders, from_=255, to=0, orient="vertical", variable=brillo_var,
             length=slider_length, width=4, sliderlength=10, showvalue=False, bg="#17291c", fg="#20bdec",
             highlightthickness=0, command=on_brillo_change).grid(row=1, column=0, padx=1)
    tk.Scale(sliders, from_=255, to=0, orient="vertical", variable=temp_var,
             length=slider_length, width=4, sliderlength=10, showvalue=False, bg="#17291c", fg="#f1c40f",
             highlightthickness=0, command=on_temp_panel).grid(row=1, column=1, padx=1)

    update_panel_visual(panel)


def snapshot_lamp_panel_states():
    states = {}
    for ip, panel in list(panels.items()):
        states[ip] = {
            "last_mode": getattr(panel, "last_mode", "colour"),
            "last_hue": getattr(panel, "last_hue", 0),
            "last_sat": getattr(panel, "last_sat", 1),
            "last_brillo": getattr(panel, "last_brillo", 0),
            "last_temp": getattr(panel, "last_temp", 128),
            "brillo_var": panel.brillo_var.get() if hasattr(panel, "brillo_var") else getattr(panel, "last_brillo", 0),
            "temp_var": panel.temp_var.get() if hasattr(panel, "temp_var") else getattr(panel, "last_temp", 128),
        }
    return states


def restore_lamp_panel_state(ip, state):
    panel = panels.get(ip)
    if panel is None or not state:
        return
    panel.last_mode = state.get("last_mode", "colour")
    panel.last_hue = state.get("last_hue", 0)
    panel.last_sat = state.get("last_sat", 1)
    panel.last_brillo = state.get("last_brillo", 0)
    panel.last_temp = state.get("last_temp", 128)
    try:
        panel.brillo_var.set(state.get("brillo_var", panel.last_brillo))
        panel.temp_var.set(state.get("temp_var", panel.last_temp))
    except Exception:
        pass
    try:
        set_panel_mode(panel, panel.last_mode, send=False)
    except Exception:
        pass
    update_panel_visual(panel)


def rebuild_lamp_layout():
    previous_states = snapshot_lamp_panel_states()

    for panel in list(panels.values()):
        try:
            panel.destroy()
        except Exception:
            pass
    panels.clear()

    for cell, (row, col) in [(cell, coords) for coords, cell in espacio_cells.items()]:
        build_espacio_empty_cell(cell, row, col)

    for key in ("efectos", "atmosfera", "sin_grupo"):
        section = group_sections[key]["frame"]
        for child in section.winfo_children():
            child.destroy()
    for child in frame_hidden_lamp_controls.winfo_children():
        child.destroy()

    normalize_espacio_laberintos()
    placed_ids = set(espacio_laberintos_data.get("placements", {}).keys())

    for lamp_id, pos in espacio_laberintos_data.get("placements", {}).items():
        ip = get_lamp_ip_by_id(lamp_id)
        if not ip:
            continue
        row = int(pos.get("row", -1))
        col = int(pos.get("col", -1))
        cell = espacio_cells.get((row, col))
        if cell is None:
            continue
        for child in cell.winfo_children():
            child.destroy()
        build_lamp_panel(cell, ip, 0)
        if ip in panels:
            panels[ip].grid_configure(row=0, column=0, sticky="nsew", padx=2, pady=2)
            cell.grid_rowconfigure(0, weight=1)
            cell.grid_columnconfigure(0, weight=1)

    for key in ("efectos", "atmosfera", "sin_grupo"):
        visible_idx = 0
        for ip in group_sections[key]["items"]:
            if str(get_lamp_id(ip)) in placed_ids:
                continue
            build_lamp_panel(frame_hidden_lamp_controls, ip, visible_idx)
            visible_idx += 1

    for ip, state in previous_states.items():
        restore_lamp_panel_state(ip, state)

    refresh_espacio_laberintos_visual()


rebuild_lamp_layout()

for ip in LAMP_IPS:
    selected_devices[ip].set(False)
    if ip in panels:
        panels[ip].last_brillo = 0
        panels[ip].brillo_var.set(0)
        update_panel_visual(panels[ip])
    send_off(ip)

# ----- 3. FRAME DERECHO (escenas) -----
frame_right = tk.Frame(frame_main, bg="#202428", width=330)
frame_right.pack(side="right", fill="both", padx=(10), pady=10)
frame_right.pack_propagate(False)
# Panel de Escenas (tu panel de siempre, a la derecha del de efectos)
frame_lateral = tk.Frame(frame_main, bg="#181b1e", width=280)


# -------- PANEL DE ESCENAS EN LA DERECHA ---------

from .escenas_proyectos import (
    load_escenas, save_escenas,
    get_effects_state, apply_effects_state,
    guardar_escena, actualizar_escena_completa,
    load_proyectos, save_proyectos,
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
    effects_state = build_scene_save_effects_state()
    effects_layers = build_scene_effect_layers(effects_state, get_scene_save_effect_target())
    save_selected_devices = build_scene_save_selected_devices()

    # 5) Llamar al módulo para que arme y guarde todo
    ok = guardar_escena(
        nombre,
        fade_in_val,
        fade_out_val,
        LAMP_IPS,
        panels,
        save_selected_devices,
        effects_state,
        effects_layers,
    )

    if ok:
        # 6) Actualizar la lista de escenas en la UI
        actualizar_lista_escenas()
        marcar_proyecto_modificado()
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

FADE_MAX_SECONDS = 30.0
FADE_UI_STEP_SECONDS = 1.0
FADE_SECONDS_PER_BRIGHTNESS_STEP = 0.125


def normalize_fade_seconds(value):
    try:
        value = float(value)
    except Exception:
        return 0.0
    if value <= 0:
        return 0.0
    return round(min(FADE_MAX_SECONDS, value), 2)


def useful_fade_seconds(requested_seconds, from_brightness, to_brightness):
    requested_seconds = normalize_fade_seconds(requested_seconds)
    delta = abs(safe_brightness(to_brightness) - safe_brightness(from_brightness))
    if requested_seconds <= 0 or delta <= 0:
        return 0.0

    dynamic_max = max(1.0, min(FADE_MAX_SECONDS, delta * FADE_SECONDS_PER_BRIGHTNESS_STEP))
    return round(min(requested_seconds, dynamic_max), 2)


def ease_in_out_sine(x):
    return -(math.cos(math.pi * x) - 1) / 2


def hay_efectos_activos():
    return any(var.get() for var in effect_vars.values())


preview_updates_suspended = False
preview_updates_block_until = 0.0


def is_preview_update_suspended():
    return preview_updates_suspended or time.monotonic() < preview_updates_block_until


def mostrar_estado_escena_en_paneles(nombre_escena, actualizar_seleccion=True):
    """
    Muestra un PREVIEW de la escena en los paneles,
    pero SIN modificar el estado real last_* de las lámparas.
    """
    global preview_updates_suspended, preview_updates_block_until
    escenas = load_escenas()
    datos = escenas.get("datos", {})

    if nombre_escena not in datos:
        return

    escena = datos[nombre_escena]

    def scene_raw_brightness(value):
        try:
            return max(0, min(255, int(float(value))))
        except Exception:
            return 0

    def estado_escena_para_ip(ip):
        estado = escena.get(ip, {})
        if estado:
            return estado, True
        lamparas = escena.get("lamparas", {})
        lamp_id = str(get_lamp_id(ip))
        nested = lamparas.get(lamp_id, {})
        if nested:
            return nested, True
        return {}, False

    def scene_involved_ips():
        involved = set()

        resolve_targets = globals().get("resolve_scene_effect_target_ips")
        if callable(resolve_targets):
            try:
                involved.update(resolve_targets(escena) or [])
            except Exception:
                pass

        for lamp_ip in LAMP_IPS:
            estado, has_state = estado_escena_para_ip(lamp_ip)
            if not has_state:
                continue
            if estado.get("state") == "on" or scene_raw_brightness(estado.get("brillo", 0)) > 0:
                involved.add(lamp_ip)

        return involved

    involved_ips = scene_involved_ips()

    preview_updates_suspended = True
    preview_updates_block_until = time.monotonic() + 0.5
    try:
        for panel in panels.values():
            panel.scene_involved = False

        for ip in LAMP_IPS:
            estado, _has_scene_state = estado_escena_para_ip(ip)
            panel = panels.get(ip)
            if panel is None:
                continue

            panel.scene_involved = ip in involved_ips

            preview_on = (
                estado.get("state", "off") == "on"
                and scene_raw_brightness(estado.get("brillo", getattr(panel, "last_brillo", 255))) > 0
            )

            # ----- PREVIEW DEL MODO -----
            modo = estado.get("modo", "colour")
            set_panel_mode_preview(panel, modo)

            # ----- PREVIEW DEL BRILLO (solo UI) -----
            if actualizar_seleccion and hasattr(panel, "brillo_var"):
                panel.brillo_var.set(scene_raw_brightness(estado.get("brillo", 0)))

            # ----- PREVIEW DE SELECCION ON/OFF -----
            # Si hay efectos corriendo, no tocamos selected_devices:
            # esa seleccion es parte del destino vivo del efecto actual.
            if actualizar_seleccion:
                if estado.get("state", "off") == "on":
                    selected_devices[ip].set(True)
                else:
                    selected_devices[ip].set(False)

            # ----- PREVIEW DE COLOR / TEMP -----
            if modo == "colour":
                h = estado.get("h", getattr(panel, "last_hue", 0))
                s = estado.get("s", getattr(panel, "last_sat", 1))
                set_panel_preview_swatch(panel, modo, h=h, s=s, is_on=preview_on)

                # NO tocamos last_hue / last_sat, solo el wheel
                if hasattr(panel, "colorwheel_lamp"):
                    v = estado.get("brillo", 255) / 255.0
                    panel.colorwheel_lamp.set_color(h, s, v)
            else:
                temp = estado.get("temp", getattr(panel, "last_temp", 4000))
                set_panel_preview_swatch(panel, modo, temp=temp, is_on=preview_on)
                if hasattr(panel, "whitewheel_lamp"):
                    panel.whitewheel_lamp.set_temp_value(temp)
                if actualizar_seleccion and hasattr(panel, "temp_var"):
                    panel.temp_var.set(temp)

            apply_lamp_visual_state(panel, update_swatch=False)

    finally:
        preview_updates_suspended = False
        preview_updates_block_until = 0.0
        refresh_espacio = globals().get("refresh_espacio_laberintos_visual")
        if callable(refresh_espacio):
            refresh_espacio()


 
 # ----------- PROYECTOS EN LA UI -----------

lista_proyectos = tk.StringVar(value=[])
proyecto_activo = {"nombre": None, "dirty": False}
proyecto_estado_var = tk.StringVar(value="Proyecto activo: ninguno")
LAST_ACTIVE_PROJECT_KEY = "ultimo_proyecto_activo"


def guardar_ultimo_proyecto_activo(nombre):
    proyectos = load_proyectos()
    meta = proyectos.setdefault("_meta", {})
    if meta.get(LAST_ACTIVE_PROJECT_KEY) == nombre:
        return
    if not nombre and LAST_ACTIVE_PROJECT_KEY not in meta:
        return

    if nombre:
        meta[LAST_ACTIVE_PROJECT_KEY] = nombre
    else:
        meta.pop(LAST_ACTIVE_PROJECT_KEY, None)
    save_proyectos(proyectos)


def obtener_ultimo_proyecto_activo():
    proyectos = load_proyectos()
    nombre = proyectos.get("_meta", {}).get(LAST_ACTIVE_PROJECT_KEY)
    if nombre in proyectos.get("datos", {}):
        return nombre
    return None


def actualizar_estado_proyecto():
    nombre = proyecto_activo.get("nombre")
    dirty = proyecto_activo.get("dirty", False)
    if not nombre and dirty:
        proyecto_estado_var.set("Proyecto activo: sin nombre  *sin guardar")
        color = "#ffcc66"
    elif not nombre:
        proyecto_estado_var.set("Proyecto activo: ninguno")
        color = "#8fb8c9"
    elif dirty:
        proyecto_estado_var.set(f"Proyecto activo: {nombre}  *sin guardar")
        color = "#ffcc66"
    else:
        proyecto_estado_var.set(f"Proyecto activo: {nombre}")
        color = "#8dfa9f"

    label = globals().get("lbl_proyecto_estado")
    if label is not None:
        try:
            label.config(fg=color)
        except Exception:
            pass


def set_proyecto_activo(nombre, dirty=False):
    proyecto_activo["nombre"] = nombre
    proyecto_activo["dirty"] = bool(dirty)
    guardar_ultimo_proyecto_activo(nombre)
    actualizar_estado_proyecto()


def marcar_proyecto_modificado():
    proyecto_activo["dirty"] = True
    actualizar_estado_proyecto()


def guardar_proyecto_activo():
    nombre = entry_proyecto.get().strip() or proyecto_activo.get("nombre")
    if not nombre:
        messagebox.showwarning("Nombre requerido", "Escribe un nombre de proyecto/obra para guardar los cambios.")
        return False

    escenas = load_escenas()
    if not escenas["orden"]:
        messagebox.showwarning("Sin escenas", "No hay escenas para guardar en el proyecto.")
        return False

    guardar_proyecto(nombre, escenas["orden"])
    actualizar_lista_proyectos()
    set_proyecto_activo(nombre, dirty=False)
    try:
        entry_proyecto.delete(0, tk.END)
        entry_proyecto.insert(0, nombre)
    except Exception:
        pass
    return True


def confirmar_cambios_proyecto_pendientes_legacy(accion="continuar"):
    if not proyecto_activo.get("dirty"):
        return True

    nombre = proyecto_activo.get("nombre") or "sin nombre"
    respuesta = messagebox.askyesnocancel(
        "Proyecto con cambios sin guardar",
        f"El proyecto '{nombre}' tiene cambios sin guardar.\n\n"
        f"¿Querés guardar el proyecto antes de {accion}?"
    )
    if respuesta is None:
        return False
    if respuesta:
        return guardar_proyecto_activo()
    return True


def confirmar_cambios_proyecto_pendientes(accion="continuar"):
    if not proyecto_activo.get("dirty"):
        return True

    nombre = proyecto_activo.get("nombre") or "sin nombre"
    respuesta = messagebox.askyesnocancel(
        "Proyecto con cambios sin guardar",
        f"El proyecto '{nombre}' tiene cambios sin guardar.\n\n"
        f"Para {accion}, primero elige una accion:\n\n"
        "Si: guardar cambios\n"
        "No: descartar cambios\n"
        "Cancelar: seguir trabajando en este proyecto"
    )
    if respuesta is None:
        return False
    if respuesta:
        return guardar_proyecto_activo()
    return True


def salir_del_proyecto_actual(limpiar_escenas=True):
    if limpiar_escenas:
        escenas = load_escenas()
        escenas["orden"] = []
        save_escenas(escenas)
        try:
            actualizar_lista_escenas()
        except Exception:
            pass

    try:
        entry_proyecto.delete(0, tk.END)
    except Exception:
        pass
    set_proyecto_activo(None, dirty=False)


def on_nuevo_proyecto():
    if not confirmar_cambios_proyecto_pendientes("crear un proyecto nuevo"):
        return
    salir_del_proyecto_actual(limpiar_escenas=True)
    set_proyecto_activo(None, dirty=True)


def on_descartar_proyecto():
    nombre = proyecto_activo.get("nombre") or "sin nombre"
    if not proyecto_activo.get("dirty") and not proyecto_activo.get("nombre"):
        messagebox.showinfo("Sin proyecto activo", "No hay un proyecto activo para descartar.")
        return

    if not messagebox.askyesno(
        "Descartar proyecto activo",
        f"Descartar los cambios del proyecto '{nombre}' y salir de este proyecto?"
    ):
        return
    salir_del_proyecto_actual(limpiar_escenas=True)

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

    if guardar_proyecto_activo():
        messagebox.showinfo("Proyecto guardado", f"Proyecto/obra '{nombre}' guardado.")
    # no borro el entry para facilitar sobreescritura


def aplicar_proyecto_por_nombre(nombre, mostrar_mensaje=True):
    try:
        escenas_proyecto = obtener_escenas_de_proyecto(nombre)
    except KeyError:
        if mostrar_mensaje:
            messagebox.showerror("Proyecto no encontrado", f"No existe el proyecto '{nombre}'.")
        return False

    escenas = load_escenas()
    nuevas = [e for e in escenas_proyecto if e in escenas["datos"]]
    if not nuevas:
        if mostrar_mensaje:
            messagebox.showwarning("Proyecto vacio", f"El proyecto '{nombre}' no tiene escenas validas.")
        return False

    escenas["orden"] = nuevas
    save_escenas(escenas)
    try:
        actualizar_lista_escenas()
    except Exception:
        pass

    try:
        entry_proyecto.delete(0, tk.END)
        entry_proyecto.insert(0, nombre)
    except Exception:
        pass

    set_proyecto_activo(nombre, dirty=False)

    try:
        proyectos = load_proyectos().get("orden", [])
        if nombre in proyectos:
            idx = proyectos.index(nombre)
            listbox_proyectos.selection_clear(0, tk.END)
            listbox_proyectos.selection_set(idx)
            listbox_proyectos.activate(idx)
            listbox_proyectos.see(idx)
    except Exception:
        pass

    if mostrar_mensaje:
        messagebox.showinfo("Proyecto cargado", f"Escenas reordenadas segun el proyecto '{nombre}'.")
    return True


def on_cargar_proyecto():
    if not confirmar_cambios_proyecto_pendientes("cargar otro proyecto"):
        return

    sel = listbox_proyectos.curselection()
    if not sel:
        messagebox.showwarning("Selecciona un proyecto", "Debes seleccionar un proyecto/obra.")
        return

    nombre = listbox_proyectos.get(sel[0])
    aplicar_proyecto_por_nombre(nombre, mostrar_mensaje=True)
    


def on_exportar_obra():
    sel = listbox_proyectos.curselection()
    if not sel:
        messagebox.showwarning("Selecciona un proyecto", "Debes seleccionar un proyecto/obra para exportar.")
        return

    nombre = listbox_proyectos.get(sel[0])

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
    if not confirmar_cambios_proyecto_pendientes("importar otra obra"):
        return

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
        entry_proyecto.delete(0, tk.END)
        entry_proyecto.insert(0, nombre_creado)
        set_proyecto_activo(nombre_creado, dirty=False)
    except Exception as e:
        messagebox.showerror("Error al importar", str(e))
        

def on_borrar_proyecto():
    sel = listbox_proyectos.curselection()
    if not sel:
        messagebox.showwarning("Selecciona un proyecto", "Debes seleccionar un proyecto para borrarlo.")
        return

    nombre = listbox_proyectos.get(sel[0])

    if proyecto_activo.get("nombre") == nombre and proyecto_activo.get("dirty"):
        if not confirmar_cambios_proyecto_pendientes("borrar este proyecto"):
            return

    if not messagebox.askyesno(
        "Confirmar borrado",
        f"¿Seguro que quieres borrar el proyecto/obra '{nombre}'?"
    ):
        return

    if borrar_proyecto(nombre):
        actualizar_lista_proyectos()
        if obtener_ultimo_proyecto_activo() == nombre:
            guardar_ultimo_proyecto_activo(None)
        if proyecto_activo.get("nombre") == nombre:
            set_proyecto_activo(None, dirty=False)
            entry_proyecto.delete(0, tk.END)
        messagebox.showinfo("Proyecto borrado", f"Se borró el proyecto '{nombre}'.")
    else:
        messagebox.showerror("Error", f"No se pudo borrar el proyecto '{nombre}'.")
            

tk.Label(
    frame_right,
    text="PROYECTOS / OBRAS",
    bg="#202428", fg="#20bdec",
    font=("Segoe UI", 14, "bold")
).pack(anchor="w", pady=(10, 4))

lbl_proyecto_estado = tk.Label(
    frame_right,
    textvariable=proyecto_estado_var,
    bg="#202428",
    fg="#8dfa9f",
    font=("Segoe UI", 9, "italic"),
    wraplength=280,
    justify="left"
)
lbl_proyecto_estado.pack(anchor="w", pady=(0, 6))
actualizar_estado_proyecto()

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


btn_nuevo_proyecto = tk.Button(
    frame_proy_bar,
    text="Nuevo",
    command=on_nuevo_proyecto,
    width=6,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 9, "bold"),
    relief="raised"
)
btn_nuevo_proyecto.grid(row=0, column=5, padx=2)

Tooltip(btn_nuevo_proyecto, "Salir del proyecto actual y empezar uno nuevo")


btn_descartar_proyecto = tk.Button(
    frame_proy_bar,
    text="Desc.",
    command=on_descartar_proyecto,
    width=5,
    bg="#ffb74d", fg="#000",
    font=("Segoe UI", 9, "bold"),
    relief="raised"
)
btn_descartar_proyecto.grid(row=0, column=6, padx=2)

Tooltip(btn_descartar_proyecto, "Descartar cambios y salir del proyecto actual")


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
                send_lamp_white_scene(ip, to_b, temp)

        # Actualiza estado
        if panel:
            panel.last_brillo = to_b
            panel.last_mode = modo
            if modo == "colour":
                panel.last_hue = h
                panel.last_sat = s
            else:
                panel.last_temp = temp
        update_lamp_state(ip, modo, h, s, temp, to_b)
        return

    # ==========================================
    #  FADE REAL
    # ==========================================
    apagando = (to_b == 0)
    fps = 8
    steps = max(1, min(80, int(tiempo * fps)))
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
                send_lamp_white_scene(ip, brillo, temp_real)

        else:
            # caso de encendido/cambio color
            if modo == "colour":
                send_lamp_color_safe(ip, h, s, brillo)
            else:
                send_lamp_white_scene(ip, brillo, temp)

        time.sleep(dt)

    # ESTADO FINAL EXACTO
    if to_b <= 0:
        send_off(ip)
    else:
        if modo == "colour":
            send_lamp_color_safe(ip, h, s, to_b)
        else:
            send_lamp_white_scene(ip, to_b, temp)

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


def avanzar_lista_escenas_si_corresponde():
    global ultima_idx_escena

    if ultima_idx_escena is None:
        return

    try:
        next_idx = ultima_idx_escena + 1
        listbox_escenas.selection_clear(0, tk.END)

        if next_idx < listbox_escenas.size():
            listbox_escenas.selection_set(next_idx)
            listbox_escenas.activate(next_idx)
            listbox_escenas.see(next_idx)

        ultima_idx_escena = None
    except Exception as e:
        print(f"[WARN] No se pudo avanzar en la lista de escenas: {e}")


def finalizar_escena(token, nombre):
    global escena_en_ejecucion, ultima_idx_escena

    # Si se lanzó otra escena después, no hacemos nada
    if fade_token[0] != token:
        return

    escena_en_ejecucion = False
    set_active_scene_runtime()
    update_midi_scene_execution_led()

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
        scene_progress_var.set(100)
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


def get_current_fade_state(ip):
    panel = panels.get(ip)
    info = lamp_state.get(ip, {})

    panel_mode = getattr(panel, "last_mode", "colour") if panel else "colour"
    mode = info.get("mode") or panel_mode
    if mode not in ("colour", "white"):
        mode = panel_mode

    info_brightness = safe_brightness(info.get("brightness", 0))
    panel_brightness = safe_brightness(getattr(panel, "last_brillo", 0)) if panel else 0
    if selected_devices.get(ip) is not None and selected_devices[ip].get():
        brightness = max(info_brightness, panel_brightness)
        mode = panel_mode
    else:
        brightness = info_brightness

    return {
        "brightness": brightness,
        "mode": mode,
        "hue": info.get("hue", getattr(panel, "last_hue", 0) if panel else 0),
        "sat": info.get("sat", getattr(panel, "last_sat", 1) if panel else 1),
        "temp": info.get("temp", getattr(panel, "last_temp", 4000) if panel else 4000),
    }


def resolve_scene_effect_target_ips(scene_data):
    layers = scene_data.get("effects_layers") or []
    if not layers:
        return None

    target_ips = set()
    for layer in layers:
        if not layer.get("enabled", True):
            continue
        target = layer.get("target", {})
        mode = target.get("mode")

        if mode == "all":
            target_ips.update(LAMP_IPS)
        elif mode == "group":
            group = target.get("group")
            target_ips.update(ip for ip in LAMP_IPS if get_lamp_group(ip) == group)
        elif mode == "lamps":
            lamp_ids = set(target.get("lamps", []))
            target_ips.update(ip for ip in LAMP_IPS if get_lamp_id(ip) in lamp_ids)

    return target_ips


def active_scene_effect_names(scene_data):
    effects = scene_data.get("effects", {})
    return {
        name for name, enabled in effects.items()
        if name != "_params" and bool(enabled)
    }


def fade_scene_lamps_outside_effect_target(scene_data, target_ips, fade_out_val, token):
    if target_ips is None:
        return

    threads = []
    for ip in LAMP_IPS:
        if ip in target_ips or not lamp_status.get(ip, True) or ip not in scene_data:
            continue

        estado_destino = scene_data.get(ip, {})
        destino_apagado = (
            estado_destino.get("state", "off") != "on"
            or safe_brightness(estado_destino.get("brillo", 0)) <= 0
        )
        if not destino_apagado:
            continue

        current = get_current_fade_state(ip)
        from_brillo = safe_brightness(current.get("brightness", 0))
        if from_brillo <= 0:
            continue

        tiempo = useful_fade_seconds(fade_out_val, from_brillo, 0)
        t = threading.Thread(
            target=fade_to,
            args=(
                ip,
                tiempo,
                from_brillo,
                0,
                current.get("mode", "colour"),
                current.get("hue", 0),
                current.get("sat", 1),
                current.get("temp", 4000),
                token,
            ),
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


def apply_scene_mode_to_effect_target(scene_data, target_ips, preserve_brightness=True, send_to_lamps=False):
    global preview_updates_suspended, preview_updates_block_until
    if target_ips is None:
        return

    preview_updates_suspended = True
    preview_updates_block_until = time.monotonic() + 0.5
    try:
        for ip in target_ips:
            if ip not in scene_data or ip not in panels:
                continue

            estado = scene_data.get(ip, {})
            panel = panels[ip]
            current_brightness = getattr(panel, "last_brillo", 0)
            modo = estado.get("modo", getattr(panel, "last_mode", "colour"))

            panel.last_mode = modo
            set_panel_mode_preview(panel, modo)

            if modo == "white":
                temp = estado.get("temp", getattr(panel, "last_temp", 4000))
                panel.last_temp = temp
                if hasattr(panel, "temp_var"):
                    panel.temp_var.set(temp)
                if hasattr(panel, "whitewheel_lamp"):
                    panel.whitewheel_lamp.set_temp_value(temp)
            else:
                h = estado.get("h", getattr(panel, "last_hue", 0))
                s = estado.get("s", getattr(panel, "last_sat", 1))
                panel.last_hue = h
                panel.last_sat = s
                if hasattr(panel, "colorwheel_lamp"):
                    panel.colorwheel_lamp.set_color(h, s, max(0.01, current_brightness / 255))

            if not preserve_brightness:
                current_brightness = safe_brightness(estado.get("brillo", current_brightness))

            panel.last_brillo = safe_brightness(current_brightness)

            if send_to_lamps and panel.last_brillo > 0 and lamp_status.get(ip, True):
                if modo == "white":
                    send_lamp_white_scene(ip, panel.last_brillo, panel.last_temp)
                else:
                    send_lamp_color_safe(ip, panel.last_hue, panel.last_sat, panel.last_brillo)
                update_lamp_state(
                    ip,
                    modo,
                    getattr(panel, "last_hue", 0),
                    getattr(panel, "last_sat", 1),
                    getattr(panel, "last_temp", 4000),
                    panel.last_brillo,
                )

            try:
                update_panel_visual(panel)
            except Exception:
                pass
    finally:
        preview_updates_suspended = False
        preview_updates_block_until = 0.0
        refresh_espacio = globals().get("refresh_espacio_laberintos_visual")
        if callable(refresh_espacio):
            refresh_espacio()


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
    update_midi_scene_execution_led()

    stop_all_active_effects("cambio de escena")
    effect_retired_ips["atardecer"].clear()

    # Deshabilitar UI
    try: btn_cargar.config(state="disabled")
    except: pass
    try: listbox_escenas.config(state="disabled")
    except: pass

    escena = datos[nombre_escena]
    set_active_scene_runtime(nombre_escena, escena)

    fade_in_val = normalize_fade_seconds(escena.get("fade_in", 0.0) or 0.0)
    fade_out_val = normalize_fade_seconds(escena.get("fade_out", 0.0) or 0.0)

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
    try:
        start_scene_timer()
    except Exception:
        pass
    try:
        start_scene_progress(nuevo_token, max(fade_in_val, fade_out_val))
    except:
        pass

    # -----------------------------------------------------
    # 🚨 DETECCIÓN DE ACCIONES DINÁMICAS
    # -----------------------------------------------------

    acciones_dinamicas = set(escena.get("acciones_dinamicas", []))
    effects = escena.get("effects", {})
    active_effects = active_scene_effect_names(escena)
    dynamic_effects = {
        "respiracion",
        "secuencia",
        "secuencia_on",
        "secuencia_on_overlay",
        "secuencia_off",
        "secuencia_off_overlay",
        "parpadeo",
        "estrobo",
        "estrobo_udp",
        "fuego",
        "mar",
        "arcoiris",
        "vela",
        "atardecer",
        "desfase",
        "latido",
        "Intercambio",
    }

    # Una escena solo es dinámica si alguna acción dinámica está en TRUE
    hay_accion_dinamica = bool(active_effects & (acciones_dinamicas | dynamic_effects))

    if hay_accion_dinamica:
        print(f"[ESCENA] {nombre_escena}: acción dinámica detectada → NO ejecutar fades.")

        target_ips = resolve_scene_effect_target_ips(escena)
        preserve_target_state = "secuencia_off" in active_effects
        overlay_target_state = "secuencia_off_overlay" in active_effects
        on_overlay_target_state = "secuencia_on_overlay" in active_effects
        sequence_finishes_scene = overlay_target_state or on_overlay_target_state or "secuencia_on" in active_effects

        if sequence_finishes_scene:
            if overlay_target_state:
                sequence_effect_name = "secuencia_off_overlay"
            elif on_overlay_target_state:
                sequence_effect_name = "secuencia_on_overlay"
            else:
                sequence_effect_name = "secuencia_on"
            try:
                start_scene_progress(
                    nuevo_token,
                    estimate_sequence_effect_seconds(escena, sequence_effect_name, target_ips)
                )
            except Exception:
                pass
        else:
            marcar_escena_terminada()

        if preserve_target_state:
            stop_all_active_effects("preparando secuencia off")

        if not overlay_target_state and not on_overlay_target_state:
            threading.Thread(
                target=fade_scene_lamps_outside_effect_target,
                args=(escena, target_ips, fade_out_val, nuevo_token),
                daemon=True,
            ).start()

        if preserve_target_state:
            apply_scene_mode_to_effect_target(
                escena,
                target_ips,
                preserve_brightness=True,
                send_to_lamps=True,
            )

        # Actualizar panel (estado visual)
        for ip in online_ips:
            if (preserve_target_state or overlay_target_state or on_overlay_target_state) and target_ips is not None and ip in target_ips:
                continue

            estado = escena[ip]
            if estado.get("state", "off") != "on":
                continue

            panel = panels[ip]
            panel.last_mode = estado.get("modo", getattr(panel, "last_mode", "colour"))
            panel.last_hue = estado.get("h", getattr(panel, "last_hue", 0))
            panel.last_sat = estado.get("s", getattr(panel, "last_sat", 1))
            panel.last_temp = estado.get("temp", getattr(panel, "last_temp", 4000))
            panel.last_brillo = safe_brightness(estado.get("brillo", getattr(panel, "last_brillo", 1)))

        # Aplicar efectos (solo si realmente hay efectos)
        effect_delay_ms = 300 if preserve_target_state else 10
        root.after(
            effect_delay_ms,
            lambda data=escena, token=nuevo_token, name=nombre_escena: apply_scene_effects_for_execution(data, token, name)
        )

        if sequence_finishes_scene:
            return

        escena_en_ejecucion = False
        set_active_scene_runtime()
        update_midi_scene_execution_led()
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

            sin_cambios = (
                from_brillo == to_brillo and
                from_mode == to_mode and
                (
                    (to_mode == "colour" and from_h == to_h and from_s == to_s) or
                    (
                        to_mode == "white" and
                        int(normalize_scene_colortemp(from_temp)) == int(normalize_scene_colortemp(to_temp))
                    )
                )
            )

            if sin_cambios:
                print(f"[SKIP] {ip}: sin cambios reales")
                continue

            if destino_on:
                start_b = from_brillo
                end_b = to_brillo
                tiempo = useful_fade_seconds(fade_in_val, start_b, end_b)
                modo = to_mode
                h = to_h
                s = to_s
                temp = to_temp
            else:
                if from_brillo <= 0:
                    print(f"[SKIP] {ip}: ya apagada")
                    continue

                start_b = from_brillo
                end_b = 0
                tiempo = useful_fade_seconds(fade_out_val, start_b, end_b)
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

        for t in threads:
            t.join()

        if effects.get("transicion_color"):
            root.after(
                0,
                lambda data=escena, token=nuevo_token, name=nombre_escena: apply_scene_effects_for_execution(data, token, name)
            )
        else:
            root.after(0, lambda: finalizar_escena(nuevo_token, nombre_escena))

    threading.Thread(target=worker, daemon=True).start()

    if "effects" in escena and not effects.get("transicion_color"):
        root.after(
            0,
            lambda data=escena: apply_scene_effects_for_execution(data)
        )

def marcar_escena_terminada():
    global escena_en_ejecucion
    escena_en_ejecucion = False
    set_active_scene_runtime()
    update_midi_scene_execution_led()

    try:
        set_estado_escena("Escena finalizada", "#03fc7f")
        scene_progress_var.set(100)
    except:
        pass
    avanzar_lista_escenas_si_corresponde()


def borrar():
    sel = listbox_escenas.curselection()
    if sel:
        escena = listbox_escenas.get(sel[0])
        if messagebox.askyesno("Eliminar escena", f"¿Estás seguro que quieres eliminar la escena '{escena}'?"):
            escenas = load_escenas()
            if escena in escenas["datos"]:
                del escenas["datos"][escena]
            if escena in escenas["orden"]:
                escenas["orden"].remove(escena)
            save_escenas(escenas)
            actualizar_lista_escenas()
            marcar_proyecto_modificado()



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
        fade_in_val = normalize_fade_seconds(fade_in_var.get())
    except Exception:
        fade_in_val = 0.0
    try:
        fade_out_val = normalize_fade_seconds(fade_out_var.get())
    except Exception:
        fade_out_val = 0.0

    if fade_in_val <= 0:
        fade_in_val = 0.0
    if fade_out_val <= 0:
        fade_out_val = 0.0

    # 👉 NUEVO: leer estado de efectos (respiración, estrobo, etc.)
    effects_state = build_scene_save_effects_state()
    effects_layers = build_scene_effect_layers(effects_state, get_scene_save_effect_target())

    # 👉 NUEVO: delegar en escenas_proyectos.guardar_escena(...)
    save_selected_devices = build_scene_save_selected_devices()
    exito = guardar_escena(
        nombre,
        fade_in_val,
        fade_out_val,
        LAMP_IPS,
        panels,
        save_selected_devices,
        effects_state,
        effects_layers,
    )

    if exito:
        actualizar_lista_escenas()
        marcar_proyecto_modificado()
        entry_escena.delete(0, tk.END)

        
def on_actualizar_escena():
    escena = escena_seleccionada_en_listbox()  # tu lógica
    if not escena:
        messagebox.showwarning("Selecciona una escena", "Elige una escena a actualizar.")
        return

    fade_in_val = normalize_fade_seconds(fade_in_var.get())
    fade_out_val = normalize_fade_seconds(fade_out_var.get())
    effects_state = build_scene_save_effects_state()
    effects_layers = build_scene_effect_layers(effects_state, get_scene_save_effect_target())

    save_selected_devices = build_scene_save_selected_devices()
    if actualizar_escena_completa(
        escena,
        fade_in_val,
        fade_out_val,
        LAMP_IPS,
        panels,
        save_selected_devices,
        effects_state,
        effects_layers,
    ):
        messagebox.showinfo("Escena actualizada", f"'{escena}' guardada.")
        actualizar_lista_escenas()
        marcar_proyecto_modificado()
        


def mostrar_fades_de_escena(event=None):
    sel = listbox_escenas.curselection()
    if sel:
        escena = listbox_escenas.get(sel[0])
        escenas = load_escenas()
        datos = escenas["datos"].get(escena, {})
        fade_in_var.set(normalize_fade_seconds(datos.get("fade_in", 0.0)))
        fade_out_var.set(normalize_fade_seconds(datos.get("fade_out", 0.0)))
        load_scene_effect_controls(datos)
        mostrar_estado_escena_en_paneles(
            escena,
            actualizar_seleccion=False
        )
               
def cargar():
    global ultima_idx_escena
    sel = listbox_escenas.curselection()
    if sel:
        ultima_idx_escena = sel[0]
        escena = listbox_escenas.get(sel[0])
        aplicar_escena(escena)


def seleccionar_escena_midi(delta):
    total = listbox_escenas.size()
    if total <= 0:
        try:
            set_estado_escena("Sin escenas para seleccionar", "#ffcc66")
        except Exception:
            pass
        return

    sel = listbox_escenas.curselection()
    current = sel[0] if sel else 0
    next_index = max(0, min(total - 1, current + delta))

    listbox_escenas.selection_clear(0, tk.END)
    listbox_escenas.selection_set(next_index)
    listbox_escenas.activate(next_index)
    listbox_escenas.see(next_index)
    mostrar_fades_de_escena()

    try:
        set_estado_escena(f"Escena preparada: {listbox_escenas.get(next_index)}", "#b9e3f7")
    except Exception:
        pass
    midi_led(get_midi_note("scene_prev"), get_midi_led_color("scene_prev"))
    midi_led(get_midi_note("scene_next"), get_midi_led_color("scene_next"))


def go_escena_midi():
    global ultima_idx_escena

    total = listbox_escenas.size()
    if total <= 0:
        try:
            set_estado_escena("Sin escenas para ejecutar", "#ffcc66")
        except Exception:
            pass
        return

    sel = listbox_escenas.curselection()
    if not sel:
        listbox_escenas.selection_set(0)
        listbox_escenas.activate(0)
        listbox_escenas.see(0)
        sel = (0,)

    idx = sel[0]
    escena = listbox_escenas.get(idx)
    ultima_idx_escena = idx
    midi_led(get_midi_note("scene_go"), get_midi_led_color("scene_go"))
    aplicar_escena(escena)


def stop_show_midi():
    global escena_en_ejecucion

    fade_token[0] = str(uuid.uuid4())
    escena_en_ejecucion = False
    set_active_scene_runtime()
    update_midi_scene_execution_led()
    stop_all_active_effects("MIDI stop")
    try:
        btn_cargar.config(state="normal")
        listbox_escenas.config(state="normal")
        scene_progress_var.set(0)
        reset_scene_timer()
        set_estado_escena("Show detenido desde MIDI", "#ffcc66")
    except Exception:
        pass
    midi_led(get_midi_note("show_stop"), get_midi_led_color("show_stop"))
        

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

    # Ejecutamos la escena solo con Enter.
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
            marcar_proyecto_modificado()
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
            marcar_proyecto_modificado()
            listbox_escenas.selection_clear(0, tk.END)
            listbox_escenas.selection_set(idx+1)
            listbox_escenas.activate(idx+1)
            
def on_fade_scroll(event, var):
    delta = FADE_UI_STEP_SECONDS if event.delta > 0 else -FADE_UI_STEP_SECONDS
    value = var.get()
    try:
        newval = normalize_fade_seconds(float(value) + delta)
    except Exception:
        newval = FADE_UI_STEP_SECONDS
    var.set(newval)
    
# ==== UI ====
tk.Label(frame_right, text="ESCENAS", bg="#202428", fg="#20bdec",
         font=("Segoe UI", 16, "bold")).pack(pady=(6, 8))

tk.Label(frame_right, text="Nombre", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).pack(anchor="w", padx=16)
entry_escena = tk.Entry(frame_right, font=("Segoe UI", 11), width=30, bg="#181b1e", fg="#b9e3f7")
entry_escena.pack(fill="x", padx=16, pady=(2, 8))
entry_escena.config(insertbackground="#20bdec")  # ¡Color del cursor!

from tkinter import ttk


estado_escena_var = tk.StringVar(value="Sin escenas en ejecución")
scene_progress_var = tk.DoubleVar(value=0.0)
scene_timer_var = tk.StringVar(value="00:00")
scene_timer_token = {"value": None, "start": None}
lbl_estado_escena = tk.Label(
    frame_right,
    textvariable=estado_escena_var,
    bg="#202428",
    fg="#b9e3f7",
    font=("Segoe UI", 10, "italic")
)
lbl_estado_escena.pack(pady=(0, 6))

scene_progress = ttk.Progressbar(
    frame_right,
    variable=scene_progress_var,
    maximum=100,
    mode="determinate",
    length=230
)
scene_progress.pack(fill="x", padx=16, pady=(0, 8))

def actualizar_escena():
    escena = escena_seleccionada_en_listbox()
    if not escena:
        messagebox.showwarning("Selecciona una escena", "Debes elegir una escena para actualizar.")
        return

    # Obtener fades
    try:
        fade_in_val = normalize_fade_seconds(fade_in_var.get())
    except:
        fade_in_val = 0.0

    try:
        fade_out_val = normalize_fade_seconds(fade_out_var.get())
    except:
        fade_out_val = 0.0

    if fade_in_val <= 0:
        fade_in_val = 0.0
    if fade_out_val <= 0:
        fade_out_val = 0.0

    # Obtener efectos
    effects_state = build_scene_save_effects_state()
    effects_layers = build_scene_effect_layers(effects_state, get_scene_save_effect_target())

    # Llamar al módulo escenas_proyectos
    save_selected_devices = build_scene_save_selected_devices()
    ok = actualizar_escena_completa(
        escena,
        fade_in_val,
        fade_out_val,
        LAMP_IPS,
        panels,
        save_selected_devices,
        effects_state,
        effects_layers,
    )

    if ok:
        messagebox.showinfo("Escena actualizada", f"La escena '{escena}' ha sido actualizada.")
        actualizar_lista_escenas()
        marcar_proyecto_modificado()

def set_estado_escena(texto, color):
    estado_escena_var.set(texto)
    lbl_estado_escena.config(fg=color)


def format_scene_elapsed(seconds):
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    rest = seconds % 60
    return f"{minutes:02d}:{rest:02d}"


def start_scene_timer():
    token = str(uuid.uuid4())
    scene_timer_token["value"] = token
    scene_timer_token["start"] = time.monotonic()
    scene_timer_var.set("00:00")

    def tick():
        if scene_timer_token.get("value") != token:
            return
        start = scene_timer_token.get("start")
        if start is None:
            return
        scene_timer_var.set(format_scene_elapsed(time.monotonic() - start))
        root.after(1000, tick)

    tick()


def reset_scene_timer():
    scene_timer_token["value"] = None
    scene_timer_token["start"] = None
    scene_timer_var.set("00:00")


def start_scene_progress(token, total_seconds):
    scene_progress_var.set(0)
    total_seconds = max(0.0, float(total_seconds or 0.0))
    if total_seconds <= 0:
        scene_progress_var.set(100)
        return

    start_time = time.monotonic()

    def tick():
        if fade_token[0] != token or not escena_en_ejecucion:
            return
        elapsed = time.monotonic() - start_time
        percent = min(100, (elapsed / total_seconds) * 100)
        scene_progress_var.set(percent)
        if percent < 100:
            root.after(100, tick)

    tick()

# Evento opcional para enganchar lógica al final de una escena
def on_escena_terminada(event):
    print("[INFO] Escena finalizada.")  # aquí puedes reproducir un sonido, loguear, etc.
root.bind("<<EscenaTerminada>>", on_escena_terminada)

# --- Sliders/entries de fade
frame_fades = tk.LabelFrame(
    frame_right,
    text="Transiciones",
    bg="#202428",
    fg="#20bdec",
    font=("Segoe UI", 10, "bold"),
    padx=8,
    pady=6
)
frame_fades.pack(fill="x", padx=16, pady=(0, 8))
frame_fades.grid_columnconfigure(1, weight=1)
tk.Label(frame_fades, text="Entrada", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", padx=(0, 8))
fade_in_var = tk.DoubleVar(value=0.0)
tk.Label(frame_fades, text="Salida", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(4, 0))
fade_out_var = tk.DoubleVar(value=0.0)    

# Para Windows (tkinter usa event.delta), para otros sistemas puede ser diferente.
fade_in_entry = tk.Spinbox(frame_fades, from_=0, to=FADE_MAX_SECONDS, increment=FADE_UI_STEP_SECONDS, textvariable=fade_in_var, width=6, font=("Segoe UI", 10), bg="#1e2224", fg="#e6e6e6", buttonbackground="#30363d", relief="flat")
fade_in_entry.grid(row=0, column=1, sticky="e")
fade_in_entry.bind("<MouseWheel>", lambda e: on_fade_scroll(e, fade_in_var))
tk.Label(frame_fades, text="seg", bg="#202428", fg="#8fb8c9", font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w", padx=(6, 0))

fade_out_entry = tk.Spinbox(frame_fades, from_=0, to=FADE_MAX_SECONDS, increment=FADE_UI_STEP_SECONDS, textvariable=fade_out_var, width=6, font=("Segoe UI", 10), bg="#1e2224", fg="#e6e6e6", buttonbackground="#30363d", relief="flat")
fade_out_entry.grid(row=1, column=1, sticky="e", pady=(4, 0))
fade_out_entry.bind("<MouseWheel>", lambda e: on_fade_scroll(e, fade_out_var))
tk.Label(frame_fades, text="seg", bg="#202428", fg="#8fb8c9", font=("Segoe UI", 9)).grid(row=1, column=2, sticky="w", padx=(6, 0), pady=(4, 0))

frame_scene_effect = tk.LabelFrame(
    frame_right,
    text="Efecto de escena",
    bg="#202428",
    fg="#20bdec",
    font=("Segoe UI", 10, "bold"),
    padx=8,
    pady=6
)
frame_scene_effect.pack(fill="x", padx=16, pady=(0, 8))
frame_scene_effect.grid_columnconfigure(1, weight=1)

chk_scene_effect = tk.Checkbutton(
    frame_scene_effect,
    text="Agregar",
    variable=scene_effect_enabled_var,
    command=update_scene_effect_status,
    bg="#202428",
    fg="#d9f3ff",
    selectcolor="#202428",
    activebackground="#202428",
    activeforeground="#20bdec",
    font=("Segoe UI", 9, "bold")
)
chk_scene_effect.grid(row=0, column=0, sticky="w", padx=(0, 8))

scene_effect_category_combo = ttk.Combobox(
    frame_scene_effect,
    textvariable=scene_effect_category_var,
    values=list(effect_categories.keys()),
    state="readonly",
    width=24
)
scene_effect_category_combo.grid(row=0, column=1, columnspan=2, sticky="ew")
scene_effect_category_combo.bind("<<ComboboxSelected>>", on_scene_effect_category_changed)

tk.Label(frame_scene_effect, text="Efecto", bg="#202428", fg="#b9e3f7",
         font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(5, 0))
scene_effect_combo = ttk.Combobox(
    frame_scene_effect,
    textvariable=scene_effect_display_var,
    state="readonly",
    width=24
)
scene_effect_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(5, 0))
scene_effect_combo.bind("<<ComboboxSelected>>", on_scene_effect_display_selected)

scene_effect_scope = tk.Frame(frame_scene_effect, bg="#202428")
scene_effect_scope.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
for label, value in (
    ("Sel.", "seleccion"),
    ("Bichos", "efectos"),
    ("Atmos.", "atmosfera"),
    ("Todas", "todas"),
):
    tk.Radiobutton(
        scene_effect_scope,
        text=label,
        variable=scene_effect_target_var,
        value=value,
        bg="#202428",
        fg="#d9f3ff",
        selectcolor="#202428",
        activebackground="#202428",
        activeforeground="#20bdec",
        font=("Segoe UI", 8)
    ).pack(side="left", padx=(0, 8))

frame_scene_effect_bottom = tk.Frame(frame_scene_effect, bg="#202428")
frame_scene_effect_bottom.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
frame_scene_effect_bottom.grid_columnconfigure(0, weight=1)
tk.Label(
    frame_scene_effect_bottom,
    textvariable=scene_effect_status_var,
    bg="#202428",
    fg="#8fb8c9",
    font=("Segoe UI", 8, "italic"),
    anchor="w"
).grid(row=0, column=0, sticky="ew")
tk.Button(
    frame_scene_effect_bottom,
    text="Config.",
    command=open_effects_config_panel,
    bg="#2b343b",
    fg="#d9f3ff",
    relief="flat",
    font=("Segoe UI", 8, "bold")
).grid(row=0, column=1, padx=(6, 0))

update_scene_effect_options()
            
# ---- UI Panel derecho ----
frame_escenas_bar = tk.Frame(frame_right, bg="#202428")
frame_escenas_bar.pack(fill="x", padx=16, pady=(2, 10))
for i in range(4):
    frame_escenas_bar.grid_columnconfigure(i, weight=1)

############ EJECUTAR ESCENA ###############

frame_saved_scenes_title = tk.Frame(frame_right, bg="#202428")
frame_saved_scenes_title.pack(fill="x", padx=16, pady=(0, 4))
tk.Label(
    frame_saved_scenes_title,
    text="Escenas guardadas",
    bg="#202428", fg="#b9e3f7",
    font=("Segoe UI", 10, "bold")
).pack(side="left")
tk.Label(
    frame_saved_scenes_title,
    textvariable=scene_timer_var,
    bg="#202428", fg="#8dfa9f",
    font=("Consolas", 11, "bold")
).pack(side="right")
lista_escenas = tk.StringVar(value=[])

btn_cargar = tk.Button(
    frame_escenas_bar,
    text="▶",
    command=cargar,
    width=3,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold"),
)
btn_cargar.config(text="Play", width=7)
btn_cargar.grid(row=0, column=0, padx=(0, 4), sticky="ew")

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
btn_guardar_escena.config(text="Guardar", width=7)
btn_guardar_escena.grid(row=0, column=1, padx=4, sticky="ew")

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
btn_actualizar_escena.config(text="Act.", width=5)
btn_actualizar_escena.grid(row=0, column=2, padx=4, sticky="ew")

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
btn_borrar.config(text="Borrar", width=6)
btn_borrar.grid(row=0, column=3, padx=(4, 0), sticky="ew")

Tooltip(btn_borrar, "Borrar escena seleccionada")


########## LISTBOX ESCENAS ###################

# --- LISTA DE ESCENAS CON SCROLLBAR ---

# --- LISTA DE ESCENAS + SCROLLBAR + BOTONES ↑ ↓ EN LA MISMA FILA ---

frame_lista_escenas = tk.Frame(frame_right, bg="#202428")
frame_lista_escenas.pack(fill="both", expand=True, pady=(4, 8))
frame_lista_escenas.grid_rowconfigure(0, weight=1)
frame_lista_escenas.grid_columnconfigure(0, weight=1)

# Listbox + scrollbar en un sub-frame
frame_listbox = tk.Frame(frame_lista_escenas, bg="#202428")
frame_listbox.grid(row=0, column=0, sticky="nsew")

scroll_esc = tk.Scrollbar(frame_listbox, orient="vertical")
scroll_esc.pack(side="right", fill="y")


listbox_escenas = tk.Listbox(
    frame_listbox,
    listvariable=lista_escenas,
    width=25, height=12,
    font=("Segoe UI", 11),
    bg="#17191c", fg="#fff",
    selectbackground="#20bdec",
    activestyle="dotbox",
    yscrollcommand=scroll_esc.set
)
listbox_escenas.pack(side="left", fill="both", expand=True)

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
btn_up.config(text="Subir", width=6)
btn_up.pack(pady=4)
Tooltip(btn_up, "Subir escena seleccionada")

btn_down = tk.Button(
    frame_updown, text="🔽",
    command=mover_abajo,
    width=4,
    bg="#4fc3f7", fg="#000",
    font=("Segoe UI", 10, "bold")
)
btn_down.config(text="Bajar", width=6)
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


def cargar_ultimo_proyecto_al_iniciar():
    nombre = obtener_ultimo_proyecto_activo()
    if nombre:
        aplicar_proyecto_por_nombre(nombre, mostrar_mensaje=False)
    else:
        actualizar_estado_proyecto()


cargar_ultimo_proyecto_al_iniciar()
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
    return listbox_escenas.get(sel[0])

#____________________________inicio_MIDI______________________________________________________________

from tablero.midi_listener import start_midi_thread


def handle_midi_event(event):
    note = event.get("note")
    vel = event.get("velocity")
    status = event.get("status")

    if event.get("note_off"):
        if is_apc_espacio_note(note):
            root.after(0, lambda n=note: handle_espacio_midi_note_off(n))
            return
        action = get_midi_action_for_note(note)
        trigger = MIDI_TRIGGER_DEFS.get(action) if action else None
        if trigger and trigger.get("hold"):
            stop_hold_trigger(action)
            return


    # ----------------------------
    # NOTE ON → ejecutar acción
    # ----------------------------
    if event.get("note_on"):
        if capture_midi_learn_note(note):
            return

        if is_apc_espacio_note(note):
            root.after(0, lambda n=note: handle_espacio_midi_note(n))
            return

        # Primero: ejecutar la acción asignada
        if note in note_map:
            try:
                note_map[note]()
            except Exception as e:
                print("[MIDI ERROR] en ejecución de note_map:", e)

        # -----------------------------------------
        # FEEDBACK ESPECIAL PARA 6 (APAGAR) y 7 (ENCENDER)
        # -----------------------------------------
        if note == get_midi_note("all_on"):   # ENCENDER TODO
            midi_led(get_midi_note("all_on"), get_midi_led_color("all_on"))
            midi_led(get_midi_note("all_off"), get_midi_led_color("all_off"))
            return  # luego de LED no procesamos efectos

        if note == get_midi_note("all_off"):   # APAGAR TODO
            midi_led(get_midi_note("all_off"), get_midi_led_color("all_off"))
            midi_led(get_midi_note("all_on"), get_midi_led_color("all_on"))
            return

        # -----------------------------------------
        # FEEDBACK PARA EFECTOS
        # -----------------------------------------
        efectos_validos = set(midi_estado_efectos.keys())
        botones_especiales = {
            get_midi_note("all_off"),
            get_midi_note("all_on"),
            get_midi_note("refresh"),
        }
        botones_disparadores = {
            get_midi_note(action)
            for action in MIDI_TRIGGER_DEFS
            if get_midi_note(action) is not None
        }

        # Si es efecto: LED verde (activo)
        if note in efectos_validos:
            led_activo(note)
            return

        if note in botones_disparadores:
            action = get_midi_action_for_note(note)
            trigger = MIDI_TRIGGER_DEFS.get(action) if action else None
            if trigger and trigger.get("hold"):
                led_activo(note)
                return
            midi_led(note, get_midi_led_color(action) if action else 21)
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


MIDI_TRIGGER_DEFS = {
    "trigger_white_impact": {
        "nombre": "Destello de portal",
        "descripcion": "Apertura blanca breve, potente y limpia.",
        "familia": "Golpe",
        "accent": "#f5fbff",
        "scope": "efectos",
        "kind": "flash_white",
        "levels": (255, 215, 90, 0),
        "step_ms": 34,
        "temp": 5000,
    },
    "trigger_warm_hit": {
        "nombre": "Pulso de antorcha",
        "descripcion": "Golpe ambar con caida organica y teatral.",
        "familia": "Golpe",
        "accent": "#ffb347",
        "scope": "efectos",
        "kind": "flash_white",
        "levels": (230, 165, 72, 18, 0),
        "step_ms": 46,
        "temp": 2300,
    },
    "trigger_fast_chase": {
        "nombre": "Cometa ascendente",
        "descripcion": "La luz viaja rapido de menor a mayor.",
        "familia": "Movimiento",
        "accent": "#34d6ff",
        "scope": "efectos",
        "kind": "chase",
        "color": (195, 1.0),
        "step_ms": 28,
        "tail_pct": 22,
        "reverse": False,
    },
    "trigger_reverse_chase": {
        "nombre": "Cometa descendente",
        "descripcion": "El mismo viaje, pero de mayor a menor.",
        "familia": "Movimiento",
        "accent": "#34d6ff",
        "scope": "efectos",
        "kind": "chase",
        "color": (195, 1.0),
        "step_ms": 28,
        "tail_pct": 22,
        "reverse": True,
    },
    "trigger_blackout_snap": {
        "nombre": "Sombra instantanea",
        "descripcion": "Micro apagado general para cortes dramaticos.",
        "familia": "Corte",
        "accent": "#0a0d10",
        "scope": "all",
        "kind": "blackout",
        "hold_ms": 110,
    },
    "trigger_red_pulse": {
        "nombre": "Latido rojo",
        "descripcion": "Doble golpe rojo, seco y profundo.",
        "familia": "Latido",
        "accent": "#ff2a2a",
        "scope": "efectos",
        "kind": "flash_color",
        "color": (0, 1.0),
        "levels": (245, 45, 230, 0),
        "step_ms": 54,
    },
    "trigger_blue_wave": {
        "nombre": "Ola fria",
        "descripcion": "Barrido azul con cola suave para transiciones.",
        "familia": "Movimiento",
        "accent": "#477bff",
        "scope": "efectos",
        "kind": "chase",
        "color": (220, 1.0),
        "step_ms": 38,
        "tail_pct": 32,
        "reverse": False,
    },
    "trigger_short_strobe": {
        "nombre": "Relampago corto",
        "descripcion": "Destellos irregulares tipo descarga electrica.",
        "familia": "Golpe",
        "accent": "#ffffff",
        "scope": "efectos",
        "kind": "flash_white",
        "levels": (255, 0, 190, 0, 255, 40, 0),
        "step_ms": 24,
        "temp": 5200,
    },
    "trigger_magenta_heartbeat": {
        "nombre": "Latido magenta",
        "descripcion": "Doble latido musical, mas emocional que agresivo.",
        "familia": "Latido",
        "accent": "#ff42d6",
        "scope": "efectos",
        "kind": "flash_color",
        "color": (305, 1.0),
        "levels": (210, 35, 255, 0),
        "step_ms": 62,
    },
    "trigger_center_open": {
        "nombre": "Apertura solar",
        "descripcion": "Se abre desde el centro hacia los extremos.",
        "familia": "Movimiento",
        "accent": "#ffd04d",
        "scope": "efectos",
        "kind": "center_open",
        "color": (48, 0.9),
        "step_ms": 38,
    },
    "trigger_star_twinkle": {
        "nombre": "Rocio de estrellas",
        "descripcion": "Titileo blanco aleatorio, delicado y brillante.",
        "familia": "Textura",
        "accent": "#f7fbff",
        "scope": "efectos",
        "kind": "sparkle_white",
        "steps": 9,
        "step_ms": 58,
        "density": 0.34,
        "min_brightness": 25,
        "max_brightness": 230,
        "temp": 4300,
    },
    "trigger_firefly_field": {
        "nombre": "Luciernagas",
        "descripcion": "Puntos verdes que aparecen y desaparecen.",
        "familia": "Textura",
        "accent": "#75ff7a",
        "scope": "efectos",
        "kind": "sparkle_color",
        "color": (108, 0.9),
        "steps": 10,
        "step_ms": 64,
        "density": 0.28,
        "min_brightness": 30,
        "max_brightness": 180,
    },
    "trigger_ghost_breath": {
        "nombre": "Respiracion fantasma",
        "descripcion": "Entrada y salida fria, corta y eterea.",
        "familia": "Textura",
        "accent": "#b7d7ff",
        "scope": "efectos",
        "kind": "breath_white",
        "levels": (0, 34, 105, 190, 95, 22, 0),
        "step_ms": 70,
        "temp": 6200,
    },
    "trigger_curtain_close": {
        "nombre": "Cierre de telon",
        "descripcion": "Los extremos se cierran hacia el centro.",
        "familia": "Movimiento",
        "accent": "#9b111e",
        "scope": "efectos",
        "kind": "edges_in",
        "color": (352, 1.0),
        "step_ms": 44,
    },
    "trigger_northern_glow": {
        "nombre": "Aurora lateral",
        "descripcion": "Barrido verde-cian con variacion de tono.",
        "familia": "Color",
        "accent": "#4dffd2",
        "scope": "efectos",
        "kind": "hue_sweep",
        "start_hue": 145,
        "hue_span": 85,
        "step_ms": 42,
        "tail_pct": 35,
    },
    "trigger_scene_crescendo": {
        "nombre": "Crescendo de escena",
        "descripcion": "Sube los colores actuales al maximo y cae lento.",
        "familia": "Sobre escena",
        "accent": "#fff4a8",
        "scope": "scene_selected",
        "kind": "scene_bloom",
        "levels": (1.0, 0.86, 0.68, 0.50, 0.34, 0.22, 0.12, 0.05),
        "step_ms": 145,
    },
    "trigger_scene_echo": {
        "nombre": "Eco de color",
        "descripcion": "Dos impulsos que respetan el color de cada lampara.",
        "familia": "Sobre escena",
        "accent": "#ffd27a",
        "scope": "scene_selected",
        "kind": "scene_echo",
        "levels": (1.0, 0.18, 0.72, 0.10),
        "step_ms": 120,
    },
    "trigger_scene_water_echo": {
        "nombre": "Eco de agua",
        "descripcion": "Impacto central con ondas expansivas que rebotan suave sobre la escena.",
        "familia": "Sobre escena",
        "accent": "#6fdcff",
        "scope": "scene_selected",
        "kind": "scene_water_echo",
        "step_ms": 82,
        "echo_gap": 3,
        "ring_width": 0.72,
        "amplitudes": (1.0, 0.58, 0.30),
        "tail_factor": 0.18,
        "base_dim_factor": 0.34,
        "impact_floor": 58,
    },
    "trigger_scene_wave": {
        "nombre": "Marea de escena",
        "descripcion": "Una ola de brillo viaja usando los colores guardados.",
        "familia": "Sobre escena",
        "accent": "#49d9ff",
        "scope": "scene_selected",
        "kind": "scene_wave",
        "step_ms": 52,
        "tail_pct": 34,
        "reverse": False,
    },
    "trigger_scene_constellation": {
        "nombre": "Constelacion viva",
        "descripcion": "Titileo aleatorio con el color propio de cada lampara.",
        "familia": "Sobre escena",
        "accent": "#e8ddff",
        "scope": "scene_selected",
        "kind": "scene_sparkle",
        "steps": 10,
        "step_ms": 72,
        "density": 0.38,
        "min_factor": 0.18,
    },
    "trigger_scene_suspense": {
        "nombre": "Suspenso tenue",
        "descripcion": "Baja la escena casi a sombra y vuelve respirando.",
        "familia": "Sobre escena",
        "accent": "#7f93ff",
        "scope": "scene_selected",
        "kind": "scene_dip",
        "levels": (0.18, 0.10, 0.22, 0.45, 0.72, 0.92),
        "step_ms": 135,
    },
    "trigger_scene_floor": {
        "nombre": "Piso de escena",
        "descripcion": "Deja las luces de escena al minimo visible, sin apagarlas.",
        "familia": "Sobre escena",
        "accent": "#6f7fa8",
        "scope": "scene_selected",
        "kind": "scene_set_level",
        "brightness": 8,
    },
    "trigger_scene_full": {
        "nombre": "Pleno de escena",
        "descripcion": "Lleva las luces de escena a brillo maximo respetando sus colores.",
        "familia": "Sobre escena",
        "accent": "#fff2a3",
        "scope": "scene_selected",
        "kind": "scene_set_level",
        "brightness": 255,
    },
    "trigger_slow_blackout": {
        "nombre": "Blackout lento",
        "descripcion": "Apaga las luces activas juntas con una caida progresiva de brillo.",
        "familia": "Corte",
        "accent": "#111519",
        "scope": "active_lights",
        "kind": "fade_blackout",
        "duration_ms": 8000,
        "steps": 64,
    },
    "trigger_hold_scene_rise": {
        "nombre": "Crecer escena",
        "descripcion": "Mientras mantenes presionado, la escena sube hasta pleno.",
        "familia": "Presion",
        "accent": "#fff2a3",
        "scope": "scene_selected",
        "kind": "hold_scene_rise",
        "hold": True,
        "step_ms": 70,
        "ramp_steps": 9,
    },
    "trigger_hold_scene_shadow": {
        "nombre": "Sombra sostenida",
        "descripcion": "Mientras mantenes presionado, la escena queda casi apagada sin morir.",
        "familia": "Presion",
        "accent": "#7385bd",
        "scope": "scene_selected",
        "kind": "hold_scene_shadow",
        "hold": True,
        "step_ms": 65,
        "ramp_steps": 5,
        "floor": 1,
    },
    "trigger_hold_scene_shimmer": {
        "nombre": "Titileo sostenido",
        "descripcion": "Mientras mantenes presionado, los colores actuales titilan vivos.",
        "familia": "Presion",
        "accent": "#e8ddff",
        "scope": "scene_selected",
        "kind": "hold_scene_shimmer",
        "hold": True,
        "step_ms": 58,
        "density": 0.42,
        "min_factor": 0.20,
    },
}


active_hold_triggers = {}


def get_trigger_target_ips(scope="efectos"):
    ordered = get_sequence_ordered_lamp_ips()
    if scope == "all":
        ips = ordered
    elif scope == "active_lights":
        ips = [
            ip for ip in ordered
            if selected_devices[ip].get()
            or safe_brightness(getattr(panels.get(ip), "last_brillo", 0)) > 0
            or safe_brightness(lamp_state.get(ip, {}).get("brightness", 0)) > 0
        ]
    elif scope == "scene_selected":
        ips = [ip for ip in ordered if selected_devices[ip].get()]
        return [ip for ip in ips if lamp_status.get(ip, True)]
    elif scope in ("efectos", "atmosfera"):
        ips = [ip for ip in ordered if get_lamp_group(ip) == scope]
    else:
        ips = [ip for ip in ordered if selected_devices[ip].get()]

    if not ips:
        ips = [ip for ip in ordered if selected_devices[ip].get()]
    if not ips:
        ips = ordered

    return [ip for ip in ips if lamp_status.get(ip, True)]


def snapshot_trigger_state(ips):
    snapshot = {}
    for ip in ips:
        panel = panels.get(ip)
        snapshot[ip] = {
            "on": bool(selected_devices[ip].get()),
            "mode": getattr(panel, "last_mode", "colour") if panel else "colour",
            "h": getattr(panel, "last_hue", 0) if panel else 0,
            "s": getattr(panel, "last_sat", 1) if panel else 1,
            "brillo": safe_brightness(getattr(panel, "last_brillo", 0) if panel else 0),
            "temp": getattr(panel, "last_temp", 255) if panel else 255,
        }
    return snapshot


def restore_trigger_state(snapshot):
    for ip, state in snapshot.items():
        panel = panels.get(ip)
        is_on = state["on"] and safe_brightness(state["brillo"]) > 0
        selected_devices[ip].set(is_on)

        if panel:
            panel.mode_var.set(state["mode"])
            panel.last_mode = state["mode"]
            panel.last_hue = state["h"]
            panel.last_sat = state["s"]
            panel.last_brillo = state["brillo"]
            panel.last_temp = state["temp"]
            try:
                panel.brillo_var.set(state["brillo"])
                panel.temp_var.set(state["temp"])
            except Exception:
                pass

        if not is_on:
            send_off(ip)
        elif state["mode"] == "white":
            send_lamp_white_scene(ip, state["brillo"], state["temp"])
        else:
            send_lamp_color_safe(ip, state["h"], state["s"], state["brillo"])

        if panel:
            update_panel_visual(panel)


def trigger_send_color(ip, hue, sat, brightness):
    if safe_brightness(brightness) <= 0:
        send_off(ip)
    else:
        send_lamp_color_safe(ip, hue, sat, brightness)


def trigger_send_white(ip, brightness, temp):
    if safe_brightness(brightness) <= 0:
        send_off(ip)
    else:
        send_lamp_white_scene(ip, brightness, temp)


def trigger_send_scene_state(ip, state, brightness):
    brightness = safe_brightness(brightness)
    if brightness <= 0:
        send_off(ip)
        return
    if state.get("mode") == "white":
        send_lamp_white_scene(ip, brightness, state.get("temp", 255))
    else:
        send_lamp_color_safe(
            ip,
            state.get("h", 0),
            state.get("s", 1),
            brightness,
        )


def scene_brightness_from_factor(state, factor):
    base = safe_brightness(state.get("brillo", 0))
    factor = max(0.0, min(1.0, float(factor)))
    if factor >= 1.0:
        return 255
    return safe_brightness(base + (255 - base) * factor)


def scene_brightness_scaled(state, factor):
    base = safe_brightness(state.get("brillo", 0))
    factor = max(0.0, min(1.2, float(factor)))
    return safe_brightness(base * factor)


def run_flash_trigger(ips, levels, step_ms=40, color=None, temp=4600):
    snapshot = snapshot_trigger_state(ips)

    def step(index=0):
        if index >= len(levels):
            root.after(35, lambda: restore_trigger_state(snapshot))
            return
        level = safe_brightness(levels[index])
        for ip in ips:
            if color is None:
                trigger_send_white(ip, level, temp)
            else:
                trigger_send_color(ip, color[0], color[1], level)
        root.after(max(20, int(step_ms)), lambda: step(index + 1))

    step()


def run_blackout_trigger(ips, hold_ms=120):
    snapshot = snapshot_trigger_state(ips)
    for ip in ips:
        send_off(ip)
    root.after(max(40, int(hold_ms)), lambda: restore_trigger_state(snapshot))


def run_fade_blackout_trigger(ips, duration_ms=3500, steps=28):
    if "stop_all_active_effects" in globals():
        stop_all_active_effects("blackout lento")
    snapshot = snapshot_trigger_state(ips)
    for ip in ips:
        panel = panels.get(ip)
        panel_brightness = safe_brightness(getattr(panel, "last_brillo", 0) if panel else 0)
        state_brightness = safe_brightness(lamp_state.get(ip, {}).get("brightness", 0))
        snapshot[ip]["brillo"] = max(snapshot[ip].get("brillo", 0), panel_brightness, state_brightness)
        snapshot[ip]["on"] = snapshot[ip]["on"] or snapshot[ip]["brillo"] > 0

    active_ips = [
        ip for ip in ips
        if safe_brightness(snapshot.get(ip, {}).get("brillo", 0)) > 0
    ]
    if not active_ips:
        return

    steps = max(3, int(steps))
    duration_ms = max(250, int(duration_ms))
    step_ms = max(30, duration_ms // steps)

    def step(index=0):
        factor = max(0.0, 1.0 - (index / steps))
        for ip in active_ips:
            state = snapshot[ip]
            brightness = safe_brightness(state.get("brillo", 0) * factor)
            if brightness <= 0 or index >= steps:
                send_off(ip)
                selected_devices[ip].set(False)
                panel = panels.get(ip)
                if panel:
                    panel.last_brillo = 0
                    try:
                        panel.brillo_var.set(0)
                    except Exception:
                        pass
                    update_panel_visual(panel)
                continue
            trigger_send_scene_state(ip, state, brightness)
        if index >= steps:
            sync_espacio_laberintos_current_state(active_ips)
            return
        root.after(step_ms, lambda: step(index + 1))

    step()


def _chase_brightness(distance, tail_pct):
    if distance == 0:
        return 255
    if distance == 1:
        return safe_brightness(255 * tail_pct / 100)
    return 0


def run_chase_trigger(ips, color=(190, 1.0), step_ms=36, tail_pct=18, reverse=False):
    snapshot = snapshot_trigger_state(ips)
    travel_ips = list(reversed(ips)) if reverse else list(ips)
    total_steps = len(travel_ips) + 1

    def step(index=0):
        if index >= total_steps:
            root.after(25, lambda: restore_trigger_state(snapshot))
            return
        for pos, ip in enumerate(travel_ips):
            brightness = _chase_brightness(abs(pos - index), tail_pct)
            trigger_send_color(ip, color[0], color[1], brightness)
        root.after(max(18, int(step_ms)), lambda: step(index + 1))

    step()


def run_center_open_trigger(ips, color=(48, 0.9), step_ms=46):
    snapshot = snapshot_trigger_state(ips)
    count = len(ips)
    if count == 0:
        return
    center = (count - 1) / 2
    max_distance = int(center) + 1

    def step(distance=0):
        if distance > max_distance:
            root.after(30, lambda: restore_trigger_state(snapshot))
            return
        for pos, ip in enumerate(ips):
            brightness = 255 if int(abs(pos - center) + 0.5) == distance else 0
            trigger_send_color(ip, color[0], color[1], brightness)
        root.after(max(20, int(step_ms)), lambda: step(distance + 1))

    step()


def run_sparkle_trigger(
    ips,
    steps=8,
    step_ms=60,
    color=None,
    temp=4300,
    density=0.33,
    min_brightness=25,
    max_brightness=220,
):
    snapshot = snapshot_trigger_state(ips)
    density = max(0.05, min(1.0, float(density)))

    def step(index=0):
        if index >= int(steps):
            root.after(45, lambda: restore_trigger_state(snapshot))
            return

        for ip in ips:
            if random.random() <= density:
                level = random.randint(int(min_brightness), int(max_brightness))
            else:
                level = 0

            if color is None:
                trigger_send_white(ip, level, temp)
            else:
                trigger_send_color(ip, color[0], color[1], level)

        root.after(max(28, int(step_ms)), lambda: step(index + 1))

    step()


def run_breath_trigger(ips, levels, step_ms=70, color=None, temp=6000):
    snapshot = snapshot_trigger_state(ips)

    def step(index=0):
        if index >= len(levels):
            root.after(40, lambda: restore_trigger_state(snapshot))
            return

        level = safe_brightness(levels[index])
        for ip in ips:
            if color is None:
                trigger_send_white(ip, level, temp)
            else:
                trigger_send_color(ip, color[0], color[1], level)

        root.after(max(35, int(step_ms)), lambda: step(index + 1))

    step()


def run_edges_in_trigger(ips, color=(352, 1.0), step_ms=44):
    snapshot = snapshot_trigger_state(ips)
    count = len(ips)
    if count == 0:
        return
    max_step = (count + 1) // 2

    def step(index=0):
        if index >= max_step + 1:
            root.after(35, lambda: restore_trigger_state(snapshot))
            return

        left = index
        right = count - 1 - index
        for pos, ip in enumerate(ips):
            distance = min(abs(pos - left), abs(pos - right))
            brightness = 245 if distance == 0 else 58 if distance == 1 else 0
            trigger_send_color(ip, color[0], color[1], brightness)

        root.after(max(28, int(step_ms)), lambda: step(index + 1))

    step()


def run_hue_sweep_trigger(ips, start_hue=145, hue_span=85, step_ms=42, tail_pct=35):
    snapshot = snapshot_trigger_state(ips)
    count = len(ips)
    if count == 0:
        return
    total_steps = count + 2

    def step(index=0):
        if index >= total_steps:
            root.after(35, lambda: restore_trigger_state(snapshot))
            return

        for pos, ip in enumerate(ips):
            distance = abs(pos - index)
            brightness = _chase_brightness(distance, tail_pct)
            hue = (float(start_hue) + (float(hue_span) * pos / max(1, count - 1))) % 360
            trigger_send_color(ip, hue, 0.88, brightness)

        root.after(max(28, int(step_ms)), lambda: step(index + 1))

    step()


def run_scene_bloom_trigger(ips, levels, step_ms=140):
    snapshot = snapshot_trigger_state(ips)

    def step(index=0):
        if index >= len(levels):
            root.after(45, lambda: restore_trigger_state(snapshot))
            return
        for ip in ips:
            state = snapshot[ip]
            trigger_send_scene_state(ip, state, scene_brightness_from_factor(state, levels[index]))
        root.after(max(45, int(step_ms)), lambda: step(index + 1))

    step()


def run_scene_echo_trigger(ips, levels, step_ms=115):
    snapshot = snapshot_trigger_state(ips)

    def step(index=0):
        if index >= len(levels):
            root.after(45, lambda: restore_trigger_state(snapshot))
            return
        for ip in ips:
            state = snapshot[ip]
            trigger_send_scene_state(ip, state, scene_brightness_from_factor(state, levels[index]))
        root.after(max(40, int(step_ms)), lambda: step(index + 1))

    step()


def run_scene_water_echo_trigger(
    ips,
    step_ms=82,
    echo_gap=3,
    ring_width=0.72,
    amplitudes=(1.0, 0.58, 0.30),
    tail_factor=0.18,
    base_dim_factor=0.34,
    impact_floor=58,
):
    snapshot = snapshot_trigger_state(ips)
    count = len(ips)
    if count == 0:
        return

    center = (count - 1) / 2
    max_distance = max(abs(pos - center) for pos in range(count))
    echo_gap = max(1, int(echo_gap))
    ring_width = max(0.25, float(ring_width))
    amplitudes = tuple(max(0.0, min(1.0, float(value))) for value in amplitudes) or (1.0,)
    tail_factor = max(0.0, min(1.0, float(tail_factor)))
    base_dim_factor = max(0.05, min(0.95, float(base_dim_factor)))
    impact_floor = safe_brightness(impact_floor)
    total_steps = int(max_distance + echo_gap * (len(amplitudes) - 1) + 3)

    def ripple_factor(distance, radius, amplitude):
        delta = abs(distance - radius)
        if delta <= ring_width:
            return amplitude * (1.0 - (delta / max(0.01, ring_width)) * 0.35)
        if 0 < radius - distance <= 1.25:
            return amplitude * tail_factor
        return 0.0

    def water_echo_brightness(state, factor):
        base = safe_brightness(state.get("brillo", 0))
        dimmed = max(1, safe_brightness(base * base_dim_factor))
        if factor <= 0:
            return dimmed

        peak = max(impact_floor, dimmed)
        return safe_brightness(peak + (255 - peak) * factor)

    def step(index=0):
        if index > total_steps:
            root.after(55, lambda: restore_trigger_state(snapshot))
            return

        for pos, ip in enumerate(ips):
            state = snapshot[ip]
            distance = abs(pos - center)
            factor = 0.0

            for echo_index, amplitude in enumerate(amplitudes):
                radius = index - echo_index * echo_gap
                if radius < 0:
                    continue
                factor = max(factor, ripple_factor(distance, radius, amplitude))

            trigger_send_scene_state(ip, state, water_echo_brightness(state, factor))

        root.after(max(35, int(step_ms)), lambda: step(index + 1))

    step()


def run_scene_wave_trigger(ips, step_ms=52, tail_pct=34, reverse=False):
    snapshot = snapshot_trigger_state(ips)
    travel_ips = list(reversed(ips)) if reverse else list(ips)
    total_steps = len(travel_ips) + 1

    def step(index=0):
        if index >= total_steps:
            root.after(45, lambda: restore_trigger_state(snapshot))
            return
        for pos, ip in enumerate(travel_ips):
            state = snapshot[ip]
            distance = abs(pos - index)
            factor = 1.0 if distance == 0 else float(tail_pct) / 100 if distance == 1 else 0.0
            trigger_send_scene_state(ip, state, scene_brightness_from_factor(state, factor))
        root.after(max(28, int(step_ms)), lambda: step(index + 1))

    step()


def run_scene_sparkle_trigger(ips, steps=10, step_ms=72, density=0.38, min_factor=0.18):
    snapshot = snapshot_trigger_state(ips)
    density = max(0.05, min(1.0, float(density)))
    min_factor = max(0.0, min(1.0, float(min_factor)))

    def step(index=0):
        if index >= int(steps):
            root.after(45, lambda: restore_trigger_state(snapshot))
            return
        for ip in ips:
            state = snapshot[ip]
            if random.random() <= density:
                factor = random.uniform(min_factor, 1.0)
                brightness = scene_brightness_from_factor(state, factor)
            else:
                brightness = scene_brightness_scaled(state, min_factor)
            trigger_send_scene_state(ip, state, brightness)
        root.after(max(35, int(step_ms)), lambda: step(index + 1))

    step()


def run_scene_dip_trigger(ips, levels, step_ms=135):
    snapshot = snapshot_trigger_state(ips)

    def step(index=0):
        if index >= len(levels):
            root.after(45, lambda: restore_trigger_state(snapshot))
            return
        for ip in ips:
            state = snapshot[ip]
            trigger_send_scene_state(ip, state, scene_brightness_scaled(state, levels[index]))
        root.after(max(45, int(step_ms)), lambda: step(index + 1))

    step()


def run_scene_set_level_trigger(ips, brightness):
    snapshot = snapshot_trigger_state(ips)
    brightness = max(8, safe_brightness(brightness))

    for ip in ips:
        state = snapshot[ip]
        panel = panels.get(ip)
        selected_devices[ip].set(True)

        trigger_send_scene_state(ip, state, brightness)

        if panel:
            panel.last_brillo = brightness
            panel.mode_var.set(state.get("mode", getattr(panel, "last_mode", "colour")))
            panel.last_mode = state.get("mode", getattr(panel, "last_mode", "colour"))
            panel.last_hue = state.get("h", getattr(panel, "last_hue", 0))
            panel.last_sat = state.get("s", getattr(panel, "last_sat", 1))
            panel.last_temp = state.get("temp", getattr(panel, "last_temp", 255))
            try:
                panel.brillo_var.set(brightness)
                panel.temp_var.set(panel.last_temp)
            except Exception:
                pass
            update_panel_visual(panel)


def stop_hold_trigger(trigger_name):
    state = active_hold_triggers.get(trigger_name)
    if not state:
        return

    state["active"] = False
    snapshot = state.get("snapshot", {})
    active_hold_triggers.pop(trigger_name, None)
    restore_trigger_state(snapshot)

    note = get_midi_note(trigger_name)
    if note is not None:
        midi_led(note, get_midi_led_color(trigger_name))


def start_hold_trigger(trigger_name, trigger, ips):
    stop_hold_trigger(trigger_name)
    snapshot = snapshot_trigger_state(ips)
    state = {
        "active": True,
        "snapshot": snapshot,
        "step": 0,
    }
    active_hold_triggers[trigger_name] = state

    note = get_midi_note(trigger_name)
    if note is not None:
        led_activo(note)

    kind = trigger.get("kind")
    step_ms = max(28, int(trigger.get("step_ms", 70)))
    ramp_steps = max(1, int(trigger.get("ramp_steps", 8)))

    def loop():
        current = active_hold_triggers.get(trigger_name)
        if not current or not current.get("active"):
            return

        step_index = int(current.get("step", 0))

        if kind == "hold_scene_rise":
            factor = min(1.0, (step_index + 1) / ramp_steps)
            for ip in ips:
                scene_state = snapshot[ip]
                trigger_send_scene_state(ip, scene_state, scene_brightness_from_factor(scene_state, factor))

        elif kind == "hold_scene_shadow":
            floor = max(1, safe_brightness(trigger.get("floor", 1)))
            dim_factor = max(0.05, 1.0 - min(1.0, (step_index + 1) / ramp_steps))
            for ip in ips:
                scene_state = snapshot[ip]
                brightness = max(floor, scene_brightness_scaled(scene_state, dim_factor))
                trigger_send_scene_state(ip, scene_state, brightness)

        elif kind == "hold_scene_shimmer":
            density = max(0.05, min(1.0, float(trigger.get("density", 0.42))))
            min_factor = max(0.0, min(1.0, float(trigger.get("min_factor", 0.20))))
            for ip in ips:
                scene_state = snapshot[ip]
                if random.random() <= density:
                    factor = random.uniform(0.45, 1.0)
                    brightness = scene_brightness_from_factor(scene_state, factor)
                else:
                    brightness = scene_brightness_scaled(scene_state, min_factor)
                trigger_send_scene_state(ip, scene_state, brightness)

        current["step"] = step_index + 1
        root.after(step_ms, loop)

    loop()


def ejecutar_disparador_midi(trigger_name):
    trigger = MIDI_TRIGGER_DEFS.get(trigger_name)
    if not trigger:
        return
    ips = get_trigger_target_ips(trigger.get("scope", "efectos"))
    if not ips:
        return

    if trigger.get("hold"):
        start_hold_trigger(trigger_name, trigger, ips)
        return

    kind = trigger.get("kind")
    if kind == "flash_white":
        run_flash_trigger(
            ips,
            trigger.get("levels", (255, 0)),
            trigger.get("step_ms", 40),
            temp=trigger.get("temp", 4600),
        )
    elif kind == "flash_color":
        run_flash_trigger(
            ips,
            trigger.get("levels", (255, 0)),
            trigger.get("step_ms", 40),
            color=trigger.get("color", (0, 1.0)),
        )
    elif kind == "chase":
        run_chase_trigger(
            ips,
            trigger.get("color", (190, 1.0)),
            trigger.get("step_ms", 36),
            trigger.get("tail_pct", 18),
            trigger.get("reverse", False),
        )
    elif kind == "blackout":
        run_blackout_trigger(ips, trigger.get("hold_ms", 120))
    elif kind == "fade_blackout":
        run_fade_blackout_trigger(
            ips,
            trigger.get("duration_ms", 3500),
            trigger.get("steps", 28),
        )
    elif kind == "center_open":
        run_center_open_trigger(
            ips,
            trigger.get("color", (48, 0.9)),
            trigger.get("step_ms", 46),
        )
    elif kind == "sparkle_white":
        run_sparkle_trigger(
            ips,
            trigger.get("steps", 8),
            trigger.get("step_ms", 60),
            temp=trigger.get("temp", 4300),
            density=trigger.get("density", 0.33),
            min_brightness=trigger.get("min_brightness", 25),
            max_brightness=trigger.get("max_brightness", 220),
        )
    elif kind == "sparkle_color":
        run_sparkle_trigger(
            ips,
            trigger.get("steps", 8),
            trigger.get("step_ms", 60),
            color=trigger.get("color", (120, 0.9)),
            density=trigger.get("density", 0.33),
            min_brightness=trigger.get("min_brightness", 25),
            max_brightness=trigger.get("max_brightness", 220),
        )
    elif kind == "breath_white":
        run_breath_trigger(
            ips,
            trigger.get("levels", (0, 80, 180, 0)),
            trigger.get("step_ms", 70),
            temp=trigger.get("temp", 6000),
        )
    elif kind == "edges_in":
        run_edges_in_trigger(
            ips,
            trigger.get("color", (352, 1.0)),
            trigger.get("step_ms", 44),
        )
    elif kind == "hue_sweep":
        run_hue_sweep_trigger(
            ips,
            trigger.get("start_hue", 145),
            trigger.get("hue_span", 85),
            trigger.get("step_ms", 42),
            trigger.get("tail_pct", 35),
        )
    elif kind == "scene_bloom":
        run_scene_bloom_trigger(
            ips,
            trigger.get("levels", (1.0, 0.6, 0.2)),
            trigger.get("step_ms", 140),
        )
    elif kind == "scene_echo":
        run_scene_echo_trigger(
            ips,
            trigger.get("levels", (1.0, 0.2, 0.7, 0.1)),
            trigger.get("step_ms", 115),
        )
    elif kind == "scene_water_echo":
        run_scene_water_echo_trigger(
            ips,
            trigger.get("step_ms", 82),
            trigger.get("echo_gap", 3),
            trigger.get("ring_width", 0.72),
            trigger.get("amplitudes", (1.0, 0.58, 0.30)),
            trigger.get("tail_factor", 0.18),
            trigger.get("base_dim_factor", 0.34),
            trigger.get("impact_floor", 58),
        )
    elif kind == "scene_wave":
        run_scene_wave_trigger(
            ips,
            trigger.get("step_ms", 52),
            trigger.get("tail_pct", 34),
            trigger.get("reverse", False),
        )
    elif kind == "scene_sparkle":
        run_scene_sparkle_trigger(
            ips,
            trigger.get("steps", 10),
            trigger.get("step_ms", 72),
            trigger.get("density", 0.38),
            trigger.get("min_factor", 0.18),
        )
    elif kind == "scene_dip":
        run_scene_dip_trigger(
            ips,
            trigger.get("levels", (0.18, 0.1, 0.5, 0.9)),
            trigger.get("step_ms", 135),
        )
    elif kind == "scene_set_level":
        run_scene_set_level_trigger(
            ips,
            trigger.get("brightness", 8),
        )


def open_midi_triggers_panel():
    win = tk.Toplevel(root)
    win.title("Disparadores MIDI")
    win.configure(bg="#181b1e")
    win.geometry("940x720")
    win.minsize(760, 560)

    shell = tk.Frame(win, bg="#181b1e")
    shell.pack(fill="both", expand=True, padx=14, pady=14)
    shell.grid_rowconfigure(1, weight=1)
    shell.grid_columnconfigure(0, weight=1)

    header = tk.Frame(shell, bg="#181b1e")
    header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
    header.grid_columnconfigure(0, weight=1)

    tk.Label(
        header,
        text="Disparadores MIDI",
        bg="#181b1e",
        fg="#20bdec",
        font=("Segoe UI", 18, "bold"),
    ).grid(row=0, column=0, sticky="w")

    tk.Label(
        header,
        text="Acentos momentaneos para vivo: golpean, respiran, titilan o viajan y luego restauran la escena activa.",
        bg="#181b1e",
        fg="#b9e3f7",
        font=("Segoe UI", 10),
    ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    status_var = tk.StringVar(value="Edita una nota y guarda solo ese disparador.")
    tk.Label(
        header,
        textvariable=status_var,
        bg="#181b1e",
        fg="#f1c40f",
        font=("Segoe UI", 10, "bold"),
        anchor="e",
    ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))

    canvas = tk.Canvas(shell, bg="#181b1e", highlightthickness=0)
    scroll = tk.Scrollbar(shell, orient="vertical", command=canvas.yview)
    body = tk.Frame(canvas, bg="#181b1e")
    body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
    body_window = canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
    canvas.configure(yscrollcommand=scroll.set)
    canvas.grid(row=1, column=0, sticky="nsew")
    scroll.grid(row=1, column=1, sticky="ns")
    bind_mousewheel_scroll(canvas, canvas, body)

    for col in range(2):
        body.grid_columnconfigure(col, weight=1, uniform="trigger_cards")

    note_vars = {}
    color_vars = {}

    def test_trigger(action):
        ejecutar_disparador_midi(action)
        if MIDI_TRIGGER_DEFS[action].get("hold"):
            root.after(1100, lambda: stop_hold_trigger(action))
        note = get_midi_note(action)
        if note is not None:
            midi_led(note, get_midi_led_color(action))
        status_var.set(f"Probando: {MIDI_TRIGGER_DEFS[action]['nombre']}")

    def save_trigger(action):
        note_var = note_vars[action]
        color_var = color_vars[action]
        if save_single_midi_mapping(action, note_var.get(), color_var.get()):
            note = get_midi_note(action)
            note_var.set("" if note is None else str(note))
            color_var.set(get_midi_led_color_name(action))
            status_var.set(f"Guardado: {MIDI_TRIGGER_DEFS[action]['nombre']}")

    grid_row = 0
    grid_col = 0
    last_category = None

    for trigger_name, trigger in MIDI_TRIGGER_DEFS.items():
        if trigger.get("hold"):
            category = "Presion"
        elif trigger.get("scope") == "scene_selected":
            category = "Sobre escena"
        else:
            category = "Color propio"
        if category != last_category:
            if grid_col != 0:
                grid_row += 1
                grid_col = 0

            title = (
                "PRESION"
                if category == "Presion"
                else "SOBRE ESCENA"
                if category == "Sobre escena"
                else "COLOR PROPIO"
            )
            if category == "Presion":
                subtitle = "Actua mientras mantenes el boton MIDI presionado y libera al soltar."
            elif category == "Sobre escena":
                subtitle = "Respeta color, blanco y brillo configurado en la escena o seleccion actual."
            else:
                subtitle = "Usa un color o textura propia para acentos generales."
            section = tk.Frame(body, bg="#181b1e")
            section.grid(row=grid_row, column=0, columnspan=2, sticky="ew", padx=6, pady=(10, 2))
            section.grid_columnconfigure(0, weight=1)
            tk.Label(
                section,
                text=title,
                bg="#181b1e",
                fg="#20bdec",
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            tk.Label(
                section,
                text=subtitle,
                bg="#181b1e",
                fg="#8fb8c9",
                font=("Segoe UI", 9),
                anchor="w",
            ).grid(row=1, column=0, sticky="w")
            grid_row += 1
            last_category = category

        row = grid_row
        col = grid_col
        card = tk.Frame(
            body,
            bg="#232b32",
            highlightthickness=1,
            highlightbackground="#3a4650",
            padx=0,
            pady=0,
        )
        card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
        card.grid_columnconfigure(1, weight=1)

        accent = trigger.get("accent", "#20bdec")
        tk.Frame(card, bg=accent, width=7).grid(row=0, column=0, rowspan=5, sticky="nsw")

        tk.Label(
            card,
            text=trigger.get("familia", "Disparador").upper(),
            bg="#232b32",
            fg=accent,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=10, pady=(9, 0))

        tk.Label(
            card,
            text=trigger["nombre"],
            bg="#232b32",
            fg="#ffffff",
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        ).grid(row=1, column=1, sticky="ew", padx=10, pady=(1, 0))

        tk.Label(
            card,
            text=trigger["descripcion"],
            bg="#232b32",
            fg="#b9e3f7",
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=320,
            justify="left",
        ).grid(row=2, column=1, columnspan=2, sticky="ew", padx=10, pady=(2, 8))

        controls = tk.Frame(card, bg="#232b32")
        controls.grid(row=3, column=1, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        controls.grid_columnconfigure(3, weight=1)

        note = get_midi_note(trigger_name)
        note_var = tk.StringVar(value="" if note is None else str(note))
        color_var = tk.StringVar(value=get_midi_led_color_name(trigger_name))
        note_vars[trigger_name] = note_var
        color_vars[trigger_name] = color_var

        tk.Label(controls, text="Nota", bg="#232b32", fg="#8fb8c9",
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        note_entry = tk.Entry(
            controls,
            textvariable=note_var,
            width=6,
            bg="#111519",
            fg="#e6e6e6",
            insertbackground="#20bdec",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        note_entry.grid(row=1, column=0, sticky="w", padx=(0, 8))
        note_entry.bind(
            "<FocusIn>",
            lambda _e, v=note_var, action=trigger_name: set_midi_learn_target(
                v,
                status_var,
                MIDI_TRIGGER_DEFS[action]["nombre"],
            ),
            add="+",
        )

        tk.Label(controls, text="LED", bg="#232b32", fg="#8fb8c9",
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=color_var,
            values=list(MIDI_LED_COLOR_OPTIONS.keys()),
            state="readonly",
            width=15,
            font=("Segoe UI", 9),
        ).grid(row=1, column=1, sticky="w", padx=(0, 8))

        tk.Button(
            controls,
            text="Guardar",
            command=lambda action=trigger_name: save_trigger(action),
            bg="#27ae60",
            fg="#ffffff",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            width=9,
        ).grid(row=1, column=2, sticky="w", padx=(0, 6))

        tk.Button(
            controls,
            text="Probar",
            command=lambda action=trigger_name: test_trigger(action),
            bg="#20bdec",
            fg="#001018",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            width=8,
        ).grid(row=1, column=3, sticky="w")

        grid_col += 1
        if grid_col >= 2:
            grid_col = 0
            grid_row += 1

    footer = tk.Frame(shell, bg="#181b1e")
    footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
    tk.Button(
        footer,
        text="Reiniciar LEDs MIDI",
        command=inicializar_leds_midi,
        bg="#2b343b",
        fg="#d9f3ff",
        relief="flat",
        font=("Segoe UI", 10, "bold"),
    ).pack(side="right")


try:
    midi_menu.add_command(label="Disparadores MIDI", command=open_midi_triggers_panel)
except Exception:
    pass



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
    if is_apc_espacio_note(note):
        refresh_espacio_midi_leds()
        return

    BOTONES_ESPECIALES = {
        get_midi_note("refresh"),
        get_midi_note("all_off"),
        get_midi_note("all_on"),
    }

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
        action = get_midi_action_for_note(note)
        midi_led(note, get_midi_led_color(action) if action else 5)


# --- diccionario de mapeo MIDI ---
note_map = {

    # Navegacion de escenas para show
    1: lambda: root.after(0, lambda: seleccionar_escena_midi(-1)),
    3: lambda: root.after(0, go_escena_midi),
    4: lambda: root.after(0, lambda: seleccionar_escena_midi(1)),
    5: lambda: root.after(0, stop_show_midi),

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
    58: lambda: root.after(0, lambda: (toggle_efecto(atardecer_var, toggle_atardecer, "atardecer"), actualizar_led_efecto(58))),
    


}
    
note_map[2] = lambda: root.after(0, lambda: efecto_golpe_de_tambor(
    send_lamp_color_safe,
    get_lamp_state,
    restore_lamp_state,
    LAMP_IPS,
    selected_devices,
    root
))


def rebuild_midi_mappings():
    global note_map, midi_estado_efectos

    def update_power_leds(on_active):
        all_on_note = get_midi_note("all_on")
        all_off_note = get_midi_note("all_off")
        if on_active:
            midi_led(all_on_note, get_midi_led_color("all_on"))
            midi_led(all_off_note, get_midi_led_color("all_off"))
        else:
            midi_led(all_off_note, get_midi_led_color("all_off"))
            midi_led(all_on_note, get_midi_led_color("all_on"))

    action_callbacks = {
        "scene_prev": lambda: root.after(0, lambda: seleccionar_escena_midi(-1)),
        "scene_go": lambda: root.after(0, go_escena_midi),
        "scene_next": lambda: root.after(0, lambda: seleccionar_escena_midi(1)),
        "show_stop": lambda: root.after(0, stop_show_midi),
        "refresh": lambda: root.after(0, refresh_lamp_status),
        "all_on": lambda: root.after(0, lambda: (encender_todo(), update_power_leds(True))),
        "all_off": lambda: root.after(0, lambda: (apagar_todo(), update_power_leds(False))),
        "drum_hit": lambda: root.after(0, lambda: efecto_golpe_de_tambor(
            send_lamp_color_safe,
            get_lamp_state,
            restore_lamp_state,
            LAMP_IPS,
            selected_devices,
            root,
        )),
        "effect_breathe": lambda: root.after(0, lambda: (
            toggle_efecto(respirando, toggle_respiracion, "respiracion"),
            actualizar_led_efecto(get_midi_note("effect_breathe"))
        )),
        "effect_sequence": lambda: root.after(0, lambda: (
            toggle_efecto(secuencia_var, toggle_secuencia, "secuencia"),
            actualizar_led_efecto(get_midi_note("effect_sequence"))
        )),
        "effect_sequence_on": lambda: root.after(0, lambda: (
            toggle_efecto(secuencia_on_var, toggle_secuencia_on, "secuencia_on"),
            actualizar_led_efecto(get_midi_note("effect_sequence_on"))
        )),
        "effect_sequence_off": lambda: root.after(0, lambda: (
            toggle_efecto(secuencia_off_var, toggle_secuencia_off, "secuencia_off"),
            actualizar_led_efecto(get_midi_note("effect_sequence_off"))
        )),
        "effect_blink": lambda: root.after(0, lambda: (
            toggle_efecto(parpadeo_var, toggle_parpadeo, "parpadeo"),
            actualizar_led_efecto(get_midi_note("effect_blink"))
        )),
        "effect_strobe": lambda: root.after(0, lambda: (
            toggle_efecto(estrobo_var, toggle_estrobo, "estrobo"),
            actualizar_led_efecto(get_midi_note("effect_strobe"))
        )),
        "effect_sunset": lambda: root.after(0, lambda: (
            toggle_efecto(atardecer_var, toggle_atardecer, "atardecer"),
            actualizar_led_efecto(get_midi_note("effect_sunset"))
        )),
    }

    for trigger_name in MIDI_TRIGGER_DEFS:
        action_callbacks[trigger_name] = (
            lambda name=trigger_name: root.after(0, lambda: ejecutar_disparador_midi(name))
        )

    midi_estado_efectos = {
        note: var
        for note, var in {
            get_midi_note("effect_breathe"): respirando,
            get_midi_note("effect_sequence"): secuencia_var,
            get_midi_note("effect_sequence_on"): secuencia_on_var,
            get_midi_note("effect_sequence_off"): secuencia_off_var,
            get_midi_note("effect_blink"): parpadeo_var,
            get_midi_note("effect_strobe"): estrobo_var,
            get_midi_note("effect_sunset"): atardecer_var,
        }.items()
        if note is not None and not is_apc_espacio_note(note)
    }

    note_map = {}
    for action in MIDI_ACTION_DEFAULT_NOTES:
        callback = action_callbacks.get(action)
        note = get_midi_note(action)
        if callback is not None and note is not None and not is_apc_espacio_note(note):
            note_map[note] = callback


rebuild_midi_mappings()
   
cc_map = {
     48: set_maestro_brillo_from_midi,  # fader 1
}


def inicializar_leds_midi():
    inicializar_leds(note_map.keys())

    for action in MIDI_ACTION_DEFAULT_NOTES:
        note = get_midi_note(action)
        if not is_apc_espacio_note(note):
            midi_led(note, get_midi_led_color(action))
    update_midi_scene_execution_led()
    refresh_espacio_midi_leds()

# --- activar el listener MIDI ---
# 1) Iniciar MIDI
if start_midi_thread(handle_midi_event):
    # 2) Una vez que MIDI está listo, esperar un poco
    #    y luego encender LEDs de acciones
    root.after(1200, inicializar_leds_midi)
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


def on_app_close():
    if not confirmar_cambios_proyecto_pendientes("salir"):
        return
    if proyecto_activo.get("dirty"):
        guardar_ultimo_proyecto_activo(None)
    stop_midi()
    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_app_close)
print("[APP] Interfaz iniciada. Si no ves la ventana, revisa si quedo detras de la terminal.")
root.mainloop()

