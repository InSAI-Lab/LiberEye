# BLE glasses parser

`libereye.glasses.GlassesBleParser` accepts newline-delimited UTF-8 JSON messages for desktop transport tests. The packet format is defined by this parser and is not a verified PCPZ M02 Ultra firmware interface. Camera integration must use the device vendor's documented transport.

The deployed system relays camera images through the phone to the backend. The backend performs perception and selects feedback; the phone plays admitted speech and sends wrist commands. See [mobile integration](mobile-app-integration.md) for this flow.

## Perception packet

The desktop parser accepts a `PerceptionFrame` payload:

```json
{
  "type": "perception",
  "payload": {
    "obstacle_distance_m": 1.4,
    "obstacle_confidence": 0.91,
    "traffic_light": "unknown",
    "vehicle_approaching": false,
    "crowd_level": "low",
    "user_intent": "navigate",
    "sensor_health": "ok"
  }
}
```

End each packet with a newline. These values are test inputs, not measurements supplied by the camera firmware.

## JPEG packets

An image is assembled from Base64-encoded chunks identified by `frame_id`:

```json
{"type":"jpeg_start","frame_id":"42","target_query":"cup"}
{"type":"jpeg_chunk","frame_id":"42","data":"BASE64_CHUNK"}
{"type":"jpeg_end","frame_id":"42"}
```

`GlassesMessageProcessor` decodes the assembled image and runs the Python perception pipeline on the host. The iOS relay instead sends the image to `/api/mobile/analyze-media` and executes the returned feedback.

## Desktop test client

Install the backend with its `hardware` extra, then run from `backend/` with a compatible test peripheral's address and notification characteristic:

```bash
python scripts/run_ble_glasses.py \
  --address GLASSES_BLE_ADDRESS \
  --notify-characteristic CHARACTERISTIC_UUID
```

The client subscribes to notifications and prints the computed assistance plan.
