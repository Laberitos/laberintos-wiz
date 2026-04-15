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

root = tk.Tk()
root.title("Control de Luces WiZ (Laberintos)")
root.geometry("1580x950")
root.configure(bg="#181b1e")

frame_main = tk.Frame(root, bg="#181b1e")
frame_main.pack(fill="both", expand=True)

frame_left = tk.Frame(frame_main, bg="#181b1e")
frame_left.pack(side="left", fill="both", expand=True)

frame_right = tk.Frame(frame_main, bg="#202428")
frame_right.pack(side="right", fill="y", padx=10, pady=18)

# -- Estado de lámparas online/offline --
lamp_status = {}
def refresh_lamp_status():
    online = get_online_ips()
    for ip, panel in panels.items():
        if ip in online:
            panel.config(bg="#182a1e")
            lamp_status[ip] = True
        else:
            panel.config(bg="#291a1a")
            lamp_status[ip] = False

# ------- Selección, paneles y envío -------
selected_devices = {ip: tk.BooleanVar(value=False) for ip in LAMP_IPS}
panels = {}

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
    if not lamp_status.get(ip, True):
        print(f"[WARN] Lámpara {ip} está OFFLINE, no se envía comando.")
        return
    brillo = map_slider_to_wiz_brightness(brillo_slider)
    r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
    r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)))
        else:
            loop.run_until_complete(wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)))
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

# -------- PANEL MAESTRO ----------
frame_maestro = tk.LabelFrame(frame_left, text="Control Maestro", bg="#181b1e", fg="#20bdec",
                             font=("Segoe UI", 16, "bold"), padx=10, pady=10)
frame_maestro.pack(fill="x", padx=30, pady=(20, 10))

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

colorwheel_maestro = RealColorWheel(frame_maestro, radius=90, callback=maestro_on_color)
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

tk.Radiobutton(controls_maestro, text="Color", variable=maestro_mode, value="colour",
               bg="#181b1e", fg="#20bdec", selectcolor="#181b1e", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=2)
tk.Radiobutton(controls_maestro, text="Blanco", variable=maestro_mode, value="white",
               bg="#181b1e", fg="#f1c40f", selectcolor="#181b1e", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=2)

tk.Button(controls_maestro, text="Aplicar Maestro",
    command=aplicar_maestro,
    font=("Segoe UI", 13, "bold"), fg="#fff", bg="#20bdec", relief="raised", width=18
).pack(pady=8)

tk.Button(controls_maestro, text="Refrescar Estado Lámparas", command=refresh_lamp_status,
    font=("Segoe UI", 10), fg="#fff", bg="#27ae60", relief="raised", width=22
).pack(pady=6)

# ---------- PANEL INDIVIDUAL POR LÁMPARA ----------
frame_lamps = tk.Frame(frame_left, bg="#212529")
frame_lamps.pack(fill="both", expand=True, padx=30, pady=20)

