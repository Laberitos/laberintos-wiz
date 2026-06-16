# Modelo de datos propuesto

## Objetivo

Definir una estructura clara para que el sistema pueda trabajar con lamparas,
grupos, escenas y efectos sin depender de decisiones dispersas dentro de la
interfaz.

## Archivos locales y ejemplos

Archivos locales no versionados:

- `lamp_ips.txt`: IPs reales de las lamparas.
- `lamp_names.json`: nombres reales asociados a cada IP.
- `lamps_config.json`: configuracion real de lamparas, IPs, nombres escenicos
  y grupos por defecto.

Archivos seguros versionables:

- `lamp_ips.example.txt`: ejemplo de lista de IPs con direcciones ficticias.
- `lamp_names.example.json`: ejemplo de nombres por IP.
- `lamps_config.example.json`: ejemplo completo de configuracion de lamparas.
- `lamp_groups.example.json`: ejemplo simple de grupos por nombre escenico.

Las IPs de ejemplo usan el rango `192.0.2.0/24`, reservado para documentacion.

## Lampara

Una lampara debe poder identificarse por:

- `id_escenico`: nombre usado en la puesta, por ejemplo `L9`.
- `ip`: direccion local real, cargada desde `lamp_ips.txt`.
- `nombre`: alias legible, cargado desde `lamp_names.json`.
- `rol_default`: `efectos` o `atmosfera`.
- `capacidades`: color RGB, blanco, dimmer.

Archivo recomendado para la nueva etapa:

```json
{
  "version": 1,
  "lamparas": [
    {
      "id_escenico": "L9",
      "ip": "192.0.2.109",
      "alias": "L9",
      "grupo_default": "efectos",
      "activa": true,
      "orden": 1
    }
  ]
}
```

## Grupos

Los grupos son conjuntos disponibles, no bloques obligatorios.

Grupo inicial de efectos:

- L9, L10, L11, L12, L13, L14, L15, L16.

Grupo inicial de atmosfera:

- L17, L18, L19, L20.

Cada escena puede seleccionar un subconjunto de cada grupo. Ejemplo: una escena
puede aplicar un efecto solo sobre L9 y L10, aunque el grupo completo de efectos
incluya L9 a L16.

## Escena

Una escena deberia guardar, como minimo:

- `nombre`: identificador visible de la escena.
- `fade_in`: tiempo de entrada.
- `fade_out`: tiempo de salida.
- `atmosfera`: estado base de las lamparas atmosfericas seleccionadas.
- `efectos`: efectos activos y lamparas participantes.
- `reglas`: comportamiento al entrar o salir de la escena.

Ejemplo conceptual:

```json
{
  "nombre": "Interior laberinto",
  "fade_in": 6.0,
  "fade_out": 3.0,
  "atmosfera": {
    "lamparas": ["L17", "L18"],
    "estado": {
      "modo": "colour",
      "h": 220,
      "s": 0.8,
      "brillo": 90
    }
  },
  "efectos": [
    {
      "tipo": "respiracion",
      "lamparas": ["L9", "L10"],
      "params": {
        "brillo_min": 20,
        "brillo_max": 180,
        "velocidad": 0.1
      }
    }
  ],
  "reglas": {
    "detener_efectos_previos": true,
    "restaurar_estado_al_salir": false
  }
}
```

## Regla clave

La escena debe decidir que lamparas participan y como participan. El grupo
define disponibilidad; la escena define seleccion.
