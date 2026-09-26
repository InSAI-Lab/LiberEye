from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import asdict
import math
import os
from pathlib import Path
import re
import unicodedata

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None  # type: ignore[assignment]
    np = None   # type: ignore[assignment]

from .models import DepthEstimate, DetectedObject, Direction, PerceptionFrame, SemanticRegion
from .vision_backends import OptionalUltralyticsBackend


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif", ".heic", ".heif"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}

# English and Chinese OCR vocabulary, retained for multilingual sign recognition.
OCR_SCENE_KEYWORDS = {
    "hospital": ("\u533b\u9662", "\u95e8\u8bca", "\u836f\u623f", "clinic", "hospital", "pharmacy"),
    "restaurant": ("\u9910", "\u996d", "\u5496\u5561", "coffee", "cafe", "restaurant", "menu"),
    "office": ("office", "\u529e\u516c", "\u4f1a\u8bae", "\u5de5\u4f4d", "\u7535\u8111"),
}


def validate_media_dimensions(width: float, height: float) -> None:
    """Apply the decoded pixel bound to still images and every video frame."""
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise ValueError("Media dimensions must be finite and positive")
    pixel_limit = int(os.getenv("LIBEREYE_MAX_IMAGE_PIXELS", "16000000"))
    if pixel_limit <= 0 or width * height > pixel_limit:
        raise ValueError("Media exceeds decoded pixel limit")


