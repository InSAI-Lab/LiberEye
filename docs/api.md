# API and device contract

Every `/api/*` request uses `Authorization: Bearer <token>`. All users of a research deployment share the configured server token. This is not an account-management service. Stateful callers also send `X-LiberEye-Session: <random-navigation-session-id>`, restricted to 1 to 128 letters, digits, underscore or ASCII hyphen. Omit it for independent stateless requests.

| Route | Input | Output |
| --- | --- | --- |
| `GET /health` | None | Liveness, model mode, counts without internal model errors |
| `GET /ready` | Auth | Readiness, 503 if required models are unavailable |
| `POST /api/mobile/analyze-perception` | PerceptionFrame JSON | EPMC mobile plan |
| `POST /api/epmc/analyze-perception` | Same JSON | Same implementation and plan |
| `POST /api/mobile/analyze-media` | Multipart `media` | EPMC mobile plan |
| `POST /api/glasses/frame` | Multipart `frame` | Same plan with this upload marked as glasses source |
| `POST /api/live` | PerceptionFrame JSON | Full EPMC AssistancePlan |
| `POST /api/analyze-media` | Multipart `media` | Full plan plus evidence |
| `GET /api/epmc/metrics` | Session header | Per-session counts and software timing |

`detail_request` defaults to false. `wrist_connected` defaults to true. For structured mobile input, send them as query parameters; for media input, send them as multipart form fields. A detail request cannot override an urgent description block. `target_query` is an optional media form field. OpenAPI at `/docs` gives the complete field schema.

Phones execute `output_actions` in order. A `ble_haptic` action precedes TTS. `command_bytes` contains `[pattern, duration_high, duration_low]`, using unsigned big-endian milliseconds. Pattern codes 1 to 4 are D1 to D4; 5 to 7 are W1 to W3; `[0,0,0]` stops the motor. `command` is a readable compatibility label, not BLE bytes. Warning cues are finite sequences, so `frequency_hz=0` indicates no periodic repetition rate.

Speak the authorized TTS action when `should_speak` is true. Never append `scene_description`, raw OCR or other evidence to speech. `description_gate`, `description_blocked`, `action_instruction` and `eligible_scene_description` expose the coordination decision. Evidence may remain available for screen display. No selected cue requires the phone to send STOP to clear any previous periodic cue. Disconnected wrist output may fall back to authorized concise speech.

BLE uses Nordic UART UUIDs `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` (service), `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` (RX write) and `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` (TX notify). Read the firmware README for ACK/NACK details. BLE write completion confirms transport only. Even firmware ACK does not measure motor onset or human perception.

401 means no token, 403 means a wrong token, 413 means body too large, 415 means unsupported extension, 422 means invalid perception or undecodable media, and 503 means unconfigured authentication, required models missing, capacity exhausted or inference busy. On 503, discard old camera work and retry with a fresh frame after backoff. Do not interpret transport failure as a clear path.
