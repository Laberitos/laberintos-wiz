# helpers_wiz.py optimizado
from pywizlight import wizlight, PilotBuilder
import colorsys
import asyncio


#VARIABLES GLOBALES
bulb_states = {}

# ===========================================================
# POOL GLOBAL DE LÁMPARAS — INSTANCIAS PERSISTENTES
# ===========================================================


WIZ_POOL = {}

def get_wiz(ip: str):
    """Devuelve una instancia persistente por IP, evitando crear wizlight(ip) repetidos."""
    
    if ip not in WIZ_POOL:
        WIZ_POOL[ip] = wizlight(ip)
    return WIZ_POOL[ip]



# ===========================================================
# EVENT LOOP SEGURO
# ===========================================================
def get_or_create_event_loop():
    """Devuelve un event loop activo y seguro, o crea uno nuevo."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


# ===========================================================
# UTILIDADES
# ===========================================================
def safe_brightness(val):
    """Brillo seguro para evitar fallback rojo de Wiz (<8)."""
    try:
        v = int(val)
    except:
        return 8
    return max(8, min(255, v))


# ===========================================================
# ACCIONES ASYNC SEGURAS
# ===========================================================
async def _send_color_async(ip, h, s, b):
    """Envia color RGB usando instancia persistente."""
    try:
        r, g, bv = colorsys.hsv_to_rgb(h / 360.0, s, 1)
        r = int(r * 255)
        g = int(g * 255)
        bv = int(bv * 255)

        brillo = safe_brightness(b)

        light = get_wiz(ip)
        pilot = PilotBuilder(rgb=(r, g, bv), brightness=brillo)
        await light.turn_on(pilot)

    except Exception as e:
        print(f"[send_color_async] Error en {ip}: {e}")


async def _turn_off_async(ip):
    """Apaga lámpara usando instancia persistente."""
    try:
        bulb = get_wiz(ip)
        await bulb.turn_off()
    except Exception as e:
        print(f"[turn_off_async] Error apagando {ip}: {e}")


# ===========================================================
# WRAPPERS SYNC PARA USO EN UI
# ===========================================================
def send_lamp_color(ip, h, s, b):
    """Enciende lámpara en modo color (sync wrapper)."""
    
   
    async def _do():
        await _send_color_async(ip, h, s, b)

    loop = get_or_create_event_loop()
    if loop.is_running():
        asyncio.run_coroutine_threadsafe(_do(), loop)
    else:
        loop.run_until_complete(_do())


def apagar_lampara(ip):
    """Apaga lámpara con wrapper sync."""
    async def _do():
        await _turn_off_async(ip)

    loop = get_or_create_event_loop()
    if loop.is_running():
        asyncio.run_coroutine_threadsafe(_do(), loop)
    else:
        loop.run_until_complete(_do())


# ===========================================================
# SEND WHITE
# ===========================================================
async def _send_white_async(ip, brillo, temp):
    try:
        brillo = safe_brightness(brillo)
        bulb = get_wiz(ip)
        pilot = PilotBuilder(brightness=brillo, colortemp=temp)
        await bulb.turn_on(pilot)
    except Exception as e:
        print(f"[send_white_async] Error {ip}: {e}")


def send_lamp_white(ip, brillo, temp):
    """Envío en blanco usando instancia persistente."""
    async def _do():
        await _send_white_async(ip, brillo, temp)

    loop = get_or_create_event_loop()
    if loop.is_running():
        asyncio.run_coroutine_threadsafe(_do(), loop)
    else:
        loop.run_until_complete(_do())

# ===========================================================
# FUNCIONES DE UTILIDAD PARA LA UI (NO WiZ)
# ===========================================================
escena_en_ejecucion = False

def bloquear_enter(event):
    """Evita que ENTER ejecute acciones mientras una escena está corriendo."""
    global escena_en_ejecucion
    if escena_en_ejecucion:
        return "break"
    
    
    
def get_lamp_state(ip):
    """
    Devuelve el estado actual (h, s, brillo) de una lámpara Wiz.
    """
    try:
        state = bulb_states[ip]  # tu dict global de estados
        return state["h"], state["s"], state["dimming"]
    except:
        return (0, 0, 0)


def restore_lamp_state(ip, estado, send_lamp_color):
    """
    Restaura un estado previo en la lámpara.
    """
    if estado:
        h, s, b = estado
        send_lamp_color(ip, h, s, b)
    