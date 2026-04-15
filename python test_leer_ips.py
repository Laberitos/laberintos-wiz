file_path = "lamp_ips.txt"
print(f"Buscando: {file_path}")

try:
    with open(file_path, "r", encoding="utf-8") as f:
        lineas = f.readlines()
        print("Lineas crudas leídas:")
        for i, linea in enumerate(lineas):
            print(f"Línea {i+1}: {repr(linea)}")
        ips = [linea.strip() for linea in lineas if linea.strip()]
        print("IPs filtradas:", ips)
except Exception as e:
    print("ERROR leyendo el archivo:", e)
