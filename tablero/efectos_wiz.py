# efectos_wiz.py optimizado
import asyncio
import random
import math
import colorsys
from pywizlight import PilotBuilder
from tablero.helpers_wiz import get_wiz, get_or_create_event_loop, safe_brightness

# almacenar tasks por nombre
_efectos_corriendo = {}  # nombre → (task, stop_event)


async def _send_rgb_to_ips(ips, rgb, brightness):
    brightness = safe_brightness(brightness)
    tasks = []
    for ip in ips:
        bulb = get_wiz(ip)
        tasks.append(bulb.turn_on(PilotBuilder(rgb=rgb, brightness=brightness)))
    await asyncio.gather(*tasks, return_exceptions=True)


# ===========================================================
# EFECTOS
# ===========================================================
async def efecto_fuego(ips, stop):
    while not stop.is_set():
        r = random.randint(220, 255)
        g = random.randint(80, 150)
        b = random.randint(0, 30)
        brillo = random.randint(100, 255)
        await _send_rgb_to_ips(ips, (r, g, b), brillo)
        await asyncio.sleep(random.uniform(0.15, 0.35))


async def efecto_mar(ips, stop):
    t = 0
    while not stop.is_set():
        h = 195 + math.sin(t) * 15
        r, g, b = colorsys.hsv_to_rgb(h/360, 0.6, 1)
        rgb = (int(r*255), int(g*255), int(b*255))
        await _send_rgb_to_ips(ips, rgb, 200)
        t += 0.15
        await asyncio.sleep(0.25)


async def efecto_arcoiris(ips, stop):
    h = 0
    while not stop.is_set():
        r, g, b = colorsys.hsv_to_rgb(h/360, 1, 1)
        rgb = (int(r*255), int(g*255), int(b*255))
        await _send_rgb_to_ips(ips, rgb, 220)
        h = (h + 10) % 360
        await asyncio.sleep(0.18)


async def efecto_vela(ips, stop):
    base = (255, 180, 90)
    while not stop.is_set():
        delta = random.randint(-15, 15)
        r = min(255, max(180, base[0] + delta))
        g = min(210, max(120, base[1] + delta))
        b = min(140, max(60, base[2] + delta))
        brillo = random.randint(50, 150)
        await _send_rgb_to_ips(ips, (r, g, b), brillo)
        await asyncio.sleep(random.uniform(0.25, 0.55))


async def efecto_atardecer(ips, stop):
    paleta = [
        ((255, 200, 120), 200),
        ((255, 160, 90), 180),
        ((240, 110, 70), 170),
        ((210, 80, 60), 160)
    ]
    i = 0
    while not stop.is_set():
        rgb, b = paleta[i]
        await _send_rgb_to_ips(ips, rgb, b)
        i = (i + 1) % len(paleta)
        await asyncio.sleep(1.2)


# ===========================================================
# START / STOP
# ===========================================================
def start_efecto(nombre, ips):
    loop = get_or_create_event_loop()

    # si ya existe, deténlo
    if nombre in _efectos_corriendo:
        stop_efecto(nombre)

    stop_event = asyncio.Event()

    async def runner():
        if nombre == "fuego":
            await efecto_fuego(ips, stop_event)
        elif nombre == "mar":
            await efecto_mar(ips, stop_event)
        elif nombre == "arcoiris":
            await efecto_arcoiris(ips, stop_event)
        elif nombre == "vela":
            await efecto_vela(ips, stop_event)
        elif nombre == "atardecer":
            await efecto_atardecer(ips, stop_event)
        else:
            print(f"[WARN] Efecto desconocido: {nombre}")

    task = loop.create_task(runner())
    _efectos_corriendo[nombre] = (task, stop_event)


def stop_efecto(nombre):
    if nombre in _efectos_corriendo:
        task, stop_event = _efectos_corriendo.pop(nombre)
        stop_event.set()



def efecto_golpe_de_tambor(
    send_lamp_color,
    get_lamp_state,
    restore_lamp_state,
    LAMP_IPS,
    selected_devices,
    root
):
    """
    Efecto de impacto 'Golpe de Tambor':
    Flash + caída + restauración del estado previo.
    """

    activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
    if not activos:
        return

    # Guardar estado previo de cada lámpara activa
    estados_previos = {}
    for ip in activos:
        estados_previos[ip] = get_lamp_state(ip)

    niveles = [255, 180, 120, 80, 40, 0]

    def paso(i):
        if i < len(niveles):
            brillo = niveles[i]

            for ip in activos:
                send_lamp_color(ip, 0, 0, brillo)

            root.after(40, lambda: paso(i + 1))

        else:
            # Restaurar estados originales
            for ip in activos:
                estado = estados_previos[ip]

                # DEBUG VALIOSO (esto sí funciona ahora)
                #print("[DEBUG ESTADO PREVIO]", ip, estado)

                # Si devuelve más de 3 valores los recortamos
                if isinstance(estado, (list, tuple)) and len(estado) >= 3:
                    h, s, b = estado[:3]
                elif isinstance(estado, dict):
                    h = estado.get("h", 0)
                    s = estado.get("s", 0)
                    b = estado.get("dimming", 0)
                else:
                    h, s, b = (0, 0, 0)

                send_lamp_color(ip, h, s, b)

    paso(0)

