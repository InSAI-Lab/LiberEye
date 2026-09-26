#include "../haptic_engine.h"
#include <cassert>
#include <cstdio>
#include <limits>
#include <vector>
using namespace libereye;

static std::vector<uint32_t> pulseStarts(uint8_t pattern, uint32_t duration) {
  HapticEngine engine;
  assert(engine.submit({pattern, static_cast<uint16_t>(duration)}, 0) == Accepted);
  std::vector<uint32_t> starts;
  uint8_t previous = 0;
  for (uint32_t now = 0; now < duration; ++now) {
    engine.tick(now);
    const uint8_t output = engine.amplitude(now);
    if (output && !previous) starts.push_back(now);
    previous = output;
  }
  return starts;
}

int main() {
  assert((pulseStarts(D1, 6000) == std::vector<uint32_t>{0, 2000, 4000}));
  assert((pulseStarts(D2, 3000) == std::vector<uint32_t>{0, 1000, 2000}));
  assert((pulseStarts(D3, 1500) == std::vector<uint32_t>{0, 500, 1000}));
  assert((pulseStarts(D4, 1000) == std::vector<uint32_t>{0, 250, 500, 750}));
  assert((pulseStarts(W1, 3000) == std::vector<uint32_t>{0, 500}));
  assert((pulseStarts(W2, 4000) == std::vector<uint32_t>{0, 500, 1000, 1650, 2150, 2650}));
  assert((pulseStarts(W3, 4000) == std::vector<uint32_t>{0, 1200, 1500, 1800, 2100}));
  for (uint8_t cue = D1; cue <= W3; ++cue) {
    HapticEngine e;
    e.submit({cue, 1}, 0);
    if (cue >= W1) {
      uint32_t onMs = 0;
      for (uint32_t t = 0; t < warningDuration(cue); ++t) {
        if (e.amplitude(t)) ++onMs;
      }
      assert(onMs == (cue == W1 ? 500U : cue == W2 ? 1500U : 1600U));
      assert(e.tick(warningDuration(cue) - 1) == Stop);
      assert(e.amplitude(warningDuration(cue) - 1) == kStrong);
      assert(e.tick(warningDuration(cue)) == cue);
      assert(e.amplitude(warningDuration(cue)) == 0);
    }
    e.stop();
    assert(e.active() == Stop && e.amplitude(0) == 0);
  }
  assert(patternAmplitude(D1, 149) == kLight && patternAmplitude(D1, 150) == 0);
  assert(patternAmplitude(D2, 149) == kLight && patternAmplitude(D2, 150) == 0);
  assert(patternAmplitude(D3, 199) == kMedium && patternAmplitude(D3, 200) == 0);
  assert(patternAmplitude(D4, 199) == kMedium && patternAmplitude(D4, 200) == 0);
  assert(patternAmplitude(W1, 249) == kStrong && patternAmplitude(W1, 250) == 0);
  assert(patternAmplitude(W2, 1249) == kStrong && patternAmplitude(W2, 1250) == 0);
  assert(patternAmplitude(W2, 1649) == 0 && patternAmplitude(W2, 1650) == kStrong);
  assert(patternAmplitude(W3, 999) == kStrong && patternAmplitude(W3, 1000) == 0);
  HapticEngine e;
  assert(e.submit({D1, 6000}, 0) == Accepted);
  assert(e.submit({W3, 1}, 10) == Accepted);
  assert(e.amplitude(10) == kStrong);
  assert(e.submit({W2, 0}, 20) == Busy);
  assert(e.submit({W3, 0}, 500) == Refreshed);
  assert(e.amplitude(1010) == 0);
  assert(e.tick(2260) == W3);
  assert(e.submit({D1, 3000}, 3000) == Accepted);
  assert(e.submit({D1, 3000}, 4000) == Refreshed);
  assert(e.amplitude(4000) == 0);
  assert(e.amplitude(5000) == kLight);
  assert(e.tick(6999) == Stop && e.active() == D1);
  assert(e.tick(7000) == D1 && e.amplitude(7000) == 0);
  e.submit({D4, 65535}, 0);
  assert(e.tick(7999) == Stop && e.tick(8000) == D4);
  e.submit({D1, 0}, 0);
  assert(e.tick(3000) == D1);
  e.submit({W3, 0}, 0);
  assert(e.submit({Stop, 0}, 10) == Stopped && e.amplitude(10) == 0);
  e.submit({D4, 0}, 0);
  assert(e.submit({8, 0}, 1) == Invalid && e.active() == D4);
  e.stop();
  const uint32_t base = std::numeric_limits<uint32_t>::max() - 999;
  e.submit({W3, 0}, base);
  assert(e.amplitude(base + 999) == kStrong);
  assert(e.amplitude(base + 1000) == 0);
  assert(e.tick(base + 2250) == W3);
  Command command{};
  const uint8_t good[] = {4, 0x0B, 0xB8};
  const uint8_t bad[] = {8, 0, 0};
  const uint8_t concat[] = {1, 0, 0, 2, 0, 0};
  assert(decode(good, 3, command) && command.pattern == D4 && command.durationMs == 3000);
  assert(!decode(nullptr, 3, command));
  assert(!decode(good, 2, command));
  assert(!decode(good, 1, command));
  assert(!decode(concat, 6, command));
  assert(!decode(bad, 3, command));
  std::puts("PASS: seven cue timings, full warnings, preemption, refresh, stop, leases, rollover, strict packets");
}
