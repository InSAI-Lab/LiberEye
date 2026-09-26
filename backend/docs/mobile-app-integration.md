# Mobile integration

The release phone app relays camera frames for backend perception, then dispatches EPMC output actions through TTS and BLE. See [cloud deployment](cloud-deployment.md) to configure an HTTPS endpoint and a private bearer token.

`http://127.0.0.1:8080` addresses the device running the client. A physical phone needs the server's reachable hostname. Development credentials and private LAN addresses are not shipped.

## Requests

Send these headers on authenticated requests:

```http
Authorization: Bearer YOUR_PRIVATE_TOKEN
X-LiberEye-Session: RANDOM_NAVIGATION_SESSION_ID
```

Use a random session ID for each navigation session. Keep it across updates during that session. Missing IDs produce independent, stateless decisions.

Upload images with `POST /api/mobile/analyze-media` or glasses frames with `POST /api/glasses/frame`. The former uses multipart field `media`; the latter uses `frame`. JPEG and PNG are the recommended phone formats. Other supported extensions still require a working decoder. These multipart fields are optional:

- `target_query`: target name.
- `detail_request`: Boolean request for scene detail.
- `wrist_connected`: Boolean observed bracelet connection status.

For media uploads, `target_query` matches a normalized detector label, such as `cup`. Target position and confidence come from the matched detection. An unmatched query has an unknown position and zero confidence. `detected_texts` contains recognized OCR strings; an empty array indicates that no readable content was returned.

`POST /api/mobile/analyze-perception` accepts structured perception input as a normalized `PerceptionFrame` JSON object for controlled integrations and replay. Its `source`, `detail_request` and `wrist_connected` options are query parameters. The caller supplies observations from its configured perception pipeline.

Structured target observations must supply `target_confidence`, which defaults to zero. Provide `target_direction` and `target_distance_m` when those estimates are available.

```json
{
  "scene_type": "crossing",
  "traffic_light": "red",
  "traffic_confidence": 0.92,
  "user_intent": "cross",
  "sensor_health": "ok"
}
```

## Execute the admitted actions

Use `output_actions` as the execution contract:

- Execute a `tts` action's `message` only when `should_speak` is true. Respect its `interrupt` flag.
- Execute a `ble_haptic` action using its `command_bytes`. Do not serialize the `bracelet` display object to BLE.
- Display `ui_status` and device state accessibly.

`description_gate` controls optional scene detail. `action_instruction` remains eligible. Raw `scene_description`, `perception_evidence`, detected text and model status are evidence for display; do not append them to speech because that would bypass the gate. Do not speak `voice_message` a second time after executing a TTS action.

When `wrist_connected=false`, the backend omits the BLE action and adds a spoken warning. When the cloud is unavailable, announce that perception is unavailable and ask the user to stop and confirm their surroundings with their mobility aid. Do not manufacture a local prediction that the road is clear.

## Bracelet bytes

The release protocol is `libereye-wrist-v1`. One GATT write contains exactly three bytes: a pattern code followed by a big-endian duration in milliseconds. Code `0` stops output; codes `1` through `7` identify D1 through D4 and W1 through W3. A 3000 ms W3 command is `[7, 11, 184]`. Warning patterns play their complete finite sequence. Intensity is configured in firmware, not encoded as the duration.

Example output action fragment:

```json
{
  "type": "ble_haptic",
  "pattern": "W3",
  "protocol": "libereye-wrist-v1",
  "command_bytes": [7, 11, 184],
  "duration_ms": 3000
}
```

See the [firmware README](../../firmware/libereye_wrist/README.md) for service and characteristic identifiers, timing, acknowledgments and hardware constraints. Periodic D1 has `frequency_hz=0.5`. W cues have `frequency_hz=0` to denote finite sequences without one repetition rate. Normalized intensity values are 25 for D1/D2, 60 for D3/D4, and 100 for W1/W2/W3. The reference firmware maps these ordinal levels to signed RTP magnitudes 32, 76, and 127. `timing_profile.reference_intensity` and `reference_rtp` document that mapping; neither is measured acceleration or a duty cycle. W1, W2, and W3 complete after 750, 2900, and 2250 ms with the documented engineering gaps.

Check HTTP responses, BLE acknowledgments, audible speech and physical vibration separately during device integration.

Subscribe to TX before writing. A matching `ACK code ok` or `refresh` confirms acceptance; `busy` means a higher priority cue is still playing and the lower priority command was not queued. Refresh the latest admitted cue on the next scene update. A repeated active warning preserves phase and does not extend the sequence; a command arriving after `EVT code done` may start a new sequence. Send STOP when leaving monitoring or when the cloud action expires.

The Python `BleWristDriver` is a synchronous bench adapter: it holds its connection through ACK and `EVT done` or D lease `EVT timeout`, then disconnects. It raises errors on missing ACK, rejected commands, driver faults, or early disconnect. Closing BLE immediately after a successful write would stop the firmware before completing the cue. The mobile app instead owns a persistent connection and may preempt or refresh playback while the bench call is waiting.