for ip in LAMP_IPS:
    
    panel = tk.LabelFrame(frame_lamps, text=lamp_names.get(ip, f"Lámpara {ip}"),
                         bg="#22292f", fg="#20bdec",
                         font=("Segoe UI", 12, "bold"), padx=8, pady=8, labelanchor="n")
    panel.pack(side="left", padx=20, pady=16, fill="y")

    entry = tk.Entry(panel, font=("Segoe UI", 11), width=18, bg="#111519", fg="#b9e3f7")
    entry.insert(0, lamp_names.get(ip, f"Lámpara {ip}"))
    entry.pack(pady=4)
    entry.bind("<FocusOut>", lambda e, ip=ip, entry=entry: update_name(ip, entry))

    modo_var = tk.StringVar(value="colour")
    panel.mode_var = modo_var
    panel.last_mode = "colour"

    tk.Checkbutton(panel, text="Encender", variable=selected_devices[ip],
                   command=lambda ip=ip: (
                       send_lamp_color(ip, getattr(panels[ip], "last_hue", 0), getattr(panels[ip], "last_sat", 1), getattr(panels[ip], "last_brillo", 1000))
                       if panels[ip].last_mode == "colour" and selected_devices[ip].get()
                       else send_lamp_white(ip, getattr(panels[ip], "last_brillo", 1000), getattr(panels[ip], "last_temp", 500))
                       if panels[ip].last_mode == "white" and selected_devices[ip].get()
                       else send_off(ip)
                   ),
                   fg="#20bdec", bg="#161a1d", selectcolor="#212529",
                   font=("Segoe UI", 11, "bold")).pack()

    brillo_var = tk.IntVar(value=1000)
    temp_var = tk.IntVar(value=500)

    def on_color(h, s, v, ip=ip, brillo_var=brillo_var, panel=panel):
        panel.last_hue = h
        panel.last_sat = s
        panel.last_brillo = brillo_var.get()
        panel.last_mode = modo_var.get()
        if modo_var.get() == "colour" and selected_devices[ip].get():
            send_lamp_color(ip, h, s, brillo_var.get())

    colorwheel_lamp = RealColorWheel(panel, radius=70, callback=on_color)
    colorwheel_lamp.pack(pady=8)
    panel.last_hue = 0
    panel.last_sat = 1
    panel.last_brillo = brillo_var.get()
    panel.last_temp = temp_var.get()

    tk.Label(panel, text="Brillo", bg="#22292f", fg="#20bdec").pack()
    tk.Scale(panel, from_=1, to=1000, orient="horizontal", variable=brillo_var,
             command=lambda v, ip=ip, panel=panel: (
                 setattr(panel, "last_brillo", int(v)),
                 send_lamp_color(ip, getattr(panel, "last_hue", 0), getattr(panel, "last_sat", 1), int(v))
                 ) if modo_var.get() == "colour" and selected_devices[ip].get()
               else (
                 setattr(panel, "last_brillo", int(v)),
                 send_lamp_white(ip, int(v), getattr(panel, "last_temp", 500))
                 ) if modo_var.get() == "white" and selected_devices[ip].get()
               else None,
             bg="#161a1d", fg="#20bdec", length=120).pack()

    def on_temp_panel(value, ip=ip, panel=panel):
        panel.last_temp = int(value)
        if panel.mode_var.get() == "white" and selected_devices[ip].get():
            send_lamp_white(ip, panel.last_brillo, panel.last_temp)

    tk.Label(panel, text="Temp (Blanco cálido–frío)", bg="#22292f", fg="#f1c40f").pack()
    tk.Scale(panel, from_=0, to=1000, orient="horizontal", variable=temp_var,
             command=lambda v, ip=ip, panel=panel: on_temp_panel(v, ip, panel),
             bg="#161a1d", fg="#f1c40f", length=120).pack()

    tk.Radiobutton(panel, text="Color", variable=modo_var, value="colour",
                   command=lambda ip=ip, panel=panel: (
                       setattr(panel, "last_mode", "colour"),
                       send_lamp_color(ip, getattr(panel, "last_hue", 0), getattr(panel, "last_sat", 1), getattr(panel, "last_brillo", 1000))
                       if selected_devices[ip].get() else None
                   ),
                   bg="#22292f", fg="#20bdec", selectcolor="#161a1d", font=("Segoe UI", 11)).pack(anchor="w", pady=2)
    tk.Radiobutton(panel, text="Blanco", variable=modo_var, value="white",
                   command=lambda ip=ip, panel=panel: (
                       setattr(panel, "last_mode", "white"),
                       send_lamp_white(ip, getattr(panel, "last_brillo", 1000), getattr(panel, "last_temp", 500))
                       if selected_devices[ip].get() else None
                   ),
                   bg="#22292f", fg="#f1c40f", selectcolor="#161a1d", font=("Segoe UI", 11)).pack(anchor="w", pady=2)

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
        # Guarda el estado ON/OFF real en el tablero
        if selected_devices[ip].get():
            panel = panels[ip]
            if panel.last_mode == "colour":
                escenas["datos"][nombre_escena][ip] = {
                    "state": "on",
                    "modo": "colour",
                    "h": panel.last_hue,
                    "s": panel.last_sat,
                    "brillo": panel.last_brillo
                }
            else:
                escenas["datos"][nombre_escena][ip] = {
                    "state": "on",
                    "modo": "white",
                    "brillo": panel.last_brillo,
                    "temp": panel.last_temp
                }
        else:
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

