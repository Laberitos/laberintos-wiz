# Laberintos WiZ

Tablero de control de luces para el proyecto Laberintos. Permite controlar lamparas WiZ, organizar el espacio escenico, guardar escenas, ejecutar efectos y disparar acciones por MIDI.

## Requisitos

- Windows 10/11
- Python 3.11.16 (version validada para este proyecto)
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

## Flujo de versiones

- `dev`: rama de trabajo y pruebas. El desarrollo nuevo se guarda aqui.
- `main`: version estable para las computadoras que operan el show.

El responsable del desarrollo trabaja siempre en `dev`:

1. Ejecuta `Publicar_DEV.cmd` para guardar y subir el trabajo a GitHub.
2. Prueba el tablero desde `dev`.
3. Cuando la version este validada, ejecuta `Crear_VERSION_ESTABLE.cmd`.

El segundo equipo trabaja siempre en `main`. Para recibir una version estable:

1. Cierra el tablero.
2. Ejecuta `Actualizar_TABLERO.cmd`.
3. Abre nuevamente el tablero.

El actualizador conserva los archivos locales ignorados por Git, como las IP de
las lamparas. Si encuentra otros cambios locales, los guarda temporalmente antes
de actualizar para evitar que se pierdan.

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
