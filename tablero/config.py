import os
import json

def get_root_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def load_lamp_ips(filename="lamp_ips.txt"):
    file_path = os.path.join(get_root_path(), filename)
    print(f"[DEBUG] Buscando lamp_ips.txt en: {file_path}")
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            ips = [line.strip() for line in f if line.strip()]
            print(f"[DEBUG] IPs leídas: {ips}")
            return ips
    else:
        print(f"[ERROR] Archivo {file_path} no encontrado.")
        return []

def load_lamp_names(lamp_ips, filename="lamp_names.json"):
    file_path = os.path.join(get_root_path(), filename)
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                data = file.read().strip()
                if not data:
                    return {ip: f"Lámpara {ip}" for ip in lamp_ips}
                return json.loads(data)
        except Exception:
            return {ip: f"Lámpara {ip}" for ip in lamp_ips}
    return {ip: f"Lámpara {ip}" for ip in lamp_ips}

def save_lamp_names(lamp_names, filename="lamp_names.json"):
    file_path = os.path.join(get_root_path(), filename)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(lamp_names, file, ensure_ascii=False, indent=2)

# Declarar después de definir las funciones:
LAMP_IPS = load_lamp_ips()
lamp_names = load_lamp_names(LAMP_IPS)
