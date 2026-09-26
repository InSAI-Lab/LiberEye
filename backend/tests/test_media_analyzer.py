from dataclasses import asdict
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from libereye.epmc import EPMCCoordinator
from libereye.media_analyzer import MediaAnalyzer
from libereye.mobility_coordinator import MobilityOrchestrator
from libereye.models import DetectedObject, SemanticRegion
from libereye.vision_backends import _regions_from_roboflow_predictions, _traffic_light_objects_from_roboflow_predictions


def test_media_analyzer_detects_synthetic_risk(tmp_path: Path):
    image = np.full((480, 640, 3), 210, dtype=np.uint8)
    cv2.rectangle(image, (260, 300), (390, 470), (35, 35, 35), -1)
    cv2.circle(image, (560, 80), 22, (0, 0, 255), -1)
    path = tmp_path / "street.png"
    cv2.imwrite(str(path), image)

    frame, evidence = MediaAnalyzer().analyze_file(path)

    assert frame.obstacle_distance_m is not None
    assert frame.depth_estimate is not None
    assert evidence["depth_estimate"]["center_depth_m"] is not None
    assert frame.semantic_regions
    assert evidence["semantic_regions"]
    assert evidence["glasses_description"].startswith("Glasses segmentation")
    assert evidence["vision_backend"]["active"] is False
    assert frame.traffic_light == "red"
    assert evidence["media_type"] == "image"


def test_media_analyzer_returns_scene_text_and_sign_candidates(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(image_to_string=lambda *args, **kwargs: "COFFEE SHOP"))
    image = np.full((480, 640, 3), 230, dtype=np.uint8)
    cv2.rectangle(image, (80, 40), (520, 120), (40, 90, 160), -1)
    cv2.putText(image, "COFFEE SHOP", (110, 92), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 3)
    path = tmp_path / "shop.png"
    cv2.imwrite(str(path), image)

    frame, evidence = MediaAnalyzer().analyze_file(path)

    assert frame.scene_description
    assert len(frame.scene_description.split()) <= 20
    assert "sign_candidates" in evidence
    assert "COFFEE SHOP" in evidence["sign_candidates"]


def test_media_analyzer_does_not_treat_red_sign_as_traffic_light(tmp_path: Path):
    image = np.full((480, 640, 3), 185, dtype=np.uint8)
    image[240:, :180] = (70, 130, 70)
    image[240:, 430:] = (55, 55, 55)
    cv2.rectangle(image, (70, 50), (420, 86), (0, 0, 220), -1)
    path = tmp_path / "sidewalk-with-red-sign.png"
    cv2.imwrite(str(path), image)

    frame, evidence = MediaAnalyzer().analyze_file(path)

    assert frame.traffic_light == "unknown"
    assert frame.vehicle_approaching is False
    assert any(region.label == "walkable_pavement" for region in frame.semantic_regions)
    assert evidence["media_type"] == "image"


def test_indoor_red_object_does_not_trigger_crossing_or_vehicle(tmp_path: Path):
    image = np.full((520, 760, 3), 205, dtype=np.uint8)
    cv2.rectangle(image, (0, 360), (760, 520), (145, 145, 145), -1)
    cv2.rectangle(image, (260, 135), (510, 455), (45, 45, 45), -1)
    cv2.circle(image, (330, 230), 28, (0, 0, 220), -1)
    path = tmp_path / "indoor-person-phone.jpg"
    cv2.imwrite(str(path), image)

    frame, evidence = MediaAnalyzer().analyze_file(path)

    assert frame.traffic_light == "unknown"
    assert frame.vehicle_approaching is False
    assert frame.scene_type != "crossing"
    assert evidence["traffic_light"] == "unknown"


def test_indoor_office_objects_suppress_crossing_risk(tmp_path: Path):
    image = np.full((520, 760, 3), 205, dtype=np.uint8)
    cv2.rectangle(image, (0, 340), (760, 520), (150, 150, 150), -1)
    path = tmp_path / "office-desk.jpg"
    cv2.imwrite(str(path), image)

    class OfficeBackend:
        def analyze(self, frame):
            return SimpleNamespace(
                detected_objects=[
                    DetectedObject("person", "center", 3.5, 0.78, [260, 120, 190, 280]),
                    DetectedObject("keyboard", "center", 1.2, 0.82, [150, 390, 460, 80]),
                    DetectedObject("monitor", "center", 2.6, 0.76, [120, 50, 520, 240]),
                ],
                semantic_regions=[
                    SemanticRegion("walkable_pavement", "center", 0.42, 0.8),
                    SemanticRegion("road_or_asphalt", "center", 0.18, 0.7),
                ],
            )

        def status(self):
            return {"active": True, "model": "fake-yolo", "models": ["fake-yolo"], "errors": []}

    frame, evidence = MediaAnalyzer(vision_backend=OfficeBackend()).analyze_file(path)

    assert frame.scene_type == "indoor"
    assert frame.scene_label == "Indoor office scene"
    assert frame.user_intent == "navigate"
    assert frame.traffic_light == "unknown"
    assert frame.vehicle_approaching is False
    assert evidence["scene_description"].startswith("Indoor office scene")


