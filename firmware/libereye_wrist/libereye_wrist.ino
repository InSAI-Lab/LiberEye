#include <bluefruit.h>
#include <Wire.h>
#include <Adafruit_DRV2605.h>
#include <FreeRTOS.h>
#include <queue.h>
#include <task.h>
#include "board_config.h"
#include "haptic_engine.h"

#if !defined(ARDUINO_NRF52840_FEATHER)
#error "This reference build targets Adafruit Feather nRF52840 Express only."
#endif

// Preserve NUS UUIDs and individual GATT write boundaries. BLEUart's byte FIFO
// cannot reject truncated or concatenated commands safely.
BLEService service("6E400001-B5A3-F393-E0A9-E50E24DCCA9E");
BLECharacteristic rx("6E400002-B5A3-F393-E0A9-E50E24DCCA9E");
BLECharacteristic tx("6E400003-B5A3-F393-E0A9-E50E24DCCA9E");
Adafruit_DRV2605 driver;
libereye::HapticEngine engine;

QueueHandle_t normalQueue;
QueueHandle_t urgentQueue;
QueueHandle_t statusQueue;
volatile uint32_t connectionEpoch = 0;
volatile bool disconnected = false;
volatile bool overflowed = false;
bool driverReady = false;
bool setupReady = false;
uint8_t lastAmplitude = 0;
uint32_t lastDriverAttempt = 0;
bool driverStarting = false;
uint32_t driverEnabledMs = 0;

// Notifications may wait inside the Bluefruit library. Keep them on a separate
// task, so TX congestion never blocks pulse timing or STOP/W3 reception.
void statusTask(void*) {
  StatusMessage message;
  while (true) {
    if (xQueueReceive(statusQueue, &message, portMAX_DELAY) != pdTRUE) continue;
    if (message.epoch == connectionEpoch && Bluefruit.connected() && tx.notifyEnabled()) {
      tx.notify(message.text, message.length);
    }
    if (Serial && Serial.availableForWrite() >= message.length) {
      Serial.write(message.text, message.length);
    }
  }
}

void status(const char* kind, uint8_t code, const char* outcome) {
  StatusMessage message{};
  const int size = snprintf(message.text, sizeof(message.text), "%s %u %s\n", kind, code, outcome);
  if (size <= 0 || size >= static_cast<int>(sizeof(message.text))) return;
  message.length = static_cast<uint8_t>(size);
  message.epoch = connectionEpoch;
  // Overload may drop a status; the phone's ACK timeout detects that condition.
  xQueueSend(statusQueue, &message, 0);
}

