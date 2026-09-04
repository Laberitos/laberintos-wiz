import json
import os


def get_root_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _root_file(filename):
    return os.path.join(get_root_path(), filename)


def load_lamps_config(filename="lamps_config.json"):
    """Carga la configuracion nueva de lamparas si existe."""
    file_path = _root_file(filename)
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as exc:
        print(f"[ERROR] No se pudo leer {filename}: {exc}")
        return None

    lamps = data.get("lamparas", [])
    if not isinstance(lamps, list):
        print(f"[ERROR] {filename} no contiene una lista 'lamparas' valida.")
        return None

    valid_lamps = []
    seen_ids = set()
    seen_ips = set()

    for index, lamp in enumerate(lamps, start=1):
        if not isinstance(lamp, dict):
            print(f"[WARN] Lampara invalida en posicion {index}: {lamp}")
            continue

        ip = str(lamp.get("ip", "")).strip()
        scenic_id = str(lamp.get("id_escenico", "")).strip()
        group = str(lamp.get("grupo_default", "")).strip()
        active = bool(lamp.get("activa", True))

        if not active:
            continue
        if not ip or not scenic_id:
            print(f"[WARN] Lampara incompleta en posicion {index}: {lamp}")
            continue
        if scenic_id in seen_ids:
            print(f"[WARN] id_escenico duplicado ignorado: {scenic_id}")
            continue
        if ip in seen_ips:
            print(f"[WARN] IP duplicada ignorada: {ip}")
            continue

        normalized = dict(lamp)
        normalized["ip"] = ip
        normalized["id_escenico"] = scenic_id
        normalized["grupo_default"] = group or "sin_grupo"
        normalized["alias"] = str(lamp.get("alias") or scenic_id).strip()
        normalized["orden"] = int(lamp.get("orden", index))

        valid_lamps.append(normalized)
        seen_ids.add(scenic_id)
        seen_ips.add(ip)

    valid_lamps.sort(key=lambda item: item.get("orden", 0))
    return {"version": data.get("version", 1), "lamparas": valid_lamps}


def save_lamps_config(config, filename="lamps_config.json"):
    file_path = _root_file(filename)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)


def load_lamp_ips(filename="lamp_ips.txt"):
    """Devuelve IPs desde lamps_config.json, con fallback a lamp_ips.txt."""
    lamps_config = load_lamps_config()
    if lamps_config:
        ips = [lamp["ip"] for lamp in lamps_config["lamparas"]]
        print(f"[CONFIG] IPs cargadas desde lamps_config.json: {ips}")
        return ips

    file_path = _root_file(filename)
    print(f"[DEBUG] Buscando lamp_ips.txt en: {file_path}")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            ips = [line.strip() for line in file if line.strip()]
            print(f"[DEBUG] IPs leidas: {ips}")
            return ips

    print(f"[ERROR] Archivo {file_path} no encontrado.")
    return []


def load_lamp_names(lamp_ips, filename="lamp_names.json"):
    """Carga nombres desde lamps_config.json y permite overrides locales."""
    lamps_config = load_lamps_config()
    names = {}

    if lamps_config:
        names = {
            lamp["ip"]: lamp.get("alias") or lamp["id_escenico"]
            for lamp in lamps_config["lamparas"]
        }

    file_path = _root_file(filename)
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                data = file.read().strip()
                if not data:
                    return names or {ip: f"Lampara {ip}" for ip in lamp_ips}

                saved_names = json.loads(data)
                for ip, name in saved_names.items():
                    names.setdefault(ip, name)
                return names
        except Exception:
            return names or {ip: f"Lampara {ip}" for ip in lamp_ips}

    return names or {ip: f"Lampara {ip}" for ip in lamp_ips}


def save_lamp_names(lamp_names, filename="lamp_names.json"):
    file_path = _root_file(filename)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(lamp_names, file, ensure_ascii=False, indent=2)


LAMPS_CONFIG = load_lamps_config()
LAMP_IPS = load_lamp_ips()
lamp_names = load_lamp_names(LAMP_IPS)