def test_hospital_text_classifies_indoor_service_scene(tmp_path: Path):
    image = np.full((420, 640, 3), 220, dtype=np.uint8)
    cv2.rectangle(image, (80, 60), (560, 130), (245, 245, 245), -1)
    path = tmp_path / "hospital-sign.jpg"
    cv2.imwrite(str(path), image)

    class HospitalBackend:
        def analyze(self, frame):
            return SimpleNamespace(
                detected_objects=[DetectedObject("person", "left", 4.0, 0.7, [60, 140, 80, 180])],
                semantic_regions=[SemanticRegion("walkable_pavement", "center", 0.36, 0.76)],
            )

        def status(self):
            return {"active": True, "model": "fake-yolo", "models": ["fake-yolo"], "errors": []}

    analyzer = MediaAnalyzer(vision_backend=HospitalBackend())
    frame, _ = analyzer._analyze_frame(image, target_query=None)

    frame, evidence = analyzer._analyze_frame(image, target_query=None)
    evidence["detected_texts"] = ["\u533b\u9662\u95e8\u8bca"]
    scene_type, scene_label = analyzer._classify_scene(
        target_query=None,
        tactile_blocked=False,
        obstacle_distance=None,
        traffic_light="unknown",
        crosswalk_score=0.0,
        semantic_regions=frame.semantic_regions,
        detected_objects=frame.detected_objects,
        detected_texts=["\u533b\u9662\u95e8\u8bca"],
        indoor_structure_score=0.0,
    )

    assert scene_type == "indoor"
    assert scene_label == "Hospital or public-service indoor scene"


def test_dense_blinds_do_not_trigger_crosswalk(tmp_path: Path):
    image = np.full((620, 760, 3), 150, dtype=np.uint8)
    for y in range(40, 570, 18):
        cv2.rectangle(image, (0, y), (760, y + 6), (225, 225, 225), -1)
        cv2.rectangle(image, (0, y + 7), (760, y + 11), (85, 85, 85), -1)
    path = tmp_path / "window-blinds.jpg"
    cv2.imwrite(str(path), image)

    frame, evidence = MediaAnalyzer().analyze_file(path)

    assert evidence["crosswalk_score"] == 0.0
    assert frame.scene_type in {"indoor", "unknown", "sidewalk"}
    assert frame.user_intent != "cross"


def test_media_analyzer_fuses_tactile_regions_with_model_outputs(tmp_path: Path):
    image = np.full((480, 640, 3), 180, dtype=np.uint8)
    cv2.rectangle(image, (292, 240), (326, 470), (0, 180, 220), -1)
    cv2.rectangle(image, (260, 320), (360, 370), (0, 180, 220), -1)
    path = tmp_path / "tactile-sidewalk.jpg"
    cv2.imwrite(str(path), image)

    class ModelOnlyBackend:
        def analyze(self, frame):
            return SimpleNamespace(
                detected_objects=[DetectedObject("bicycle", "center", 6.0, 0.78, [410, 90, 80, 80])],
                semantic_regions=[SemanticRegion("bicycle", "center", 0.01, 0.78)],
            )

        def status(self):
            return {"active": True, "model": "fake-yolo", "models": ["fake-yolo"], "errors": []}

    frame, evidence = MediaAnalyzer(vision_backend=ModelOnlyBackend()).analyze_file(path)

    assert any(region.label == "tactile_paving" for region in frame.semantic_regions)
    assert any(region["label"] == "tactile_paving" for region in evidence["semantic_regions"])
    assert "tactile_color_texture" in evidence["semantic_sources"]
    assert "tactile paving" in evidence["glasses_description"]


