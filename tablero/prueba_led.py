import rtmidi
import time

print("=== TEST COLORES PARA BOTÓN 107 ===")

# Abrir puerto correcto
m = rtmidi.MidiOut()
ports = m.get_ports()
print("Puertos disponibles:", ports)

# Normalmente APC MINI MK2 está en puerto 1
m.open_port(1)

note = 107

print("\nProbando colores del botón 107...\n")

for vel in range(0, 128):
    print(f"Velocity {vel} →", end=" ")
    m.send_message([0x90, note, vel])
    time.sleep(0.10)

# Apagar LED al final
m.send_message([0x90, note, 0])

print("\nFIN DEL TEST. Mira la consola para ver los valores notables.")