# --- FADE IN/OUT ---
import asyncio

async def fade_out(ip, tiempo, from_brillo, modo, h=0, s=1, temp=4000):
    if tiempo <= 0:
        try:
            await wizlight(ip).turn_off()
        except Exception as e:
            print(f"[WARN] Apagando {ip} al final del fade-out: {e}")
        return
    steps = 60
    interval = max(tiempo / steps, 0.01)
    for i in range(steps, 0, -1):
        brillo = safe_brightness((from_brillo * i) / steps)
        try:
            if modo == "colour":
                r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
                r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
                await wizlight(ip).turn_on(PilotBuilder(rgb=(r,g,b), brightness=brillo))
            else:
                await wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp))
        except Exception as e:
            print(f"[WARN] Fade-out {ip}: {e}")
        await asyncio.sleep(interval)
    try:
        await wizlight(ip).turn_off()
    except Exception as e:
        print(f"[WARN] Apagando {ip} al final del fade-out: {e}")

async def fade_in(ip, tiempo, to_brillo, modo, h=0, s=1, temp=4000):
    if tiempo <= 0:
        try:
            if modo == "colour":
                r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
                r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
                await wizlight(ip).turn_on(PilotBuilder(rgb=(r,g,b), brightness=safe_brightness(to_brillo)))
            else:
                await wizlight(ip).turn_on(PilotBuilder(brightness=safe_brightness(to_brillo), colortemp=temp))
        except Exception as e:
            print(f"[WARN] Fade-in {ip}: {e}")
        return
    steps = 60
    interval = max(tiempo / steps, 0.01)
    for i in range(1, steps+1):
        brillo = safe_brightness((to_brillo * i) / steps)
        try:
            if modo == "colour":
                r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
                r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
                await wizlight(ip).turn_on(PilotBuilder(rgb=(r,g,b), brightness=brillo))
            else:
                await wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp))
        except Exception as e:
            print(f"[WARN] Fade-in {ip}: {e}")
        await asyncio.sleep(interval)



def aplicar_escena(nombre_escena):
    escenas = load_escenas()
    datos = escenas["datos"]
    if nombre_escena not in datos:
        print(f"No existe la escena: {nombre_escena}")
        return
    escena = datos[nombre_escena]
    fade_in_val = escena.get("fade_in", 0.0)
    fade_out_val = escena.get("fade_out", 0.0)
    online_ips = [ip for ip in LAMP_IPS if lamp_status.get(ip, True) and ip in escena]

    async def apply_fade():
            # 1. Prepara las listas de on y off según la escena destino
            ips_to_off = []
            ips_to_on = []
            for ip in online_ips:
                if ip not in escena:
                    continue
                estado = escena[ip]
                if estado.get("state", "on") == "off":
                    ips_to_off.append(ip)
                else:
                    ips_to_on.append(ip)

            # 2. Apaga de inmediato las que deben estar apagadas
            for ip in ips_to_off:
                selected_devices[ip].set(False)
                try:
                    await wizlight(ip).turn_off()
                except Exception as e:
                    print(f"[WARN] Apagando {ip}: {e}")

            # 3. Fade out sólo para las que deben quedar encendidas
            fade_out_tasks = []
            for ip in ips_to_on:
                if ip not in escena:
                    continue
                estado_actual = get_lamp_state(ip)
                fade_out_tasks.append(
                    fade_out(
                        ip, fade_out_val, estado_actual.get("brillo", 255),
                        estado_actual.get("modo", "colour"),
                        estado_actual.get("h", 0), estado_actual.get("s", 1), estado_actual.get("temp", 4000)
                    )
                )
            await asyncio.gather(*fade_out_tasks, return_exceptions=True)

            # 4. Fade in sólo para las que deben quedar encendidas
            fade_in_tasks = []
            for ip in ips_to_on:
                if ip not in escena:
                    continue
                estado = escena[ip]
                selected_devices[ip].set(True)
                panels[ip].mode_var.set(estado["modo"])
                panels[ip].last_mode = estado["modo"]
                panels[ip].last_brillo = estado.get("brillo", 255)
                if estado["modo"] == "colour":
                    panels[ip].last_hue = estado.get("h", 0)
                    panels[ip].last_sat = estado.get("s", 1)
                    fade_in_tasks.append(
                        fade_in(
                            ip, fade_in_val, estado["brillo"], "colour",
                            estado["h"], estado["s"]
                        )
                    )
                else:
                    panels[ip].last_temp = estado.get("temp", 4000)
                    fade_in_tasks.append(
                        fade_in(
                            ip, fade_in_val, estado["brillo"], "white", 0, 1, estado["temp"]
                        )
                    )
            await asyncio.gather(*fade_in_tasks, return_exceptions=True)


    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(apply_fade())
        else:
            loop.run_until_complete(apply_fade())
    except Exception as e:
        print(f"[WARN] Escena: {e}")


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

