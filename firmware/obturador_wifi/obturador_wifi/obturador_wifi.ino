#include <Arduino.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <WiFi.h>

// No guardes la clave real del Wi-Fi en Git. Completa estos valores solamente
// en la copia que vayas a cargar en la placa.
constexpr char WIFI_SSID[] = "CAMBIAR_NOMBRE_WIFI";
constexpr char WIFI_PASSWORD[] = "CAMBIAR_CLAVE_WIFI";

constexpr char DEVICE_NAME[] = "obturador-laberintos";
constexpr char FALLBACK_AP_PASSWORD[] = "Laberintos2026";

constexpr uint8_t SERVO_PIN = 18;
constexpr uint8_t OPEN_BUTTON_PIN = 25;
constexpr uint8_t CLOSE_BUTTON_PIN = 26;
constexpr uint8_t STATUS_LED_PIN = 27;

constexpr uint32_t SERVO_FREQUENCY_HZ = 50;
constexpr uint8_t SERVO_RESOLUTION_BITS = 16;
constexpr uint32_t SERVO_PERIOD_US = 20000;
constexpr uint32_t SERVO_MAX_DUTY = (1UL << SERVO_RESOLUTION_BITS) - 1;

// REEMPLAZAR con los dos valores descubiertos usando calibracion_servo.ino.
constexpr uint16_t OPEN_PULSE_US = 1200;
constexpr uint16_t CLOSED_PULSE_US = 1800;

constexpr uint32_t SERVO_MOVE_TIME_MS = 800;
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;
constexpr uint32_t BUTTON_DEBOUNCE_MS = 40;

// La corredera original tiene retencion mecanica. Desactivar el PWM luego de
// mover reduce ruido, consumo y calentamiento del servo.
constexpr bool RELEASE_SERVO_AFTER_MOVE = true;

enum class ShutterState {
  Unknown,
  Open,
  Closed,
};

WebServer server(80);
ShutterState shutterState = ShutterState::Unknown;
bool servoAttached = false;

bool lastOpenReading = HIGH;
bool stableOpenState = HIGH;
uint32_t openChangedAt = 0;

bool lastCloseReading = HIGH;
bool stableCloseState = HIGH;
uint32_t closeChangedAt = 0;

uint32_t pulseUsToDuty(uint16_t pulseUs) {
  return static_cast<uint32_t>(
      (static_cast<uint64_t>(pulseUs) * SERVO_MAX_DUTY) / SERVO_PERIOD_US);
}

bool attachServo() {
  if (servoAttached) {
    return true;
  }

  servoAttached = ledcAttach(
      SERVO_PIN, SERVO_FREQUENCY_HZ, SERVO_RESOLUTION_BITS);
  return servoAttached;
}

void releaseServo() {
  if (!servoAttached || !RELEASE_SERVO_AFTER_MOVE) {
    return;
  }

  ledcDetach(SERVO_PIN);
  pinMode(SERVO_PIN, INPUT);
  servoAttached = false;
}

bool moveShutter(uint16_t pulseUs, ShutterState targetState) {
  if (!attachServo()) {
    Serial.println("ERROR: no se pudo activar el PWM del servo.");
    return false;
  }

  digitalWrite(STATUS_LED_PIN, HIGH);
  ledcWrite(SERVO_PIN, pulseUsToDuty(pulseUs));
  delay(SERVO_MOVE_TIME_MS);
  releaseServo();

  shutterState = targetState;
  digitalWrite(STATUS_LED_PIN, targetState == ShutterState::Closed ? HIGH : LOW);
  return true;
}

bool openShutter() {
  Serial.println("Abriendo obturador...");
  return moveShutter(OPEN_PULSE_US, ShutterState::Open);
}

bool closeShutter() {
  Serial.println("Cerrando obturador...");
  return moveShutter(CLOSED_PULSE_US, ShutterState::Closed);
}

const char* stateText() {
  switch (shutterState) {
    case ShutterState::Open:
      return "abierto";
    case ShutterState::Closed:
      return "cerrado";
    default:
      return "desconocido";
  }
}

