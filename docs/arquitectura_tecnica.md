# Arquitectura tecnica - Proyecto Laberintos

## Proposito

Sistema de luces programable para la puesta luminica del Proyecto Laberintos.
El sistema debe permitir crear, guardar y ejecutar escenas, combinando estados
fijos de lamparas con efectos dinamicos integrados.

## Concepto escenico

Cada escena puede estar formada por dos capas principales:

- Capa de atmosfera: lamparas que sostienen el clima luminico general.
- Capa de efectos: lamparas destinadas a cambios constantes, movimientos,
  secuencias y comportamientos dinamicos.

La organizacion recomendada es mixta: cada lampara puede tener un rol por
defecto, pero una escena puede redefinir temporalmente ese rol si la puesta lo
necesita.

## Grupos iniciales de lamparas

Distribucion inicial definida para la puesta:

- Grupo de efectos: L9, L10, L11, L12, L13, L14, L15 y L16.
- Grupo de atmosfera: L17, L18, L19 y L20.

Esta separacion es el punto de partida. A futuro, el sistema debe permitir
incorporar mas lamparas a cada grupo o redefinir los grupos por escena.

Importante: los grupos funcionan como conjuntos disponibles, no como bloques
obligatorios. Cada escena debe poder elegir subconjuntos dentro de cada grupo.
Por ejemplo, una escena puede usar solo L9 y L10 para un efecto, mientras L11 a
L16 quedan fuera de ese comportamiento. Lo mismo aplica para la capa de
atmosfera: una escena puede usar solo algunas lamparas atmosfericas si la puesta
lo requiere.

## Hardware de iluminacion

- Lamparas: Philips 60 W, 806 lumen, rosca E27.
- Capacidades: color RGB y luz blanca.
- Cantidad prevista: 12 lamparas.
- Identificacion escenica actual: L9 a L20.
- Firmware observado: versiones 1.35.0, 1.30.4.0 y 1.37.0.

Los datos sensibles de red, como IPs y MACs reales, no deben versionarse. La
lista local de IPs se mantiene en `lamp_ips.txt`, archivo ignorado por Git.

## Red local

- Router/modem dedicado: TP-Link AC1200.
- Uso previsto: red local dedicada para el sistema de luces.
- Distancia maxima estimada entre router y lamparas: 15 metros.
- Asignacion de red: reservas DHCP configuradas en el router para mantener una
  IP estable por lampara.

Recomendaciones operativas:

- Mantener las lamparas en una red Wi-Fi dedicada, con la menor cantidad posible
  de dispositivos ajenos.
- Priorizar estabilidad sobre velocidad: los comandos WiZ dependen de una red
  local consistente.
- Mantener las reservas DHCP actualizadas cada vez que se agregue, reemplace o
  renombre una lampara.

## Computadora de control

- Sistema operativo: Windows 11 Home.
- Arquitectura: 64 bits, procesador x64.
- Procesador: 12th Gen Intel Core i7-12650H, 2.30 GHz.
- Memoria RAM: 32 GB.

Esta computadora tiene recursos suficientes para ejecutar la interfaz, el
control MIDI, el envio de comandos WiZ y procesos de efectos simultaneos.

## Control MIDI

- Consola: Akai APC Mini.
- Uso previsto: disparo de escenas, activacion de efectos, controles maestros y
  retroalimentacion visual mediante LEDs.

## Lineamientos de diseno

- Una escena no debe limitarse a una foto estatica: puede incluir fades,
  secuencias, efectos y comportamientos temporales.
- Los efectos deben poder aplicarse principalmente sobre el grupo de lamparas de
  efecto, sin perturbar innecesariamente la capa de atmosfera.
- La ejecucion en vivo debe ser predecible: al disparar una escena, el sistema
  debe saber que efectos se detienen, cuales continuan y que lamparas quedan
  bajo control de la escena.
- La configuracion sensible de red debe vivir en archivos locales ignorados por
  Git.
- La configuracion de lamparas debe poder hacerse desde la interfaz grafica:
  detectar lamparas por IP, asignar nombre escenico y elegir grupo por defecto.

## Proximas decisiones tecnicas

- Definir el modulo grafico de configuracion de lamparas.
- Definir como una escena elige subconjuntos de lamparas dentro de cada grupo.
- Definir si una escena puede sobrescribir temporalmente los roles por defecto.
- Definir como se guarda una escena con dos capas: atmosfera y efectos.
- Definir reglas de conflicto: que ocurre si una escena nueva se dispara mientras
  un efecto sigue activo.
- Incorporar `lamps_config.json` al codigo como configuracion local de lamparas,
  nombres escenicos y grupos.