# ==== UI ====
tk.Label(frame_right, text="ESCENAS", bg="#202428", fg="#20bdec",
         font=("Segoe UI", 16, "bold")).pack(pady=(6, 12))

tk.Label(frame_right, text="Nombre:", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 11)).pack(anchor="w")
entry_escena = tk.Entry(frame_right, font=("Segoe UI", 11), width=20, bg="#181b1e", fg="#b9e3f7")
entry_escena.pack(pady=(0,4))

# --- Sliders/entries de fade
frame_fades = tk.Frame(frame_right, bg="#202428")
frame_fades.pack(pady=(0,8))
tk.Label(frame_fades, text="Fade In (seg):", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="e")
fade_in_var = tk.DoubleVar(value=0.0)
tk.Label(frame_fades, text="Fade Out (seg):", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="e")
fade_out_var = tk.DoubleVar(value=0.0)

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


def cargar():
    sel = listbox_escenas.curselection()
    if sel:
        escena = listbox_escenas.get(sel)
        aplicar_escena(escena)

def on_listbox_enter(event):
    sel = listbox_escenas.curselection()
    if sel:
        escena = listbox_escenas.get(sel)
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
    delta = 0.0 if event.delta > 0 else -0.1
    value = var.get()
    try:
        newval = round(max(0.1, float(value) + delta), 2)
    except Exception:
        newval = 0.0
    var.set(newval)

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

tk.Label(frame_right, text="Escenas guardadas:", bg="#202428", fg="#b9e3f7", font=("Segoe UI", 11)).pack(anchor="w", pady=(8,2))
lista_escenas = tk.StringVar(value=[])
listbox_escenas = tk.Listbox(frame_right, listvariable=lista_escenas, width=20, height=14, font=("Segoe UI", 11), bg="#17191c", fg="#fff", selectbackground="#20bdec", activestyle="dotbox")
listbox_escenas.pack(pady=(0,8), fill="x")
actualizar_lista_escenas()

btn_up = tk.Button(frame_right, text="↑ Subir", command=mover_arriba, bg="#b9e3f7", fg="#202428", font=("Segoe UI", 11, "bold"))
btn_up.pack(fill="x", pady=(0,2))
btn_down = tk.Button(frame_right, text="↓ Bajar", command=mover_abajo, bg="#b9e3f7", fg="#202428", font=("Segoe UI", 11, "bold"))
btn_down.pack(fill="x", pady=(0,10))

btn_cargar = tk.Button(frame_right, text="Aplicar escena", command=cargar, bg="#28ad7c", fg="#fff", font=("Segoe UI", 11, "bold"))
btn_cargar.pack(fill="x", pady=(0, 4))
btn_borrar = tk.Button(frame_right, text="Eliminar escena", command=borrar, bg="#db3434", fg="#fff", font=("Segoe UI", 11, "bold"))
btn_borrar.pack(fill="x", pady=(0, 12))

listbox_escenas.bind("<Return>", on_listbox_enter)


refresh_lamp_status()
root.mainloop()
