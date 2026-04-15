# escenas_proyectos.py
# -*- coding: utf-8 -*-

import os
import json
from tkinter import messagebox

ESCENAS_FILE = "escenas.json"
PROYECTOS_FILE = "proyectos.json"


# ============================= ESCENAS =============================

def load_escenas():
    """Carga el archivo de escenas en formato:
    {
      "orden": ["escena1", "escena2", ...],
      "datos": {
         "escena1": { ... },
         "escena2": { ... }
      }
    }
    """
    if os.path.exists(ESCENAS_FILE):
        with open(ESCENAS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "orden" not in data or "datos" not in data:
            # compatibilidad con formato viejo simple {nombre: {...}}
            orden = list(data.keys())
            datos = data
            return {"orden": orden, "datos": datos}
        return data
    return {"orden": [], "datos": {}}


def save_escenas(escenas):
    with open(ESCENAS_FILE, "w", encoding="utf-8") as f:
        json.dump(escenas, f, ensure_ascii=False, indent=2)


def guardar_escena(
    nombre_escena,
    fade_in_val,
    fade_out_val,
    LAMP_IPS,
    panels,
    selected_devices,
    effects_state: dict,
):
    """
    Guarda una escena completa:
      - fades
      - estado de efectos (effects_state)
      - estado por lámpara (modo, color, brillo, temp, on/off)
    """
    escenas = load_escenas()
    if nombre_escena in escenas["orden"]:
        return False

    escenas["orden"].append(nombre_escena)
    escenas["datos"][nombre_escena] = {
        "fade_in": float(fade_in_val),
        "fade_out": float(fade_out_val),
        "effects": effects_state,
    }

    usa_secuencia_on = effects_state.get("secuencia_on", False)

    for ip in LAMP_IPS:
        panel = panels[ip]

        # Si usa secuencia_on, entonces siempre guardamos state="off"
        if usa_secuencia_on:
            escena_lampara = {
                "state": "off",
                "modo": panel.last_mode,
                "brillo": panel.last_brillo,
            }

            if panel.last_mode == "colour":
                escena_lampara.update({
                    "h": panel.last_hue,
                    "s": panel.last_sat,
                })
            else:
                escena_lampara.update({
                    "temp": getattr(panel, "last_temp", 4000),
                })

            escenas["datos"][nombre_escena][ip] = escena_lampara
            continue  # saltamos al siguiente IP


        # --- COMPORTAMIENTO NORMAL (sin secuencia_on) ---
        if selected_devices[ip].get():
            estado = {
                "state": "on",
                "modo": panel.last_mode,
                "brillo": panel.last_brillo,
            }
            if panel.last_mode == "colour":
                estado.update({
                    "h": panel.last_hue,
                    "s": panel.last_sat,
                })
            else:
                estado.update({
                    "temp": getattr(panel, "last_temp", 4000),
                })
            escenas["datos"][nombre_escena][ip] = estado
        else:
            escenas["datos"][nombre_escena][ip] = {"state": "off"}

    save_escenas(escenas)
    return True


def actualizar_escena_completa(
    nombre_escena,
    fade_in_val,
    fade_out_val,
    LAMP_IPS,
    panels,
    selected_devices,
    effects_state: dict,
):
    """
    Actualiza TODOS los datos de una escena:
      - fades
      - efectos
      - estados por lámpara
    """
    escenas = load_escenas()
    if nombre_escena not in escenas["datos"]:
        messagebox.showerror("Escena no encontrada",
                             f"No existe la escena '{nombre_escena}'.")
        return False

    escenas["datos"][nombre_escena]["fade_in"] = float(fade_in_val)
    escenas["datos"][nombre_escena]["fade_out"] = float(fade_out_val)
    escenas["datos"][nombre_escena]["effects"] = effects_state

        # --- NUEVO: si la escena usa SECUENCIA_ON, entonces forzamos state="off" ---
    usa_secuencia_on = effects_state.get("secuencia_on", False)

    for ip in LAMP_IPS:
        panel = panels[ip]

        if usa_secuencia_on:
            # Guardamos siempre en OFF pero conservamos los valores
            estado = {
                "state": "off",
                "modo": panel.last_mode,
                "brillo": panel.last_brillo,
            }

            if panel.last_mode == "colour":
                estado.update({
                    "h": panel.last_hue,
                    "s": panel.last_sat,
                })
            else:
                estado.update({
                    "temp": getattr(panel, "last_temp", 4000),
                })

            escenas["datos"][nombre_escena][ip] = estado
            continue  # Pasamos al siguiente IP


        # --- MODO NORMAL (cuando NO hay secuencia_on) ---
        if selected_devices[ip].get():
            estado = {
                "state": "on",
                "modo": panel.last_mode,
                "brillo": panel.last_brillo,
            }
            if panel.last_mode == "colour":
                estado.update({
                    "h": panel.last_hue,
                    "s": panel.last_sat,
                })
            else:
                estado.update({
                    "temp": getattr(panel, "last_temp", 4000),
                })
            escenas["datos"][nombre_escena][ip] = estado
        else:
            escenas["datos"][nombre_escena][ip] = {"state": "off"}


    save_escenas(escenas)
    return True


# ===================== ESTADO DE EFECTOS =====================

def get_effects_state(effect_vars: dict) -> dict:
    """effect_vars: dict nombre -> tk.BooleanVar"""
    return {name: var.get() for name, var in effect_vars.items()}


def apply_effects_state(effects: dict, effect_vars: dict, toggles: dict):
    """
    Aplica un dict de efectos guardado:
      - effect_vars: nombre -> tk.BooleanVar
      - toggles: nombre -> función toggle_...
    """
    if not effects:
        return
    for name, target in effects.items():
        var = effect_vars.get(name)
        toggle = toggles.get(name)
        if var is None or toggle is None:
            continue
        if var.get() != target:
            var.set(target)
            toggle()


# ============================= PROYECTOS =============================

def load_proyectos():
    if os.path.exists(PROYECTOS_FILE):
        with open(PROYECTOS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "orden" not in data or "datos" not in data:
            # compat: dict simple {nombre: [escenas]}
            orden = list(data.keys())
            datos = {k: {"escenas": v} for k, v in data.items()}
            return {"orden": orden, "datos": datos}
        return data
    return {"orden": [], "datos": {}}


def save_proyectos(proyectos):
    with open(PROYECTOS_FILE, "w", encoding="utf-8") as f:
        json.dump(proyectos, f, ensure_ascii=False, indent=2)


def guardar_proyecto(nombre_proyecto, escenas_orden):
    """
    Guarda o ACTUALIZA un proyecto:
      - nombre_proyecto: string
      - escenas_orden: lista de nombres de escena en orden
    """
    proyectos = load_proyectos()

    if nombre_proyecto not in proyectos["orden"]:
        proyectos["orden"].append(nombre_proyecto)

    proyectos["datos"][nombre_proyecto] = {
        "escenas": list(escenas_orden)
    }
    save_proyectos(proyectos)
    return True


def obtener_escenas_de_proyecto(nombre_proyecto):
    proyectos = load_proyectos()
    if nombre_proyecto not in proyectos["datos"]:
        raise KeyError(f"No existe el proyecto '{nombre_proyecto}'")
    return proyectos["datos"][nombre_proyecto].get("escenas", [])


# ============================= OBRAS (exportar/importar) =============================

def exportar_proyecto_a_archivo(nombre_proyecto, filename):
    """
    Exporta una obra a un archivo JSON:
      - nombre_proyecto
      - escenas_orden (de ese proyecto)
      - escenas_datos (la configuración completa de esas escenas)
    """
    escenas = load_escenas()
    proyectos = load_proyectos()

    if nombre_proyecto not in proyectos["datos"]:
        raise KeyError(f"No existe el proyecto '{nombre_proyecto}'")

    escenas_proyecto = proyectos["datos"][nombre_proyecto].get("escenas", [])

    escenas_datos = {
        nombre: escenas["datos"][nombre]
        for nombre in escenas_proyecto
        if nombre in escenas["datos"]
    }

    data = {
        "tipo": "obra_luces",
        "version": 1,
        "nombre_proyecto": nombre_proyecto,
        "escenas_orden": escenas_proyecto,
        "escenas_datos": escenas_datos,
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def importar_obra_desde_archivo(filename):
    """
    Importa una obra desde un JSON exportado:
      - fusiona las escenas en escenas.json
      - crea un proyecto nuevo con ese conjunto
    Devuelve el nombre final del proyecto creado.
    """
    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("tipo") != "obra_luces":
        raise ValueError("El archivo no parece ser una obra exportada válida.")

    nombre_proyecto = data.get("nombre_proyecto", "Obra_importada")
    escenas_orden = data.get("escenas_orden", [])
    escenas_datos = data.get("escenas_datos", {})

    escenas = load_escenas()
    proyectos = load_proyectos()

    # Fusionar escenas nuevas
    for nombre, cfg in escenas_datos.items():
        escenas["datos"][nombre] = cfg
        if nombre not in escenas["orden"]:
            escenas["orden"].append(nombre)

    save_escenas(escenas)

    # Evitar colisión de nombre de proyecto
    original = nombre_proyecto
    i = 2
    while nombre_proyecto in proyectos["orden"]:
        nombre_proyecto = f"{original}_{i}"
        i += 1

    proyectos["orden"].append(nombre_proyecto)
    proyectos["datos"][nombre_proyecto] = {
        "escenas": escenas_orden
    }
    save_proyectos(proyectos)

    return nombre_proyecto


######################## LIMPIAR EL TEXTBOX DE PROYECTOS ####################

def borrar_proyecto(nombre_proyecto):
    """
    Elimina un proyecto del archivo proyectos.json.
    Devuelve True si lo borró, False si no existía.
    """
    proyectos = load_proyectos()
    if nombre_proyecto not in proyectos["orden"]:
        return False

    proyectos["orden"].remove(nombre_proyecto)
    proyectos["datos"].pop(nombre_proyecto, None)
    save_proyectos(proyectos)
    return True


def borrar_todos_los_proyectos():
    """
    Borra TODOS los proyectos registrados.
    """
    proyectos = {"orden": [], "datos": {}}
    save_proyectos(proyectos)
    return True

