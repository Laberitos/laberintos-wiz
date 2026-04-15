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

fade_token = [None]
semaforo_fades = asyncio.Semaphore(10)  # Solo 5 fades simultáneos, puedes ajustar el número

import screeninfo

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



# -- Estado de lámparas online/offline --
lamp_status = {}
def refresh_lamp_status():
    online = get_online_ips()
    for ip, panel in panels.items():
        if ip in online:
            panel.config(bg="#172d1f")
            lamp_status[ip] = True
        else:
            panel.config(bg="#321c1c")
            lamp_status[ip] = False


async def send_color_to_lamps(ips, h, s, brillo):
    brillo = safe_brightness(brillo)
    r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
    r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
    tasks = [wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)) for ip in ips]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for ip, result in zip(ips, results):
        if isinstance(result, Exception):
            print(f"[WARN] No se pudo enviar color a {ip}: {result}")

async def send_white_to_lamps(ips, brillo, temp):
    brillo = safe_brightness(brillo)
    tasks = [wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp)) for ip in ips]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for ip, result in zip(ips, results):
        if isinstance(result, Exception):
            print(f"[WARN] No se pudo enviar blanco a {ip}: {result}")

def send_lamp_color(ip, h, s, brillo_slider):
    r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
    r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
    brillo = map_slider_to_wiz_brightness(brillo_slider)
    try:
        import asyncio
        try:
            # Intenta usar el event loop actual
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Si estamos en el main thread con loop corriendo, usa ensure_future
                asyncio.ensure_future(wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)))
            else:
                loop.run_until_complete(wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)))
        except RuntimeError:
            # Si no hay event loop en este thread, crea uno nuevo
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)))
            loop.close()
    except Exception as e:
        print(f"[WARN] No se pudo enviar color a {ip}: {e}")


def send_lamp_white(ip, brillo_slider, temp_slider):
    if not lamp_status.get(ip, True):
        print(f"[WARN] Lámpara {ip} está OFFLINE, no se envía comando.")
        return
    brillo = map_slider_to_wiz_brightness(brillo_slider)
    temp = map_slider_to_wiz_temperature(temp_slider)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp)))
        else:
            loop.run_until_complete(wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp)))
    except Exception as e:
        print(f"[WARN] No se pudo enviar blanco a {ip}: {e}")

def send_off(ip):
    if not lamp_status.get(ip, True):
        print(f"[WARN] Lámpara {ip} está OFFLINE, no se apaga.")
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(wizlight(ip).turn_off())
        else:
            loop.run_until_complete(wizlight(ip).turn_off())
    except Exception as e:
        print(f"[WARN] No se pudo apagar la lámpara {ip}: {e}")

def update_name(ip, entry):
    lamp_names[ip] = entry.get()
    save_lamp_names(lamp_names)


def safe_brightness(brillo):
    try:
        brillo = int(round(float(brillo)))
    except Exception:
        brillo = 255
    return max(1, min(255, brillo))


def map_slider_to_wiz_brightness(slider_value):
    val = round(10 + (int(slider_value) - 1) * (255 - 10) / (1000 - 1))
    return safe_brightness(val)

def map_slider_to_wiz_temperature(slider_value):
    # Slider a la izquierda = cálido, derecha = frío (más intuitivo)
    return int(2200 + ((int(slider_value)) * (6500 - 2200) / 1000))

# === Estado de conexión de las lámparas ===
def ip_online(ip):
    try:
        result = subprocess.run(["ping", "-n", "1", "-w", "100", ip], capture_output=True)
        return result.returncode == 0
    except Exception:
        return False

def get_online_ips():
    return [ip for ip in LAMP_IPS if ip_online(ip)]

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
frame_main.pack(fill="both", expand=True)

# ----- 1. FRAME IZQUIERDO (vertical, maestro + efectos) -----
frame_left = tk.Frame(frame_main, bg="#181b1e")
frame_left.pack(side="left", fill="y", padx=(15, 8), pady=15)


# ---- CONTROL MAESTRO ----
frame_maestro = tk.LabelFrame(
    frame_left, text="Control Maestro", bg="#181b1e", fg="#20bdec",
    font=("Segoe UI", 16, "bold"), padx=5, pady=5, width=410, height=350
)
frame_maestro.pack(side="top", fill="x", expand=False, pady=(0, 16))

# ---- PANEL DE EFECTOS ----
frame_efectos = tk.LabelFrame(
    frame_left, text="Efectos", bg="#232b32", fg="#20bdec",
    font=("Segoe UI", 15, "bold"), padx=14, pady=14, width=410, height=250
)
frame_efectos.pack(side="top", fill="x", expand=False)
frame_efectos.pack_propagate(False)

