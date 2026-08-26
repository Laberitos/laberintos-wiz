# Laberintos WiZ

Tablero de control de luces para el proyecto Laberintos. Permite controlar lamparas WiZ, organizar el espacio escenico, guardar escenas, ejecutar efectos y disparar acciones por MIDI.

## Requisitos

- Windows 10/11
- Python 3.11 o superior
- Red local donde esten conectadas las lamparas WiZ
- Opcional: APC Mini / controlador MIDI
- Opcional: loopMIDI si se quiere disparar escenas desde Ableton

## Instalacion en una PC nueva

Abrir PowerShell en la carpeta donde se quiera descargar el proyecto y ejecutar:

```powershell
git clone https://github.com/Laberitos/laberintos-wiz.git
cd laberintos-wiz
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuracion de lamparas

El archivo real `lamp_names.json` no se sube a Git porque contiene IPs locales. Para preparar una PC nueva:

```powershell
copy lamp_names.example.json lamp_names.json
```

Luego editar `lamp_names.json` y reemplazar las IPs de ejemplo por las IPs reales de las lamparas en esa red.

Ejemplo:

```json
{
  "192.168.0.109": "L9",
  "192.168.0.110": "L10"
}
```

## Ejecutar el tablero

Con el entorno activado:

```powershell
python -m tablero.main
```

## Actualizar cambios desde Git

Cuando haya una nueva version subida al repositorio:

```powershell
git pull origin dev
pip install -r requirements.txt
python -m tablero.main
```

## Archivos que no se comparten

Estos archivos quedan fuera de Git porque son locales de cada computadora o generados automaticamente:

- `.venv/`
- `__pycache__/`
- `*.pyc`
- `lamp_names.json`
- `lamp_ips.txt`
- `lamp_groups.json`
- `lamps_config.json`
- `backups/`

Las escenas y proyectos principales si se versionan para que el show pueda viajar con el codigo.