def test_media_analyzer_detects_pale_tactile_paving_under_shadow(tmp_path: Path):
    image = np.full((520, 760, 3), (150, 166, 156), dtype=np.uint8)
    cv2.rectangle(image, (220, 0), (270, 510), (96, 166, 206), -1)
    cv2.rectangle(image, (172, 230), (335, 285), (96, 166, 206), -1)
    cv2.rectangle(image, (520, 0), (750, 520), (120, 128, 128), -1)
    cv2.rectangle(image, (260, 335), (500, 470), (185, 190, 190), -1)
    path = tmp_path / "pale-tactile.jpg"
    cv2.imwrite(str(path), image)

    frame, evidence = MediaAnalyzer().analyze_file(path)

    tactile_regions = [region for region in frame.semantic_regions if region.label == "tactile_paving"]
    assert tactile_regions
    assert max(region.coverage for region in tactile_regions) >= 0.006
    assert "tactile paving" in evidence["glasses_description"]


def test_distant_bicycle_does_not_trigger_vehicle_emergency():
    analyzer = MediaAnalyzer()

    distant_bicycle = analyzer._vehicle_approaching(
        obstacle_score=0.2,
        traffic_light="unknown",
        semantic_regions=[],
        detected_objects=[DetectedObject("bicycle", "center", 6.0, 0.78, [410, 90, 80, 80])],
    )
    near_bicycle = analyzer._vehicle_approaching(
        obstacle_score=0.2,
        traffic_light="unknown",
        semantic_regions=[],
        detected_objects=[DetectedObject("bicycle", "center", 1.8, 0.78, [250, 220, 150, 180])],
    )

    assert distant_bicycle is False
    assert near_bicycle is True


def test_roboflow_tactile_predictions_convert_to_regions():
    regions = _regions_from_roboflow_predictions(
        [
            {"class": "line", "confidence": 0.82, "x": 320, "y": 220, "width": 80, "height": 300},
            {"class": "person", "confidence": 0.9, "x": 80, "y": 220, "width": 80, "height": 300},
        ],
        width=640,
        height=480,
        min_confidence=0.18,
    )

    assert len(regions) == 1
    assert regions[0].label == "tactile_paving"
    assert regions[0].direction == "center"


def test_roboflow_crossing_predictions_convert_to_regions_and_lights():
    crosswalk = _regions_from_roboflow_predictions(
        [{"class": "zebra_crossing", "confidence": 0.81, "x": 330, "y": 280, "width": 520, "height": 160}],
        width=640,
        height=480,
        min_confidence=0.2,
        label_predicate=lambda label: "zebra" in label,
        normalized_label="crosswalk",
    )
    lights = _traffic_light_objects_from_roboflow_predictions(
        [{"class": "green_light", "confidence": 0.86, "x": 520, "y": 80, "width": 28, "height": 60}],
        width=640,
        height=480,
        min_confidence=0.2,
    )

    assert crosswalk[0].label == "crosswalk"
    assert lights[0].label == "traffic_light_green"


def test_media_analyzer_auto_classifies_crosswalk_scene(tmp_path: Path):
    image = np.full((480, 640, 3), 45, dtype=np.uint8)
    for y in (250, 315, 380):
        cv2.rectangle(image, (40, y), (600, y + 28), (235, 235, 235), -1)
    path = tmp_path / "crosswalk.jpg"
    cv2.imwrite(str(path), image)

    frame, evidence = MediaAnalyzer().analyze_file(path)

    assert frame.scene_type == "crossing"
    assert frame.user_intent == "cross"
    assert evidence["scene_label"] == "Road crossing"
    assert evidence["crosswalk_score"] > 0.05
    assert frame.vehicle_confidence >= 0.55


def test_media_analyzer_detects_mid_frame_crosswalk_with_occlusion(tmp_path: Path):
    image = np.full((360, 520, 3), 110, dtype=np.uint8)
    for y in (120, 165, 210, 255):
        cv2.rectangle(image, (25, y), (500, y + 18), (238, 238, 238), -1)
    cv2.rectangle(image, (220, 40), (280, 260), (28, 28, 28), -1)
    path = tmp_path / "occluded-crosswalk.jpg"
    cv2.imwrite(str(path), image)

    frame, evidence = MediaAnalyzer().analyze_file(path)

    assert frame.scene_type == "crossing"
    assert evidence["crosswalk_score"] > 0.035
    assert any(region.label == "crosswalk" for region in frame.semantic_regions)


class TargetModelBackend:
    def __init__(self, objects):
        self.objects = objects

    def analyze(self, frame):
        return SimpleNamespace(detected_objects=self.objects, semantic_regions=[])

    def status(self):
        return {"active": bool(self.objects), "models": ["test-detector"] if self.objects else []}


