import math


TIMING_TIMED = "timed"
TIMING_CONTINUOUS = "continuous"
TIMING_INSTANT = "instant"


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _milliseconds(value, default=0.0):
    return max(0.0, _number(value, default))


def get_scene_timing(scene_data, lamp_count=0):
    """Return the expected timing without changing scene or lamp state."""
    scene_data = scene_data if isinstance(scene_data, dict) else {}
    scripted = scene_data.get("scripted_scene")
    scripted = scripted if isinstance(scripted, dict) else {}

    duration_ms = _milliseconds(scripted.get("duration_ms"))
    if duration_ms > 0:
        return {"kind": TIMING_TIMED, "seconds": duration_ms / 1000.0}

    planned_duration_ms = _milliseconds(scripted.get("planned_duration_ms"))
    if planned_duration_ms > 0:
        return {"kind": TIMING_TIMED, "seconds": planned_duration_ms / 1000.0}

    if scripted.get("type") == "bichos_flor_marchita":
        duration_ms = (
            _milliseconds(scripted.get("fade_in_ms", 5000))
            + _milliseconds(scripted.get("transition_ms", 90000))
            + _milliseconds(scripted.get("final_fade_ms", 2500))
        )
        return {"kind": TIMING_TIMED, "seconds": duration_ms / 1000.0}

    effects = scene_data.get("effects")
    effects = effects if isinstance(effects, dict) else {}
    active_effects = {
        name for name, enabled in effects.items()
        if name != "_params" and bool(enabled)
    }
    params = effects.get("_params")
    params = params if isinstance(params, dict) else {}
    lamp_count = max(1, int(_number(lamp_count, 1)))

    if "secuencia_off_overlay" in active_effects:
        config = params.get("secuencia_off_overlay", {})
        spacing = _milliseconds(config.get("tiempo_off_ms", 5000), 5000)
        fade = _milliseconds(config.get("fade_ms", 5000), 5000)
        seconds = (((lamp_count - 1) * spacing) + fade) / 1000.0
        return {"kind": TIMING_TIMED, "seconds": max(0.5, seconds)}

    for effect_name in ("secuencia_on_overlay", "secuencia_on"):
        if effect_name in active_effects:
            config = params.get(effect_name, {})
            spacing = _milliseconds(config.get("tiempo_on_ms", 500), 500)
            seconds = (lamp_count * spacing) / 1000.0
            return {"kind": TIMING_TIMED, "seconds": max(0.5, seconds)}

    if "transicion_color" in active_effects:
        config = params.get("transicion_color", {})
        duration_ms = _milliseconds(config.get("duracion_ms", 10000), 10000)
        return {"kind": TIMING_TIMED, "seconds": max(0.1, duration_ms / 1000.0)}

    if active_effects:
        return {"kind": TIMING_CONTINUOUS, "seconds": None}

    fade_seconds = max(
        _number(scene_data.get("fade_in")),
        _number(scene_data.get("fade_out")),
    )
    if fade_seconds > 0:
        return {"kind": TIMING_TIMED, "seconds": fade_seconds}

    return {"kind": TIMING_INSTANT, "seconds": 0.0}


def format_scene_duration(seconds):
    total = max(0, int(math.floor(_number(seconds) + 0.5)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
