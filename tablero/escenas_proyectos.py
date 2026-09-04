# escenas_proyectos.py
# -*- coding: utf-8 -*-

import os
import json
import shutil
from datetime import datetime
from tkinter import messagebox

ESCENAS_FILE = "escenas.json"
PROYECTOS_FILE = "proyectos.json"
LAMPS_CONFIG_FILE = "lamps_config.json"
BACKUP_DIR = "backups"
SCENE_FORMAT_VERSION = 2
PROJECT_FORMAT_VERSION = 2


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def backup_file(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"{base}_{stamp}.json")
    shutil.copy2(path, backup_path)
    return backup_path


def load_lamps_config_snapshot():
    if not os.path.exists(LAMPS_CONFIG_FILE):
        return None
    try:
        with open(LAMPS_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_ip_to_lamp_id():
    config = load_lamps_config_snapshot() or {}
    mapping = {}
    for lamp in config.get("lamparas", []):
        ip = str(lamp.get("ip", "")).strip()
        lamp_id = str(lamp.get("id_escenico", "")).strip()
        if ip and lamp_id:
            mapping[ip] = lamp_id
    return mapping


def compact_effects_state(effects_state):
    active = {}
    params = effects_state.get("_params", {}) if isinstance(effects_state, dict) else {}
    for name, enabled in (effects_state or {}).items():
        if name == "_params":
            continue
        if enabled:
            active[name] = {
                "enabled": True,
                "params": params.get(name, {}),
            }
    return {
        "version": 1,
        "active": active,
    }


def infer_scene_kind(LAMP_IPS, selected_devices, effects_layers):
    has_lights = any(selected_devices[ip].get() for ip in LAMP_IPS)
    has_effects = bool(effects_layers)
    if has_lights and has_effects:
        return "look_with_effect"
    if has_effects:
        return "effect_only"
    return "look"


def is_sequence_on_effect(effects_state):
    return bool(
        (effects_state or {}).get("secuencia_on")
        or (effects_state or {}).get("secuencia_on_overlay")
    )


def scene_brightness_for_sequence_on(panel, fallback=180):
    try:
        value = int(getattr(panel, "last_brillo", fallback))
    except Exception:
        value = fallback
    if value > 0:
        return max(1, min(255, value))

    try:
        value = int(panel.brillo_var.get())
    except Exception:
        value = fallback
    if value > 0:
        return max(1, min(255, value))

    return fallback


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
    backup_file(ESCENAS_FILE)
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
    effects_layers: list | None = None,
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

    ip_to_lamp_id = build_ip_to_lamp_id()
    timestamp = now_iso()
    effect_layers_data = effects_layers or []
    scene_kind = infer_scene_kind(LAMP_IPS, selected_devices, effect_layers_data)

    escenas["orden"].append(nombre_escena)
    escenas["datos"][nombre_escena] = {
        "tipo": "escena_luces",
        "version": SCENE_FORMAT_VERSION,
        "scene_kind": scene_kind,
        "nombre": nombre_escena,
        "created_at": timestamp,
        "updated_at": timestamp,
        "fade_in": float(fade_in_val),
        "fade_out": float(fade_out_val),
        "effects": effects_state,
        "effects_config": compact_effects_state(effects_state),
        "effects_layers": effect_layers_data,
        "lamparas": {},
    }

    for ip in LAMP_IPS:
        panel = panels[ip]

        if selected_devices[ip].get():
            brillo = panel.last_brillo
            if is_sequence_on_effect(effects_state):
                brillo = scene_brightness_for_sequence_on(panel)
            estado = {
                "state": "on",
                "modo": panel.last_mode,
                "brillo": brillo,
            }
            if is_sequence_on_effect(effects_state):
                estado["initial_state"] = "off"
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
            lamp_id = ip_to_lamp_id.get(ip, ip)
            escenas["datos"][nombre_escena]["lamparas"][lamp_id] = dict(estado, ip=ip)
        else:
            escenas["datos"][nombre_escena][ip] = {"state": "off"}
            lamp_id = ip_to_lamp_id.get(ip, ip)
            escenas["datos"][nombre_escena]["lamparas"][lamp_id] = {"ip": ip, "state": "off"}

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
    effects_layers: list | None = None,
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

    ip_to_lamp_id = build_ip_to_lamp_id()
    escena_data = escenas["datos"][nombre_escena]
    escena_data.setdefault("tipo", "escena_luces")
    escena_data.setdefault("version", SCENE_FORMAT_VERSION)
    escena_data.setdefault("nombre", nombre_escena)
    escena_data.setdefault("created_at", now_iso())
    escena_data["updated_at"] = now_iso()
    escena_data["lamparas"] = {}
    effect_layers_data = effects_layers or []

    escenas["datos"][nombre_escena]["fade_in"] = float(fade_in_val)
    escenas["datos"][nombre_escena]["fade_out"] = float(fade_out_val)
    escenas["datos"][nombre_escena]["effects"] = effects_state
    escenas["datos"][nombre_escena]["effects_config"] = compact_effects_state(effects_state)
    escenas["datos"][nombre_escena]["effects_layers"] = effect_layers_data
    escenas["datos"][nombre_escena]["scene_kind"] = infer_scene_kind(
        LAMP_IPS,
        selected_devices,
        effect_layers_data,
    )

    for ip in LAMP_IPS:
        panel = panels[ip]

        if selected_devices[ip].get():
            brillo = panel.last_brillo
            if is_sequence_on_effect(effects_state):
                brillo = scene_brightness_for_sequence_on(panel)
            estado = {
                "state": "on",
                "modo": panel.last_mode,
                "brillo": brillo,
            }
            if is_sequence_on_effect(effects_state):
                estado["initial_state"] = "off"
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
            lamp_id = ip_to_lamp_id.get(ip, ip)
            escenas["datos"][nombre_escena]["lamparas"][lamp_id] = dict(estado, ip=ip)
        else:
            escenas["datos"][nombre_escena][ip] = {"state": "off"}
            lamp_id = ip_to_lamp_id.get(ip, ip)
            escenas["datos"][nombre_escena]["lamparas"][lamp_id] = {"ip": ip, "state": "off"}


    save_escenas(escenas)
    return True


# ===================== ESTADO DE EFECTOS =====================

def get_effects_state(effect_vars: dict, effect_param_vars: dict | None = None) -> dict:
    """effect_vars: dict nombre -> tk.BooleanVar"""
    state = {name: var.get() for name, var in effect_vars.items()}
    if effect_param_vars:
        state["_params"] = {
            name: {param: var.get() for param, var in params.items()}
            for name, params in effect_param_vars.items()
        }
    return state


def apply_effects_state(effects: dict, effect_vars: dict, toggles: dict, effect_param_vars: dict | None = None):
    """
    Aplica un dict de efectos guardado:
      - effect_vars: nombre -> tk.BooleanVar
      - toggles: nombre -> función toggle_...
    """
    if not effects:
        return
    params_state = effects.get("_params", {})
    if effect_param_vars and params_state:
        for name, params in params_state.items():
            target_params = effect_param_vars.get(name, {})
            for param, value in params.items():
                var = target_params.get(param)
                if var is not None:
                    var.set(value)

    for name, target in effects.items():
        if name == "_params":
            continue
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
    backup_file(PROYECTOS_FILE)
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
        created_at = now_iso()
    else:
        created_at = proyectos["datos"].get(nombre_proyecto, {}).get("created_at", now_iso())

    proyectos["datos"][nombre_proyecto] = {
        "tipo": "proyecto_luces",
        "version": PROJECT_FORMAT_VERSION,
        "nombre": nombre_proyecto,
        "created_at": created_at,
        "updated_at": now_iso(),
        "modo_reproduccion": proyectos["datos"].get(nombre_proyecto, {}).get("modo_reproduccion", "manual"),
        "notas": proyectos["datos"].get(nombre_proyecto, {}).get("notas", ""),
        "escenas": list(escenas_orden),
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
        "version": 2,
        "nombre_proyecto": nombre_proyecto,
        "exported_at": now_iso(),
        "escenas_orden": escenas_proyecto,
        "escenas_datos": escenas_datos,
        "lamparas_config": load_lamps_config_snapshot(),
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
        "tipo": "proyecto_luces",
        "version": PROJECT_FORMAT_VERSION,
        "nombre": nombre_proyecto,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "modo_reproduccion": "manual",
        "notas": f"Importado desde {os.path.basename(filename)}",
        "escenas": escenas_orden,
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


def diagnosticar_escenas():
    """
    Devuelve informacion de mantenimiento sin modificar archivos.
    """
    escenas = load_escenas()
    orden = set(escenas.get("orden", []))
    datos = set(escenas.get("datos", {}).keys())
    return {
        "total_en_orden": len(orden),
        "total_datos": len(datos),
        "huerfanas": sorted(datos - orden),
        "faltantes": sorted(orden - datos),
    }


def limpiar_escenas_huerfanas():
    """
    Elimina escenas que existen en datos pero no en orden.
    Hace backup antes de guardar.
    """
    escenas = load_escenas()
    orden = set(escenas.get("orden", []))
    datos = escenas.get("datos", {})
    huerfanas = [nombre for nombre in list(datos.keys()) if nombre not in orden]
    for nombre in huerfanas:
        datos.pop(nombre, None)
    save_escenas(escenas)
    return huerfanas