# --- CONTROLES DE EFECTOS DENTRO DE frame_efectos ---

tk.Label(
    frame_efectos, text="Respiración",
    bg="#232b32", fg="#20bdec", font=("Segoe UI", 14, "bold")
).pack(pady=(0, 8))

respirando = tk.BooleanVar(value=False)

from acciones.acciones import efecto_respiracion

def toggle_respiracion():
    if respirando.get():
        btn_resp.config(text="Detener Respiración", bg="#ef5350")
        efecto_respiracion(
          send_lamp_color, LAMP_IPS, panels, selected_devices,
          10, 1000,    # brillo_min, brillo_max
          0.1, 0.1, # velocidad_subida, velocidad_bajada
    respirando, root
)
    else:
        btn_resp.config(text="Iniciar Respiración", bg="#20bdec")


btn_resp = tk.Checkbutton(
    frame_efectos,
    text="Respiración",
    variable=respirando,
    font=("Segoe UI", 13, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    width=20,
    command=toggle_respiracion
)
btn_resp.pack(pady=24)


#EFECTO SECUENCUENCIA
chase_var = tk.BooleanVar(value=False)

from acciones.acciones import efecto_chase

def toggle_chase():
    if chase_var.get():
        btn_chase.config(text="Detener Secuencia", bg="#ef5350")
        efecto_chase(
            send_lamp_color, LAMP_IPS, panels, selected_devices,
            1000, 500, chase_var, root
        )
    else:
        btn_chase.config(text="Iniciar Secuencia", bg="#20bdec")
        
btn_chase = tk.Checkbutton(
    frame_efectos,
    text="Secuencia",
    variable=chase_var,
    font=("Segoe UI", 13, "bold"),
    bg="#20bdec", fg="#fff", selectcolor="#232b32",
    width=20,
    command=toggle_chase
)
btn_chase.pack(pady=12)


maestro_hsv = {"h": 0, "s": 1}
maestro_brillo = tk.IntVar(value=1000)
maestro_temp = tk.IntVar(value=500)
maestro_mode = tk.StringVar(value="colour")

def maestro_on_color(h, s, v):
    maestro_hsv["h"] = h
    maestro_hsv["s"] = s
    if maestro_mode.get() == "colour":
        h = maestro_hsv["h"]
        s = maestro_hsv["s"]
        brillo = maestro_brillo.get()
        selected_ips = [ip for ip in LAMP_IPS if selected_devices[ip].get() and lamp_status.get(ip, True)]
        for ip in selected_ips:
            panels[ip].mode_var.set("colour")
            panels[ip].last_mode = "colour"
            panels[ip].last_hue = h
            panels[ip].last_sat = s
            panels[ip].last_brillo = brillo
        if selected_ips:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(send_color_to_lamps(selected_ips, h, s, brillo))
                else:
                    loop.run_until_complete(send_color_to_lamps(selected_ips, h, s, brillo))
            except Exception as e:
                print(f"[WARN] Maestro color: {e}")

def maestro_on_temp(value):
    if maestro_mode.get() == "white":
        brillo = maestro_brillo.get()
        temp = maestro_temp.get()
        print("[DEBUG] Temperatura slider (raw):", value, "| Temperatura enviada:", map_slider_to_wiz_temperature(temp))
        selected_ips = [ip for ip in LAMP_IPS if selected_devices[ip].get() and lamp_status.get(ip, True)]
        for ip in selected_ips:
            panels[ip].mode_var.set("white")
            panels[ip].last_mode = "white"
            panels[ip].last_brillo = brillo
            panels[ip].last_temp = temp
        if selected_ips:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(send_white_to_lamps(selected_ips, brillo, map_slider_to_wiz_temperature(temp)))
                else:
                    loop.run_until_complete(send_white_to_lamps(selected_ips, brillo, map_slider_to_wiz_temperature(temp)))
            except Exception as e:
                print(f"[WARN] Maestro blanco: {e}")
                
def maestro_on_brillo(value):
    modo = maestro_mode.get()
    h = maestro_hsv["h"]
    s = maestro_hsv["s"]
    brillo = int(value)
    temp = maestro_temp.get()
    selected_ips = [ip for ip in LAMP_IPS if selected_devices[ip].get() and lamp_status.get(ip, True)]
    for ip in selected_ips:
        panels[ip].last_brillo = brillo
        panels[ip].mode_var.set(modo)
        panels[ip].last_mode = modo
    if selected_ips:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                if modo == "colour":
                    asyncio.ensure_future(send_color_to_lamps(selected_ips, h, s, brillo))
                else:
                    asyncio.ensure_future(send_white_to_lamps(selected_ips, brillo, maestro_temp.get()))
            else:
                if modo == "colour":
                    loop.run_until_complete(send_color_to_lamps(selected_ips, h, s, brillo))
                else:
                    loop.run_until_complete(send_white_to_lamps(selected_ips, brillo, maestro_temp.get()))
        except Exception as e:
            print(f"[WARN] Maestro brillo: {e}")
                

def aplicar_maestro():
    modo = maestro_mode.get()
    h = maestro_hsv["h"]
    s = maestro_hsv["s"]
    brillo = maestro_brillo.get()
    temp = maestro_temp.get()
    selected_ips = [ip for ip in LAMP_IPS if selected_devices[ip].get() and lamp_status.get(ip, True)]
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
            loop = asyncio.get_event_loop()
            if loop.is_running():
                if modo == "colour":
                    asyncio.ensure_future(send_color_to_lamps(selected_ips, h, s, brillo))
                else:
                    asyncio.ensure_future(send_white_to_lamps(selected_ips, brillo, temp))
            else:
                if modo == "colour":
                    loop.run_until_complete(send_color_to_lamps(selected_ips, h, s, brillo))
                else:
                    loop.run_until_complete(send_white_to_lamps(selected_ips, brillo, temp))
        except Exception as e:
            print(f"[WARN] Maestro aplicar: {e}")

colorwheel_maestro = RealColorWheel(frame_maestro, radius=90, callback=maestro_on_color, bg="#181b1e", bd=0, highlightthickness=0)
colorwheel_maestro.pack(side="left", padx=16)

controls_maestro = tk.Frame(frame_maestro, bg="#181b1e")
controls_maestro.pack(side="left", padx=18)

tk.Label(controls_maestro, text="Brillo", bg="#181b1e", fg="#fff").pack()
tk.Scale(controls_maestro, from_=1, to=1000, orient="horizontal", variable=maestro_brillo,
         length=260, bg="#181b1e", fg="#20bdec", command=maestro_on_brillo).pack()

tk.Label(controls_maestro, text="Temp (Blanco cálido–frío)", bg="#181b1e", fg="#f1c40f").pack()
tk.Scale(controls_maestro, from_=0, to=1000, orient="horizontal", variable=maestro_temp,
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

#CIERRE MAESTRO Y EFECTOS__________________________________________________________________________________________

# ----- 2. FRAME CENTRAL (lámparas) -------------------------------------------------------------------------------
frame_center = tk.Frame(frame_main, bg="#181b1e")
frame_center.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=15)

frame_lamps = tk.Frame(frame_center, bg="#212529")
frame_lamps.pack(fill="both", expand=False, padx=30, pady=20)

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
    panel.grid(row=idx//5, column=idx%5, padx=12, pady=16, sticky="nsew")

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
            send_lamp_color(ip, getattr(panels[ip], "last_hue", 0), getattr(panels[ip], "last_sat", 1), getattr(panels[ip], "last_brillo", 1000))
            if panels[ip].last_mode == "colour" and selected_devices[ip].get()
            else send_lamp_white(ip, getattr(panels[ip], "last_brillo", 1000), getattr(panels[ip], "last_temp", 500))
            if panels[ip].last_mode == "white" and selected_devices[ip].get()
            else send_off(ip)
        ),
        fg="#20bdec",
        bg="#161a1d",
        selectcolor="#212529",
        font=("Segoe UI", 11, "bold")
    ).pack()

    brillo_var = tk.IntVar(value=1000)
    temp_var = tk.IntVar(value=500)
    
    panel.brillo_var = brillo_var
    panel.temp_var = temp_var

    def on_color(h, s, v, ip=ip, brillo_var=brillo_var, panel=panel):
        panel.last_hue = h
        panel.last_sat = s
        panel.last_brillo = brillo_var.get()
        panel.mode_var.set("colour")
        panel.last_mode = "colour"
        if selected_devices[ip].get():
            send_lamp_color(ip, h, s, brillo_var.get())

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
                send_lamp_color(ip, getattr(panel, "last_hue", 0), getattr(panel, "last_sat", 1), panel.last_brillo)
            elif modo == "white":
                send_lamp_white(ip, panel.last_brillo, getattr(panel, "last_temp", 500))

    tk.Scale(panel, from_=1, to=1000, orient="horizontal", variable=brillo_var,
            command=lambda v, ip=ip, panel=panel: on_brillo_change(v, ip, panel),
            bg="#161a1d", fg="#20bdec", length=120).pack()

    tk.Label(panel, text="Temp (Blanco cálido–frío)", bg="#22292f", fg="#f1c40f").pack()

    def on_temp_panel(value, ip=ip, panel=panel):
        panel.last_temp = int(value)
        if panel.mode_var.get() == "white" and selected_devices[ip].get():
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)

    tk.Scale(panel, from_=0, to=1000, orient="horizontal", variable=temp_var,
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
            send_lamp_color(ip, getattr(panel, "last_hue", 0), getattr(panel, "last_sat", 1), getattr(panel, "last_brillo", 1000))
            if selected_devices[ip].get() else None
        ),
        bg="#22292f", fg="#20bdec", selectcolor="#161a1d", font=("Segoe UI", 11)
    ).pack(side="left", padx=2)

    tk.Radiobutton(
        frame_modos,
        text="Blanco", variable=modo_var, value="white",
        command=lambda ip=ip, panel=panel: (
            setattr(panel, "last_mode", "white"),
            send_lamp_white(ip, getattr(panel, "last_brillo", 1000), getattr(panel, "last_temp", 500))
            if selected_devices[ip].get() else None
        ),
        bg="#22292f", fg="#f1c40f", selectcolor="#161a1d", font=("Segoe UI", 11)
    ).pack(side="left", padx=2)

    send_off(ip)
    panels[ip] = panel


