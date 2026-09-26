#ifndef LIBEREYE_BOARD_CONFIG_H
#define LIBEREYE_BOARD_CONFIG_H

#include <stdint.h>

struct Packet { uint8_t data[3]; uint8_t length; };
struct StatusMessage { char text[21]; uint8_t length; uint32_t epoch; };

// Reference target: Adafruit Feather nRF52840 Express, DRV2605L with exposed controllable EN, 3 V ERM.
// EN needs a 10 kOhm pulldown to disable the driver during reset.
constexpr uint8_t kDriverEnablePin = 5;
constexpr uint8_t kDriverAddress = 0x5A;
constexpr uint32_t kDriverRetryMs = 3000;
constexpr uint32_t kWatchdogSeconds = 2;

#endif
