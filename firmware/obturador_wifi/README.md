# Obturador Wi-Fi para el Epson W42+

Este firmware controla mediante Wi-Fi un servo MG90S unido a la corredera
original A/V Mute del proyector.

## Requisitos

- ESP32 DevKit basada en ESP32-WROOM-32.
- Arduino IDE.
- Paquete de placas `esp32 by Espressif Systems`, version 3.x.
- Fuente externa regulada de 5 V / 2 A.
- Servo MG90S alimentado desde 5 V, nunca desde 3V3.

## Orden correcto

1. Montar el circuito sin conectar la varilla al proyector.
2. Cargar `calibracion_servo/calibracion_servo.ino`.
3. Abrir el monitor serie a 115200 baudios.
4. Encontrar lentamente los pulsos de apertura y cierre.
5. Copiar esos valores en `OPEN_PULSE_US` y `CLOSED_PULSE_US` dentro de
   `obturador_wifi/obturador_wifi.ino`.
6. Completar `WIFI_SSID` y `WIFI_PASSWORD` solo en la copia local.
7. Cargar el firmware final.

## Direcciones de prueba

- `http://obturador-laberintos.local/`
- `http://obturador-laberintos.local/estado`
- `POST http://obturador-laberintos.local/abrir`
- `POST http://obturador-laberintos.local/cerrar`

Si no puede conectarse al router, la placa crea la red
`Obturador-Laberintos`. Su direccion de emergencia es `http://192.168.4.1/`.

## Seguridad mecanica

- Calibrar primero con la varilla desconectada.
- No comenzar probando 0 y 180 grados.
- Avanzar en pasos pequenos y detenerse antes de que el servo fuerce el tope.
- Mantener libres las ventilaciones y controles del proyector.
- Incorporar una forma de desacoplar manualmente la varilla.