void sendJsonStatus(int statusCode = 200) {
  String json = "{\"estado\":\"";
  json += stateText();
  json += "\",\"ip\":\"";
  json += WiFi.getMode() == WIFI_AP ? WiFi.softAPIP().toString() : WiFi.localIP().toString();
  json += "\",\"wifi_dbm\":";
  json += WiFi.getMode() == WIFI_AP ? "0" : String(WiFi.RSSI());
  json += "}";

  server.sendHeader("Cache-Control", "no-store");
  server.send(statusCode, "application/json", json);
}

void handleOpen() {
  sendJsonStatus(openShutter() ? 200 : 500);
}

void handleClose() {
  sendJsonStatus(closeShutter() ? 200 : 500);
}

void handleHome() {
  const char page[] PROGMEM = R"HTML(
<!doctype html>
<html lang="es">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Obturador Laberintos</title>
<style>
body{font-family:Arial;background:#151a1e;color:#fff;max-width:520px;margin:40px auto;padding:20px}
h1{color:#22bde8}.state{padding:14px;background:#222b31;margin:20px 0}
button{width:48%;padding:18px;border:0;font-weight:bold;font-size:18px;cursor:pointer}
.open{background:#28b76b}.close{background:#f0b52f}
</style>
<h1>Obturador Laberintos</h1>
<div class="state">Estado: <strong id="state">consultando...</strong></div>
<button class="open" onclick="send('/abrir')">ABRIR</button>
<button class="close" onclick="send('/cerrar')">CERRAR</button>
<script>
async function refresh(){const r=await fetch('/estado');const j=await r.json();state.textContent=j.estado}
async function send(path){await fetch(path,{method:'POST'});await refresh()}
refresh();setInterval(refresh,2000)
</script>
</html>
)HTML";

  server.send(200, "text/html", page);
}

void registerRoutes() {
  server.on("/", HTTP_GET, handleHome);
  server.on("/estado", HTTP_GET, []() { sendJsonStatus(); });
  server.on("/abrir", HTTP_GET, handleOpen);
  server.on("/abrir", HTTP_POST, handleOpen);
  server.on("/cerrar", HTTP_GET, handleClose);
  server.on("/cerrar", HTTP_POST, handleClose);
  server.onNotFound([]() {
    server.send(404, "application/json", "{\"error\":\"ruta no encontrada\"}");
  });
}

void startNetwork() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setHostname(DEVICE_NAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("Conectando a %s", WIFI_SSID);
  const uint32_t startedAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < WIFI_CONNECT_TIMEOUT_MS) {
    delay(300);
    Serial.print('.');
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("No se pudo conectar. Iniciando red de emergencia.");
    WiFi.mode(WIFI_AP);
    WiFi.softAP("Obturador-Laberintos", FALLBACK_AP_PASSWORD);
    Serial.print("IP de emergencia: ");
    Serial.println(WiFi.softAPIP());
  }

  if (MDNS.begin(DEVICE_NAME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("Direccion local: http://%s.local/\n", DEVICE_NAME);
  }
}

void updateButton(
    uint8_t pin,
    bool& lastReading,
    bool& stableState,
    uint32_t& changedAt,
    void (*pressedAction)()) {
  const bool reading = digitalRead(pin);

  if (reading != lastReading) {
    changedAt = millis();
    lastReading = reading;
  }

  if (millis() - changedAt < BUTTON_DEBOUNCE_MS || reading == stableState) {
    return;
  }

  stableState = reading;
  if (stableState == LOW) {
    pressedAction();
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(OPEN_BUTTON_PIN, INPUT_PULLUP);
  pinMode(CLOSE_BUTTON_PIN, INPUT_PULLUP);
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);

  startNetwork();
  registerRoutes();
  server.begin();

  // Estado seguro al arrancar. Ejecutar solamente despues de calibrar ambos
  // pulsos y confirmar que OPEN_PULSE_US abre sin forzar el mecanismo.
  openShutter();
  Serial.println("Servidor listo.");
}

void loop() {
  server.handleClient();

  updateButton(
      OPEN_BUTTON_PIN,
      lastOpenReading,
      stableOpenState,
      openChangedAt,
      []() { openShutter(); });

  updateButton(
      CLOSE_BUTTON_PIN,
      lastCloseReading,
      stableCloseState,
      closeChangedAt,
      []() { closeShutter(); });

  delay(2);
}
