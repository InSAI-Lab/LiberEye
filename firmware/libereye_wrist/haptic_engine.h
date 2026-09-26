#ifndef LIBEREYE_HAPTIC_ENGINE_H
#define LIBEREYE_HAPTIC_ENGINE_H

#include <stddef.h>
#include <stdint.h>

namespace libereye {

// Amplitudes and unreported gaps are engineering defaults. Table 1 reports
// ordinal intensity only, not calibrated actuator amplitudes.
constexpr uint8_t kLight = 32;
constexpr uint8_t kMedium = 76;
constexpr uint8_t kStrong = 127;
constexpr uint16_t kDefaultLeaseMs = 3000;
constexpr uint16_t kMaxLeaseMs = 8000;
constexpr uint16_t kGroupGapMs = 250;
constexpr uint16_t kW2PulseMs = 250;
constexpr uint16_t kW2PauseMs = 400;
constexpr uint16_t kW3LeadGapMs = 200;
constexpr uint16_t kRapidGapMs = 150;

enum Pattern : uint8_t { Stop = 0, D1, D2, D3, D4, W1, W2, W3 };
enum Result : uint8_t { Accepted, Refreshed, Busy, Stopped, Invalid };

struct Command { uint8_t pattern; uint16_t durationMs; };

inline bool decode(const uint8_t* bytes, size_t length, Command& command) {
  if (!bytes || length != 3 || bytes[0] > W3) return false;
  command.pattern = bytes[0];
  command.durationMs = (static_cast<uint16_t>(bytes[1]) << 8) | bytes[2];
  return true;
}

inline uint16_t warningDuration(uint8_t pattern) {
  if (pattern == W1) return 250 * 2 + kGroupGapMs;
  if (pattern == W2) return 6 * kW2PulseMs + 4 * kGroupGapMs + kW2PauseMs;
  if (pattern == W3) return 1000 + kW3LeadGapMs + 4 * 150 + 3 * kRapidGapMs;
  return 0;
}

inline uint8_t groupedAmplitude(uint32_t elapsed, uint8_t count,
                                uint16_t onMs, uint16_t gapMs) {
  const uint32_t period = onMs + gapMs;
  return elapsed / period < count && elapsed % period < onMs ? kStrong : 0;
}

inline uint8_t patternAmplitude(uint8_t pattern, uint32_t elapsed) {
  switch (pattern) {
    case D1: return elapsed % 2000 < 150 ? kLight : 0;
    case D2: return elapsed % 1000 < 150 ? kLight : 0;
    case D3: return elapsed % 500 < 200 ? kMedium : 0;
    case D4: return elapsed % 250 < 200 ? kMedium : 0;
    case W1: return groupedAmplitude(elapsed, 2, 250, kGroupGapMs);
    case W2: {
      const uint16_t groupMs = 3 * kW2PulseMs + 2 * kGroupGapMs;
      if (elapsed < groupMs) return groupedAmplitude(elapsed, 3, kW2PulseMs, kGroupGapMs);
      if (elapsed < groupMs + kW2PauseMs) return 0;
      return groupedAmplitude(elapsed - groupMs - kW2PauseMs, 3, kW2PulseMs, kGroupGapMs);
    }
    case W3:
      if (elapsed < 1000) return kStrong;
      if (elapsed < 1000 + kW3LeadGapMs) return 0;
      return groupedAmplitude(elapsed - 1000 - kW3LeadGapMs, 4, 150, kRapidGapMs);
    default: return 0;
  }
}

class HapticEngine {
 public:
  uint8_t active() const { return pattern_; }
  void stop() { pattern_ = Stop; }

  // Return the completed pattern once. Unsigned subtraction handles millis
  // rollover; sessions are far shorter than the rollover interval.
  uint8_t tick(uint32_t now) {
    if (pattern_ == Stop) return Stop;
    const bool expired = pattern_ >= W1
        ? now - startedMs_ >= warningDuration(pattern_)
        : now - refreshedMs_ >= leaseMs_;
    if (!expired) return Stop;
    const uint8_t ended = pattern_;
    stop();
    return ended;
  }

  Result submit(Command command, uint32_t now) {
    tick(now);
    if (command.pattern > W3) return Invalid;
    if (command.pattern == Stop) { stop(); return Stopped; }
    if (pattern_ > command.pattern) return Busy;
    const uint16_t requested = command.durationMs == 0 ? kDefaultLeaseMs : command.durationMs;
    const uint16_t lease = requested > kMaxLeaseMs ? kMaxLeaseMs : requested;
    if (pattern_ == command.pattern) {
      // Scene refreshes preserve phase. Warning refreshes do not extend or
      // restart the sequence, so rapid updates cannot suppress its tail.
      if (pattern_ < W1) { refreshedMs_ = now; leaseMs_ = lease; }
      return Refreshed;
    }
    pattern_ = command.pattern;
    startedMs_ = refreshedMs_ = now;
    leaseMs_ = lease;
    return Accepted;
  }

  uint8_t amplitude(uint32_t now) const {
    return patternAmplitude(pattern_, now - startedMs_);
  }

 private:
  uint8_t pattern_ = Stop;
  uint32_t startedMs_ = 0;
  uint32_t refreshedMs_ = 0;
  uint16_t leaseMs_ = kDefaultLeaseMs;
};

}  // namespace libereye
#endif