# --- Botones de apagar/encender todo ---
frame_bottom = tk.Frame(frame_left, bg="#181b1e")
frame_bottom.pack(fill="x", pady=18)

def apagar_todo():
    ips = [ip for ip in LAMP_IPS if lamp_status.get(ip, True)]
    async def apagar_lamps():
        tasks = [wizlight(ip).turn_off() for ip in ips]
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

def encender_todo():
    modo = maestro_mode.get()
    h = maestro_hsv["h"]
    s = maestro_hsv["s"]
    brillo = maestro_brillo.get()
    temp = maestro_temp.get()
    ips = [ip for ip in LAMP_IPS if lamp_status.get(ip, True)]
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
    async def encender_lamps():
        if modo == "colour":
            await send_color_to_lamps(ips, h, s, brillo)
        else:
            await send_white_to_lamps(ips, brillo, temp)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(encender_lamps())
        else:
            loop.run_until_complete(encender_lamps())
    except Exception as e:
        print(f"[WARN] Encender todo: {e}")

tk.Button(frame_bottom, text="Apagar Todo", command=apagar_todo,
          bg="#404040", fg="#fff", font=("Segoe UI", 12, "bold")).pack(side="left", padx=30)
tk.Button(frame_bottom, text="Encender Todo", command=encender_todo,
          bg="#20bdec", fg="#fff", font=("Segoe UI", 12, "bold")).pack(side="left", padx=20)


