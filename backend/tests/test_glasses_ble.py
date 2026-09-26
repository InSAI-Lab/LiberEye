import base64
import json

from libereye.glasses import GlassesBleParser, GlassesImageMessage, GlassesPerceptionMessage


def test_ble_parser_reads_perception_frame_across_chunks():
    parser = GlassesBleParser()
    packet = {
        "type": "perception",
        "payload": {
            "obstacle_distance_m": 1.4,
            "obstacle_confidence": 0.91,
            "sensor_health": "ok",
        },
    }
    raw = (json.dumps(packet) + "\n").encode("utf-8")

    assert parser.feed(raw[:10]) == []
    messages = parser.feed(raw[10:])

    assert len(messages) == 1
    assert isinstance(messages[0], GlassesPerceptionMessage)
    assert messages[0].frame.obstacle_distance_m == 1.4


def test_ble_parser_reassembles_jpeg_chunks():
    parser = GlassesBleParser()
    image = b"\xff\xd8fake-jpeg\xff\xd9"
    encoded = base64.b64encode(image).decode("ascii")

    packets = [
        {"type": "jpeg_start", "frame_id": "42", "target_query": "cup"},
        {"type": "jpeg_chunk", "frame_id": "42", "data": encoded[:8]},
        {"type": "jpeg_chunk", "frame_id": "42", "data": encoded[8:]},
        {"type": "jpeg_end", "frame_id": "42"},
    ]
    messages = []
    for packet in packets:
        messages.extend(parser.feed((json.dumps(packet) + "\n").encode("utf-8")))

    assert len(messages) == 1
    assert isinstance(messages[0], GlassesImageMessage)
    assert messages[0].image_bytes == image
    assert messages[0].target_query == "cup"
