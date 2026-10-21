#include <Arduino.h>

// Arduino-ESP32 3.x. El servo debe alimentarse con la fuente externa de 5 V.
// La ESP32 y el servo deben compartir GND.
constexpr uint8_t SERVO_PIN = 18;
constexpr uint32_t SERVO_FREQUENCY_HZ = 50;
constexpr uint8_t SERVO_RESOLUTION_BITS = 16;
constexpr uint32_t SERVO_PERIOD_US = 20000;
constexpr uint32_t SERVO_MAX_DUTY = (1UL << SERVO_RESOLUTION_BITS) - 1;

constexpr uint16_t SAFE_MIN_US = 900;
constexpr uint16_t SAFE_MAX_US = 2100;
constexpr uint16_t START_US = 1500;
constexpr uint16_t STEP_US = 10;

uint16_t currentPulseUs = START_US;

uint32_t pulseUsToDuty(uint16_t pulseUs) {
  return static_cast<uint32_t>(
      (static_cast<uint64_t>(pulseUs) * SERVO_MAX_DUTY) / SERVO_PERIOD_US);
}

void writeServo(uint16_t pulseUs) {
  currentPulseUs = constrain(pulseUs, SAFE_MIN_US, SAFE_MAX_US);
  ledcWrite(SERVO_PIN, pulseUsToDuty(currentPulseUs));
  Serial.printf("Pulso actual: %u us\n", currentPulseUs);
}

void printHelp() {
  Serial.println();
  Serial.println("CALIBRACION SEGURA DEL SERVO");
  Serial.println("  +        aumenta 10 us");
  Serial.println("  -        disminuye 10 us");
  Serial.println("  p 1500   mueve al pulso indicado");
  Serial.println("  ?        muestra esta ayuda");
  Serial.println();
  Serial.println("Empieza sin la varilla conectada. Luego ajusta en pasos pequenos.");
}

void setup() {
  Serial.begin(115200);
  delay(500);

  if (!ledcAttach(SERVO_PIN, SERVO_FREQUENCY_HZ, SERVO_RESOLUTION_BITS)) {
    Serial.println("ERROR: no se pudo configurar PWM en GPIO 18.");
    while (true) {
      delay(1000);
    }
  }

  writeServo(START_US);
  printHelp();
}

void loop() {
  if (!Serial.available()) {
    return;
  }

  String command = Serial.readStringUntil('\n');
  command.trim();

  if (command == "+") {
    writeServo(currentPulseUs + STEP_US);
  } else if (command == "-") {
    writeServo(currentPulseUs - STEP_US);
  } else if (command.startsWith("p ")) {
    writeServo(static_cast<uint16_t>(command.substring(2).toInt()));
  } else if (command == "?") {
    printHelp();
  } else if (command.length() > 0) {
    Serial.println("Comando no reconocido. Escribe ? para ver la ayuda.");
  }
}