class MediaAnalyzer:
    """Analyze images and video using optional model outputs and visual heuristics.

    Model detections and semantic regions are combined with heuristic evidence;
    heuristics provide fallback evidence when model outputs are unavailable.
    Perception accuracy and distance estimates require validation and calibration
    for the intended camera and environment.
    """

    def __init__(self, vision_backend: OptionalUltralyticsBackend | None = None) -> None:
        self.vision_backend = vision_backend or OptionalUltralyticsBackend()

    def analyze_file(self, path: str | Path, target_query: str | None = None) -> tuple[PerceptionFrame, dict]:
        media_path = Path(path)
        suffix = media_path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            frame = self._read_image(media_path)
            perception, evidence = self._analyze_frame(frame, target_query=target_query)
            evidence["media_type"] = "image"
            return perception, evidence
        if suffix in VIDEO_SUFFIXES:
            return self._analyze_video(media_path, target_query=target_query)
        raise ValueError(f"Unsupported media type: {suffix}")

    @contextmanager
    def _open_video(self, path: Path):
        if cv2 is None:
            raise ValueError("OpenCV is required for video decoding")
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise ValueError("Unable to read video file")
            validate_media_dimensions(capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            yield capture
        except cv2.error as exc:
            raise ValueError("Unable to decode video within supported limits") from exc
        finally:
            capture.release()

    def validate_video(self, path: Path) -> None:
        """Reject invalid or oversized video metadata before decoding frames."""
        with self._open_video(path):
            pass

    def _analyze_video(self, path: Path, target_query: str | None) -> tuple[PerceptionFrame, dict]:
        perceptions: list[PerceptionFrame] = []
        evidences: list[dict] = []
        with self._open_video(path) as capture:
            frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            if not math.isfinite(frame_count) or frame_count < 0:
                raise ValueError("Invalid video frame count")
            total_frames = int(frame_count)
            sample_count = 8
            indices = np.linspace(0, max(total_frames - 1, 0), sample_count, dtype=int) if total_frames else np.arange(sample_count)
            for index in indices:
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
                ok, frame = capture.read()
                if not ok:
                    continue
                if frame is None or len(frame.shape) < 2:
                    raise ValueError("Invalid decoded video frame")
                # Some streams change dimensions after the initial metadata.
                validate_media_dimensions(frame.shape[1], frame.shape[0])
                perception, evidence = self._analyze_frame(frame, target_query=target_query)
                perceptions.append(perception)
                evidences.append(evidence)

        if not perceptions:
            raise ValueError("No readable frames found in video")

        highest_risk_index, highest_risk_frame = max(enumerate(perceptions), key=lambda item: self._risk_score(item[1]))
        evidence = dict(evidences[highest_risk_index])
        evidence.update({
            "media_type": "video",
            "sampled_frames": len(perceptions),
            "max_risk_score": self._risk_score(highest_risk_frame),
            "frame_evidence": [self._compact_frame_evidence(item) for item in evidences[:3]],
        })
        return highest_risk_frame, evidence

    def _read_image(self, path: Path) -> np.ndarray:
        frame = cv2.imread(str(path))
        if frame is not None:
            return frame

        try:
            from PIL import Image
        except ImportError as exc:
            raise ValueError("Unable to read image file") from exc

        try:
            try:
                import pillow_avif  # type: ignore  # noqa: F401
            except ImportError:
                pass
            with Image.open(path) as image:
                rgb = image.convert("RGB")
                array = np.array(rgb)
        except Exception as exc:
            raise ValueError("Unable to read image file") from exc
        return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)

    def _compact_frame_evidence(self, evidence: dict) -> dict:
        compact = dict(evidence)
        compact.pop("visualization", None)
        compact.pop("perception", None)
        return compact

    def _analyze_frame(self, frame: np.ndarray, target_query: str | None) -> tuple[PerceptionFrame, dict]:
        target_query = target_query.strip() if target_query else None
        target_query = target_query or None
        resized = self._resize(frame)
        height, width = resized.shape[:2]
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

        lower_half = resized[height // 2 :, :]
        lower_gray = gray[height // 2 :, :]
        center = lower_gray[:, width // 3 : (width * 2) // 3]
        left = lower_gray[:, : width // 3]
        right = lower_gray[:, (width * 2) // 3 :]

        raw_obstacle_score = self._obstacle_score(center)
        left_score = self._obstacle_score(left)
        right_score = self._obstacle_score(right)
        model_outputs = self.vision_backend.analyze(resized)
        target_distance, target_direction, target_confidence = self._locate_target(
            target_query, model_outputs.detected_objects
        )
        heuristic_regions = self._semantic_regions(resized, hsv)
        semantic_regions = self._merge_semantic_regions(model_outputs.semantic_regions, heuristic_regions)
        tactile_score = self._tactile_score(resized, hsv)
        indoor_structure_score = self._indoor_structure_score(resized, gray)
        obstacle_score = self._adjust_obstacle_score(raw_obstacle_score, semantic_regions, tactile_score)
        obstacle_distance = self._score_to_distance(obstacle_score)
        obstacle_confidence = self._heuristic_obstacle_confidence(obstacle_score)
        depth_estimate = self._depth_estimate(obstacle_score, left_score, right_score)
        detected_objects = model_outputs.detected_objects or self._detected_objects(resized, obstacle_distance, obstacle_confidence, obstacle_score)
        model_obstacle_distance, model_obstacle_confidence = self._obstacle_from_detected_objects(detected_objects)
        if model_obstacle_distance is not None and model_obstacle_confidence >= 0.5:
            if obstacle_distance is None or model_obstacle_confidence >= obstacle_confidence or model_obstacle_distance < obstacle_distance:
                obstacle_distance = model_obstacle_distance
                obstacle_confidence = model_obstacle_confidence

        tactile_from_seg = any(region.label == "tactile_paving" for region in semantic_regions)
        tactile_blocked = tactile_from_seg and self._tactile_is_blocked(resized, hsv, gray, obstacle_score)
        tactile_confidence = min(0.92, 0.55 + tactile_score * 4)

        crosswalk_score = max(self._crosswalk_score(resized, hsv, gray), self._region_coverage(semantic_regions, "crosswalk"))
        traffic_context = self._traffic_context(semantic_regions, crosswalk_score)
        traffic_light, traffic_confidence = self._traffic_light(hsv[: height // 2, :], require_context=traffic_context)
        model_traffic_light, model_traffic_confidence = self._traffic_light_from_objects(detected_objects, require_context=traffic_context)
        if model_traffic_light != "unknown" and (traffic_light == "unknown" or model_traffic_confidence >= traffic_confidence):
            traffic_light, traffic_confidence = model_traffic_light, model_traffic_confidence
        crowd_level, crowd_score = self._crowd_level(lower_half)
        detected_texts = self._ocr_texts(resized)
        sign_candidates = self._sign_candidates(resized, detected_texts)
        scene_type, scene_label = self._classify_scene(
            target_query=target_query,
            tactile_blocked=tactile_blocked,
            obstacle_distance=obstacle_distance,
            traffic_light=traffic_light,
            crosswalk_score=crosswalk_score,
            semantic_regions=semantic_regions,
            detected_objects=detected_objects,
            detected_texts=detected_texts,
            indoor_structure_score=indoor_structure_score,
        )
        scene_description = self._scene_description(
            obstacle_distance=obstacle_distance,
            tactile_blocked=tactile_blocked,
            traffic_light=traffic_light,
            crowd_level=crowd_level,
            detected_texts=detected_texts,
            sign_candidates=sign_candidates,
            semantic_regions=semantic_regions,
            scene_type=scene_type,
            scene_label=scene_label,
        )
        glasses_description = self._glasses_description(
            semantic_regions=semantic_regions,
            detected_objects=detected_objects,
            obstacle_distance=obstacle_distance,
            traffic_light=traffic_light,
            depth_estimate=depth_estimate,
        )
        vehicle_approaching = self._vehicle_approaching(obstacle_score, traffic_light, semantic_regions, detected_objects)
        vehicle_confidence = self._vehicle_confidence(vehicle_approaching, obstacle_score, crosswalk_score, traffic_light)

        perception = PerceptionFrame(
            obstacle_distance_m=obstacle_distance,
            obstacle_confidence=obstacle_confidence,
            tactile_blocked=tactile_blocked,
            tactile_confidence=tactile_confidence,
            traffic_light=traffic_light,
            traffic_confidence=traffic_confidence,
            vehicle_approaching=vehicle_approaching,
            vehicle_confidence=vehicle_confidence,
            target_query=target_query or None,
            target_distance_m=target_distance,
            target_direction=target_direction,
            target_confidence=target_confidence,
            crowd_level=crowd_level,
            user_intent=self._user_intent(target_query, scene_type),
            scene_type=scene_type,
            scene_label=scene_label,
            detected_objects=detected_objects,
            semantic_regions=semantic_regions,
            depth_estimate=depth_estimate,
            detected_texts=detected_texts,
            sign_candidates=sign_candidates,
            scene_description=scene_description,
            sensor_health="ok",
        )
        evidence = {
            "scene_description": scene_description,
            "glasses_description": glasses_description,
            "obstacle_score": round(obstacle_score, 3),
            "raw_obstacle_score": round(raw_obstacle_score, 3),
            "yellow_tactile_score": round(tactile_score, 3),
            "semantic_sources": self._semantic_sources(model_outputs.semantic_regions, heuristic_regions),
            "vision_backend": self.vision_backend.status(),
            "frame_size": {"width": width, "height": height},
            "traffic_light": traffic_light,
            "traffic_confidence": round(traffic_confidence, 3),
            "crosswalk_score": round(crosswalk_score, 3),
            "vehicle_confidence": round(vehicle_confidence, 3),
            "indoor_structure_score": round(indoor_structure_score, 3),
            "distance_method": "monocular heuristic from texture, object box size, and optional model confidence",
            "scene_type": scene_type,
            "scene_label": scene_label,
            "scene_switch_message": self._scene_switch_message(scene_type, scene_label),
            "crowd_score": round(crowd_score, 3),
            "detected_objects": [asdict(obj) for obj in detected_objects],
            "semantic_regions": [asdict(region) for region in semantic_regions],
            "depth_estimate": asdict(depth_estimate),
            "detected_texts": detected_texts,
            "sign_candidates": sign_candidates,
            "perception": asdict(perception),
        }
        evidence["visualization"] = self._visualization_payload(resized, detected_objects, semantic_regions)
        return perception, evidence

    def _locate_target(
        self, query: str | None, model_objects: list[DetectedObject]
    ) -> tuple[float | None, Direction, float]:
        """Match a detector label without interpreting a query as an observation."""
        def normalized_label(value: str) -> str:
            return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()

        label = normalized_label(query or "")
        if not label:
            return None, "unknown", 0.0
        matches = [
            obj for obj in model_objects
            if normalized_label(obj.label) == label
            and math.isfinite(obj.confidence)
            and 0 < obj.confidence <= 1
        ]
        if not matches:
            return None, "unknown", 0.0
        # Preserve detector order for equal scores rather than mixing observations.
        target = max(matches, key=lambda obj: obj.confidence)
        distance = target.distance_m
        if distance is not None and (not math.isfinite(distance) or distance <= 0):
            distance = None
        direction = target.direction if target.direction in {"left", "center", "right"} else "unknown"
        return distance, direction, target.confidence

    def _classify_scene(
        self,
        target_query: str | None,
        tactile_blocked: bool,
        obstacle_distance: float | None,
        traffic_light: str,
        crosswalk_score: float,
        semantic_regions: list[SemanticRegion],
        detected_objects: list[DetectedObject],
        detected_texts: list[str],
        indoor_structure_score: float,
    ) -> tuple[str, str]:
        if target_query:
            return "finding", "Object search"
        road_coverage = self._region_coverage(semantic_regions, "road_or_asphalt")
        center_road = self._region_coverage(semantic_regions, "road_or_asphalt", "center")
        walkable_coverage = self._region_coverage(semantic_regions, "walkable_pavement")
        crosswalk_coverage = self._region_coverage(semantic_regions, "crosswalk")
        crossing_context = self._crossing_context(
            crosswalk_score=crosswalk_score,
            crosswalk_coverage=crosswalk_coverage,
            road_coverage=road_coverage,
            center_road=center_road,
            walkable_coverage=walkable_coverage,
        )
        indoor_label = self._indoor_scene_label(
            detected_objects,
            detected_texts,
            semantic_regions,
            crossing_context,
            indoor_structure_score,
        )
        if indoor_label:
            return "indoor", indoor_label
        if crossing_context and (crosswalk_score > 0.035 or crosswalk_coverage > 0.006):
            return "crossing", "Road crossing"
        if traffic_light != "unknown" and road_coverage > max(0.08, walkable_coverage * 1.15):
            return "crossing", "Road crossing"
        if tactile_blocked or (obstacle_distance is not None and obstacle_distance <= 2.2):
            return "blocked", "Blocked tactile paving or nearby obstacle"
        if self._region_coverage(semantic_regions, "tactile_paving") > 0.015 or self._region_coverage(semantic_regions, "walkable_pavement") > 0.08:
            return "sidewalk", "Sidewalk navigation"
        if road_coverage > 0.12:
            return "street", "Street or roadside scene"
        if crossing_context and road_coverage > max(0.16, walkable_coverage * 1.15):
            return "crossing", "Roadway confirmation"
        return "unknown", "Unknown scene"

    def _user_intent(self, target_query: str | None, scene_type: str) -> str:
        if target_query:
            return "find"
        if scene_type == "crossing":
            return "cross"
        return "navigate"

    def _scene_switch_message(self, scene_type: str, scene_label: str) -> str:
        messages = {
            "crossing": f"Switched to {scene_label}. Confirm traffic signals and vehicles before crossing.",
            "blocked": f"Switched to {scene_label}. Slow down and wait for avoidance guidance.",
            "finding": f"Switched to {scene_label}. Search for the target at a slow pace.",
            "sidewalk": f"Switched to {scene_label}. Continue along the walkable area.",
            "street": f"Detected {scene_label}. Crossing intent is unconfirmed. Stay on the sidewalk or safe side.",
            "indoor": f"Detected {scene_label}. Provide a scene summary without crossing prompts.",
            "transit": f"Switched to {scene_label}. Confirm the direction of the transit stop.",
        }
        return messages.get(scene_type, "The scene is unclear. Slow down and continue capturing frames.")

    def _indoor_scene_label(
        self,
        detected_objects: list[DetectedObject],
        detected_texts: list[str],
        semantic_regions: list[SemanticRegion],
        crossing_context: bool,
        indoor_structure_score: float,
    ) -> str | None:
        labels = {obj.label.lower().replace(" ", "_") for obj in detected_objects if obj.confidence >= 0.28}
        text = " ".join(detected_texts).lower()
        office_objects = {"keyboard", "mouse", "monitor", "laptop", "phone", "book"}
        restaurant_objects = {"cup", "bottle", "table", "chair"}
        hospital_objects = {"bed", "bench", "chair"}
        indoor_objects = office_objects | restaurant_objects | hospital_objects | {"person"}
        office_words = OCR_SCENE_KEYWORDS["office"]
        restaurant_words = OCR_SCENE_KEYWORDS["restaurant"]
        hospital_words = OCR_SCENE_KEYWORDS["hospital"]

        indoor_hits = len(labels & indoor_objects)
        text_indoor = any(word in text for word in (*office_words, *restaurant_words, *hospital_words))
        walkable_coverage = self._region_coverage(semantic_regions, "walkable_pavement")
        road_coverage = self._region_coverage(semantic_regions, "road_or_asphalt")
        crosswalk_coverage = self._region_coverage(semantic_regions, "crosswalk")
        weak_outdoor_context = not crossing_context and crosswalk_coverage < 0.02 and road_coverage <= max(0.22, walkable_coverage * 0.9)
        visual_indoor = indoor_structure_score >= 0.42
        if indoor_hits == 0 and not text_indoor and not visual_indoor:
            return None
        if not weak_outdoor_context:
            return None
        if labels & office_objects or any(word in text for word in office_words):
            return "Indoor office scene"
        if labels & restaurant_objects or any(word in text for word in restaurant_words):
            return "Indoor dining or tabletop scene"
        if labels & hospital_objects or any(word in text for word in hospital_words):
            return "Hospital or public-service indoor scene"
        return "Indoor scene"

    def _region_coverage(self, regions: list[SemanticRegion], label: str, direction: str | None = None) -> float:
        return sum(
            region.coverage
            for region in regions
            if region.label == label and (direction is None or region.direction == direction)
        )

    def _resize(self, frame: np.ndarray, max_width: int = 960) -> np.ndarray:
        height, width = frame.shape[:2]
        if width <= max_width:
            return frame
        scale = max_width / width
        return cv2.resize(frame, (max_width, int(height * scale)))

    def _glasses_description(
        self,
        semantic_regions: list[SemanticRegion],
        detected_objects: list[DetectedObject],
        obstacle_distance: float | None,
        traffic_light: str,
        depth_estimate: DepthEstimate,
    ) -> str:
        parts: list[str] = []

        regions = sorted(semantic_regions, key=lambda item: item.coverage, reverse=True)
        tactile = self._first_region(regions, {"tactile_paving"})
        walkable = tactile or self._first_region(regions, {"walkable_pavement"})
        crosswalk = self._first_region(regions, {"crosswalk"})
        road = self._first_region(regions, {"road_or_asphalt"})
        vegetation = self._first_region(regions, {"vegetation"})

        if walkable:
            parts.append(f"{self._region_label(walkable.label)} {self._direction_label(walkable.direction)}")
        if crosswalk:
            parts.append(f"{self._region_label(crosswalk.label)} {self._direction_label(crosswalk.direction)}")
        if road:
            parts.append(f"{self._region_label(road.label)} {self._direction_label(road.direction)}")
        if vegetation and len(parts) < 3:
            parts.append(f"{self._region_label(vegetation.label)} {self._direction_label(vegetation.direction)}")

        nearest_objects = self._dedupe_objects(
            sorted(
                detected_objects,
                key=lambda obj: obj.distance_m if obj.distance_m is not None else 99.0,
            )
        )[:2]
        for obj in nearest_objects:
            distance = f"{obj.distance_m:.1f} m" if obj.distance_m is not None else "distance unknown"
            parts.append(f"{self._object_label(obj.label)} {self._direction_label(obj.direction)}, {distance}")

        if traffic_light != "unknown":
            parts.append(f"Traffic light: {traffic_light}")
        if obstacle_distance is not None and obstacle_distance <= 2.5 and not nearest_objects:
            parts.append(f"Obstacle ahead: {obstacle_distance:.1f} m")
        if depth_estimate.center_depth_m is not None and not parts:
            parts.append(f"Depth ahead: about {depth_estimate.center_depth_m:.1f} m")

        if not parts:
            return "Segmentation is unclear. Slow down and capture the next frame."
        return "Glasses segmentation: " + ", ".join(parts[:5]) + "."

    def _first_region(self, regions: list[SemanticRegion], labels: set[str]) -> SemanticRegion | None:
        return next((region for region in regions if region.label in labels), None)

    def _merge_semantic_regions(
        self,
        model_regions: list[SemanticRegion],
        heuristic_regions: list[SemanticRegion],
    ) -> list[SemanticRegion]:
        merged: dict[tuple[str, str], SemanticRegion] = {}
        for region in [*model_regions, *heuristic_regions]:
            key = (region.label, region.direction)
            existing = merged.get(key)
            if existing is None or self._region_rank(region) > self._region_rank(existing):
                merged[key] = region
        return sorted(
            merged.values(),
            key=lambda region: (region.label == "tactile_paving", region.coverage * region.confidence),
            reverse=True,
        )

    def _semantic_sources(
        self,
        model_regions: list[SemanticRegion],
        heuristic_regions: list[SemanticRegion],
    ) -> list[str]:
        sources: list[str] = []
        if model_regions:
            sources.append("model")
        if any(region.label == "tactile_paving" for region in heuristic_regions):
            sources.append("tactile_color_texture")
        if any(region.label in {"walkable_pavement", "road_or_asphalt", "vegetation", "crosswalk"} for region in heuristic_regions):
            sources.append("scene_color_texture")
        return sources or ["none"]

    def _region_rank(self, region: SemanticRegion) -> float:
        bonus = 0.15 if region.label == "tactile_paving" else 0.0
        return region.coverage * region.confidence + bonus

    def _dedupe_objects(self, objects: list[DetectedObject]) -> list[DetectedObject]:
        deduped: list[DetectedObject] = []
        seen: set[tuple[str, str, float | None]] = set()
        for obj in objects:
            rounded_distance = round(obj.distance_m, 1) if obj.distance_m is not None else None
            key = (obj.label, obj.direction, rounded_distance)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(obj)
        return deduped

    def _direction_label(self, direction: str) -> str:
        labels = {"left": "on the left", "center": "ahead", "right": "on the right", "unknown": "nearby"}
        return labels.get(direction, "nearby")

    def _region_label(self, label: str) -> str:
        labels = {
            "vegetation": "vegetation",
            "tactile_paving": "tactile paving",
            "road_or_asphalt": "roadway/asphalt",
            "crosswalk": "crosswalk",
            "walkable_pavement": "walkable pavement",
        }
        return labels.get(label, label.replace("_", " "))

    def _object_label(self, label: str) -> str:
        labels = {
            "person": "pedestrian",
            "bicycle": "bicycle",
            "car": "car",
            "motorcycle": "motorcycle",
            "bus": "bus",
            "truck": "truck",
            "traffic light": "traffic light",
            "traffic_light": "traffic light",
            "traffic_light_red": "Red light",
            "traffic_light_green": "Green light",
            "traffic_light_yellow": "Yellow light",
            "obstacle": "obstacle",
            "person_or_obstacle": "pedestrian/obstacle",
            "segmented_object": "segmented object",
        }
        return labels.get(label, label.replace("_", " "))

    def _visualization_payload(
        self,
        frame: np.ndarray,
        detected_objects: list[DetectedObject],
        semantic_regions: list[SemanticRegion],
    ) -> dict:
        annotated = self._draw_visualization(frame, detected_objects, semantic_regions)
        ok, encoded = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 84])
        image_data = ""
        if ok:
            image_data = "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")
        return {
            "image_data": image_data,
            "width": int(annotated.shape[1]),
            "height": int(annotated.shape[0]),
            "labels": self._visual_labels(detected_objects, semantic_regions),
        }

    def _draw_visualization(
        self,
        frame: np.ndarray,
        detected_objects: list[DetectedObject],
        semantic_regions: list[SemanticRegion],
    ) -> np.ndarray:
        canvas = frame.copy()
        overlay = canvas.copy()
        height, width = canvas.shape[:2]

        for region in self._visual_regions(semantic_regions):
            x1, x2 = self._direction_band(region.direction, width)
            y1 = height // 2
            y2 = height
            color = self._region_color(region.label)
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
            label = f"{self._region_display_label(region.label)} {int(region.coverage * 100)}%"
            self._draw_cv_label(overlay, label, (x1 + 8, y1 + 10), color)

        canvas = cv2.addWeighted(overlay, 0.34, canvas, 0.66, 0)

        for obj in sorted(detected_objects, key=lambda item: item.confidence, reverse=True)[:8]:
            if len(obj.bbox) != 4:
                continue
            x, y, w, h = [int(value) for value in obj.bbox]
            if w <= 0 or h <= 0:
                continue
            color = (36, 104, 214)
            cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 3)
            distance = f" {obj.distance_m:.1f}m" if obj.distance_m is not None else ""
            label = f"{self._object_display_label(obj.label)}{distance}"
            self._draw_cv_label(canvas, label, (x, max(0, y - 26)), color)
        return canvas

    def _direction_band(self, direction: str, width: int) -> tuple[int, int]:
        if direction == "left":
            return 0, width // 3
        if direction == "right":
            return (width * 2) // 3, width
        if direction == "center":
            return width // 3, (width * 2) // 3
        return 0, width

    def _region_color(self, label: str) -> tuple[int, int, int]:
        colors = {
            "vegetation": (64, 165, 90),
            "tactile_paving": (28, 187, 232),
            "road_or_asphalt": (88, 94, 104),
            "crosswalk": (235, 235, 235),
            "walkable_pavement": (197, 132, 50),
            "person": (46, 94, 220),
            "bicycle": (45, 148, 230),
            "car": (64, 82, 220),
            "bus": (50, 120, 210),
            "truck": (50, 120, 210),
        }
        return colors.get(label, (204, 108, 56))

    def _draw_cv_label(self, frame: np.ndarray, text: str, origin: tuple[int, int], color: tuple[int, int, int]) -> None:
        x, y = origin
        y = max(4, y)
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.55
        thickness = 1
        (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
        cv2.rectangle(
            frame,
            (x, y),
            (min(frame.shape[1] - 1, x + text_width + 10), min(frame.shape[0] - 1, y + text_height + baseline + 10)),
            color,
            -1,
        )
        cv2.putText(frame, text, (x + 5, y + text_height + 4), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

    def _visual_labels(self, detected_objects: list[DetectedObject], semantic_regions: list[SemanticRegion]) -> list[dict]:
        labels: list[dict] = []
        for obj in sorted(detected_objects, key=lambda item: item.confidence, reverse=True)[:8]:
            labels.append({
                "type": "object",
                "label": self._object_display_label(obj.label),
                "raw_label": obj.label,
                "direction": obj.direction,
                "distance_m": obj.distance_m,
                "confidence": round(obj.confidence, 3),
                "bbox": obj.bbox,
            })
        for region in self._visual_regions(semantic_regions):
            labels.append({
                "type": "region",
                "label": self._region_display_label(region.label),
                "raw_label": region.label,
                "direction": region.direction,
                "coverage": round(region.coverage, 3),
                "confidence": round(region.confidence, 3),
            })
        return labels

    def _visual_regions(self, regions: list[SemanticRegion], limit: int = 5) -> list[SemanticRegion]:
        visible = [
            region
            for region in regions
            if region.coverage >= 0.025 or region.label == "tactile_paving"
        ]
        return sorted(
            visible,
            key=lambda region: (region.label == "tactile_paving", region.coverage),
            reverse=True,
        )[:limit]

    def _object_display_label(self, label: str) -> str:
        labels = {
            "person": "person",
            "bicycle": "bicycle",
            "car": "car",
            "motorcycle": "motorcycle",
            "bus": "bus",
            "truck": "truck",
            "traffic light": "traffic light",
            "traffic_light": "traffic light",
            "traffic_light_red": "red light",
            "traffic_light_green": "green light",
            "traffic_light_yellow": "yellow light",
            "bench": "bench",
            "backpack": "backpack",
            "chair": "chair",
            "obstacle": "obstacle",
            "person_or_obstacle": "person/obstacle",
            "segmented_object": "segmented object",
        }
        return labels.get(label, label.replace("_", " "))

    def _region_display_label(self, label: str) -> str:
        labels = {
            "vegetation": "vegetation",
            "tactile_paving": "tactile paving",
            "road_or_asphalt": "road/asphalt",
            "crosswalk": "crosswalk",
            "walkable_pavement": "walkable pavement",
            "person": "person area",
            "bicycle": "bicycle area",
            "car": "car area",
            "bus": "bus area",
            "truck": "truck area",
            "obstacle": "obstacle area",
            "person_or_obstacle": "obstacle area",
            "segmented_object": "segmented area",
        }
        return labels.get(label, label.replace("_", " "))

    def _obstacle_score(self, center_gray: np.ndarray) -> float:
        blur = cv2.GaussianBlur(center_gray, (5, 5), 0)
        edges = cv2.Canny(blur, 60, 140)
        edge_density = float(np.count_nonzero(edges)) / edges.size
        darkness = 1.0 - float(np.mean(center_gray)) / 255.0
        texture = float(np.std(center_gray)) / 90.0
        return float(np.clip(edge_density * 1.8 + darkness * 0.35 + texture * 0.25, 0.0, 1.0))

    def _score_to_distance(self, score: float) -> float | None:
        if score < 0.32:
            return None
        return float(np.clip(4.2 - score * 4.0, 0.8, 4.0))

    def _heuristic_obstacle_confidence(self, score: float) -> float:
        if score < 0.32:
            return 0.35
        return float(np.clip(0.38 + score * 0.62, 0.45, 0.9))

    def _score_to_clearance(self, score: float) -> float:
        return float(np.clip(4.8 - score * 4.2, 0.6, 4.8))

    def _indoor_structure_score(self, frame: np.ndarray, gray: np.ndarray) -> float:
        height, width = gray.shape[:2]
        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 130)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=max(45, width // 18),
            minLineLength=max(45, width // 5),
            maxLineGap=8,
        )
        if lines is None:
            return 0.0

        horizontal = 0
        vertical = 0
        upper_horizontal = 0
        y_bins: set[int] = set()
        for raw_line in lines[:120]:
            x1, y1, x2, y2 = raw_line[0]
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            if dx >= width * 0.2 and dy <= max(5, dx * 0.05):
                horizontal += 1
                y_bins.add(int(((y1 + y2) / 2) // max(8, height // 48)))
                if (y1 + y2) / 2 < height * 0.65:
                    upper_horizontal += 1
            elif dy >= height * 0.18 and dx <= max(5, dy * 0.06):
                vertical += 1

        line_density = min(1.0, (horizontal + vertical * 0.6) / 32)
        repeated_horizontal = min(1.0, len(y_bins) / 18)
        upper_bias = min(1.0, upper_horizontal / max(horizontal, 1))
        return float(np.clip(line_density * 0.45 + repeated_horizontal * 0.4 + upper_bias * 0.15, 0.0, 1.0))

    def _depth_estimate(self, center_score: float, left_score: float, right_score: float) -> DepthEstimate:
        center_depth = self._score_to_distance(center_score) or 4.5
        left_clearance = self._score_to_clearance(left_score)
        right_clearance = self._score_to_clearance(right_score)
        return DepthEstimate(
            min_depth_m=min(center_depth, left_clearance, right_clearance),
            center_depth_m=center_depth,
            left_clearance_m=left_clearance,
            right_clearance_m=right_clearance,
            confidence=min(0.92, 0.5 + max(center_score, left_score, right_score)),
        )

    def _detected_objects(
        self,
        frame: np.ndarray,
        obstacle_distance: float | None,
        confidence: float,
        obstacle_score: float,
    ) -> list[DetectedObject]:
        if obstacle_score < 0.36 or obstacle_distance is None:
            return []
        height, width = frame.shape[:2]
        lower = frame[height // 2 :, :]
        gray = cv2.cvtColor(lower, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 60, 140)
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        objects: list[DetectedObject] = []
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < width * height * 0.006:
                continue
            area_ratio = area / (width * height)
            aspect = w / max(h, 1)
            if area_ratio > 0.22 or aspect > 4.2 or aspect < 0.12:
                continue
            if w < 16 or h < 28:
                continue
            center_x = x + w / 2
            if center_x < width / 3:
                direction = "left"
            elif center_x > width * 2 / 3:
                direction = "right"
            else:
                direction = "center"
            normalized_size = min(1.0, area / (width * height * 0.28))
            distance = obstacle_distance or float(np.clip(4.4 - normalized_size * 3.2, 1.0, 4.4))
            label = "person_or_obstacle" if h > w * 1.2 else "obstacle"
            objects.append(
                DetectedObject(
                    label=label,
                    direction=direction,
                    distance_m=distance,
                    confidence=max(0.45, min(0.92, confidence)),
                    bbox=[int(x), int(y + height // 2), int(w), int(h)],
                )
            )
        return objects

    def _obstacle_from_detected_objects(self, objects: list[DetectedObject]) -> tuple[float | None, float]:
        mobility_obstacles = [
            obj
            for obj in objects
            if obj.direction == "center"
            and obj.distance_m is not None
            and obj.confidence >= 0.5
            and obj.label
            in {
                "person",
                "bicycle",
                "motorcycle",
                "car",
                "bus",
                "truck",
                "bench",
                "chair",
                "suitcase",
                "backpack",
                "obstacle",
                "person_or_obstacle",
            }
        ]
        if not mobility_obstacles:
            return None, 0.0
        nearest = min(mobility_obstacles, key=lambda obj: obj.distance_m or 99.0)
        return nearest.distance_m, nearest.confidence

    def _semantic_regions(self, frame: np.ndarray, hsv: np.ndarray) -> list[SemanticRegion]:
        height, width = frame.shape[:2]
        lower_hsv = hsv[height // 2 :, :]
        regions: list[SemanticRegion] = []

        green_mask = cv2.inRange(lower_hsv, np.array([35, 35, 35]), np.array([90, 255, 255])) > 0
        yellow_mask = self._tactile_mask(frame, hsv)[height // 2 :, :]
        crosswalk_mask = self._crosswalk_mask(frame, hsv)[height // 2 :, :]
        gray = cv2.cvtColor(frame[height // 2 :, :], cv2.COLOR_BGR2GRAY)
        full_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        dark_mask = (gray < 95) & ~green_mask & ~yellow_mask & ~crosswalk_mask
        mid_mask = (gray >= 95) & (gray <= 215) & ~green_mask & ~yellow_mask & ~crosswalk_mask

        for label, mask in [
            ("vegetation", green_mask),
            ("tactile_paving", yellow_mask),
            ("crosswalk", crosswalk_mask),
            ("road_or_asphalt", dark_mask),
            ("walkable_pavement", mid_mask),
        ]:
            coverage = float(mask.mean())
            min_coverage = 0.006 if label in {"tactile_paving", "crosswalk"} else 0.02
            if coverage < min_coverage:
                continue
            if label == "crosswalk" and self._crosswalk_score(frame, hsv, full_gray) < 0.035:
                continue
            direction = self._mask_direction(mask)
            confidence = min(0.9, 0.52 + coverage * 3.8) if label in {"tactile_paving", "crosswalk"} else min(0.9, 0.45 + coverage * 2.2)
            regions.append(SemanticRegion(label=label, direction=direction, coverage=coverage, confidence=confidence))
        return regions

    def _adjust_obstacle_score(self, score: float, regions: list[SemanticRegion], tactile_score: float) -> float:
        walkable_coverage = sum(
            region.coverage
            for region in regions
            if region.label in {"walkable_pavement", "tactile_paving"} and region.direction in {"center", "left"}
        )
        road_center = any(region.label == "road_or_asphalt" and region.direction == "center" and region.coverage > 0.08 for region in regions)
        adjusted = score
        if walkable_coverage > 0.16 or tactile_score > 0.04:
            adjusted *= 0.62
        elif walkable_coverage > 0.08 or tactile_score > 0.025:
            adjusted *= 0.78
        if road_center and walkable_coverage < 0.06:
            adjusted = max(adjusted, 0.38)
        return float(np.clip(adjusted, 0.0, 1.0))

    def _tactile_is_blocked(self, frame: np.ndarray, hsv: np.ndarray, gray: np.ndarray, obstacle_score: float) -> bool:
        height, width = hsv.shape[:2]
        lower_gray = gray[height // 2 :, :]
        yellow_mask = self._tactile_mask(frame, hsv)[height // 2 :, :]
        if float(yellow_mask.mean()) < 0.006:
            return False

        rows = np.array_split(yellow_mask, 3, axis=0)
        row_coverage = [float(row.mean()) for row in rows]
        continuous = sum(coverage > 0.012 for coverage in row_coverage) >= 2
        if continuous and obstacle_score < 0.45:
            return False

        tactile_cols = np.where(yellow_mask)[1]
        if tactile_cols.size == 0:
            return False
        col_min = max(0, int(tactile_cols.min()) - width // 20)
        col_max = min(width, int(tactile_cols.max()) + width // 20)
        path_gray = lower_gray[:, col_min:col_max]
        if path_gray.size == 0:
            return False
        dark_ratio = float((path_gray < 70).mean())
        return bool((not continuous and row_coverage[-1] > 0.012) or (obstacle_score > 0.48 and dark_ratio > 0.12))

    def _mask_direction(self, mask: np.ndarray) -> str:
        cols = np.where(mask)[1]
        if cols.size == 0:
            return "unknown"
        mean_col = float(cols.mean())
        width = mask.shape[1]
        if mean_col < width / 3:
            return "left"
        if mean_col > width * 2 / 3:
            return "right"
        return "center"

    def _tactile_score(self, frame: np.ndarray, hsv: np.ndarray) -> float:
        height = frame.shape[0]
        mask = self._tactile_mask(frame, hsv)[height // 2 :, :]
        return float(np.count_nonzero(mask)) / mask.size

    def _tactile_mask(self, frame: np.ndarray, hsv: np.ndarray) -> np.ndarray:
        strict_hsv = cv2.inRange(hsv, np.array([15, 45, 65]), np.array([48, 255, 255])) > 0
        pale_hsv = cv2.inRange(hsv, np.array([10, 22, 105]), np.array([55, 190, 255])) > 0

        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        lightness = lab[:, :, 0]
        yellow_blue = lab[:, :, 2]
        lab_yellow = (yellow_blue > 138) & (lightness > 72)

        blue = frame[:, :, 0].astype(np.float32)
        green = frame[:, :, 1].astype(np.float32)
        red = frame[:, :, 2].astype(np.float32)
        yellow_dominant = (red > 92) & (green > 78) & (red > blue * 1.08) & (green > blue * 1.02) & (np.abs(red - green) < 92)

        green_vegetation = cv2.inRange(hsv, np.array([35, 35, 35]), np.array([92, 255, 255])) > 0
        too_dark = lightness < 45
        raw = (strict_hsv | (pale_hsv & lab_yellow) | (lab_yellow & yellow_dominant)) & ~green_vegetation & ~too_dark

        mask = raw.astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((13, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 17), np.uint8))
        return mask > 0

    def _crosswalk_score(self, frame: np.ndarray, hsv: np.ndarray, gray: np.ndarray) -> float:
        height, width = frame.shape[:2]
        roi_start = int(height * 0.45)
        white_mask = self._crosswalk_mask(frame, hsv)[roi_start:, :].astype(np.uint8) * 255
        white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, np.ones((3, 7), np.uint8))
        white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, np.ones((5, 31), np.uint8))
        contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        stripe_area = 0.0
        stripe_count = 0
        for contour in contours:
            x, _, w, h = cv2.boundingRect(contour)
            area = float(cv2.contourArea(contour))
            if area < width * height * 0.0008:
                continue
            aspect = w / max(h, 1)
            if aspect < 2.2 or w < width * 0.12:
                continue
            if h > height * 0.11:
                continue
            if x > width * 0.92 or x + w < width * 0.08:
                continue
            stripe_area += area
            stripe_count += 1

        if stripe_count < 2:
            return 0.0
        if stripe_count > 10:
            return 0.0
        lower_area = white_mask.shape[0] * white_mask.shape[1]
        return float(np.clip(stripe_area / lower_area + min(stripe_count, 8) * 0.01, 0.0, 1.0))

    def _crosswalk_mask(self, frame: np.ndarray, hsv: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        white = ((gray > 188) & (saturation < 105) & (value > 175)).astype(np.uint8) * 255
        white = cv2.morphologyEx(white, cv2.MORPH_OPEN, np.ones((3, 7), np.uint8))
        white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((5, 31), np.uint8))
        return white > 0

    def _traffic_context(self, regions: list[SemanticRegion], crosswalk_score: float) -> bool:
        road_coverage = self._region_coverage(regions, "road_or_asphalt")
        center_road = self._region_coverage(regions, "road_or_asphalt", "center")
        walkable_coverage = self._region_coverage(regions, "walkable_pavement")
        crosswalk_coverage = self._region_coverage(regions, "crosswalk")
        return self._crossing_context(
            crosswalk_score=crosswalk_score,
            crosswalk_coverage=crosswalk_coverage,
            road_coverage=road_coverage,
            center_road=center_road,
            walkable_coverage=walkable_coverage,
        )

    def _crossing_context(
        self,
        crosswalk_score: float,
        crosswalk_coverage: float,
        road_coverage: float,
        center_road: float,
        walkable_coverage: float,
    ) -> bool:
        if crosswalk_score > 0.08 and crosswalk_coverage > 0.03:
            return True
        if crosswalk_score > 0.035 or crosswalk_coverage > 0.006:
            return road_coverage > max(0.1, walkable_coverage * 0.75)
        return center_road > 0.12 and road_coverage > max(0.12, walkable_coverage * 1.15)

    def _traffic_light(self, upper_hsv: np.ndarray, require_context: bool = True) -> tuple[str, float]:
        if not require_context:
            return "unknown", 1.0
        red_mask_1 = cv2.inRange(upper_hsv, np.array([0, 95, 100]), np.array([10, 255, 255]))
        red_mask_2 = cv2.inRange(upper_hsv, np.array([170, 95, 100]), np.array([180, 255, 255]))
        green_mask = cv2.inRange(upper_hsv, np.array([45, 80, 90]), np.array([92, 255, 255]))

        candidates = [
            ("red", score)
            for score in self._light_candidate_scores(red_mask_1 | red_mask_2)
        ] + [
            ("green", score)
            for score in self._light_candidate_scores(green_mask)
        ]
        if not candidates:
            return "unknown", 1.0
        color, score = max(candidates, key=lambda item: item[1])
        return color, min(0.95, 0.55 + score * 22)

    def _light_candidate_scores(self, mask: np.ndarray) -> list[float]:
        clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        total_area = mask.shape[0] * mask.shape[1]
        scores: list[float] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < total_area * 0.00035 or area > total_area * 0.018:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            aspect = w / max(h, 1)
            if aspect < 0.55 or aspect > 1.85:
                continue
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < 0.45:
                continue
            scores.append(float(area / total_area))
        return scores

    def _traffic_light_from_objects(self, objects: list[DetectedObject], require_context: bool = True) -> tuple[str, float]:
        if not require_context:
            return "unknown", 0.0
        candidates: list[tuple[str, float]] = []
        for obj in objects:
            label = obj.label.lower()
            if label in {"traffic_light_red", "red_light"}:
                candidates.append(("red", obj.confidence))
            elif label in {"traffic_light_green", "green_light"}:
                candidates.append(("green", obj.confidence))
            elif label in {"traffic_light_yellow", "yellow_light"}:
                candidates.append(("yellow", obj.confidence))
        if not candidates:
            return "unknown", 0.0
        return max(candidates, key=lambda item: item[1])

    def _vehicle_approaching(
        self,
        obstacle_score: float,
        traffic_light: str,
        semantic_regions: list[SemanticRegion],
        detected_objects: list[DetectedObject],
    ) -> bool:
        road_ahead = any(
            region.label == "road_or_asphalt" and region.direction == "center" and region.coverage > 0.12
            for region in semantic_regions
        )
        road_coverage = self._region_coverage(semantic_regions, "road_or_asphalt")
        walkable_coverage = self._region_coverage(semantic_regions, "walkable_pavement")
        road_ahead = road_ahead and road_coverage > max(0.12, walkable_coverage * 1.15)
        for obj in detected_objects:
            label = obj.label.lower()
            distance = obj.distance_m if obj.distance_m is not None else 99.0
            if label in {"vehicle", "car", "bus", "truck", "motorcycle"}:
                if distance <= 3.2 or (road_ahead and distance <= 5.0):
                    return True
            if label == "bicycle":
                if distance <= 2.4 and obj.direction in {"center", "unknown"}:
                    return True
        if traffic_light in {"red", "green", "yellow"} and obstacle_score > 0.62:
            return True
        return bool(road_ahead and obstacle_score > 0.68)

    def _vehicle_confidence(self, vehicle_approaching: bool, obstacle_score: float, crosswalk_score: float, traffic_light: str) -> float:
        if vehicle_approaching:
            return min(0.92, 0.62 + obstacle_score * 0.32)
        if crosswalk_score > 0.035 or traffic_light != "unknown":
            return 0.72
        return min(0.9, 0.35 + obstacle_score)

    def _crowd_level(self, lower_half: np.ndarray) -> tuple[str, float]:
        gray = cv2.cvtColor(lower_half, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 180)
        score = float(np.count_nonzero(edges)) / edges.size
        if score > 0.16:
            return "high", score
        if score > 0.08:
            return "medium", score
        return "low", score

    def _ocr_texts(self, frame: np.ndarray) -> list[str]:
        try:
            import pytesseract
        except ImportError:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 7, 50, 50)
        for lang in ("chi_sim+eng", "eng"):
            try:
                text = pytesseract.image_to_string(gray, lang=lang)
            except Exception:
                continue
            candidates = [clean for line in text.splitlines() if (clean := self._clean_text(line))]
            if candidates:
                return self._dedupe(candidates)[:8]
        return []

    def _sign_candidates(self, frame: np.ndarray, detected_texts: list[str]) -> list[str]:
        text_signs = [text for text in detected_texts if self._looks_like_sign_text(text)]
        if text_signs:
            return text_signs[:4]
        return []

    def _scene_description(
        self,
        obstacle_distance: float | None,
        tactile_blocked: bool,
        traffic_light: str,
        crowd_level: str,
        detected_texts: list[str],
        sign_candidates: list[str],
        semantic_regions: list[SemanticRegion],
        scene_type: str,
        scene_label: str,
    ) -> str:
        if traffic_light == "red":
            return f"{scene_label}. Red light. Stop and wait."
        if scene_type == "crossing":
            return "Road crossing. Stop first and check traffic signals and vehicles."
        if tactile_blocked:
            return "Obstruction ahead. Slow down and wait for avoidance guidance."
        if obstacle_distance is not None and obstacle_distance <= 2.0:
            return f"Obstacle {obstacle_distance:.1f} m ahead. Slow down."
        if scene_type == "finding":
            return "Searching for the target. Keep a slow pace and continue scanning."
        if scene_type == "indoor":
            return f"{scene_label}. No obvious mobility hazard detected."
        if scene_type == "street":
            return "Roadside scene. Crossing is unconfirmed. Stay on the safe side."
        if scene_type == "sidewalk":
            return "Sidewalk. The path ahead appears clear. Continue straight."
        if crowd_level == "high":
            return "Complex surroundings. Proceed slowly."
        return "The scene is unclear. Slow down and check."

    def _region_summary(self, regions: list[SemanticRegion]) -> str | None:
        if not regions:
            return None
        labels: dict[str, SemanticRegion] = {}
        for region in sorted(regions, key=lambda item: item.coverage, reverse=True):
            labels.setdefault(region.label, region)
        parts: list[str] = []
        if "walkable_pavement" in labels:
            parts.append("Walkable pavement below")
        if "tactile_paving" in labels:
            parts.append("Tactile paving cues detected")
        road = labels.get("road_or_asphalt")
        if road:
            direction = {"left": "on the left", "center": "in the center", "right": "on the right", "unknown": "nearby"}[road.direction]
            parts.append(f"Roadway or asphalt {direction}")
        if "vegetation" in labels:
            parts.append("Vegetation along the edge")
        return ", ".join(parts) if parts else None

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"[^\w\u4e00-\u9fff .,&\-\u53f7\u5e97\u8def\u8857\u95e8\u53e3\u5165\u53e3\u51fa\u53e3]", "", text)
        return text if len(text) >= 2 else ""

    def _looks_like_sign_text(self, text: str) -> bool:
        sign_words = ("\u5e97", "\u8d85\u5e02", "\u9910", "\u5496\u5561", "\u94f6\u884c", "\u836f\u623f", "\u5165\u53e3", "\u51fa\u53e3", "market", "shop", "cafe", "store", "bank")
        lower = text.lower()
        return any(word in lower for word in sign_words) or len(text) >= 4

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _risk_score(self, frame: PerceptionFrame) -> float:
        score = 0.0
        if frame.obstacle_distance_m is not None:
            score += max(0.0, 4.0 - frame.obstacle_distance_m)
        if frame.tactile_blocked:
            score += 1.2
        if frame.traffic_light == "red":
            score += 2.0
        if frame.vehicle_approaching:
            score += 2.5
        if frame.sensor_health != "ok":
            score += 3.0
        return score