#___________________________________________________________________________________

# ----- 3. FRAME DERECHO (escenas) -----
frame_right = tk.Frame(frame_main, bg="#202428",width=520)
frame_right.pack(side="right", fill="y", padx=(8, 15), pady=15)
frame_right.pack_propagate(False)
# Panel de Escenas (tu panel de siempre, a la derecha del de efectos)
frame_lateral = tk.Frame(root, bg="#181b1e", width=520)
frame_lateral.pack(side="right", fill="y", padx=12, pady=18)
frame_lateral.pack_propagate(False)

frame_escenas = tk.LabelFrame(
    frame_lateral, text="Escenas", bg="#212b32", fg="#20bdec",
    font=("Segoe UI", 15, "bold"), padx=14, pady=14, width=340
)
frame_escenas.pack(side="left", fill="both", expand=False, padx=(0, 0))
frame_escenas.pack_propagate(False)

# -------- PANEL DE ESCENAS EN LA DERECHA ---------
ESCENAS_FILE = "escenas.json"

def load_escenas():
    if os.path.exists(ESCENAS_FILE):
        with open(ESCENAS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Adaptar si es estructura antigua
            if "orden" not in data or "datos" not in data:
                orden = list(data.keys())
                datos = data
                return {"orden": orden, "datos": datos}
            return data
    return {"orden": [], "datos": {}}

def save_escenas(escenas):
    with open(ESCENAS_FILE, "w", encoding="utf-8") as f:
        json.dump(escenas, f, ensure_ascii=False, indent=2)
        

def guardar_escena(nombre_escena, fade_in_val, fade_out_val):
    escenas = load_escenas()
    if nombre_escena in escenas["orden"]:
        return False
    escenas["orden"].append(nombre_escena)
    escenas["datos"][nombre_escena] = {
        "fade_in": fade_in_val,
        "fade_out": fade_out_val
    }
    for ip in LAMP_IPS:
        panel = panels[ip]
        if selected_devices[ip].get():
            # GUARDA EL ESTADO REAL, NO valores por defecto
            estado = {
                "state": "on",
                "modo": panel.last_mode,
                "brillo": panel.last_brillo
            }
            if panel.last_mode == "colour":
                estado.update({
                    "h": panel.last_hue,
                    "s": panel.last_sat
                })
            else:
                estado.update({
                    "temp": panel.last_temp
                })
            escenas["datos"][nombre_escena][ip] = estado
        else:
            # GUARDA APAGADA (nunca dejes valores por defecto)
            escenas["datos"][nombre_escena][ip] = {"state": "off"}
    save_escenas(escenas)
    return True



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
    panel = panels[ip]
    state = {"on": selected_devices[ip].get()}
    if state["on"]:
        if getattr(panel, "last_mode", "colour") == "colour":
            state.update({
                "modo": "colour",
                "h": getattr(panel, "last_hue", 0),
                "s": getattr(panel, "last_sat", 1),
                "brillo": getattr(panel, "last_brillo", 255)
            })
        else:
            state.update({
                "modo": "white",
                "brillo": getattr(panel, "last_brillo", 255),
                "temp": getattr(panel, "last_temp", 4000)
            })
    return state

def estados_son_iguales(actual, destino):
    if actual.get("on") != (destino.get("state", "on") == "on"):
        return False
    if actual.get("on"):
        if actual.get("modo") != destino.get("modo"):
            return False
        if actual.get("brillo") != destino.get("brillo"):
            return False
        if actual.get("modo") == "colour":
            return (actual.get("h") == destino.get("h") and
                    actual.get("s") == destino.get("s"))
        else:
            return actual.get("temp") == destino.get("temp")
    return True        

# --- FADE IN/OUT ---
import asyncio
import math


def ease_in_out_sine(x):
    return -(math.cos(math.pi * x) - 1) / 2


def mostrar_estado_escena_en_paneles(nombre_escena):
    escenas = load_escenas()
    datos = escenas["datos"]
   
    if nombre_escena not in datos:
        return
    escena = datos[nombre_escena]
    for ip in LAMP_IPS:
        estado = escena.get(ip, {})
        panel = panels.get(ip)
        if panel is None:
            continue  # Ignora lámparas que no existan

        modo = estado.get("modo", "colour")
        panel.mode_var.set(modo)
        panel.last_mode = modo
        panel.last_brillo = estado.get("brillo", 255)

        # Actualiza sliders
        if hasattr(panel, "brillo_var"):
            panel.brillo_var.set(estado.get("brillo", 0))
        if estado.get("state", "off") == "on":
            selected_devices[ip].set(True)
        else:
            selected_devices[ip].set(False)
            
        if modo == "colour":
            h = estado.get("h", panel.__dict__.get("last_hue", 0))
            s = estado.get("s", panel.__dict__.get("last_sat", 1))
            panel.last_hue = h
            panel.last_sat = s
            # Mueve el cursor del wheel si existe
            if hasattr(panel, "colorwheel_lamp"):
                # v opcional en 0..1; usamos brillo mapeado 1000->1.0 por consistencia visual
                v = estado.get("brillo", 255) / 1000.0
                panel.colorwheel_lamp.set_color(h, s, v)
        else:
            panel.last_temp = estado.get("temp", 4000)
            if hasattr(panel, "temp_var") and "temp" in estado:
                panel.temp_var.set(estado.get("temp", 4000))
        color_borde = "#03A125" if estado.get("state", "off") == "on" else "#252e36"
        panel.config(highlightbackground=color_borde, highlightcolor=color_borde)

   


async def fade_to(ip, tiempo, from_brillo, to_brillo, modo, h=0, s=1, temp=4000):
    if tiempo <= 0:
        # Aplica directamente el valor destino
        try:
            if to_brillo == 0:
                await wizlight(ip).turn_off()
            elif modo == "colour":
                r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
                r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
                await wizlight(ip).turn_on(PilotBuilder(rgb=(r,g,b), brightness=safe_brightness(to_brillo)))
            else:
                await wizlight(ip).turn_on(PilotBuilder(brightness=safe_brightness(to_brillo), colortemp=temp))
        except Exception as e:
            print(f"[WARN] Fade-to {ip}: {e}")
        return
    max_updates_per_sec = 30  # limita frecuencia de envío
    steps = max(1, int(tiempo * max_updates_per_sec))
    start = time.perf_counter()
    for i in range(1, steps + 1):
        progress = i / steps
        curva = ease_in_out_sine(progress)
        brillo = safe_brightness(from_brillo + (to_brillo - from_brillo) * curva)
        try:
            if modo == "colour":
                r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
                r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
                await wizlight(ip).turn_on(PilotBuilder(rgb=(r,g,b), brightness=brillo))
            else:
                await wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp))
        except Exception as e:
            print(f"[WARN] Fade-to {ip}: {e}")

        # sincroniza el tiempo exacto
        target = start + tiempo * i / steps
        now = time.perf_counter()
        await asyncio.sleep(max(0, target - now))

    # Apaga si to_brillo == 0
    if to_brillo == 0:
        try:
            await wizlight(ip).turn_off()
        except Exception as e:
            print(f"[WARN] Apagando {ip} al final del fade-to: {e}")