@pytest.fixture
def target_analyzer(monkeypatch):
    analyzer = MediaAnalyzer(vision_backend=TargetModelBackend([]))
    monkeypatch.setattr(analyzer, "_ocr_texts", lambda frame: [])
    return analyzer


def test_requested_target_without_model_match_remains_unlocalized(target_analyzer):
    image = np.full((96, 128, 3), 200, dtype=np.uint8)
    frame, evidence = target_analyzer._analyze_frame(image, target_query="cup")

    assert frame.target_query == "cup"
    assert frame.target_distance_m is None
    assert frame.target_direction == "unknown"
    assert frame.target_confidence == 0.0
    assert evidence["perception"]["target_distance_m"] is None
    for coordinator in (MobilityOrchestrator(), EPMCCoordinator()):
        plan = coordinator.analyze_perception(frame)
        text = json.dumps(asdict(plan)).lower()
        assert "found cup" not in text
        assert "found target cup" not in text
        assert "cup is nearby" not in text
        assert "approach the target" not in text
        assert "approach slowly" not in plan.main_instruction.lower()
        assert not any(event.metadata.get("target_query") for event in plan.mobility_events)


def test_target_search_does_not_promote_heuristic_boxes(target_analyzer, monkeypatch):
    monkeypatch.setattr(target_analyzer, "_detected_objects", lambda *args: [
        DetectedObject("obstacle", "left", 2.4, 0.9, [10, 40, 20, 40])
    ])
    frame, _ = target_analyzer._analyze_frame(np.full((96, 128, 3), 200, dtype=np.uint8), "obstacle")

    assert frame.detected_objects[0].label == "obstacle"
    assert (frame.target_distance_m, frame.target_direction, frame.target_confidence) == (None, "unknown", 0.0)


def test_target_label_matching_uses_one_highest_confidence_observation(target_analyzer):
    target_analyzer.vision_backend.objects = [
        DetectedObject("coffee_cup", "left", 1.2, 0.6),
        DetectedObject("coffee_cup", "right", 3.4, 0.91),
        DetectedObject("coffee_cup", "center", 0.5, 0.91),
        DetectedObject("cupboard", "center", 2.0, 0.99),
    ]
    frame, _ = target_analyzer._analyze_frame(np.full((96, 128, 3), 200, dtype=np.uint8), "  COFFEE-CUP  ")

    assert frame.target_query == "COFFEE-CUP"
    assert (frame.target_distance_m, frame.target_direction, frame.target_confidence) == (3.4, "right", 0.91)
    plan = EPMCCoordinator().analyze_perception(frame)
    event = next(event for event in plan.mobility_events if event.metadata.get("target_query"))
    assert event.confidence == 0.91
    assert "on the right" in event.recommendation
    assert "3.4 m" in event.recommendation


@pytest.mark.parametrize("query", ["cup", "find a cup", "", "   "])
def test_target_queries_require_a_complete_detector_label(target_analyzer, query):
    objects = [DetectedObject("cupboard", "right", 1.8, 0.95)]
    assert target_analyzer._locate_target(query, objects) == (None, "unknown", 0.0)


@pytest.mark.parametrize("distance", [None, 0.0, -2.0, float("nan"), float("inf")])
def test_target_match_preserves_unknown_distance(target_analyzer, distance):
    assert target_analyzer._locate_target("cup", [DetectedObject("cup", "left", distance, 0.82)]) == (None, "left", 0.82)


@pytest.mark.parametrize("confidence", [0.0, -0.1, 1.1, float("nan"), float("inf")])
def test_invalid_target_confidence_cannot_establish_a_match(target_analyzer, confidence):
    assert target_analyzer._locate_target("cup", [DetectedObject("cup", "right", 1.8, confidence)]) == (None, "unknown", 0.0)


def test_detected_target_can_have_no_localization_estimate(target_analyzer):
    target_analyzer.vision_backend.objects = [DetectedObject("cup", "unknown", None, 0.82)]
    frame, _ = target_analyzer._analyze_frame(np.full((96, 128, 3), 200, dtype=np.uint8), "cup")

    assert (frame.target_distance_m, frame.target_direction, frame.target_confidence) == (None, "unknown", 0.82)
    plan = EPMCCoordinator().analyze_perception(frame)
    event = next(event for event in plan.mobility_events if event.metadata.get("target_query"))
    assert "m away" not in event.recommendation
    assert event.confidence == 0.82