bool writeRegister(uint8_t address, uint8_t value) {
  Wire.beginTransmission(kDriverAddress);
  Wire.write(address);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

void driverFault() {
  const uint8_t active = engine.active();
  digitalWrite(kDriverEnablePin, LOW);
  driverReady = false;
  driverStarting = false;
  lastAmplitude = 0;
  engine.stop();
  status("EVT", active, "driver");
}

bool applyMotor(uint32_t now) {
  const uint8_t amplitude = engine.amplitude(now);
  if (!driverReady) return amplitude == 0;
  if (amplitude == lastAmplitude) return true;
  if (!writeRegister(DRV2605_REG_RTPIN, amplitude)) { driverFault(); return false; }
  lastAmplitude = amplitude;
  return true;
}

void initializeDriver(uint32_t now) {
  if (!driverStarting) {
    lastDriverAttempt = driverEnabledMs = now;
    driverStarting = true;
    digitalWrite(kDriverEnablePin, HIGH);
    return;
  }
  // Allow the DRV2605L to leave hardware standby without blocking the loop.
  if (now - driverEnabledMs < 2) return;
  driverStarting = false;
  if (!driver.begin(&Wire)) { driverFault(); return; }
  driver.useERM();
  // Signed RTP magnitude 0..127 in real-time mode.
  const uint8_t control3 = (driver.readRegister8(DRV2605_REG_CONTROL3) | 0x20) & ~0x08;
  driverReady = writeRegister(DRV2605_REG_RTPIN, 0)
      && writeRegister(DRV2605_REG_CONTROL3, control3)
      && writeRegister(DRV2605_REG_MODE, DRV2605_MODE_REALTIME);
  if (!driverReady) { driverFault(); return; }
  lastAmplitude = 0;
  status("EVT", 0, "ready");
}

void onWrite(uint16_t, BLECharacteristic*, uint8_t* data, uint16_t length) {
  Packet packet = {{0, 0, 0}, static_cast<uint8_t>(length == 3 ? 3 : 0)};
  if (length == 3) memcpy(packet.data, data, 3);
  if (length == 3 && (data[0] == libereye::Stop || data[0] == libereye::W3)) {
    // Urgent writes cannot be starved by a full ordinary receive queue.
    xQueueOverwrite(urgentQueue, &packet);
  } else if (xQueueSend(normalQueue, &packet, 0) != pdTRUE) {
    overflowed = true;
  }
}

void onDisconnect(uint16_t, uint8_t) { ++connectionEpoch; disconnected = true; }

void expire(uint32_t now) {
  const uint8_t completed = engine.tick(now);
  applyMotor(now);
  if (completed) status("EVT", completed, completed >= libereye::W1 ? "done" : "timeout");
}

void execute(const Packet& packet, uint32_t now) {
  libereye::Command command;
  if (!libereye::decode(packet.data, packet.length, command)) {
    status("ACK", packet.length == 3 ? packet.data[0] : 255, "invalid");
    return;
  }
  if (command.pattern != libereye::Stop && !driverReady) {
    status("ACK", command.pattern, "driver");
    return;
  }
  expire(now);
  const libereye::Result result = engine.submit(command, now);
  if (!applyMotor(now)) { status("ACK", command.pattern, "driver"); return; }
  const char* results[] = {"ok", "refresh", "busy", "stopped", "invalid"};
  status("ACK", command.pattern, results[result]);
}

void setup() {
  pinMode(kDriverEnablePin, OUTPUT);
  digitalWrite(kDriverEnablePin, LOW);
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);
  normalQueue = xQueueCreate(8, sizeof(Packet));
  urgentQueue = xQueueCreate(1, sizeof(Packet));
  statusQueue = xQueueCreate(32, sizeof(StatusMessage));
  if (!normalQueue || !urgentQueue || !statusQueue) return;
  if (xTaskCreate(statusTask, "haptic-status", 512, nullptr, 1, nullptr) != pdPASS) return;
  Bluefruit.begin(1, 0);
  Bluefruit.setName("LiberEye-Haptic");
  Bluefruit.setTxPower(4);
  Bluefruit.Periph.setDisconnectCallback(onDisconnect);
  service.begin();
  tx.setProperties(CHR_PROPS_NOTIFY);
  tx.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  tx.setMaxLen(20);
  tx.begin();
  rx.setProperties(CHR_PROPS_WRITE | CHR_PROPS_WRITE_WO_RESP);
  rx.setPermission(SECMODE_NO_ACCESS, SECMODE_OPEN);
  rx.setMaxLen(20);
  rx.setWriteCallback(onWrite);
  rx.begin();
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(service);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);
  initializeDriver(millis());
  // EN pulldown disables the actuator during a watchdog reset.
  NRF_WDT->CONFIG = WDT_CONFIG_SLEEP_Run << WDT_CONFIG_SLEEP_Pos;
  NRF_WDT->CRV = 32768 * kWatchdogSeconds;
  NRF_WDT->RREN = WDT_RREN_RR0_Msk;
  NRF_WDT->TASKS_START = 1;
  setupReady = true;
}

void loop() {
  if (!setupReady) return;
  NRF_WDT->RR[0] = WDT_RR_RR_Reload;
  const uint32_t now = millis();
  if (disconnected || !Bluefruit.connected()) {
    const uint8_t previous = engine.active();
    engine.stop();
    applyMotor(now);
    xQueueReset(normalQueue);
    xQueueReset(urgentQueue);
    disconnected = false;
    if (previous) status("EVT", previous, "disconnect");
  }
  expire(now);
  Packet packet;
  if (xQueueReceive(urgentQueue, &packet, 0) == pdTRUE) {
    xQueueReset(normalQueue);
    execute(packet, now);
  } else if (xQueueReceive(normalQueue, &packet, 0) == pdTRUE) {
    execute(packet, now);
  }
  if (overflowed) { overflowed = false; status("ACK", 255, "overflow"); }
  if (!driverReady && (driverStarting || now - lastDriverAttempt >= kDriverRetryMs)) initializeDriver(now);
  // Arduino yields between loop calls. No pulse delays or serial waits.
}