def update_progress_global(tiempo_total):
    start = time.time()
    def _update(_progress=None):
        elapsed = time.time() - start
        frac = min(elapsed / tiempo_total, 1.0)
        frame_right.update_idletasks()
    return _update


def aplicar_escena(nombre_escena):
    escenas = load_escenas()
    datos = escenas["datos"]
    if nombre_escena not in datos:
        print(f"No existe la escena: {nombre_escena}")
        return
    escena = datos[nombre_escena]
    fade_in_val = float(escena.get("fade_in", 0.0))
    fade_out_val = float(escena.get("fade_out", 0.0))
    online_ips = [ip for ip in LAMP_IPS if lamp_status.get(ip, True) and ip in escena]
    
    # --- TOKEN ÚNICO para este fade ---
    nuevo_token = str(uuid.uuid4())
    fade_token[0] = nuevo_token

    tiempo_max_fade = max(fade_in_val, fade_out_val)
    frame_right.update_idletasks()
    if tiempo_max_fade > 0:
    # Indicar que la escena empezó + prevenir dobles clics
     set_estado_escena(f"Ejecutando escena: {nombre_escena}…", "#ff4d4d")  # Rojo
     frame_right.update_idletasks()
    try:
        btn_cargar.config(state="disabled")
    except Exception:
        pass
    
    async def fade_to_token(ip, tiempo, from_brillo, to_brillo, modo, h=0, s=1, temp=4000):
        # --- CONTROL DE TOKEN PARA CANCELAR FADES ANTERIORES ---
        mi_token = fade_token[0]
        if tiempo <= 0:
            try:
                if to_brillo == 0:
                    await wizlight(ip).turn_off()
                elif modo == "colour":
                    r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
                    r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
                    await wizlight(ip).turn_on(PilotBuilder(rgb=(r,g,b), brightness=safe_brightness(to_brillo)))
                else:
                    await wizlight(ip).turn_on(PilotBuilder(brightness=safe_brightness(to_brillo), colortemp=temp))
            except Exception as e:
                print(f"[WARN] Fade-to {ip}: {e}")
            return
        max_updates_per_sec = 30  # limita frecuencia de envío
        steps = max(1, int(tiempo * max_updates_per_sec))
        start = time.perf_counter()
        for i in range(1, steps + 1):
            progress = i / steps
            curva = ease_in_out_sine(progress)
            brillo = safe_brightness(from_brillo + (to_brillo - from_brillo) * curva)
            try:
                if modo == "colour":
                    r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
                    r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
                    await wizlight(ip).turn_on(PilotBuilder(rgb=(r,g,b), brightness=brillo))
                else:
                    await wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp))
            except Exception as e:
                print(f"[WARN] Fade-to {ip}: {e}")

            # sincroniza el tiempo exacto
            target = start + tiempo * i / steps
            now = time.perf_counter()
            await asyncio.sleep(max(0, target - now))

        # Apaga si to_brillo == 0
        if to_brillo == 0:
            try:
                await wizlight(ip).turn_off()
            except Exception as e:
                print(f"[WARN] Apagando {ip} al final del fade-to: {e}")

                        

    async def apply_fade():
        fade_tasks = []
        for ip in online_ips:
            if ip not in escena:
                continue
            estado_destino = escena[ip]
            estado_actual = estado_lampara_actual(ip)
            actual_on = estado_actual.get("on")
            destino_on = (estado_destino.get("state", "on") == "on")

            # Valores actuales reales del panel
            from_brillo = estado_actual.get("brillo", 0 if not actual_on else 255)
            to_brillo = estado_destino.get("brillo", 255 if destino_on else 0)
            modo_actual = estado_actual.get("modo", "colour")
            modo_destino = estado_destino.get("modo", "colour")

            h_actual = getattr(panels[ip], "last_hue", 0)
            s_actual = getattr(panels[ip], "last_sat", 1)
            temp_actual = getattr(panels[ip], "last_temp", 4000)

            h_destino = estado_destino.get("h", 0)
            s_destino = estado_destino.get("s", 1)
            temp_destino = estado_destino.get("temp", 4000)

            if actual_on and not destino_on:
                # Fade out: SOLO bajar brillo en el modo actual
                tiempo_fade = fade_out_val
                fade_mode = modo_actual
                fade_h = h_actual
                fade_s = s_actual
                fade_temp = temp_actual
                fade_from_brillo = from_brillo
                fade_to_brillo = 0
            elif not actual_on and destino_on:
                # Fade in: sube brillo al destino en modo destino
                tiempo_fade = fade_in_val
                fade_mode = modo_destino
                fade_h = h_destino
                fade_s = s_destino
                fade_temp = temp_destino
                fade_from_brillo = 0
                fade_to_brillo = to_brillo
            elif actual_on and destino_on:
                # Cambio de escena (mantén modo destino)
                tiempo_fade = fade_in_val
                fade_mode = modo_destino
                fade_h = h_destino
                fade_s = s_destino
                fade_temp = temp_destino
                fade_from_brillo = from_brillo
                fade_to_brillo = to_brillo
            else:
                tiempo_fade = 0
                fade_mode = modo_destino
                fade_h = h_destino
                fade_s = s_destino
                fade_temp = temp_destino
                fade_from_brillo = from_brillo
                fade_to_brillo = to_brillo

            fade_tasks.append(
                fade_to(
                    ip, tiempo_fade, fade_from_brillo, fade_to_brillo,
                    fade_mode, fade_h, fade_s, fade_temp
                )
            )

            # Panel UI (sin tocar el botón de encendido)
            panels[ip].mode_var.set(fade_mode)
            panels[ip].last_mode = fade_mode
            panels[ip].last_brillo = fade_to_brillo
            if fade_mode == "colour":
                panels[ip].last_hue = fade_h
                panels[ip].last_sat = fade_s
            else:
                panels[ip].last_temp = fade_temp



        # Si nadie lanzó una nueva escena (token intacto), marcamos FIN
        if fade_token[0] == nuevo_token:
            set_estado_escena(f"Escena '{nombre_escena}' terminada", "#28a745")  # Verde
            try:
                root.event_generate("<<EscenaTerminada>>", when="tail")
            except Exception as e:
                print(f"[WARN] Al generar <<EscenaTerminada>>: {e}")
        else:
            # Otra escena se inició en el medio; no marcamos FIN para evitar confusión
            print("[INFO] Se inició otra escena antes de terminar esta; no marco FIN.")

        # Rehabilitar botón aplicar escena
        try:
            btn_cargar.config(state="normal")
        except Exception:
            pass


    def run_fade():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(apply_fade())
        except Exception as e:
            print(f"[WARN] Escena: {e}")
        finally:
            loop.close()

    threading.Thread(target=run_fade, daemon=True).start()

                        

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
        messagebox.showerror("Nombre duplicado", f"Ya existe una escena llamada '{nombre}'.\nPor favor elige otro nombre.")
        entry_escena.focus_set()
        entry_escena.selection_range(0, tk.END)
        return
    try:
        fade_in_val = float(fade_in_var.get())
    except Exception:
        fade_in_val = 0.0
    try:
        fade_out_val = float(fade_out_var.get())
    except Exception:
        fade_out_val = 0.0

    # Forzar fade a 0.0 si es un valor menor o igual a cero (por si hay -0.0, -1, etc.)
    if fade_in_val <= 0:
        fade_in_val = 0.0
    if fade_out_val <= 0:
        fade_out_val = 0.0

    exito = guardar_escena(nombre, fade_in_val, fade_out_val)
    if exito:
        actualizar_lista_escenas()
        entry_escena.delete(0, tk.END)
        
        