def test_low_confidence_target_is_not_announced_as_found(target_analyzer):
    target_analyzer.vision_backend.objects = [DetectedObject("cup", "right", 2.4, 0.2)]
    frame, _ = target_analyzer._analyze_frame(np.full((96, 128, 3), 200, dtype=np.uint8), "cup")

    assert frame.target_confidence == 0.2
    for coordinator in (MobilityOrchestrator(), EPMCCoordinator()):
        plan = coordinator.analyze_perception(frame)
        assert "Found cup" not in plan.voice_message
        assert "Approach" not in plan.main_instruction
        assert not any(event.metadata.get("target_query") for event in plan.mobility_events)


@pytest.mark.parametrize("ocr_case", ["missing", "failure", "blank", "filtered"])
def test_unrecognized_text_regions_cannot_become_text_guidance(monkeypatch, ocr_case):
    calls = []

    def recognize(frame, lang):
        calls.append(lang)
        if ocr_case == "failure":
            raise RuntimeError("Recognizer unavailable")
        return " \n\t" if ocr_case == "blank" else "!\n?\na"

    monkeypatch.setitem(sys.modules, "pytesseract", None if ocr_case == "missing" else SimpleNamespace(image_to_string=recognize))
    image = np.full((160, 320, 3), 230, dtype=np.uint8)
    cv2.putText(image, "COFFEE SHOP", (12, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    frame, evidence = MediaAnalyzer(vision_backend=TargetModelBackend([]))._analyze_frame(image, target_query=None)

    assert frame.detected_texts == []
    assert frame.sign_candidates == []
    assert evidence["detected_texts"] == []
    assert evidence["sign_candidates"] == []
    assert calls == ([] if ocr_case == "missing" else ["chi_sim+eng", "eng"])
    for coordinator in (MobilityOrchestrator(), EPMCCoordinator()):
        plan = coordinator.analyze_perception(frame)
        text = json.dumps(asdict(plan)).lower()
        assert "text region 1" not in text
        assert "recognized sign text:" not in text
        assert "recognized text:" not in text
        assert not any("texts" in event.metadata for event in plan.mobility_events)


@pytest.mark.parametrize("first_result", ["failure", "blank"])
def test_ocr_retries_english_and_returns_only_recognized_text(monkeypatch, first_result):
    calls = []

    def recognize(frame, lang):
        calls.append(lang)
        if lang == "chi_sim+eng":
            if first_result == "failure":
                raise RuntimeError("Language data unavailable")
            return "\n"
        return "  COFFEE    SHOP!  \ncoffee shop\n!\na\n MAIN STREET "

    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(image_to_string=recognize))
    analyzer = MediaAnalyzer(vision_backend=TargetModelBackend([]))
    assert analyzer._ocr_texts(np.full((96, 128, 3), 200, dtype=np.uint8)) == ["COFFEE SHOP", "MAIN STREET"]
    assert calls == ["chi_sim+eng", "eng"]


def test_successful_ocr_is_cleaned_deduplicated_and_bounded(monkeypatch):
    calls = []

    def recognize(frame, lang):
        calls.append(lang)
        return "SHOP\nshop\n" + "\n".join(f"Street {index}" for index in range(10))

    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(image_to_string=recognize))
    analyzer = MediaAnalyzer(vision_backend=TargetModelBackend([]))
    assert analyzer._ocr_texts(np.full((96, 128, 3), 200, dtype=np.uint8)) == ["SHOP"] + [f"Street {index}" for index in range(7)]
    assert calls == ["chi_sim+eng"]


def test_recognized_text_reaches_both_coordinators_without_region_labels(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(image_to_string=lambda *args, **kwargs: "MAIN STREET"))
    analyzer = MediaAnalyzer(vision_backend=TargetModelBackend([]))
    frame, evidence = analyzer._analyze_frame(np.full((96, 128, 3), 200, dtype=np.uint8), target_query=None)

    assert frame.detected_texts == ["MAIN STREET"]
    assert evidence["detected_texts"] == ["MAIN STREET"]
    legacy = MobilityOrchestrator().analyze_perception(frame)
    assert any("Recognized text: MAIN STREET" in result.status for result in legacy.agent_results)
    production = EPMCCoordinator().analyze_perception(frame, detail_request=True)
    assert any(event.metadata.get("texts") and "MAIN STREET" in event.recommendation for event in production.mobility_events)
    assert "Text region" not in json.dumps(asdict(legacy)) + json.dumps(asdict(production))
