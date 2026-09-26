from __future__ import annotations

import math
import os
import secrets
import statistics
import sys
import tempfile
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from PIL import Image, UnidentifiedImageError
from starlette.datastructures import Headers

from .cloud_sessions import sessions
from .glasses import GlassesWifiReceiver
from .media_analyzer import IMAGE_SUFFIXES, VIDEO_SUFFIXES, MediaAnalyzer, validate_media_dimensions
from .mobile_contract import perception_evidence
from .models import PerceptionFrame
from .mobility_coordinator import MobilityOrchestrator
from .smartphone_relay import format_smartphone_plan

API_TOKEN_ENV = "LIBEREYE_API_TOKEN"
authorization_header = APIKeyHeader(name="Authorization", auto_error=False)


def _check_token(authorization: str | None) -> None:
    expected = os.getenv(API_TOKEN_ENV, "").strip()
    if not expected:
        if os.getenv("LIBEREYE_ALLOW_INSECURE", "0") == "1":
            return
        raise HTTPException(503, "Server authentication is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    if not secrets.compare_digest(authorization[7:].strip().encode(), expected.encode()):
        raise HTTPException(403, "Invalid bearer token")


def verify_token(authorization: str | None = Depends(authorization_header)) -> None:
    _check_token(authorization)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _check_token("Bearer " + os.getenv(API_TOKEN_ENV, ""))
    yield


app = FastAPI(
    title="LiberEye Cloud API",
    description="EPMC research service. Coordination timing is not physical output latency.",
    version="0.2.0",
    lifespan=lifespan,
)


class RequestGuard:
    """Authenticate before multipart parsing and bound actual ASGI body bytes."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if scope["path"].startswith("/api/") and scope["method"] != "OPTIONS":
            try:
                _check_token(headers.get("authorization"))
            except HTTPException as exc:
                return await JSONResponse({"detail": exc.detail}, exc.status_code, headers=exc.headers)(scope, receive, send)
        limit = int(os.getenv("LIBEREYE_MAX_UPLOAD_BYTES", "16777216"))
        length = headers.get("content-length")
        if length is not None:
            try:
                size = int(length)
                if size < 0:
                    raise ValueError
            except ValueError:
                return await JSONResponse({"detail": "Invalid Content-Length"}, 400)(scope, receive, send)
            if size > limit:
                return await JSONResponse({"detail": "Request body too large"}, 413)(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, bounded_receive, send)


app.add_middleware(RequestGuard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[v.strip() for v in os.getenv("LIBEREYE_CORS_ORIGINS", "").split(",") if v.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-LiberEye-Session"],
)

# Models are shared under a lock; temporal decision state is per session.
media_analyzer = MediaAnalyzer()
_inference_lock = threading.Lock()
# Legacy local-demo imports. The API never uses their global decision state.
orchestrator = MobilityOrchestrator()
glasses_receiver = GlassesWifiReceiver(media_analyzer=media_analyzer)


def session_id(value: str | None = Header(default=None, alias="X-LiberEye-Session", pattern=r"^[A-Za-z0-9_-]{1,128}$")) -> str | None:
    return value


def _validate_numbers(value: Any, key: str = "") -> None:
    if isinstance(value, dict):
        for name, item in value.items():
            _validate_numbers(item, name)
    elif isinstance(value, list):
        for item in value:
            _validate_numbers(item, key)
    elif isinstance(value, (float, int)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise HTTPException(422, "Perception numbers must be finite")
        if (key.endswith("confidence") or key == "coverage") and not 0 <= value <= 1:
            raise HTTPException(422, f"{key} must be between 0 and 1")
        if (key.endswith("_m") or key == "timestamp_s") and value < 0:
            raise HTTPException(422, f"{key} must be nonnegative")


def _plan(frame: PerceptionFrame, sid: str | None, detail: bool = False):
    _validate_numbers(asdict(frame))
    with sessions.use(sid) as coordinator:
        return coordinator.analyze_perception(frame, detail_request=detail)


@app.get("/health")
def health() -> dict[str, Any]:
    backend = media_analyzer.vision_backend
    errors = list(getattr(backend, "errors", []))
    torch = sys.modules.get("torch")
    try:
        gpu_available = bool(torch is not None and torch.cuda.is_available())
    except Exception:
        gpu_available = False
    return {
        "status": "degraded" if errors else "ok", "service": "libereye-cloud", "version": app.version,
        "models_loaded": {name: getattr(backend, f"{name}_model", None) is not None for name in ("tactile", "crosswalk", "traffic_light")},
        "perception_mode": "model" if backend.available else "heuristic",
        "gpu_available": gpu_available, "model_error_count": len(errors),
        "latency_scope": "software_coordination_only", "session_storage": "single_process_memory",
    }


@app.get("/ready")
def ready(_: None = Depends(verify_token)) -> dict[str, Any]:
    backend = media_analyzer.vision_backend
    if os.getenv("LIBEREYE_REQUIRE_MODELS", "0") == "1":
        missing = [name for name in ("yolo", "tactile", "crosswalk", "traffic_light") if getattr(backend, f"{name}_model", None) is None]
        if missing or getattr(backend, "errors", []):
            raise HTTPException(503, {"message": "Required perception models unavailable", "missing": missing})
    return {"status": "ready", "perception_mode": health()["perception_mode"]}


@app.get("/api/scenarios")
def scenarios(_: None = Depends(verify_token)) -> dict[str, Any]:
    return {"scenarios": orchestrator.available_scenarios()}


@app.post("/api/live")
def analyze_live(frame: PerceptionFrame, sid: str | None = Depends(session_id), _: None = Depends(verify_token)) -> dict[str, Any]:
    return asdict(_plan(frame, sid))


@app.post("/api/epmc/analyze-perception")
@app.post("/api/mobile/analyze-perception")
def analyze_perception_for_mobile(
    frame: PerceptionFrame, source: str = "structured", detail_request: bool = False,
    wrist_connected: bool = True, sid: str | None = Depends(session_id), _: None = Depends(verify_token),
) -> JSONResponse:
    plan = _plan(frame, sid, detail_request)
    evidence = perception_evidence(asdict(frame), source=source)
    return JSONResponse(format_smartphone_plan(plan, evidence=evidence, source=source, wrist_connected=wrist_connected))


def _analyze_file(path: Path, target_query: str | None, sid: str | None, detail: bool):
    ready()
    # Do not queue stale camera frames behind arbitrarily many model jobs.
    if not _inference_lock.acquire(blocking=False):
        raise HTTPException(503, "Perception service busy; retry with a fresh frame", headers={"Retry-After": "1"})
    try:
        _validate_media(path)
        frame, evidence = media_analyzer.analyze_file(path, target_query=target_query)
        # Backends record prediction failures and can return fallback evidence.
        # Required-model deployments must reject the failing request itself.
        ready()
        return _plan(frame, sid, detail), evidence
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "Media could not be decoded within supported limits") from None
    finally:
        _inference_lock.release()


def _validate_media(path: Path) -> None:
    try:
        # Inspect content even with a video suffix. OpenCV will decode a still
        # image renamed to .mp4, so suffix-only validation bypasses pixel limits.
        with Image.open(path) as image:
            validate_media_dimensions(image.width, image.height)
            image.verify()
    except UnidentifiedImageError:
        if path.suffix.lower() not in VIDEO_SUFFIXES:
            raise
        media_analyzer.validate_video(path)


async def _uploaded_plan(media: UploadFile, target: str | None, sid: str | None, detail: bool):
    path = await _save_upload(media)
    try:
        return await run_in_threadpool(_analyze_file, path, target, sid, detail)
    finally:
        path.unlink(missing_ok=True)


@app.post("/api/analyze-media")
async def analyze_media(
    media: UploadFile = File(...), target_query: str | None = Form(default=None),
    detail_request: bool = Form(default=False), sid: str | None = Depends(session_id), _: None = Depends(verify_token),
) -> dict[str, Any]:
    plan, evidence = await _uploaded_plan(media, target_query, sid, detail_request)
    return {**asdict(plan), "media_evidence": evidence}


@app.post("/api/mobile/analyze-media")
async def analyze_media_for_mobile(
    media: UploadFile = File(...), target_query: str | None = Form(default=None),
    detail_request: bool = Form(default=False), wrist_connected: bool = Form(default=True),
    sid: str | None = Depends(session_id), _: None = Depends(verify_token),
) -> JSONResponse:
    plan, evidence = await _uploaded_plan(media, target_query, sid, detail_request)
    return JSONResponse(format_smartphone_plan(plan, evidence=evidence, source="phone_media", wrist_connected=wrist_connected))


@app.post("/api/glasses/frame")
async def glasses_frame(
    frame: UploadFile = File(...), target_query: str | None = Form(default=None),
    detail_request: bool = Form(default=False), wrist_connected: bool = Form(default=True),
    sid: str | None = Depends(session_id), _: None = Depends(verify_token),
) -> JSONResponse:
    plan, evidence = await _uploaded_plan(frame, target_query, sid, detail_request)
    evidence["glasses_source"] = "wifi"
    # This response confirms this upload only, not a persistent physical connection.
    return JSONResponse(format_smartphone_plan(plan, evidence=evidence, source="glasses_wifi", glasses_connected=True, wrist_connected=wrist_connected))


@app.get("/api/epmc/metrics")
def epmc_metrics(sid: str | None = Depends(session_id), _: None = Depends(verify_token)) -> dict[str, Any]:
    with sessions.use(sid) as coordinator:
        samples = coordinator.alert_latency_ms_samples
        return {
            "speech_suppression_count": coordinator.speech_suppression_count,
            "haptic_preemption_count": coordinator.haptic_preemption_count,
            "total_updates": coordinator.total_updates,
            "median_processing_latency_ms": round(statistics.median(samples), 3) if samples else 0.0,
            "latency_scope": "software_coordination_only",
            "fsm_phase": coordinator.fsm.current_phase,
        }


async def _save_upload(media: UploadFile) -> Path:
    path: Path | None = None
    try:
        suffix = Path(media.filename or "").suffix.lower()
        if suffix not in IMAGE_SUFFIXES | VIDEO_SUFFIXES:
            raise HTTPException(415, "Unsupported media extension")
        count = 0
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            path = Path(tmp.name)
            while chunk := await media.read(1024 * 1024):
                count += len(chunk)
                if count > int(os.getenv("LIBEREYE_MAX_UPLOAD_BYTES", "16777216")):
                    raise HTTPException(413, "Media too large")
                tmp.write(chunk)
        if count == 0:
            raise HTTPException(422, "Empty media upload")
        return path
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise
    finally:
        await media.close()