def actualizar_escena():
    sel = listbox_escenas.curselection()
    if not sel:
        messagebox.showwarning("Selecciona una escena", "Selecciona una escena para actualizar.")
        return
    escena = listbox_escenas.get(sel)
    escenas = load_escenas()
    if escena not in escenas["orden"]:
        messagebox.showerror("Error", "La escena no existe.")
        return
    try:
        fade_in_val = float(fade_in_var.get())
    except Exception:
        fade_in_val = 0.0
    try:
        fade_out_val = float(fade_out_var.get())
    except Exception:
        fade_out_val = 0.0

    escenas["datos"][escena]["fade_in"] = fade_in_val
    escenas["datos"][escena]["fade_out"] = fade_out_val

    # Ahora, guarda el estado actual de TODAS las lámparas
    for ip in LAMP_IPS:
        
        panel = panels[ip]
        estado = escenas["datos"][escena].get(ip, {})   
        if estado.get("state", "off") == "on" and estado.get("modo", "colour") == "colour":
            h = estado.get("h", 0)
            s = estado.get("s", 1)
            v = estado.get("brillo", 255) / 1000  # O adapta el rango según tu slider
            if hasattr(panel, "colorwheel_lamp"):
             panel.colorwheel_lamp.set_color(h, s, v)
        if selected_devices[ip].get():
            if panel.mode_var.get() == "colour":
                escenas["datos"][escena][ip] = {
                    "state": "on",
                    "modo": "colour",
                    "h": getattr(panel, "last_hue", 0),
                    "s": getattr(panel, "last_sat", 1),
                    "brillo": getattr(panel, "last_brillo", 255)
                }
            else:
                escenas["datos"][escena][ip] = {
                    "state": "on",
                    "modo": "white",
                    "brillo": getattr(panel, "last_brillo", 255),
                    "temp": getattr(panel, "last_temp", 4000)
                }
        else:
            escenas["datos"][escena][ip] = {"state": "off"}
    save_escenas(escenas)
    messagebox.showinfo("Actualizado", f"Todos los valores guardados en '{escena}'.")

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
    sel = listbox_escenas.curselection()
    if sel:
        escena = listbox_escenas.get(sel)
        escenas = load_escenas()
        aplicar_escena(escena)
        next_idx = sel[0] + 1
        if next_idx < listbox_escenas.size():
            listbox_escenas.selection_clear(0, tk.END)
            listbox_escenas.selection_set(next_idx)
            listbox_escenas.activate(next_idx)
            listbox_escenas.see(next_idx)
        else:
            listbox_escenas.selection_clear(0, tk.END)
            

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
btn_guardar = tk.Button(frame_right, text="Guardar escena", command=guardar, bg="#20bdec", fg="#fff", font=("Segoe UI", 11, "bold"))
btn_guardar.pack(fill="x", pady=(0, 4))

