def efecto_respiracion(
    send_lamp_color, LAMP_IPS, panels, selected_devices,
    brillo_min, brillo_max, velocidad_subida, velocidad_bajada, respirando_var, root
):
    import threading
    def ciclo(brillo_actual, direction):
        if not respirando_var.get():
            return
        activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
        colores = {ip: (getattr(panels[ip], "last_hue", 0), getattr(panels[ip], "last_sat", 1)) for ip in activos}

        threads = []
        for ip in activos:
            h, s = colores.get(ip, (0,1))
            t = threading.Thread(target=send_lamp_color, args=(ip, h, s, brillo_actual))
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=0.05)  # Espera muy poco para no retrasar el ciclo

        # Resto del ciclo igual que antes
        if direction == "up":
            if brillo_actual < brillo_max:
                root.after(int(velocidad_subida*100), ciclo, min(brillo_actual+60, brillo_max), "up")
            else:
                root.after(int(velocidad_bajada*100), ciclo, brillo_max, "down")
        else:
            if brillo_actual > brillo_min:
                root.after(int(velocidad_bajada*100), ciclo, max(brillo_actual-60, brillo_min), "down")
            else:
                root.after(int(velocidad_subida*100), ciclo, brillo_min, "up")
    ciclo(brillo_min, "up")


import threading
from tablero.helpers_wiz import apagar_lampara

import threading

def efecto_chase(
    send_lamp_color, LAMP_IPS, panels, selected_devices,
    brillo_on, tiempo_on_ms, chase_var, root
):
    def ciclo(idx):
        if not chase_var.get():
            activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
            for ip in activos:
                threading.Thread(target=apagar_lampara, args=(ip,)).start()
            return

        activos = [ip for ip in LAMP_IPS if selected_devices[ip].get()]
        if not activos:
            root.after(300, ciclo, idx)
            return
        if idx >= len(activos):
            idx = 0

        ip_on = activos[idx]
        h_on, s_on = getattr(panels[ip_on], "last_hue", 0), getattr(panels[ip_on], "last_sat", 1)

        # Apaga todas las demás antes de prender la nueva (por seguridad)
        for ip in activos:
            if ip != ip_on:
                threading.Thread(target=apagar_lampara, args=(ip,)).start()

        # Enciende solo la actual
        threading.Thread(target=send_lamp_color, args=(ip_on, h_on, s_on, brillo_on)).start()

        # Al terminar el tiempo_on_ms, apaga y pasa a la siguiente
        def apagar_y_seguir():
            threading.Thread(target=apagar_lampara, args=(ip_on,)).start()
            root.after(50, ciclo, idx + 1)  # Breve pausa entre bombillas (opcional)

        root.after(tiempo_on_ms, apagar_y_seguir)

    ciclo(0)
