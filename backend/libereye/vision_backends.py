from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import parse, request

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None  # type: ignore[assignment]
    np = None   # type: ignore[assignment]

from .models import DetectedObject, Direction, SemanticRegion


class ObjectDetector(Protocol):
    def detect(self, frame: np.ndarray) -> list[DetectedObject]:
        raise NotImplementedError


class SemanticSegmenter(Protocol):
    def segment(self, frame: np.ndarray) -> list[SemanticRegion]:
        raise NotImplementedError


@dataclass(frozen=True)
class VisionModelOutputs:
    detected_objects: list[DetectedObject]
    semantic_regions: list[SemanticRegion]
    backend_name: str = "heuristic"
    models: list[str] | None = None
    errors: list[str] | None = None


class OptionalUltralyticsBackend:
    """Optional YOLO detection and SAM segmentation backend.

    Model pipeline:
      - YOLO26 segmentation/detection gives object classes and obstacle boxes.
      - SAM2.1 refines YOLO boxes into object masks.
      - SAM3 can be supplied manually through `LIBEREYE_SAM_MODEL=sam3.pt`.
      - A fine-tuned sidewalk/tactile/road model can be used as the YOLO model.

    Environment variables:
      - LIBEREYE_ENABLE_STRONG_VISION=1 enables default balanced models.
      - LIBEREYE_VISION_PRESET=strong uses larger models.
      - LIBEREYE_YOLO_MODEL overrides the YOLO model.
      - LIBEREYE_TACTILE_MODEL adds a tactile paving detector trained on
        tactile/sidewalk classes and fuses it with the general model.
      - LIBEREYE_CROSSWALK_MODEL adds a crosswalk/zebra crossing detector.
      - LIBEREYE_TRAFFIC_LIGHT_MODEL adds a red/green/yellow traffic light detector.
      - LIBEREYE_ROBOFLOW_TACTILE_MODEL uses a hosted Roboflow model id, for
        example tactile-paving-image-dataset-cb4u9/2.
      - LIBEREYE_ROBOFLOW_CROSSWALK_MODEL uses a hosted crosswalk model id.
      - LIBEREYE_ROBOFLOW_TRAFFIC_LIGHT_MODEL uses a hosted traffic light model id.
      - LIBEREYE_ROBOFLOW_API_KEY authorizes the hosted Roboflow call.
      - LIBEREYE_SAM_MODEL overrides the SAM/SAM2 model.

    Example balanced local setup:
      LIBEREYE_ENABLE_STRONG_VISION=1

    Example cloud setup with larger models:
      LIBEREYE_VISION_PRESET=strong

    The backend stays inactive when ultralytics or model weights are missing.
    """

    def __init__(self, model_path: str | None = None, confidence: float = 0.25) -> None:
        self.preset = os.getenv("LIBEREYE_VISION_PRESET", "").strip().lower()
        self.roboflow_tactile_model_id = os.getenv("LIBEREYE_ROBOFLOW_TACTILE_MODEL", "").strip()
        self.roboflow_crosswalk_model_id = os.getenv("LIBEREYE_ROBOFLOW_CROSSWALK_MODEL", "").strip()
        self.roboflow_traffic_light_model_id = os.getenv("LIBEREYE_ROBOFLOW_TRAFFIC_LIGHT_MODEL", "").strip()
        self.roboflow_api_key = os.getenv("LIBEREYE_ROBOFLOW_API_KEY", "").strip()
        self.enabled = os.getenv("LIBEREYE_ENABLE_STRONG_VISION", "").strip().lower() in {"1", "true", "yes"} or bool(
            model_path
            or os.getenv("LIBEREYE_YOLO_MODEL")
            or os.getenv("LIBEREYE_TACTILE_MODEL")
            or os.getenv("LIBEREYE_CROSSWALK_MODEL")
            or os.getenv("LIBEREYE_TRAFFIC_LIGHT_MODEL")
            or (
                self.roboflow_api_key
                and (self.roboflow_tactile_model_id or self.roboflow_crosswalk_model_id or self.roboflow_traffic_light_model_id)
            )
            or os.getenv("LIBEREYE_SAM_MODEL")
            or self.preset
        )
        self.yolo_model_path, self.sam_model_path = self._model_paths(model_path)
        self.tactile_model_path = os.getenv("LIBEREYE_TACTILE_MODEL")
        self.crosswalk_model_path = os.getenv("LIBEREYE_CROSSWALK_MODEL")
        self.traffic_light_model_path = os.getenv("LIBEREYE_TRAFFIC_LIGHT_MODEL")
        self.model_path = self.yolo_model_path
        self.confidence = confidence
        self.tactile_confidence = float(os.getenv("LIBEREYE_TACTILE_CONF", "0.18"))
        self.crosswalk_confidence = float(os.getenv("LIBEREYE_CROSSWALK_CONF", "0.2"))
        self.traffic_light_confidence = float(os.getenv("LIBEREYE_TRAFFIC_LIGHT_CONF", "0.2"))
        self.model = None  # Backward-compatible alias for the YOLO model.
        self.yolo_model = None
        self.tactile_model = None
        self.crosswalk_model = None
        self.traffic_light_model = None
        self.sam_model = None
        self.sam3_predictor = None
        self.errors: list[str] = []
        if not self.enabled:
            return
        try:
            from ultralytics import SAM, YOLO
        except ImportError as exc:
            self.errors.append(f"ultralytics unavailable: {exc}")
            SAM = None
            YOLO = None

        if YOLO is None:
            if self.tactile_model_path:
                self.errors.append("tactile YOLO unavailable: ultralytics is not installed")
            if self.crosswalk_model_path:
                self.errors.append("crosswalk YOLO unavailable: ultralytics is not installed")
            if self.traffic_light_model_path:
                self.errors.append("traffic light YOLO unavailable: ultralytics is not installed")

        if self.yolo_model_path and YOLO is not None:
            try:
                self.yolo_model = YOLO(self.yolo_model_path)
                self.model = self.yolo_model
            except Exception as exc:
                self.errors.append(f"YOLO load failed: {exc}")

        if self.tactile_model_path and YOLO is not None:
            try:
                self.tactile_model = YOLO(self.tactile_model_path)
            except Exception as exc:
                self.errors.append(f"tactile YOLO load failed: {exc}")

        if self.crosswalk_model_path and YOLO is not None:
            try:
                self.crosswalk_model = YOLO(self.crosswalk_model_path)
            except Exception as exc:
                self.errors.append(f"crosswalk YOLO load failed: {exc}")

        if self.traffic_light_model_path and YOLO is not None:
            try:
                self.traffic_light_model = YOLO(self.traffic_light_model_path)
            except Exception as exc:
                self.errors.append(f"traffic light YOLO load failed: {exc}")

        if self.sam_model_path and os.path.basename(self.sam_model_path).lower().startswith("sam3"):
            try:
                from ultralytics.models.sam import SAM3SemanticPredictor

                self.sam3_predictor = SAM3SemanticPredictor(
                    overrides=dict(conf=self.confidence, task="segment", mode="predict", model=self.sam_model_path, verbose=False)
                )
            except Exception as exc:
                self.errors.append(f"SAM3 load failed: {exc}")
        elif self.sam_model_path and SAM is not None:
            try:
                self.sam_model = SAM(self.sam_model_path)
            except Exception as exc:
                self.errors.append(f"SAM load failed: {exc}")

    @property
    def available(self) -> bool:
        return (
            self.yolo_model is not None
            or self.tactile_model is not None
            or self.crosswalk_model is not None
            or self.traffic_light_model is not None
            or bool(
                self.roboflow_api_key
                and (self.roboflow_tactile_model_id or self.roboflow_crosswalk_model_id or self.roboflow_traffic_light_model_id)
            )
            or self.sam_model is not None
            or self.sam3_predictor is not None
        )

    @property
    def models(self) -> list[str]:
        return [
            model
            for model in [
                self.yolo_model_path,
                self.tactile_model_path,
                self.crosswalk_model_path,
                self.traffic_light_model_path,
                self.sam_model_path,
            ]
            if model
        ]

    def status(self) -> dict[str, Any]:
        return {
            "name": "ultralytics-yolo-sam2",
            "active": self.available,
            "model": self.yolo_model_path,
            "tactile_model": self.tactile_model_path,
            "crosswalk_model": self.crosswalk_model_path,
            "traffic_light_model": self.traffic_light_model_path,
            "roboflow_tactile_model": self.roboflow_tactile_model_id or None,
            "roboflow_crosswalk_model": self.roboflow_crosswalk_model_id or None,
            "roboflow_traffic_light_model": self.roboflow_traffic_light_model_id or None,
            "models": self.models,
            "preset": self.preset or ("balanced" if self.enabled else "off"),
            "errors": self.errors,
        }

    def analyze(self, frame: np.ndarray) -> VisionModelOutputs:
        if not self.available:
            return VisionModelOutputs([], [], backend_name="heuristic", models=[], errors=self.errors)

        detected_objects, semantic_regions, xyxy_prompts = self._analyze_yolo(frame)
        tactile_regions = self._analyze_tactile_model(frame)
        crosswalk_regions = self._analyze_crosswalk_model(frame)
        traffic_light_objects = self._analyze_traffic_light_model(frame)
        roboflow_tactile_regions = self._analyze_roboflow_tactile(frame)
        roboflow_crosswalk_regions = self._analyze_roboflow_crosswalk(frame)
        roboflow_traffic_light_objects = self._analyze_roboflow_traffic_light(frame)
        sam_regions = self._analyze_sam(frame, xyxy_prompts, detected_objects)
        detected_objects = detected_objects + traffic_light_objects + roboflow_traffic_light_objects
        semantic_regions = self._dedupe_regions(
            semantic_regions + tactile_regions + crosswalk_regions + roboflow_tactile_regions + roboflow_crosswalk_regions + sam_regions
        )
        return VisionModelOutputs(
            detected_objects=detected_objects,
            semantic_regions=semantic_regions,
            backend_name="ultralytics-yolo-sam2",
            models=self.models,
            errors=self.errors,
        )

    def _model_paths(self, explicit_yolo_model: str | None) -> tuple[str | None, str | None]:
        yolo_model = explicit_yolo_model or os.getenv("LIBEREYE_YOLO_MODEL")
        sam_model = os.getenv("LIBEREYE_SAM_MODEL")

        if not yolo_model and not sam_model and self.enabled:
            if self.preset == "strong":
                return "yolo26x-seg.pt", "sam2.1_l.pt"
            return "yolo26n-seg.pt", "sam2.1_b.pt"
        return yolo_model, sam_model

    def _analyze_yolo(self, frame: np.ndarray) -> tuple[list[DetectedObject], list[SemanticRegion], list[list[float]]]:
        if self.yolo_model is None:
            return [], [], []
        try:
            results = self.yolo_model.predict(frame, conf=self.confidence, verbose=False)
        except Exception as exc:
            self.errors.append(f"YOLO predict failed: {exc}")
            return [], [], []
        if not results:
            return [], [], []

        result = results[0]
        names = result.names or {}
        height, width = frame.shape[:2]
        detected_objects: list[DetectedObject] = []
        semantic_regions: list[SemanticRegion] = []
        xyxy_prompts: list[list[float]] = []

        boxes = getattr(result, "boxes", None)
        if boxes is not None:
            for box in boxes:
                cls_id = int(_tensor_item(box.cls[0]))
                label = str(names.get(cls_id, cls_id))
                confidence = float(_tensor_item(box.conf[0]))
                x1, y1, x2, y2 = [_tensor_item(v) for v in box.xyxy[0]]
                bbox = [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]
                direction = _direction_from_center((x1 + x2) / 2, width)
                distance = _distance_from_bbox(bbox, width, height)
                normalized_label = _normalize_object_label(label)
                detected_objects.append(
                    DetectedObject(label=normalized_label, direction=direction, distance_m=distance, confidence=confidence, bbox=bbox)
                )
                xyxy_prompts.append([float(x1), float(y1), float(x2), float(y2)])

        masks = getattr(result, "masks", None)
        if masks is not None and masks.data is not None:
            for index, mask_tensor in enumerate(masks.data):
                cls_id = int(_tensor_item(boxes[index].cls[0])) if boxes is not None and index < len(boxes) else -1
                label = str(names.get(cls_id, cls_id))
                mask = _mask_array(mask_tensor)
                coverage = float(mask.mean())
                direction = _direction_from_mask(mask)
                confidence = float(_tensor_item(boxes[index].conf[0])) if boxes is not None and index < len(boxes) else 0.6
                semantic_regions.append(
                    SemanticRegion(label=_normalize_region_label(label), direction=direction, coverage=coverage, confidence=confidence)
                )

        return detected_objects, semantic_regions, xyxy_prompts

    def _analyze_tactile_model(self, frame: np.ndarray) -> list[SemanticRegion]:
        if self.tactile_model is None:
            return []
        try:
            results = self.tactile_model.predict(frame, conf=self.tactile_confidence, verbose=False)
        except Exception as exc:
            self.errors.append(f"tactile YOLO predict failed: {exc}")
            return []
        if not results:
            return []

        result = results[0]
        names = result.names or {}
        height, width = frame.shape[:2]
        regions: list[SemanticRegion] = []

        masks = getattr(result, "masks", None)
        boxes = getattr(result, "boxes", None)
        if masks is not None and masks.data is not None:
            for index, mask_tensor in enumerate(masks.data):
                label = self._label_from_boxes(boxes, names, index)
                if not _is_tactile_label(label):
                    continue
                mask = _mask_array(mask_tensor)
                coverage = float(mask.mean())
                if coverage <= 0.001:
                    continue
                confidence = self._confidence_from_boxes(boxes, index, fallback=0.72)
                regions.append(
                    SemanticRegion(
                        label="tactile_paving",
                        direction=_direction_from_mask(mask),
                        coverage=coverage,
                        confidence=confidence,
                    )
                )
            return regions

        if boxes is None:
            return []
        for box in boxes:
            cls_id = int(_tensor_item(box.cls[0]))
            label = str(names.get(cls_id, cls_id))
            if not _is_tactile_label(label):
                continue
            confidence = float(_tensor_item(box.conf[0]))
            x1, y1, x2, y2 = [_tensor_item(v) for v in box.xyxy[0]]
            bbox_width = max(1.0, x2 - x1)
            bbox_height = max(1.0, y2 - y1)
            coverage = float(np.clip((bbox_width * bbox_height) / (width * height), 0.001, 1.0))
            direction = _direction_from_center((x1 + x2) / 2, width)
            regions.append(SemanticRegion("tactile_paving", direction, coverage, confidence))
        return regions

    def _analyze_crosswalk_model(self, frame: np.ndarray) -> list[SemanticRegion]:
        if self.crosswalk_model is None:
            return []
        try:
            results = self.crosswalk_model.predict(frame, conf=self.crosswalk_confidence, verbose=False)
        except Exception as exc:
            self.errors.append(f"crosswalk YOLO predict failed: {exc}")
            return []
        if not results:
            return []
        return self._regions_from_yolo_result(results[0], frame.shape[1], frame.shape[0], _is_crosswalk_label, "crosswalk")

    def _analyze_traffic_light_model(self, frame: np.ndarray) -> list[DetectedObject]:
        if self.traffic_light_model is None:
            return []
        try:
            results = self.traffic_light_model.predict(frame, conf=self.traffic_light_confidence, verbose=False)
        except Exception as exc:
            self.errors.append(f"traffic light YOLO predict failed: {exc}")
            return []
        if not results:
            return []
        return self._traffic_light_objects_from_yolo_result(results[0], frame.shape[1], frame.shape[0])

    def _regions_from_yolo_result(
        self,
        result: Any,
        width: int,
        height: int,
        label_predicate: Any,
        normalized_label: str,
    ) -> list[SemanticRegion]:
        names = result.names or {}
        regions: list[SemanticRegion] = []
        masks = getattr(result, "masks", None)
        boxes = getattr(result, "boxes", None)
        if masks is not None and masks.data is not None:
            for index, mask_tensor in enumerate(masks.data):
                label = self._label_from_boxes(boxes, names, index)
                if not label_predicate(label):
                    continue
                mask = _mask_array(mask_tensor)
                coverage = float(mask.mean())
                if coverage <= 0.001:
                    continue
                confidence = self._confidence_from_boxes(boxes, index, fallback=0.7)
                regions.append(SemanticRegion(normalized_label, _direction_from_mask(mask), coverage, confidence))
            return regions
        if boxes is None:
            return []
        for box in boxes:
            cls_id = int(_tensor_item(box.cls[0]))
            label = str(names.get(cls_id, cls_id))
            if not label_predicate(label):
                continue
            confidence = float(_tensor_item(box.conf[0]))
            x1, y1, x2, y2 = [_tensor_item(v) for v in box.xyxy[0]]
            bbox_width = max(1.0, x2 - x1)
            bbox_height = max(1.0, y2 - y1)
            coverage = float(np.clip((bbox_width * bbox_height) / (width * height), 0.001, 1.0))
            regions.append(SemanticRegion(normalized_label, _direction_from_center((x1 + x2) / 2, width), coverage, confidence))
        return regions

    def _traffic_light_objects_from_yolo_result(self, result: Any, width: int, height: int) -> list[DetectedObject]:
        names = result.names or {}
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        objects: list[DetectedObject] = []
        for box in boxes:
            cls_id = int(_tensor_item(box.cls[0]))
            label = str(names.get(cls_id, cls_id))
            state = _traffic_light_state_from_label(label)
            if state is None and not _is_traffic_light_label(label):
                continue
            x1, y1, x2, y2 = [_tensor_item(v) for v in box.xyxy[0]]
            bbox = [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]
            direction = _direction_from_center((x1 + x2) / 2, width)
            confidence = float(_tensor_item(box.conf[0]))
            normalized = f"traffic_light_{state}" if state else "traffic_light"
            objects.append(DetectedObject(normalized, direction, _distance_from_bbox(bbox, width, height), confidence, bbox))
        return objects

    def _analyze_roboflow_tactile(self, frame: np.ndarray) -> list[SemanticRegion]:
        if not self.roboflow_tactile_model_id or not self.roboflow_api_key:
            return []
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
        if not ok:
            self.errors.append("Roboflow encode failed")
            return []
        endpoint = f"https://serverless.roboflow.com/{self.roboflow_tactile_model_id}"
        url = endpoint + "?" + parse.urlencode({"api_key": self.roboflow_api_key})
        try:
            request_obj = request.Request(
                url,
                data=encoded.tobytes(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with request.urlopen(request_obj, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.errors.append(f"Roboflow tactile inference failed: {exc}")
            return []
        predictions = payload.get("predictions", []) if isinstance(payload, dict) else []
        return _regions_from_roboflow_predictions(predictions, frame.shape[1], frame.shape[0], self.tactile_confidence, _is_tactile_label, "tactile_paving")

    def _analyze_roboflow_crosswalk(self, frame: np.ndarray) -> list[SemanticRegion]:
        if not self.roboflow_crosswalk_model_id or not self.roboflow_api_key:
            return []
        payload = self._call_roboflow_model(frame, self.roboflow_crosswalk_model_id, "crosswalk")
        predictions = payload.get("predictions", []) if isinstance(payload, dict) else []
        return _regions_from_roboflow_predictions(predictions, frame.shape[1], frame.shape[0], self.crosswalk_confidence, _is_crosswalk_label, "crosswalk")

    def _analyze_roboflow_traffic_light(self, frame: np.ndarray) -> list[DetectedObject]:
        if not self.roboflow_traffic_light_model_id or not self.roboflow_api_key:
            return []
        payload = self._call_roboflow_model(frame, self.roboflow_traffic_light_model_id, "traffic light")
        predictions = payload.get("predictions", []) if isinstance(payload, dict) else []
        return _traffic_light_objects_from_roboflow_predictions(predictions, frame.shape[1], frame.shape[0], self.traffic_light_confidence)

    def _call_roboflow_model(self, frame: np.ndarray, model_id: str, label: str) -> dict:
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
        if not ok:
            self.errors.append(f"Roboflow {label} encode failed")
            return {}
        endpoint = f"https://serverless.roboflow.com/{model_id}"
        url = endpoint + "?" + parse.urlencode({"api_key": self.roboflow_api_key})
        try:
            request_obj = request.Request(
                url,
                data=encoded.tobytes(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with request.urlopen(request_obj, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.errors.append(f"Roboflow {label} inference failed: {exc}")
            return {}
        return payload

    def _label_from_boxes(self, boxes: Any, names: dict, index: int) -> str:
        if boxes is None or getattr(boxes, "cls", None) is None or index >= len(boxes):
            return "tactile_paving"
        cls_id = int(_tensor_item(boxes[index].cls[0]))
        return str(names.get(cls_id, cls_id))

    def _confidence_from_boxes(self, boxes: Any, index: int, fallback: float) -> float:
        if boxes is None or getattr(boxes, "conf", None) is None or index >= len(boxes):
            return fallback
        return float(_tensor_item(boxes[index].conf[0]))

    def _analyze_sam(
        self,
        frame: np.ndarray,
        xyxy_prompts: list[list[float]],
        detected_objects: list[DetectedObject],
    ) -> list[SemanticRegion]:
        if self.sam3_predictor is not None:
            return self._analyze_sam3(frame, xyxy_prompts, detected_objects)
        if self.sam_model is None:
            return []

        try:
            if xyxy_prompts:
                results = self.sam_model(frame, bboxes=xyxy_prompts, verbose=False)
            elif os.getenv("LIBEREYE_SAM_EVERYTHING", "").strip().lower() in {"1", "true", "yes"}:
                results = self.sam_model(frame, verbose=False)
            else:
                return []
        except Exception as exc:
            self.errors.append(f"SAM predict failed: {exc}")
            return []

        if not results:
            return []
        masks = getattr(results[0], "masks", None)
        if masks is None or masks.data is None:
            return []

        regions: list[SemanticRegion] = []
        for index, mask_tensor in enumerate(masks.data):
            mask = _mask_array(mask_tensor)
            coverage = float(mask.mean())
            if coverage <= 0.002:
                continue
            detected = detected_objects[index] if index < len(detected_objects) else None
            label = detected.label if detected else "segmented_object"
            confidence = detected.confidence if detected else 0.62
            regions.append(
                SemanticRegion(
                    label=_normalize_region_label(label),
                    direction=_direction_from_mask(mask),
                    coverage=coverage,
                    confidence=confidence,
                )
            )
        return regions

    def _analyze_sam3(
        self,
        frame: np.ndarray,
        xyxy_prompts: list[list[float]],
        detected_objects: list[DetectedObject],
    ) -> list[SemanticRegion]:
        if self.sam3_predictor is None:
            return []
        try:
            self.sam3_predictor.set_image(frame)
            prompts = _sam3_text_prompts(detected_objects)
            if prompts:
                results = self.sam3_predictor(text=prompts)
            elif xyxy_prompts:
                results = self.sam3_predictor(bboxes=xyxy_prompts)
            else:
                return []
        except Exception as exc:
            self.errors.append(f"SAM3 predict failed: {exc}")
            return []

        if not results:
            return []
        regions: list[SemanticRegion] = []
        for result in results:
            masks = getattr(result, "masks", None)
            boxes = getattr(result, "boxes", None)
            if masks is None or masks.data is None:
                continue
            for index, mask_tensor in enumerate(masks.data):
                mask = _mask_array(mask_tensor)
                coverage = float(mask.mean())
                if coverage <= 0.002:
                    continue
                label = _sam3_label_from_result(boxes, detected_objects, index)
                regions.append(SemanticRegion(label=_normalize_region_label(label), direction=_direction_from_mask(mask), coverage=coverage, confidence=0.72))
        return regions

    def _dedupe_regions(self, regions: list[SemanticRegion]) -> list[SemanticRegion]:
        best: dict[tuple[str, Direction], SemanticRegion] = {}
        for region in regions:
            key = (region.label, region.direction)
            previous = best.get(key)
            if previous is None or region.confidence * region.coverage > previous.confidence * previous.coverage:
                best[key] = region
        return sorted(best.values(), key=lambda item: item.confidence * item.coverage, reverse=True)


def _direction_from_center(center_x: float, width: int) -> Direction:
    if center_x < width / 3:
        return "left"
    if center_x > width * 2 / 3:
        return "right"
    return "center"


def _direction_from_mask(mask: np.ndarray) -> Direction:
    cols = np.where(mask > 0.5)[1]
    if cols.size == 0:
        return "unknown"
    return _direction_from_center(float(cols.mean()), mask.shape[1])


def _distance_from_bbox(bbox: list[int], width: int, height: int) -> float:
    _, _, box_w, box_h = bbox
    area_ratio = max(0.0001, (box_w * box_h) / (width * height))
    return float(np.clip(1.0 / np.sqrt(area_ratio) * 0.65, 0.7, 6.0))


def _tensor_item(value: Any) -> float:
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "item"):
        return float(value.item())
    return float(value)


def _mask_array(mask_tensor: Any) -> np.ndarray:
    if hasattr(mask_tensor, "detach"):
        mask_tensor = mask_tensor.detach().cpu().numpy()
    return np.asarray(mask_tensor) > 0.5


def _normalize_object_label(label: str) -> str:
    label = label.lower().replace(" ", "_")
    aliases = {
        "traffic_light": "traffic_light",
        "red": "traffic_light_red",
        "red_light": "traffic_light_red",
        "red_lights": "traffic_light_red",
        "red_traffic_light": "traffic_light_red",
        "green": "traffic_light_green",
        "green_light": "traffic_light_green",
        "green_lights": "traffic_light_green",
        "green_traffic_light": "traffic_light_green",
        "yellow": "traffic_light_yellow",
        "yellow_light": "traffic_light_yellow",
        "yellow_lights": "traffic_light_yellow",
        "yellow_traffic_light": "traffic_light_yellow",
        "stop_sign": "traffic_sign",
        "person": "person",
        "car": "vehicle",
        "bus": "vehicle",
        "truck": "vehicle",
        "motorcycle": "vehicle",
        "bicycle": "bicycle",
        "bench": "bench",
        "chair": "chair",
        "dining_table": "table",
        "dining table": "table",
        "cell_phone": "phone",
        "cell phone": "phone",
        "mobile_phone": "phone",
        "laptop": "laptop",
        "keyboard": "keyboard",
        "mouse": "mouse",
        "tv": "monitor",
        "monitor": "monitor",
        "cup": "cup",
        "bottle": "bottle",
        "book": "book",
        "suitcase": "suitcase",
        "backpack": "backpack",
        "potted_plant": "plant",
    }
    return aliases.get(label, label)


def _normalize_region_label(label: str) -> str:
    label = label.lower().replace(" ", "_")
    if label in {"sidewalk", "pavement", "footpath", "walkable", "floor", "walkable_pavement"}:
        return "walkable_pavement"
    if label in {"road", "street", "lane", "asphalt", "road_or_asphalt"}:
        return "road_or_asphalt"
    if _is_crosswalk_label(label):
        return "crosswalk"
    if label in {"vegetation", "tree", "plant", "grass", "potted_plant"}:
        return "vegetation"
    if label in {"tactile", "tactile_paving", "blind_road", "braille_block"}:
        return "tactile_paving"
    if label in {"car", "bus", "truck", "motorcycle", "vehicle"}:
        return "vehicle"
    if label in {"person", "bicycle", "bench", "chair", "suitcase", "backpack", "obstacle"}:
        return "obstacle"
    return label


def _is_tactile_label(label: str) -> bool:
    normalized = label.lower().replace(" ", "_").replace("-", "_")
    tactile_labels = {
        "tactile",
        "tactile_paving",
        "paving_tactile",
        "blind_road",
        "braille_block",
        "tenji_block",
        "warning_block",
        "guidance_block",
        "line",
        "dot",
        "go",
        "stop",
    }
    return normalized in tactile_labels or "tactile" in normalized


def _is_crosswalk_label(label: str) -> bool:
    normalized = label.lower().replace(" ", "_").replace("-", "_")
    labels = {
        "crosswalk",
        "cross_walk",
        "zebra_crossing",
        "zebra_cross",
        "zebra",
        "pedestrian_crossing",
        "pedestriancross",
        "crossing",
    }
    return normalized in labels or "crosswalk" in normalized or "zebra" in normalized


def _is_traffic_light_label(label: str) -> bool:
    normalized = label.lower().replace(" ", "_").replace("-", "_")
    return "traffic_light" in normalized or normalized in {"red", "green", "yellow", "red_light", "green_light", "yellow_light"}


def _traffic_light_state_from_label(label: str) -> str | None:
    normalized = label.lower().replace(" ", "_").replace("-", "_")
    if normalized in {"red", "red_light", "red_lights", "red_traffic_light", "traffic_light_red", "merah"}:
        return "red"
    if normalized in {"green", "green_light", "green_lights", "green_traffic_light", "traffic_light_green", "hijau"}:
        return "green"
    if normalized in {"yellow", "yellow_light", "yellow_lights", "yellow_traffic_light", "traffic_light_yellow", "kuning"}:
        return "yellow"
    return None


def _regions_from_roboflow_predictions(
    predictions: list[dict],
    width: int,
    height: int,
    min_confidence: float,
    label_predicate: Any = _is_tactile_label,
    normalized_label: str = "tactile_paving",
) -> list[SemanticRegion]:
    regions: list[SemanticRegion] = []
    for prediction in predictions:
        label = str(prediction.get("class") or prediction.get("class_name") or prediction.get("label") or "")
        if not label_predicate(label):
            continue
        confidence = float(prediction.get("confidence", 0.0) or 0.0)
        if confidence < min_confidence:
            continue
        box_w = float(prediction.get("width", 0.0) or 0.0)
        box_h = float(prediction.get("height", 0.0) or 0.0)
        center_x = float(prediction.get("x", width / 2) or width / 2)
        if box_w <= 0 or box_h <= 0:
            continue
        coverage = float(np.clip((box_w * box_h) / max(width * height, 1), 0.001, 1.0))
        regions.append(
            SemanticRegion(
                label=normalized_label,
                direction=_direction_from_center(center_x, width),
                coverage=coverage,
                confidence=confidence,
            )
        )
    return regions


def _traffic_light_objects_from_roboflow_predictions(
    predictions: list[dict],
    width: int,
    height: int,
    min_confidence: float,
) -> list[DetectedObject]:
    objects: list[DetectedObject] = []
    for prediction in predictions:
        label = str(prediction.get("class") or prediction.get("class_name") or prediction.get("label") or "")
        state = _traffic_light_state_from_label(label)
        if state is None and not _is_traffic_light_label(label):
            continue
        confidence = float(prediction.get("confidence", 0.0) or 0.0)
        if confidence < min_confidence:
            continue
        box_w = float(prediction.get("width", 0.0) or 0.0)
        box_h = float(prediction.get("height", 0.0) or 0.0)
        center_x = float(prediction.get("x", width / 2) or width / 2)
        center_y = float(prediction.get("y", height / 2) or height / 2)
        if box_w <= 0 or box_h <= 0:
            continue
        x1 = int(center_x - box_w / 2)
        y1 = int(center_y - box_h / 2)
        bbox = [x1, y1, int(box_w), int(box_h)]
        normalized = f"traffic_light_{state}" if state else "traffic_light"
        objects.append(
            DetectedObject(
                label=normalized,
                direction=_direction_from_center(center_x, width),
                distance_m=_distance_from_bbox(bbox, width, height),
                confidence=confidence,
                bbox=bbox,
            )
        )
    return objects


def _sam3_text_prompts(detected_objects: list[DetectedObject]) -> list[str]:
    labels = []
    for obj in detected_objects:
        if obj.label in {"person", "vehicle", "bicycle", "traffic_light", "traffic_sign", "obstacle"}:
            labels.append(obj.label.replace("_", " "))
    return sorted(set(labels))[:8]


def _sam3_label_from_result(boxes: Any, detected_objects: list[DetectedObject], index: int) -> str:
    if index < len(detected_objects):
        return detected_objects[index].label
    if boxes is not None and getattr(boxes, "cls", None) is not None and index < len(boxes):
        return str(int(_tensor_item(boxes[index].cls[0])))
    return "segmented_object"
