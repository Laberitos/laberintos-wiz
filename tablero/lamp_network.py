import colorsys
import json
import select
import socket
import time


WIZ_UDP_PORT = 38899
DEFAULT_PROBE_TIMEOUT = 4.2
DEFAULT_RETRY_OFFSETS = (0.0, 0.7, 1.7, 3.1)


def _clamp_int(value, minimum, maximum, default=0):
    try:
        return max(minimum, min(maximum, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def pilot_result_to_info(result):
    if not isinstance(result, dict):
        return None

    dimming_percent = _clamp_int(result.get("dimming", 0), 0, 100)
    brightness = _clamp_int(dimming_percent * 255 / 100, 0, 255)
    is_on = bool(result.get("state", brightness > 0))
    temperature = _clamp_int(result.get("temp", 4000), 1000, 10000, 4000)
    has_rgb = all(key in result for key in ("r", "g", "b"))
    hue = 0.0
    saturation = 0.0

    if has_rgb:
        red = _clamp_int(result.get("r"), 0, 255)
        green = _clamp_int(result.get("g"), 0, 255)
        blue = _clamp_int(result.get("b"), 0, 255)
        hue, saturation, _value = colorsys.rgb_to_hsv(
            red / 255.0,
            green / 255.0,
            blue / 255.0,
        )
        hue *= 360.0

    return {
        "brightness": brightness,
        "is_on": is_on,
        "mode": "colour" if has_rgb else "white",
        "hue": hue,
        "sat": saturation,
        "temp": temperature,
        "mac": str(result.get("mac", "")).strip(),
        "rssi": result.get("rssi"),
    }


def probe_known_lamps(
    lamp_ips,
    timeout=DEFAULT_PROBE_TIMEOUT,
    retry_offsets=DEFAULT_RETRY_OFFSETS,
    port=WIZ_UDP_PORT,
):
    """Consulta getPilot por UDP sin cambiar el estado de ninguna lámpara."""
    ips = list(dict.fromkeys(str(ip).strip() for ip in lamp_ips if str(ip).strip()))
    results = {
        ip: {"online": False, "info": None}
        for ip in ips
    }
    if not ips:
        return results

    payload = json.dumps(
        {"method": "getPilot", "params": {}},
        separators=(",", ":"),
    ).encode("utf-8")
    pending = set(ips)
    started = time.monotonic()
    deadline = started + max(0.2, float(timeout))
    offsets = tuple(sorted(max(0.0, float(value)) for value in retry_offsets)) or (0.0,)
    retry_index = 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        while pending and time.monotonic() < deadline:
            now = time.monotonic()
            while retry_index < len(offsets) and now >= started + offsets[retry_index]:
                for ip in tuple(pending):
                    try:
                        sock.sendto(payload, (ip, int(port)))
                    except OSError:
                        pass
                retry_index += 1

            next_retry = (
                started + offsets[retry_index]
                if retry_index < len(offsets)
                else deadline
            )
            wait_time = max(0.0, min(0.25, deadline - now, next_retry - now))
            readable, _writable, _errors = select.select([sock], [], [], wait_time)
            if not readable:
                continue

            while True:
                try:
                    data, address = sock.recvfrom(65535)
                except BlockingIOError:
                    break
                except OSError:
                    break

                source_ip = str(address[0])
                if source_ip not in pending:
                    continue
                try:
                    response = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue

                info = pilot_result_to_info(response.get("result"))
                if info is None:
                    continue
                results[source_ip] = {"online": True, "info": info}
                pending.discard(source_ip)
    finally:
        sock.close()

    return results
