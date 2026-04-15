import tkinter as tk
import json
import colorsys
import asyncio
from pywizlight import wizlight, PilotBuilder
from tablero.real_colorwheel import RealColorWheel
from tablero.config import LAMP_IPS  # Tu lista de IPs


def map_slider_to_wiz_brightness(slider_value):
    return int(10 + (int(slider_value) - 1) * (255 - 10) / (1000 - 1))

def map_slider_to_wiz_temperature(slider_value):
    # Mapear 0-1000 (slider) a 2200-6500K (WiZ)
    return int(2200 + (int(slider_value) * (6500 - 2200) / 1000))

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

selected_devices = {ip: tk.BooleanVar(value=False) for ip in LAMP_IPS}
panels = {}

def send_lamp_color(ip, h, s, brillo_slider):
    r, g, b = colorsys.hsv_to_rgb(h/360.0, s, 1)
    r, g, b = int(round(r*255)), int(round(g*255)), int(round(b*255))
    brillo = map_slider_to_wiz_brightness(brillo_slider)
    print(f"[COLOR] {ip}: RGB=({r},{g},{b}), Brightness={brillo}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)))
        else:
            loop.run_until_complete(wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)))
    except RuntimeError:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(wizlight(ip).turn_on(PilotBuilder(rgb=(r, g, b), brightness=brillo)))
        new_loop.close()

def send_lamp_white(ip, brillo_slider, temp_slider):
    brillo = map_slider_to_wiz_brightness(brillo_slider)
    temp = map_slider_to_wiz_temperature(temp_slider)
    print(f"[BLANCO] {ip}: White Temp={temp}K, Brightness={brillo}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp)))
        else:
            loop.run_until_complete(wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp)))
    except RuntimeError:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(wizlight(ip).turn_on(PilotBuilder(brightness=brillo, colortemp=temp)))
        new_loop.close()


def send_off(ip):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(wizlight(ip).turn_off())
        else:
            loop.run_until_complete(wizlight(ip).turn_off())
    except RuntimeError:
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(wizlight(ip).turn_off())
        new_loop.close()

def update_name(ip, entry):
    lamp_names[ip] = entry.get()
    save_lamp_names(lamp_names)

# ---------- PANEL MAESTRO ----------
frame_maestro = tk.LabelFrame(root, text="Control Maestro", bg="#181b1e", fg="#20bdec",
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
        for ip in LAMP_IPS:
            if selected_devices[ip].get():
                panels[ip].mode_var.set("colour")
                panels[ip].last_mode = "colour"
                panels[ip].last_hue = h
                panels[ip].last_sat = s
                panels[ip].last_brillo = maestro_brillo.get()
                send_lamp_color(ip, h, s, maestro_brillo.get())


def maestro_aplicar():
    modo = maestro_mode.get()
    h = maestro_hsv["h"]
    s = maestro_hsv["s"]
    brillo = maestro_brillo.get()
    temp = maestro_temp.get()
    for ip in LAMP_IPS:
        if selected_devices[ip].get():
            panels[ip].mode_var.set(modo)
            panels[ip].last_mode = modo
            if modo == "colour":
                panels[ip].last_hue = h
                panels[ip].last_sat = s
                panels[ip].last_brillo = brillo
                send_lamp_color(ip, h, s, brillo)
            else:
                panels[ip].last_brillo = brillo
                panels[ip].last_temp = temp
                send_lamp_white(ip, brillo, temp)

colorwheel_maestro = RealColorWheel(frame_maestro, radius=90, callback=maestro_on_color)
colorwheel_maestro.pack(side="left", padx=16)

controls_maestro = tk.Frame(frame_maestro, bg="#181b1e")
controls_maestro.pack(side="left", padx=18)

tk.Label(controls_maestro, text="Brillo", bg="#181b1e", fg="#fff").pack()
tk.Scale(controls_maestro, from_=1, to=1000, orient="horizontal", variable=maestro_brillo,
         length=260, bg="#181b1e", fg="#20bdec").pack()

tk.Label(controls_maestro, text="Temp (Blanco cálido–frío)", bg="#181b1e", fg="#f1c40f").pack()
tk.Scale(controls_maestro, from_=0, to=1000, orient="horizontal", variable=maestro_temp,
         length=240, bg="#181b1e", fg="#f1c40f").pack()

tk.Radiobutton(controls_maestro, text="Color", variable=maestro_mode, value="colour",
               bg="#181b1e", fg="#20bdec", selectcolor="#181b1e", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=2)
tk.Radiobutton(controls_maestro, text="Blanco", variable=maestro_mode, value="white",
               bg="#181b1e", fg="#f1c40f", selectcolor="#181b1e", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=2)

tk.Button(controls_maestro, text="Aplicar Maestro", command=maestro_aplicar,
          font=("Segoe UI", 13, "bold"), fg="#fff", bg="#20bdec", relief="raised", width=18).pack(pady=8)

# ---------- PANEL INDIVIDUAL POR LÁMPARA ----------
frame_lamps = tk.Frame(root, bg="#212529")
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

    tk.Label(panel, text="Temp (Blanco cálido–frío)", bg="#22292f", fg="#f1c40f").pack()
    tk.Scale(panel, from_=0, to=1000, orient="horizontal", variable=temp_var,
             command=lambda v, ip=ip, panel=panel: (
                 setattr(panel, "last_temp", int(v)),
                 send_lamp_white(ip, getattr(panel, "last_brillo", 1000), int(v))
                 ) if modo_var.get() == "white" and selected_devices[ip].get()
               else setattr(panel, "last_temp", int(v)),
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
frame_bottom = tk.Frame(root, bg="#181b1e")
frame_bottom.pack(fill="x", pady=18)

def apagar_todo():
    for ip in LAMP_IPS:
        selected_devices[ip].set(False)
        send_off(ip)
def encender_todo():
    for ip in LAMP_IPS:
        selected_devices[ip].set(True)
        panel = panels[ip]
        if panel.last_mode == "colour":
            send_lamp_color(ip, getattr(panel, "last_hue", 0), getattr(panel, "last_sat", 1), getattr(panel, "last_brillo", 1000))
        else:
            send_lamp_white(ip, getattr(panel, "last_brillo", 1000), getattr(panel, "last_temp", 500))

tk.Button(frame_bottom, text="Apagar Todo", command=apagar_todo,
          bg="#404040", fg="#fff", font=("Segoe UI", 12, "bold")).pack(side="left", padx=30)
tk.Button(frame_bottom, text="Encender Todo", command=encender_todo,
          bg="#20bdec", fg="#fff", font=("Segoe UI", 12, "bold")).pack(side="left", padx=20)

root.mainloop()
