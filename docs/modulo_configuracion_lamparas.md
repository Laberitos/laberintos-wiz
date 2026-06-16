# Modulo de configuracion de lamparas

## Objetivo

Permitir configurar las lamparas desde la interfaz grafica, sin editar archivos
manuales cada vez que se agrega, reemplaza o reorganiza una lampara.

## Flujo deseado

1. El usuario conecta una lampara a la red local dedicada.
2. El sistema detecta la lampara por IP.
3. La interfaz muestra la lampara detectada.
4. El usuario le asigna un nombre escenico, por ejemplo `L9`.
5. El usuario la asigna a un grupo por defecto: `efectos` o `atmosfera`.
6. El sistema guarda esa configuracion localmente.
7. Las escenas pueden usar esa informacion para ofrecer subconjuntos de
   lamparas disponibles por grupo.

## Informacion por lampara

Cada lampara configurada deberia guardar:

- `id_escenico`: nombre de puesta, por ejemplo `L9`.
- `ip`: IP local asignada por reserva DHCP.
- `alias`: nombre humano opcional.
- `grupo_default`: `efectos` o `atmosfera`.
- `activa`: indica si la lampara esta disponible para uso.
- `orden`: posicion visual en la interfaz.

Ejemplo conceptual:

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
    },
    {
      "id_escenico": "L17",
      "ip": "192.0.2.117",
      "alias": "L17",
      "grupo_default": "atmosfera",
      "activa": true,
      "orden": 9
    }
  ]
}
```

Las IPs del ejemplo son ficticias y usan el rango reservado para documentacion.

## Vista grafica propuesta

Una pestana o panel llamado `Configuracion` con:

- Boton `Detectar lamparas`.
- Tabla de lamparas detectadas.
- Columna de IP.
- Campo editable para nombre escenico.
- Campo editable para alias.
- Selector de grupo: `efectos` / `atmosfera`.
- Indicador online/offline.
- Boton para guardar configuracion.

## Reglas importantes

- La IP real no debe subirse a GitHub.
- La asignacion principal debe guardarse localmente en `lamps_config.json`.
- El sistema debe validar nombres duplicados: no puede haber dos lamparas con el
  mismo `id_escenico`.
- Si una lampara cambia de IP, la interfaz debe permitir actualizarla sin perder
  escenas vinculadas a su `id_escenico`.

## Decision recomendada

Usar `id_escenico` como identidad estable de puesta y no la IP.

La IP es una direccion tecnica de red. El nombre escenico, como `L9`, es la
identidad que deberian usar escenas, grupos y efectos. Asi, si en el futuro una
lampara cambia de IP o se reemplaza fisicamente, las escenas pueden seguir
apuntando a `L9`.