btn_actualizar = tk.Button(
    frame_right, text="Actualizar escena",
    command=actualizar_escena,
    bg="#f7b731", fg="#222",
    font=("Segoe UI", 11, "bold")
)
btn_actualizar.pack(fill="x", pady=(0, 4))


tk.Label(frame_right, text="Escenas guardadas:", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 11)).pack(anchor="w", pady=(8,2))
lista_escenas = tk.StringVar(value=[])
listbox_escenas = tk.Listbox(frame_right, listvariable=lista_escenas, width=20, height=14, font=("Segoe UI", 11), bg="#17191c", fg="#fff", selectbackground="#20bdec", activestyle="dotbox")
listbox_escenas.pack(pady=(0,8), fill="x")
actualizar_lista_escenas()
listbox_escenas.bind("<<ListboxSelect>>", mostrar_fades_de_escena)

btn_up = tk.Button(frame_right, text="↑ Subir", command=mover_arriba, bg="#b9e3f7", fg="#202428", font=("Segoe UI", 11, "bold"))
btn_up.pack(fill="x", pady=(0,2))
btn_down = tk.Button(frame_right, text="↓ Bajar", command=mover_abajo, bg="#b9e3f7", fg="#202428", font=("Segoe UI", 11, "bold"))
btn_down.pack(fill="x", pady=(0,10))

btn_cargar = tk.Button(frame_right, text="Aplicar escena", command=cargar, bg="#28ad7c", fg="#fff", font=("Segoe UI", 11, "bold"))
btn_cargar.pack(fill="x", pady=(0, 4))
btn_borrar = tk.Button(frame_right, text="Eliminar escena", command=borrar, bg="#db3434", fg="#fff", font=("Segoe UI", 11, "bold"))
btn_borrar.pack(fill="x", pady=(0, 12))


listbox_escenas.bind("<Return>", on_listbox_enter)
# CIERRE PANEL ESCENAS_________________________________________________________________________________________________________

root.after(300, refresh_lamp_status)# se toma un tiempo
root.mainloop()